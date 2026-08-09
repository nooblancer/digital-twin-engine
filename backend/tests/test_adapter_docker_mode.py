"""Tests for the C-MAPSS adapter Docker mode entry point.

Validates: Requirements 6.1, 6.2, 6.3, 6.4
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.adapters.__main__ import (
    _INITIAL_BACKOFF_S,
    _MAX_BACKOFF_S,
    _BACKOFF_MULTIPLIER,
    _wait_for_health,
    _stream_to_websocket,
    run_docker_mode,
)
from digital_twin_engine.adapters.cmapss_replay import CMAPSSConfig


# ---------------------------------------------------------------------------
# Tests for _wait_for_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_health_succeeds_immediately():
    """Health check passes on first attempt."""
    with patch(
        "digital_twin_engine.adapters.__main__.urllib.request.urlopen"
    ) as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        await _wait_for_health("http://ingestion-server:8080")
        mock_urlopen.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_health_retries_on_failure():
    """Health check retries with backoff when server is unavailable."""
    import urllib.error

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise urllib.error.URLError("Connection refused")
        return MagicMock()

    with patch(
        "digital_twin_engine.adapters.__main__.urllib.request.urlopen",
        side_effect=side_effect,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _wait_for_health("http://ingestion-server:8080")
            assert call_count == 3
            # Should have slept twice (before 2nd and 3rd attempts)
            assert mock_sleep.call_count == 2
            # First sleep should be initial backoff
            mock_sleep.assert_any_call(_INITIAL_BACKOFF_S)
            # Second sleep should be doubled
            mock_sleep.assert_any_call(_INITIAL_BACKOFF_S * _BACKOFF_MULTIPLIER)


# ---------------------------------------------------------------------------
# Tests for run_docker_mode reconnection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_docker_mode_retries_on_connection_loss():
    """Adapter retries WebSocket connection on disconnection (Requirement 6.4)."""
    import websockets.exceptions

    attempt_count = 0

    async def mock_stream_to_ws(ws_url, config):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise websockets.exceptions.ConnectionClosed(None, None)
        # On 3rd attempt, raise KeyboardInterrupt to stop the loop
        raise KeyboardInterrupt("Stop test")

    with patch(
        "digital_twin_engine.adapters.__main__._wait_for_health",
        new_callable=AsyncMock,
    ) as mock_health:
        with patch(
            "digital_twin_engine.adapters.__main__._stream_to_websocket",
            side_effect=mock_stream_to_ws,
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                config = CMAPSSConfig(data_dir="data/cmapss", dataset="FD001")
                with pytest.raises(KeyboardInterrupt):
                    await run_docker_mode("http://ingestion-server:8080", config)

                assert attempt_count == 3
                # Health check called: once at start + twice on reconnection
                assert mock_health.call_count == 3


# ---------------------------------------------------------------------------
# Tests for backoff parameters
# ---------------------------------------------------------------------------


def test_backoff_parameters():
    """Verify backoff configuration matches design (1s initial, 30s max)."""
    assert _INITIAL_BACKOFF_S == 1.0
    assert _MAX_BACKOFF_S == 30.0
    assert _BACKOFF_MULTIPLIER == 2.0


def test_backoff_capping():
    """Verify backoff never exceeds MAX_BACKOFF_S."""
    backoff = _INITIAL_BACKOFF_S
    for _ in range(20):
        backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)
    assert backoff == _MAX_BACKOFF_S


# ---------------------------------------------------------------------------
# Tests for main() Docker mode detection
# ---------------------------------------------------------------------------


def test_main_detects_docker_mode_via_env():
    """main() uses INGESTION_URL env var to detect Docker mode."""
    from digital_twin_engine.adapters.__main__ import main

    with patch.dict(os.environ, {"INGESTION_URL": "http://ingestion-server:8080"}):
        with patch(
            "digital_twin_engine.adapters.__main__.asyncio.run"
        ) as mock_run:
            with patch("sys.argv", ["__main__"]):
                main()
                mock_run.assert_called_once()
                # The coroutine passed to asyncio.run should be run_docker_mode
                coro = mock_run.call_args[0][0]
                assert coro is not None


def test_main_defaults_to_standalone_mode():
    """main() runs standalone mode when INGESTION_URL is not set."""
    from digital_twin_engine.adapters.__main__ import main

    with patch.dict(os.environ, {}, clear=False):
        # Make sure INGESTION_URL is not set
        os.environ.pop("INGESTION_URL", None)
        with patch(
            "digital_twin_engine.adapters.__main__.asyncio.run"
        ) as mock_run:
            with patch("sys.argv", ["__main__"]):
                main()
                mock_run.assert_called_once()
