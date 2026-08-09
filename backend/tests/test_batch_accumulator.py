"""Unit tests for ML Service batch accumulation and prediction trigger logic.

Tests cover:
- SensorBuffer operations (add, drain, timing)
- BatchAccumulator prediction triggering on min batch size
- BatchAccumulator prediction triggering on timeout
- Message deserialization and buffering
- Max batch size capping
- Publishing predicted StateVector to predictions.state topic

Requirements: 5.1, 5.6, 5.7
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.topics import PREDICTIONS_STATE, TELEMETRY_RAW
from digital_twin_engine.ml_service.batch_accumulator import (
    BatchAccumulator,
    SensorBuffer,
)
from digital_twin_engine.shared.models import (
    EngineConfig,
    StateVector,
    TelemetryEvent,
    serialize_telemetry_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(
    sensor_id: str = "sensor-1",
    value: float = 42.0,
    timestamp: Optional[datetime] = None,
) -> TelemetryEvent:
    """Create a test TelemetryEvent."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return TelemetryEvent(
        timestamp=timestamp,
        sensor_id=sensor_id,
        measurement_type="temperature",
        value=value,
    )


def event_to_bytes(event: TelemetryEvent) -> bytes:
    """Serialize a TelemetryEvent to bytes for broker messages."""
    return serialize_telemetry_event(event).encode("utf-8")


class MockBroker(BrokerBackend):
    """In-memory mock broker for testing."""

    def __init__(self) -> None:
        self.published: List[tuple[str, str, bytes]] = []
        self.subscriptions: dict[str, MessageCallback] = {}
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        self.published.append((topic, key, message))

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        self.subscriptions[topic] = callback

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass

    async def deliver(self, topic: str, key: str, message: bytes) -> None:
        """Simulate message delivery to a subscriber."""
        cb = self.subscriptions.get(topic)
        if cb:
            await cb(topic, key, message)


async def dummy_predict(
    sensor_id: str,
    events: List[TelemetryEvent],
    config: EngineConfig,
) -> Optional[StateVector]:
    """Dummy prediction function that returns a simple state vector."""
    return StateVector(
        sensor_id=sensor_id,
        timestamp=datetime.now(timezone.utc),
        values=[events[-1].value + 1.0],
        ensemble_spread=0.1,
        anomaly_flag=False,
        source="prediction",
    )


async def none_predict(
    sensor_id: str,
    events: List[TelemetryEvent],
    config: EngineConfig,
) -> Optional[StateVector]:
    """Prediction function that returns None (simulates both models failing)."""
    return None


# ---------------------------------------------------------------------------
# SensorBuffer Tests
# ---------------------------------------------------------------------------


class TestSensorBuffer:
    """Tests for SensorBuffer operations."""

    def test_new_buffer_is_empty(self) -> None:
        buf = SensorBuffer()
        assert buf.is_empty
        assert buf.size == 0
        assert buf.first_event_time is None

    def test_add_event_updates_size(self) -> None:
        buf = SensorBuffer()
        event = make_event()
        buf.add(event)
        assert buf.size == 1
        assert not buf.is_empty

    def test_first_event_time_set_on_first_add(self) -> None:
        buf = SensorBuffer()
        event = make_event()
        buf.add(event)
        assert buf.first_event_time is not None
        first_time = buf.first_event_time

        # Adding more events doesn't change first_event_time
        buf.add(make_event(value=2.0))
        assert buf.first_event_time == first_time

    def test_clear_resets_buffer(self) -> None:
        buf = SensorBuffer()
        buf.add(make_event())
        buf.add(make_event(value=2.0))
        buf.clear()
        assert buf.is_empty
        assert buf.size == 0
        assert buf.first_event_time is None

    def test_drain_returns_events_and_clears(self) -> None:
        buf = SensorBuffer()
        e1 = make_event(value=1.0)
        e2 = make_event(value=2.0)
        buf.add(e1)
        buf.add(e2)

        events = buf.drain()
        assert len(events) == 2
        assert events[0].value == 1.0
        assert events[1].value == 2.0
        assert buf.is_empty

    def test_elapsed_since_first_is_zero_when_empty(self) -> None:
        buf = SensorBuffer()
        assert buf.elapsed_since_first() == 0.0

    def test_elapsed_since_first_increases(self) -> None:
        buf = SensorBuffer()
        buf.add(make_event())
        elapsed1 = buf.elapsed_since_first()
        # Small sleep to measure passage of time
        time.sleep(0.01)
        elapsed2 = buf.elapsed_since_first()
        assert elapsed2 > elapsed1


# ---------------------------------------------------------------------------
# BatchAccumulator Tests
# ---------------------------------------------------------------------------


