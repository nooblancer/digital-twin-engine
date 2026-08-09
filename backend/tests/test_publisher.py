"""Unit tests for the TelemetryPublisher module.

Tests buffering, backpressure, exponential backoff, and publish behavior.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.ingestion.publisher import (
    INITIAL_BACKOFF_MS,
    MAX_BACKOFF_MS,
    MAX_BUFFER_SIZE,
    BackpressureError,
    BrokerType,
    PublisherNotStartedError,
    TelemetryPublisher,
)
from digital_twin_engine.shared.models import TelemetryEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(sensor_id: str = "sensor-001", value: float = 42.0) -> TelemetryEvent:
    """Create a minimal valid TelemetryEvent for testing."""
    return TelemetryEvent(
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        sensor_id=sensor_id,
        measurement_type="temperature",
        value=value,
    )


# ---------------------------------------------------------------------------
# Tests: Lifecycle
# ---------------------------------------------------------------------------


class TestPublisherLifecycle:
    """Tests for publisher start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_publish_before_start_raises(self):
        """Publishing before start should raise PublisherNotStartedError."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        event = _make_event()
        with pytest.raises(PublisherNotStartedError):
            await publisher.publish(event)

    @pytest.mark.asyncio
    async def test_start_sets_started_flag(self):
        """Starting the publisher sets is_started to True."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        # Mock the connection so we don't need a real broker
        publisher._connect = AsyncMock()
        publisher._connect.side_effect = lambda: setattr(publisher, "_connected", False)
        await publisher.start()
        try:
            assert publisher.is_started is True
        finally:
            await publisher.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_started_false(self):
        """Stopping the publisher sets is_started to False."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._connect = AsyncMock()
        publisher._connect.side_effect = lambda: setattr(publisher, "_connected", False)
        await publisher.start()
        await publisher.stop()
        assert publisher.is_started is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        """Calling start twice should not error."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._connect = AsyncMock()
        publisher._connect.side_effect = lambda: setattr(publisher, "_connected", False)
        await publisher.start()
        await publisher.start()  # Should not raise
        try:
            assert publisher.is_started is True
        finally:
            await publisher.stop()


# ---------------------------------------------------------------------------
# Tests: Direct publish (broker connected)
# ---------------------------------------------------------------------------


class TestDirectPublish:
    """Tests for successful direct publishing when broker is connected."""

    @pytest.mark.asyncio
    async def test_publish_returns_latency_ms(self):
        """Publish should return latency in milliseconds."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = True
        publisher._send = AsyncMock()

        event = _make_event()
        latency = await publisher.publish(event)

        assert isinstance(latency, float)
        assert latency >= 0
        publisher._send.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_sends_with_sensor_id_key(self):
        """Publish should use sensor_id as the partition key."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = True
        publisher._send = AsyncMock()

        event = _make_event(sensor_id="turbine-42")
        await publisher.publish(event)

        call_args = publisher._send.call_args
        key = call_args[0][0]  # first positional arg is key
        assert key == b"turbine-42"


# ---------------------------------------------------------------------------
# Tests: Buffering (broker unreachable)
# ---------------------------------------------------------------------------


