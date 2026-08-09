"""Unit tests for the TSDB Consumer.

Tests the async consumer that reads TelemetryEvents from the message broker
and batch-writes them to the TSDB via the TSDBWriter.

Tests cover:
- Broker subscription and message deserialization
- Batch size trigger (flush when batch_size reached)
- Time window trigger (flush when 1 second elapses)
- Field value preservation (no modification during pipeline)
- Retry with exponential backoff on write failure
- Permanent failure logging with sensor_id, timestamp, and failure reason
- Graceful start/stop lifecycle

Validates: Requirements 4.1, 4.5, 4.6
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.topics import TELEMETRY_RAW
from digital_twin_engine.shared.models import TelemetryEvent, serialize_telemetry_event
from digital_twin_engine.tsdb.consumer import TSDBConsumer, TSDB_CONSUMER_GROUP
from digital_twin_engine.tsdb.writer import (
    InMemoryTSDBBackend,
    TSDBWriteError,
    TSDBWriter,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class MockBrokerBackend(BrokerBackend):
    """In-memory broker for testing the consumer.

    Captures the subscription callback so tests can manually deliver messages.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, MessageCallback] = {}
        self._started = False
        self._subscriptions: List[tuple] = []

    @property
    def started(self) -> bool:
        return self._started

    @property
    def subscriptions(self) -> List[tuple]:
        return list(self._subscriptions)

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        pass

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        self._callbacks[topic] = callback
        self._subscriptions.append((topic, group_id))

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass

    async def deliver(self, topic: str, key: str, message: bytes) -> None:
        """Simulate a message delivery to the subscribed callback."""
        if topic in self._callbacks:
            await self._callbacks[topic](topic, key, message)


def make_event(
    sensor_id: str = "sensor-001",
    measurement_type: str = "temperature",
    value: float = 25.0,
    timestamp: Optional[datetime] = None,
) -> TelemetryEvent:
    """Helper to create a TelemetryEvent."""
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return TelemetryEvent(
        timestamp=timestamp,
        sensor_id=sensor_id,
        measurement_type=measurement_type,
        value=value,
    )


def serialize_event(event: TelemetryEvent) -> bytes:
    """Serialize an event to JSON bytes as it would appear on the broker."""
    return serialize_telemetry_event(event).encode("utf-8")


# ---------------------------------------------------------------------------
# Test: Broker subscription
# ---------------------------------------------------------------------------