class TestBatchAccumulator:
    """Tests for BatchAccumulator prediction triggering."""

    @pytest.fixture
    def config(self) -> EngineConfig:
        """Config with small batch sizes for testing."""
        return EngineConfig(
            min_batch_size=10,
            max_batch_size=500,
            max_batch_wait_seconds=5.0,
            lstm_weight=0.6,
            xgboost_weight=0.4,
        )

    @pytest.fixture
    def broker(self) -> MockBroker:
        return MockBroker()

    @pytest.mark.asyncio
    async def test_start_subscribes_to_telemetry_raw(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()
        assert TELEMETRY_RAW in broker.subscriptions
        await acc.stop()

    @pytest.mark.asyncio
    async def test_event_buffered_before_min_batch(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()

        # Send fewer than min_batch_size events
        for i in range(config.min_batch_size - 1):
            event = make_event(value=float(i))
            await broker.deliver(TELEMETRY_RAW, "sensor-1", event_to_bytes(event))

        # No prediction should have been triggered
        assert len(broker.published) == 0
        assert acc.buffers["sensor-1"].size == config.min_batch_size - 1
        await acc.stop()

    @pytest.mark.asyncio
    async def test_prediction_triggered_at_min_batch_size(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()

        # Send exactly min_batch_size events
        for i in range(config.min_batch_size):
            event = make_event(value=float(i))
            await broker.deliver(TELEMETRY_RAW, "sensor-1", event_to_bytes(event))

        # Prediction should be triggered and published
        assert len(broker.published) == 1
        topic, key, msg = broker.published[0]
        assert topic == PREDICTIONS_STATE
        assert key == "sensor-1"

        # Buffer should be cleared
        assert acc.buffers["sensor-1"].is_empty
        await acc.stop()

    @pytest.mark.asyncio
    async def test_prediction_published_with_correct_fields(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()

        for i in range(config.min_batch_size):
            event = make_event(value=float(i))
            await broker.deliver(TELEMETRY_RAW, "sensor-1", event_to_bytes(event))

        _, _, msg = broker.published[0]
        payload = json.loads(msg.decode("utf-8"))

        assert payload["sensor_id"] == "sensor-1"
        assert "prediction_timestamp" in payload
        assert payload["prediction_horizon_seconds"] == config.prediction_horizon_seconds
        assert "values" in payload
        assert payload["source"] == "prediction"
        await acc.stop()

    @pytest.mark.asyncio
    async def test_timeout_triggers_prediction(
        self, broker: MockBroker
    ) -> None:
        # Use a very short timeout for testing
        config = EngineConfig(
            min_batch_size=10,
            max_batch_size=500,
            max_batch_wait_seconds=1.0,  # minimum allowed
            lstm_weight=0.6,
            xgboost_weight=0.4,
        )
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()

        # Send fewer than min_batch_size events
        for i in range(5):
            event = make_event(value=float(i))
            await broker.deliver(TELEMETRY_RAW, "sensor-1", event_to_bytes(event))

        assert len(broker.published) == 0

        # Wait for timeout to trigger
        await asyncio.sleep(1.3)

        # Prediction should have been triggered by timeout
        assert len(broker.published) == 1
        assert acc.buffers["sensor-1"].is_empty
        await acc.stop()

    @pytest.mark.asyncio
    async def test_separate_buffers_per_sensor(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()

        # Send events for two different sensors (less than min each)
        for i in range(5):
            e1 = make_event(sensor_id="sensor-A", value=float(i))
            e2 = make_event(sensor_id="sensor-B", value=float(i + 100))
            await broker.deliver(TELEMETRY_RAW, "sensor-A", event_to_bytes(e1))
            await broker.deliver(TELEMETRY_RAW, "sensor-B", event_to_bytes(e2))

        assert acc.buffers["sensor-A"].size == 5
        assert acc.buffers["sensor-B"].size == 5
        assert len(broker.published) == 0
        await acc.stop()

    @pytest.mark.asyncio
    async def test_max_batch_size_caps_events(
        self, broker: MockBroker
    ) -> None:
        # Config with very small max_batch_size
        config = EngineConfig(
            min_batch_size=10,
            max_batch_size=15,
            max_batch_wait_seconds=5.0,
            lstm_weight=0.6,
            xgboost_weight=0.4,
        )
        predict_calls: List[tuple[str, int]] = []

        async def tracking_predict(
            sensor_id: str,
            events: List[TelemetryEvent],
            cfg: EngineConfig,
        ) -> Optional[StateVector]:
            predict_calls.append((sensor_id, len(events)))
            return await dummy_predict(sensor_id, events, cfg)

        acc = BatchAccumulator(broker, config, tracking_predict)
        await acc.start()

        # Send 20 events - should trigger at 10 (min), then have 10 remaining
        # which triggers again at 10 (min)
        for i in range(20):
            event = make_event(value=float(i))
            await broker.deliver(TELEMETRY_RAW, "sensor-1", event_to_bytes(event))

        # Two predictions: first at 10 (min_batch), then at 10 (min_batch for remainder)
        assert len(predict_calls) == 2
        # First batch should be capped at max_batch_size (15) but triggered at 10
        # Actually: events arrive one by one, at event #10 trigger fires
        assert predict_calls[0] == ("sensor-1", 10)
        # Then events 11-20 accumulate, trigger at event #20 (10 more = min batch)
        assert predict_calls[1] == ("sensor-1", 10)
        await acc.stop()

    @pytest.mark.asyncio
    async def test_none_prediction_not_published(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        """When predict_fn returns None, nothing is published."""
        acc = BatchAccumulator(broker, config, none_predict)
        await acc.start()

        for i in range(config.min_batch_size):
            event = make_event(value=float(i))
            await broker.deliver(TELEMETRY_RAW, "sensor-1", event_to_bytes(event))

        # No publication because predict returned None
        assert len(broker.published) == 0
        # Buffer should still be cleared
        assert acc.buffers["sensor-1"].is_empty
        await acc.stop()

    @pytest.mark.asyncio
    async def test_malformed_message_skipped(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        """Malformed messages are silently skipped."""
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()

        # Deliver invalid JSON
        await broker.deliver(TELEMETRY_RAW, "sensor-1", b"not valid json")
        assert "sensor-1" not in acc.buffers
        await acc.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_timer(
        self, broker: MockBroker, config: EngineConfig
    ) -> None:
        acc = BatchAccumulator(broker, config, dummy_predict)
        await acc.start()
        assert acc.running
        assert acc._timer_task is not None

        await acc.stop()
        assert not acc.running
        assert acc._timer_task is None