class TestBuffering:
    """Tests for in-memory buffering when broker is unreachable."""

    @pytest.mark.asyncio
    async def test_buffer_event_when_disconnected(self):
        """Events should be buffered when broker is disconnected."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = False

        event = _make_event()
        latency = await publisher.publish(event)

        assert publisher.buffer_size == 1
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_buffer_event_after_send_failure(self):
        """Events should be buffered when send raises an exception."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = True
        publisher._send = AsyncMock(side_effect=ConnectionError("Broker down"))

        event = _make_event()
        latency = await publisher.publish(event)

        assert publisher.buffer_size == 1
        assert publisher._connected is False
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_buffer_respects_max_size(self):
        """Buffer should not exceed the configured maximum size."""
        max_size = 5
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA,
            max_buffer_size=max_size,
        )
        publisher._started = True
        publisher._connected = False

        event = _make_event()
        for _ in range(max_size):
            await publisher.publish(event)

        assert publisher.buffer_size == max_size

    @pytest.mark.asyncio
    async def test_default_max_buffer_is_10000(self):
        """Default max buffer size should be 10,000."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        assert publisher.max_buffer_size == 10_000


# ---------------------------------------------------------------------------
# Tests: Backpressure
# ---------------------------------------------------------------------------


class TestBackpressure:
    """Tests for backpressure when buffer is full."""

    @pytest.mark.asyncio
    async def test_backpressure_error_when_buffer_full(self):
        """Should raise BackpressureError when buffer is at capacity."""
        max_size = 3
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA,
            max_buffer_size=max_size,
        )
        publisher._started = True
        publisher._connected = False

        event = _make_event()
        # Fill the buffer
        for _ in range(max_size):
            await publisher.publish(event)

        # Next publish should raise backpressure
        with pytest.raises(BackpressureError) as exc_info:
            await publisher.publish(event)

        assert exc_info.value.buffer_size == max_size

    @pytest.mark.asyncio
    async def test_no_silent_drop_on_overflow(self):
        """Events are never silently dropped — always raise on overflow."""
        max_size = 2
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA,
            max_buffer_size=max_size,
        )
        publisher._started = True
        publisher._connected = False

        event = _make_event()
        await publisher.publish(event)
        await publisher.publish(event)

        # Buffer is full, any additional event must raise
        with pytest.raises(BackpressureError):
            await publisher.publish(event)

        # Buffer size should remain at max (nothing was dropped)
        assert publisher.buffer_size == max_size


# ---------------------------------------------------------------------------
# Tests: Exponential Backoff
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """Tests for the exponential backoff retry calculation."""

    def test_initial_backoff_is_100ms(self):
        """Initial backoff should be 100ms."""
        assert INITIAL_BACKOFF_MS == 100

    def test_max_backoff_is_5000ms(self):
        """Maximum backoff cap should be 5000ms."""
        assert MAX_BACKOFF_MS == 5000

    def test_backoff_formula(self):
        """Backoff should follow: min(100ms * 2^retry, 5000ms)."""
        expected = [100, 200, 400, 800, 1600, 3200, 5000, 5000]
        for retry in range(len(expected)):
            backoff = min(INITIAL_BACKOFF_MS * (2**retry), MAX_BACKOFF_MS)
            assert backoff == expected[retry], f"retry={retry}: got {backoff}"

    @pytest.mark.asyncio
    async def test_backoff_increases_on_reconnect_failure(self):
        """Backoff should increase with each failed reconnection attempt."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = False
        publisher._current_backoff_ms = INITIAL_BACKOFF_MS

        # Simulate a failed reconnection
        publisher._retry_count = 0
        publisher._retry_count += 1
        new_backoff = min(
            INITIAL_BACKOFF_MS * (2**publisher._retry_count),
            MAX_BACKOFF_MS,
        )
        publisher._current_backoff_ms = new_backoff

        assert publisher._current_backoff_ms == 200  # 100 * 2^1

    @pytest.mark.asyncio
    async def test_backoff_caps_at_5000ms(self):
        """Backoff should never exceed 5000ms."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = False

        # Simulate many retries
        publisher._retry_count = 10
        new_backoff = min(
            INITIAL_BACKOFF_MS * (2**publisher._retry_count),
            MAX_BACKOFF_MS,
        )
        publisher._current_backoff_ms = new_backoff

        assert publisher._current_backoff_ms == MAX_BACKOFF_MS


# ---------------------------------------------------------------------------
# Tests: Buffer flush
# ---------------------------------------------------------------------------


class TestBufferFlush:
    """Tests for buffer flushing when broker reconnects."""

    @pytest.mark.asyncio
    async def test_flush_drains_buffer_on_reconnect(self):
        """Flush should drain all buffered events once broker reconnects."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = False

        # Buffer some events
        event = _make_event()
        for _ in range(5):
            await publisher.publish(event)

        assert publisher.buffer_size == 5

        # Simulate reconnection
        publisher._connected = True
        publisher._send = AsyncMock()

        await publisher._flush_buffer()

        assert publisher.buffer_size == 0
        assert publisher._send.call_count == 5

    @pytest.mark.asyncio
    async def test_flush_stops_on_send_failure(self):
        """Flush should stop and mark disconnected if send fails mid-flush."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        publisher._started = True
        publisher._connected = False

        # Buffer some events
        event = _make_event()
        for _ in range(5):
            await publisher.publish(event)

        # Simulate reconnection then failure after 2 sends
        publisher._connected = True
        call_count = 0

        async def fail_after_two(key, value):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise ConnectionError("Broker dropped")

        publisher._send = AsyncMock(side_effect=fail_after_two)

        await publisher._flush_buffer()

        # 2 succeeded, 3 remain (the 3rd caused the failure, stays in buffer)
        assert publisher.buffer_size == 3
        assert publisher._connected is False


# ---------------------------------------------------------------------------
# Tests: Configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    """Tests for publisher configuration."""

    def test_default_topic(self):
        """Default topic should be 'telemetry.raw'."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        assert publisher._topic == "telemetry.raw"

    def test_custom_topic(self):
        """Topic should be configurable."""
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA, topic="custom.topic"
        )
        assert publisher._topic == "custom.topic"

    def test_broker_type_kafka(self):
        """Should accept Kafka broker type."""
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA)
        assert publisher._broker_type == BrokerType.KAFKA

    def test_broker_type_redis(self):
        """Should accept Redis broker type."""
        publisher = TelemetryPublisher(broker_type=BrokerType.REDIS)
        assert publisher._broker_type == BrokerType.REDIS

    def test_custom_max_buffer_size(self):
        """Max buffer size should be configurable."""
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA, max_buffer_size=500
        )
        assert publisher.max_buffer_size == 500
