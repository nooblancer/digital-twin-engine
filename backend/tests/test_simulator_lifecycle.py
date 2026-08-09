"""Unit tests for simulator connection lifecycle and reporting.

Tests the connection retry logic, reconnection on failure, stop signal handling,
duration watchdog, and summary reporting of the TelemetrySimulator.

Validates: Requirements 10.6, 10.7, 10.8, 10.9
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.simulator.config import SensorSimConfig, SimulatorConfig
from digital_twin_engine.simulator.patterns import SteadyStateConfig
from digital_twin_engine.simulator.simulator import SimulationSummary, TelemetrySimulator


def _make_ws_mock():
    """Create a mock WebSocket connection object."""
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.close = AsyncMock()
    return mock_ws


def _make_connect_coroutine(result):
    """Create a coroutine function that returns result (simulating websockets.connect).

    websockets.connect() returns a coroutine that resolves to a WebSocket.
    We simulate this by returning an async function that returns the result.
    """

    async def _connect(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    return _connect


def _make_connect_sequence(results):
    """Create a connect function that returns different results on each call.

    Args:
        results: List of results. Exception instances will be raised.
    """
    call_idx = {"i": 0}

    async def _connect(*args, **kwargs):
        idx = call_idx["i"]
        call_idx["i"] += 1
        if idx < len(results):
            r = results[idx]
        else:
            r = results[-1]
        if isinstance(r, Exception):
            raise r
        return r

    return _connect


def _make_config(
    server_url: str = "ws://localhost:8080/ws/telemetry",
    emission_rate: float = 10.0,
    duration_seconds: float = 2.0,
    connect_timeout_seconds: float = 5.0,
    max_connect_retries: int = 3,
    retry_delay_seconds: float = 2.0,
) -> SimulatorConfig:
    """Create a minimal valid SimulatorConfig for testing."""
    return SimulatorConfig(
        server_url=server_url,
        sensors=[
            SensorSimConfig(
                sensor_id="test-sensor",
                measurement_type="temperature",
                pattern_config=SteadyStateConfig(base=25.0, sigma=0.0),
            )
        ],
        emission_rate=emission_rate,
        duration_seconds=duration_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        max_connect_retries=max_connect_retries,
        retry_delay_seconds=retry_delay_seconds,
    )


# ---------------------------------------------------------------------------
# Connection with retry tests (Requirement 10.6, 10.7)
# ---------------------------------------------------------------------------


class TestConnectWithRetry:
    """Tests for _connect_with_retry: connect within 5s, retry up to 3 times."""

    @pytest.mark.asyncio
    async def test_connects_on_first_attempt(self):
        """Should connect successfully on first attempt."""
        config = _make_config()
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            await sim._connect_with_retry()

        assert sim._websocket is mock_ws

    @pytest.mark.asyncio
    async def test_connects_after_transient_failure(self):
        """Should succeed on second attempt after first fails."""
        config = _make_config(retry_delay_seconds=0.01)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_sequence([OSError("refused"), mock_ws]),
        ):
            await sim._connect_with_retry()

        assert sim._websocket is mock_ws
        assert sim._connection_errors == 1

    @pytest.mark.asyncio
    async def test_connects_on_last_retry(self):
        """Should succeed on the last retry attempt (attempt 4 = initial + 3 retries)."""
        config = _make_config(max_connect_retries=3, retry_delay_seconds=0.01)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_sequence(
                [OSError("fail1"), OSError("fail2"), OSError("fail3"), mock_ws]
            ),
        ):
            await sim._connect_with_retry()

        assert sim._websocket is mock_ws
        assert sim._connection_errors == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        """Should raise ConnectionError after all retries fail."""
        config = _make_config(max_connect_retries=3, retry_delay_seconds=0.01)
        sim = TelemetrySimulator(config, seed=42)

        call_count = {"n": 0}

        async def always_fail(*args, **kwargs):
            call_count["n"] += 1
            raise OSError("connection refused")

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=always_fail,
        ):
            with pytest.raises(ConnectionError, match="Failed to connect"):
                await sim._connect_with_retry()

        # 4 attempts total (1 initial + 3 retries)
        assert call_count["n"] == 4
        assert sim._connection_errors == 4

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self):
        """A connection attempt that times out should count as a failure and retry."""
        config = _make_config(
            connect_timeout_seconds=0.05,
            max_connect_retries=2,
            retry_delay_seconds=0.01,
        )
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()
        call_count = {"n": 0}

        async def connect_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                await asyncio.sleep(10)  # Will timeout
            return mock_ws

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=connect_side_effect,
        ):
            await sim._connect_with_retry()

        assert sim._websocket is mock_ws
        assert sim._connection_errors == 2

    @pytest.mark.asyncio
    async def test_connect_timeout_respects_config(self):
        """Connection timeout should use connect_timeout_seconds from config."""
        config = _make_config(
            connect_timeout_seconds=5.0,
            max_connect_retries=0,
            retry_delay_seconds=0.01,
        )
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            await sim._connect_with_retry()

        assert sim._websocket is mock_ws

    @pytest.mark.asyncio
    async def test_retry_delay_is_applied(self):
        """Should wait retry_delay_seconds between attempts."""
        config = _make_config(max_connect_retries=1, retry_delay_seconds=0.1)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        start = time.monotonic()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_sequence([OSError("fail"), mock_ws]),
        ):
            await sim._connect_with_retry()
        elapsed = time.monotonic() - start

        # Should have waited at least 0.1 seconds for retry delay
        assert elapsed >= 0.09


# ---------------------------------------------------------------------------
# Reconnection tests (Requirement 10.9)
# ---------------------------------------------------------------------------


class TestReconnect:
    """Tests for _reconnect: reconnect up to 3 times with 2-second delay."""

    @pytest.mark.asyncio
    async def test_reconnect_succeeds_first_attempt(self):
        """Should successfully reconnect on first attempt."""
        config = _make_config(retry_delay_seconds=0.01)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = AsyncMock()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            result = await sim._reconnect()

        assert result is True
        assert sim._websocket is mock_ws

    @pytest.mark.asyncio
    async def test_reconnect_succeeds_after_failures(self):
        """Should succeed on last reconnection attempt."""
        config = _make_config(max_connect_retries=3, retry_delay_seconds=0.01)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = AsyncMock()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_sequence(
                [OSError("fail1"), OSError("fail2"), mock_ws]
            ),
        ):
            result = await sim._reconnect()

        assert result is True
        assert sim._websocket is mock_ws

    @pytest.mark.asyncio
    async def test_reconnect_fails_all_attempts(self):
        """Should return False when all reconnection attempts fail."""
        config = _make_config(max_connect_retries=3, retry_delay_seconds=0.01)
        sim = TelemetrySimulator(config, seed=42)

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(OSError("connection refused")),
        ):
            result = await sim._reconnect()

        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_delay_between_attempts(self):
        """Should wait retry_delay_seconds between reconnection attempts."""
        config = _make_config(max_connect_retries=2, retry_delay_seconds=0.1)
        sim = TelemetrySimulator(config, seed=42)

        start = time.monotonic()
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(OSError("connection refused")),
        ):
            await sim._reconnect()
        elapsed = time.monotonic() - start

        # Should wait retry_delay_seconds before each attempt (2 attempts × 0.1s)
        assert elapsed >= 0.18


# ---------------------------------------------------------------------------
# Stop signal and duration tests (Requirement 10.8)
# ---------------------------------------------------------------------------


class TestStopAndDuration:
    """Tests for stop signal and duration watchdog."""

    @pytest.mark.asyncio
    async def test_stop_signal_ceases_generation(self):
        """Calling stop() should cease event generation."""
        config = _make_config(emission_rate=100.0, duration_seconds=10.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            # Schedule stop after a short delay
            async def delayed_stop():
                await asyncio.sleep(0.2)
                sim.stop()

            stop_task = asyncio.create_task(delayed_stop())
            summary = await sim.run()
            await stop_task

        # Should have stopped before the full 10s duration
        assert summary.elapsed_seconds < 5.0
        assert sim.is_running is False

    @pytest.mark.asyncio
    async def test_duration_elapsed_ceases_generation(self):
        """When duration elapses, simulator should stop."""
        config = _make_config(emission_rate=10.0, duration_seconds=1.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            summary = await sim.run()

        # Should stop close to 1 second
        assert summary.elapsed_seconds < 2.0
        assert sim.is_running is False

    @pytest.mark.asyncio
    async def test_connection_closed_on_stop(self):
        """WebSocket connection should be closed on stop."""
        config = _make_config(emission_rate=10.0, duration_seconds=1.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            await sim.run()

        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_closed_on_external_stop(self):
        """WebSocket should be closed when stop() is called externally."""
        config = _make_config(emission_rate=10.0, duration_seconds=10.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            async def delayed_stop():
                await asyncio.sleep(0.1)
                sim.stop()

            stop_task = asyncio.create_task(delayed_stop())
            await sim.run()
            await stop_task

        mock_ws.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Summary reporting tests (Requirement 10.8)
# ---------------------------------------------------------------------------


class TestSummaryReporting:
    """Tests for summary reporting on completion."""

    @pytest.mark.asyncio
    async def test_summary_total_events(self):
        """Summary should report total events emitted."""
        config = _make_config(emission_rate=50.0, duration_seconds=1.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            summary = await sim.run()

        assert summary.total_events_emitted > 0
        assert summary.total_events_emitted == mock_ws.send.await_count

    @pytest.mark.asyncio
    async def test_summary_elapsed_time(self):
        """Summary should report elapsed time close to duration."""
        config = _make_config(emission_rate=10.0, duration_seconds=1.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            summary = await sim.run()

        # Should be approximately 1 second (within reasonable margin)
        assert 0.8 <= summary.elapsed_seconds <= 2.0

    @pytest.mark.asyncio
    async def test_summary_actual_average_rate(self):
        """Summary should report actual average rate = total_events / elapsed."""
        config = _make_config(emission_rate=10.0, duration_seconds=1.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            summary = await sim.run()

        if summary.elapsed_seconds > 0:
            expected_rate = summary.total_events_emitted / summary.elapsed_seconds
            assert abs(summary.actual_average_rate - expected_rate) < 0.01

    @pytest.mark.asyncio
    async def test_summary_events_per_sensor(self):
        """Summary should report events per sensor."""
        sensors = [
            SensorSimConfig(
                sensor_id="sensor-a",
                measurement_type="temp",
                pattern_config=SteadyStateConfig(base=25.0, sigma=0.0),
            ),
            SensorSimConfig(
                sensor_id="sensor-b",
                measurement_type="pressure",
                pattern_config=SteadyStateConfig(base=100.0, sigma=0.0),
            ),
        ]
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=sensors,
            emission_rate=20.0,
            duration_seconds=1.0,
        )
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            summary = await sim.run()

        assert "sensor-a" in summary.events_per_sensor
        assert "sensor-b" in summary.events_per_sensor
        total_per_sensor = sum(summary.events_per_sensor.values())
        assert total_per_sensor == summary.total_events_emitted

    @pytest.mark.asyncio
    async def test_summary_timestamps(self):
        """Summary should include started_at and stopped_at timestamps."""
        config = _make_config(emission_rate=10.0, duration_seconds=1.0)
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws),
        ):
            summary = await sim.run()

        # Timestamps should be valid ISO 8601 strings
        from datetime import datetime

        started = datetime.fromisoformat(summary.started_at)
        stopped = datetime.fromisoformat(summary.stopped_at)
        assert stopped >= started

    @pytest.mark.asyncio
    async def test_summary_connection_errors_counted(self):
        """Summary should count connection errors that occurred."""
        config = _make_config(
            emission_rate=10.0,
            duration_seconds=1.0,
            retry_delay_seconds=0.01,
        )
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = _make_ws_mock()

        # Fail twice before succeeding
        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_sequence(
                [OSError("fail1"), OSError("fail2"), mock_ws]
            ),
        ):
            summary = await sim.run()

        assert summary.connection_errors == 2


# ---------------------------------------------------------------------------
# Connection loss during transmission (Requirement 10.9)
# ---------------------------------------------------------------------------


class TestConnectionLossDuringTransmission:
    """Tests for reconnection behavior when connection drops during transmission."""

    @pytest.mark.asyncio
    async def test_reconnect_on_connection_closed_during_send(self):
        """Should attempt reconnection when connection is lost during send."""
        from websockets.exceptions import ConnectionClosed

        config = _make_config(
            emission_rate=10.0, duration_seconds=1.0, retry_delay_seconds=0.01
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()

        # First WS: fails on first send with ConnectionClosed
        mock_ws1 = AsyncMock()
        mock_ws1.send = AsyncMock(
            side_effect=ConnectionClosed(None, None)
        )
        mock_ws1.close = AsyncMock()

        # Second WS: works fine
        mock_ws2 = _make_ws_mock()

        sim._websocket = mock_ws1
        sim._start_time = time.monotonic()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(mock_ws2),
        ):
            result = await sim._send_event('{"test": "event"}')

        assert result is True
        assert sim._websocket is mock_ws2

    @pytest.mark.asyncio
    async def test_terminate_when_reconnect_fails_during_send(self):
        """Should terminate with error when reconnection fails during transmission."""
        from websockets.exceptions import ConnectionClosed

        config = _make_config(
            emission_rate=10.0,
            duration_seconds=10.0,
            max_connect_retries=3,
            retry_delay_seconds=0.01,
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()
        sim._stop_event = asyncio.Event()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=ConnectionClosed(None, None))
        mock_ws.close = AsyncMock()

        sim._websocket = mock_ws
        sim._start_time = time.monotonic()

        with patch(
            "digital_twin_engine.simulator.simulator.websockets.connect",
            side_effect=_make_connect_coroutine(OSError("connection refused")),
        ):
            with pytest.raises(ConnectionError, match="reconnection failed"):
                await sim._send_event('{"test": "event"}')

        # Stop event should be set
        assert sim._stop_event.is_set()


# ---------------------------------------------------------------------------
# Close connection tests
# ---------------------------------------------------------------------------


class TestCloseConnection:
    """Tests for graceful WebSocket close."""

    @pytest.mark.asyncio
    async def test_close_connection_when_websocket_exists(self):
        """Should close the WebSocket and set to None."""
        config = _make_config()
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        sim._websocket = mock_ws

        await sim._close_connection()

        mock_ws.close.assert_awaited_once()
        assert sim._websocket is None

    @pytest.mark.asyncio
    async def test_close_connection_when_no_websocket(self):
        """Should not raise when websocket is None."""
        config = _make_config()
        sim = TelemetrySimulator(config, seed=42)
        sim._websocket = None

        # Should not raise
        await sim._close_connection()
        assert sim._websocket is None

    @pytest.mark.asyncio
    async def test_close_connection_handles_error_gracefully(self):
        """Should swallow exceptions during close."""
        config = _make_config()
        sim = TelemetrySimulator(config, seed=42)

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("close failed"))
        sim._websocket = mock_ws

        # Should not raise
        await sim._close_connection()
        assert sim._websocket is None