class TestBrokerSubscription:
    """Test that the consumer correctly subscribes to the broker."""

    @pytest.mark.asyncio
    async def test_subscribes_to_telemetry_raw_topic(self):
        """Consumer subscribes to the telemetry.raw topic on start."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(broker=broker, tsdb_backend=backend, batch_size=100)

        await consumer.start()
        try:
            assert len(broker.subscriptions) == 1
            topic, group_id = broker.subscriptions[0]
            assert topic == TELEMETRY_RAW
            assert group_id == TSDB_CONSUMER_GROUP
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_custom_consumer_group(self):
        """Consumer uses a custom group ID when specified."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            consumer_group="custom-group",
        )

        await consumer.start()
        try:
            _, group_id = broker.subscriptions[0]
            assert group_id == "custom-group"
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_is_running_after_start(self):
        """Consumer reports running state after start."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(broker=broker, tsdb_backend=backend)

        assert not consumer.is_running
        await consumer.start()
        assert consumer.is_running
        await consumer.stop()
        assert not consumer.is_running


# ---------------------------------------------------------------------------
# Test: Message deserialization and buffering
# ---------------------------------------------------------------------------


class TestMessageDeserialization:
    """Test that messages from the broker are correctly deserialized."""

    @pytest.mark.asyncio
    async def test_valid_message_is_buffered(self):
        """A valid JSON message is deserialized and added to the writer buffer."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker, tsdb_backend=backend, batch_size=10
        )

        await consumer.start()
        try:
            event = make_event()
            await broker.deliver(TELEMETRY_RAW, event.sensor_id, serialize_event(event))

            # Event should be in the buffer (not yet flushed)
            assert consumer.writer.buffer_size == 1
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_invalid_message_is_skipped(self):
        """Invalid JSON is logged and skipped without crashing."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker, tsdb_backend=backend, batch_size=10
        )

        await consumer.start()
        try:
            # Deliver an invalid message
            await broker.deliver(TELEMETRY_RAW, "bad-sensor", b"not-valid-json{")

            # Buffer should remain empty
            assert consumer.writer.buffer_size == 0
            # No crash
            assert consumer.is_running
        finally:
            await consumer.stop()


# ---------------------------------------------------------------------------
# Test: Batch size trigger
# ---------------------------------------------------------------------------


class TestBatchSizeTrigger:
    """Test that reaching batch_size triggers a flush."""

    @pytest.mark.asyncio
    async def test_flush_on_batch_size_reached(self):
        """Buffer is flushed to TSDB when batch_size events are received."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        batch_size = 5
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=batch_size,
            batch_window_seconds=10.0,  # Large window to ensure size triggers first
        )

        await consumer.start()
        try:
            # Deliver exactly batch_size events
            for i in range(batch_size):
                event = make_event(sensor_id=f"sensor-{i}", value=float(i))
                await broker.deliver(
                    TELEMETRY_RAW, event.sensor_id, serialize_event(event)
                )

            # All events should be written to the backend
            assert len(backend.events) == batch_size
            assert consumer.writer.buffer_size == 0
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_partial_batch_not_flushed_by_size(self):
        """Events below batch_size stay in buffer (not flushed by size)."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=10,
            batch_window_seconds=10.0,  # Large window
        )

        await consumer.start()
        try:
            # Deliver fewer events than batch_size
            for i in range(3):
                event = make_event(sensor_id=f"sensor-{i}", value=float(i))
                await broker.deliver(
                    TELEMETRY_RAW, event.sensor_id, serialize_event(event)
                )

            # Events should still be in the buffer
            assert consumer.writer.buffer_size == 3
            assert len(backend.events) == 0
        finally:
            await consumer.stop()


# ---------------------------------------------------------------------------
# Test: Time window trigger
# ---------------------------------------------------------------------------


class TestTimeWindowTrigger:
    """Test that the 1-second time window triggers a flush."""

    @pytest.mark.asyncio
    async def test_flush_after_time_window_elapses(self):
        """Events are flushed when the time window elapses."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=1000,  # Large batch size to ensure time triggers first
            batch_window_seconds=0.3,  # Short window for testing
        )

        await consumer.start()
        try:
            # Deliver some events (less than batch_size)
            for i in range(3):
                event = make_event(sensor_id=f"sensor-{i}", value=float(i))
                await broker.deliver(
                    TELEMETRY_RAW, event.sensor_id, serialize_event(event)
                )

            # Wait for the time window to trigger flush
            await asyncio.sleep(0.6)

            # Events should now be written
            assert len(backend.events) == 3
            assert consumer.writer.buffer_size == 0
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_no_flush_before_time_window(self):
        """Events are NOT flushed before the time window elapses."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=1000,
            batch_window_seconds=2.0,  # Long window
        )

        await consumer.start()
        try:
            event = make_event()
            await broker.deliver(TELEMETRY_RAW, event.sensor_id, serialize_event(event))

            # Check immediately - should not be flushed
            assert consumer.writer.buffer_size == 1
            assert len(backend.events) == 0
        finally:
            await consumer.stop()


# ---------------------------------------------------------------------------
# Test: Field value preservation
# ---------------------------------------------------------------------------


class TestFieldValuePreservation:
    """Test that all original field values are preserved without modification."""

    @pytest.mark.asyncio
    async def test_all_fields_preserved_through_pipeline(self):
        """Timestamp, sensor_id, measurement_type, and value are unchanged."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker, tsdb_backend=backend, batch_size=1
        )

        await consumer.start()
        try:
            original = make_event(
                sensor_id="turbine-001-temp",
                measurement_type="temperature_celsius",
                value=342.17,
                timestamp=datetime(2024, 1, 15, 10, 30, 0, 123456, tzinfo=timezone.utc),
            )
            await broker.deliver(
                TELEMETRY_RAW, original.sensor_id, serialize_event(original)
            )

            # Verify written event matches original
            assert len(backend.events) == 1
            written = backend.events[0]
            assert written.timestamp == original.timestamp
            assert written.sensor_id == original.sensor_id
            assert written.measurement_type == original.measurement_type
            assert written.value == original.value
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_float_precision_preserved(self):
        """Float64 values are preserved within 15 significant digits."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker, tsdb_backend=backend, batch_size=1
        )

        await consumer.start()
        try:
            # Use a value that round-trips exactly through 15-digit serialization
            original = make_event(value=342.17)
            await broker.deliver(
                TELEMETRY_RAW, original.sensor_id, serialize_event(original)
            )

            assert len(backend.events) == 1
            assert backend.events[0].value == 342.17
        finally:
            await consumer.stop()


# ---------------------------------------------------------------------------
# Test: Retry with exponential backoff
# ---------------------------------------------------------------------------


class TestRetryOnWriteFailure:
    """Test retry behavior on TSDB write failure."""

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self):
        """Writer retries on transient failure and eventually succeeds."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        # Fail first 2 writes, then succeed
        backend.set_fail_writes(True)

        call_count = 0
        original_write = backend.write_events

        async def failing_then_success(events):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TSDBWriteError(
                    "Transient failure",
                    sensor_id=events[0].sensor_id,
                    timestamp=str(events[0].timestamp),
                )
            backend._events.extend(events)

        backend.write_events = failing_then_success
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=1,
            max_retries=3,
            initial_retry_delay_ms=1,  # Fast for tests
        )

        await consumer.start()
        try:
            event = make_event()
            await broker.deliver(TELEMETRY_RAW, event.sensor_id, serialize_event(event))

            # Should have succeeded after retries
            assert len(backend._events) == 1
            assert consumer.writer.failure_log == []
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_logs_permanent_failure_after_retry_exhaustion(self):
        """After 3 retries, failure is logged with required fields."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        backend.set_fail_writes(True)  # Always fail

        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=1,
            max_retries=3,
            initial_retry_delay_ms=1,
        )

        await consumer.start()
        try:
            event = make_event(
                sensor_id="failed-sensor",
                timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
            await broker.deliver(TELEMETRY_RAW, event.sensor_id, serialize_event(event))

            # Verify permanent failure was logged
            failures = consumer.writer.failure_log
            assert len(failures) == 1

            failure = failures[0]
            assert failure.sensor_id == "failed-sensor"
            assert failure.timestamp == event.timestamp
            assert failure.failure_reason != ""
            assert failure.retry_count == 3
        finally:
            await consumer.stop()


# ---------------------------------------------------------------------------
# Test: Stop flushes remaining buffer
# ---------------------------------------------------------------------------


class TestStopBehavior:
    """Test that stopping the consumer flushes remaining events."""

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_buffer(self):
        """Stopping the consumer flushes any buffered events."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(
            broker=broker,
            tsdb_backend=backend,
            batch_size=100,  # Large batch size
            batch_window_seconds=10.0,  # Long window
        )

        await consumer.start()

        # Deliver some events (less than batch_size)
        for i in range(5):
            event = make_event(sensor_id=f"sensor-{i}", value=float(i))
            await broker.deliver(TELEMETRY_RAW, event.sensor_id, serialize_event(event))

        # Verify they're buffered
        assert consumer.writer.buffer_size == 5
        assert len(backend.events) == 0

        # Stop should flush
        await consumer.stop()

        assert len(backend.events) == 5
        assert consumer.writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self):
        """Calling stop twice doesn't raise."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(broker=broker, tsdb_backend=backend)

        await consumer.start()
        await consumer.stop()
        await consumer.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        """Calling start twice doesn't create duplicate subscriptions."""
        broker = MockBrokerBackend()
        backend = InMemoryTSDBBackend()
        consumer = TSDBConsumer(broker=broker, tsdb_backend=backend)

        await consumer.start()
        await consumer.start()  # Should not duplicate

        assert len(broker.subscriptions) == 1
        await consumer.stop()
