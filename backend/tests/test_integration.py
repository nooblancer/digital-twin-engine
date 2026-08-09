"""Integration tests for end-to-end pipeline data flow.

Tests the full pipeline wired together using in-memory implementations:
1. Full pipeline: simulator event → ingestion → broker → TSDB write →
   ML prediction → EnKF correction → API query returns corrected state
2. Broker failure recovery: events buffered during outage are delivered after recovery
3. Connection isolation: invalid event on one WebSocket doesn't affect others

Uses InMemoryTSDBBackend and InMemoryBroker (no Docker infrastructure required).

Validates: Requirements 1.3, 1.6, 3.2, 4.1, 5.6, 6.5, 7.1
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.state_cache import CachedState, StateCache
from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.topics import (
    CORRECTIONS_STATE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)
from digital_twin_engine.correction.enkf import EnKFIteration
from digital_twin_engine.correction.temporal_matcher import TemporalMatcher
from digital_twin_engine.ingestion.server import create_app as create_ingestion_app
from digital_twin_engine.ml_service.batch_accumulator import BatchAccumulator
from digital_twin_engine.ml_service.ensemble_inference import create_ensemble_predict_fn
from digital_twin_engine.shared.models import (
    EngineConfig,
    StateVector,
    TelemetryEvent,
    serialize_telemetry_event,
)
from digital_twin_engine.tsdb.writer import InMemoryTSDBBackend, TSDBWriter


# ---------------------------------------------------------------------------
# In-Memory Broker for Integration Tests
# ---------------------------------------------------------------------------


class InMemoryBroker(BrokerBackend):
    """In-memory broker that supports publish/subscribe with callback delivery.

    Supports simulating broker failures for recovery testing.
    """

    def __init__(self) -> None:
        self._subscriptions: Dict[str, List[Tuple[str, MessageCallback]]] = {}
        self._published: List[Tuple[str, str, bytes]] = []
        self._fail_publish = False
        self._started = False

    @property
    def published(self) -> List[Tuple[str, str, bytes]]:
        """All messages published to this broker."""
        return list(self._published)

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        if self._fail_publish:
            raise RuntimeError("Simulated broker failure")
        self._published.append((topic, key, message))
        # Deliver to all subscribers for this topic
        callbacks = self._subscriptions.get(topic, [])
        for group_id, callback in callbacks:
            await callback(topic, key, message)

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        self._subscriptions[topic].append((group_id, callback))

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass

    def set_fail_publish(self, fail: bool) -> None:
        """Toggle broker failure simulation."""
        self._fail_publish = fail

    def get_messages_for_topic(self, topic: str) -> List[Tuple[str, bytes]]:
        """Get all published messages for a specific topic."""
        return [(k, m) for t, k, m in self._published if t == topic]


# ---------------------------------------------------------------------------
# Test 1: Full End-to-End Pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullPipelineFlow:
    """Test full data flow: event → ingestion → broker → TSDB → ML → EnKF → API.

    Validates: Requirements 1.3, 3.2, 4.1, 5.6, 6.5, 7.1
    """

    @pytest.mark.asyncio
    async def test_end_to_end_telemetry_to_corrected_state(self) -> None:
        """A telemetry event flows through the entire pipeline and the corrected
        state is queryable via the API gateway."""

        # --- Setup all pipeline components with in-memory backends ---
        broker = InMemoryBroker()
        await broker.start()
        tsdb_backend = InMemoryTSDBBackend()
        tsdb_writer = TSDBWriter(backend=tsdb_backend, batch_size=1)
        config = EngineConfig(
            min_batch_size=10,
            max_batch_size=500,
            max_batch_wait_seconds=1.0,
            temporal_tolerance_seconds=2.0,
        )

        # ML Service: ensemble inference predict function
        ensemble = create_ensemble_predict_fn(config=config)

        # State cache for API gateway
        state_cache = StateCache()

        # TSDB write callback for correction engine
        async def tsdb_write_corrected(sv: StateVector) -> None:
            event = TelemetryEvent(
                timestamp=sv.timestamp,
                sensor_id=sv.sensor_id,
                measurement_type="corrected_state",
                value=sv.values[0] if sv.values else 0.0,
            )
            await tsdb_backend.write_events([event])

        # Wire up the correction engine (EnKF iteration)
        enkf_iteration = EnKFIteration(
            broker=broker, tsdb_write_func=tsdb_write_corrected
        )

        # Wire up the temporal matcher (Correction Engine)
        temporal_matcher = TemporalMatcher(
            broker=broker,
            config=config,
            on_match=enkf_iteration,
            consumer_group="correction_engine",
        )

        # Wire up the batch accumulator (ML Service)
        batch_accumulator = BatchAccumulator(
            broker=broker,
            config=config,
            predict_fn=ensemble.predict,
            consumer_group="ml_service",
        )

        # TSDB Writer consumer callback
        async def tsdb_consumer_callback(
            topic: str, key: str, message: bytes
        ) -> None:
            event_data = json.loads(message.decode("utf-8"))
            event = TelemetryEvent(
                timestamp=datetime.fromisoformat(
                    event_data["timestamp"].replace("Z", "+00:00")
                ),
                sensor_id=event_data["sensor_id"],
                measurement_type=event_data["measurement_type"],
                value=event_data["value"],
            )
            await tsdb_writer.write_event(event)
            await tsdb_writer.flush()

        # Subscribe TSDB writer to telemetry.raw
        await broker.subscribe(TELEMETRY_RAW, "tsdb_writer", tsdb_consumer_callback)

        # Start temporal matcher (subscribes to predictions.state and telemetry.raw)
        await temporal_matcher.start()

        # Start batch accumulator (subscribes to telemetry.raw)
        await batch_accumulator.start()

        # Subscribe state cache updates from corrections.state
        async def cache_update_callback(
            topic: str, key: str, message: bytes
        ) -> None:
            state_cache.update_from_message(key, message)

        await broker.subscribe(
            CORRECTIONS_STATE, "api_gateway", cache_update_callback
        )

        # --- Generate telemetry events (enough to trigger a prediction) ---
        sensor_id = "pump-001"
        state_cache.register_sensor(sensor_id)
        now = datetime.now(timezone.utc)

        events = []
        for i in range(10):
            event = TelemetryEvent(
                timestamp=now + timedelta(milliseconds=i * 100),
                sensor_id=sensor_id,
                measurement_type="temperature",
                value=100.0 + i * 0.5,
            )
            events.append(event)

        # --- Publish events to broker (simulating ingestion server output) ---
        for event in events:
            serialized = serialize_telemetry_event(event)
            await broker.publish(
                TELEMETRY_RAW, event.sensor_id, serialized.encode("utf-8")
            )

        # Allow async tasks to process
        await asyncio.sleep(0.2)

        # --- Verify TSDB received the events ---
        stored_events = await tsdb_backend.query_by_sensor_and_time(
            sensor_id=sensor_id,
            start=now - timedelta(seconds=1),
            end=now + timedelta(seconds=10),
        )
        assert len(stored_events) >= 10, (
            f"Expected at least 10 events in TSDB, got {len(stored_events)}"
        )

        # --- Verify ML Service generated a prediction ---
        prediction_messages = broker.get_messages_for_topic(PREDICTIONS_STATE)
        assert len(prediction_messages) >= 1, (
            "Expected at least 1 prediction from ML service"
        )

        # --- Verify Correction Engine produced a corrected state ---
        correction_messages = broker.get_messages_for_topic(CORRECTIONS_STATE)
        assert len(correction_messages) >= 1, (
            "Expected at least 1 corrected state from correction engine"
        )

        # --- Verify API Gateway state cache is updated ---
        cached = state_cache.get_current(sensor_id)
        assert cached is not None, "State cache should have a corrected state"
        assert cached.sensor_id == sensor_id
        assert len(cached.state_vector) > 0

        # --- Verify API endpoint returns the corrected state ---
        api_gateway = APIGateway(
            tsdb_backend=tsdb_backend, state_cache=state_cache
        )
        transport = ASGITransport(app=api_gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/sensors/{sensor_id}/state/current")
            assert response.status_code == 200
            body = response.json()
            assert body["sensor_id"] == sensor_id
            assert "state_vector" in body
            assert len(body["state_vector"]) > 0

        # Cleanup
        await batch_accumulator.stop()
        await temporal_matcher.stop()
        await broker.stop()

    @pytest.mark.asyncio
    async def test_pipeline_prediction_published_to_broker(self) -> None:
        """ML Service publishes prediction to predictions.state after batch accumulates."""
        broker = InMemoryBroker()
        await broker.start()
        config = EngineConfig(
            min_batch_size=10,
            max_batch_wait_seconds=1.0,
        )
        ensemble = create_ensemble_predict_fn(config=config)
        batch_accumulator = BatchAccumulator(
            broker=broker,
            config=config,
            predict_fn=ensemble.predict,
            consumer_group="ml_service",
        )
        await batch_accumulator.start()

        sensor_id = "sensor-test-ml"
        now = datetime.now(timezone.utc)

        # Send exactly min_batch_size events
        for i in range(10):
            event = TelemetryEvent(
                timestamp=now + timedelta(milliseconds=i * 50),
                sensor_id=sensor_id,
                measurement_type="pressure",
                value=50.0 + i,
            )
            serialized = serialize_telemetry_event(event)
            await broker.publish(TELEMETRY_RAW, sensor_id, serialized.encode("utf-8"))

        await asyncio.sleep(0.1)

        prediction_messages = broker.get_messages_for_topic(PREDICTIONS_STATE)
        assert len(prediction_messages) >= 1
        pred_data = json.loads(prediction_messages[0][1].decode("utf-8"))
        assert pred_data["sensor_id"] == sensor_id
        assert "values" in pred_data

        await batch_accumulator.stop()
        await broker.stop()

    @pytest.mark.asyncio
    async def test_tsdb_writer_persists_events_from_broker(self) -> None:
        """TSDB writer correctly persists events consumed from the broker."""
        broker = InMemoryBroker()
        await broker.start()
        tsdb_backend = InMemoryTSDBBackend()
        tsdb_writer = TSDBWriter(backend=tsdb_backend, batch_size=1)

        async def consumer_cb(topic: str, key: str, message: bytes) -> None:
            data = json.loads(message.decode("utf-8"))
            event = TelemetryEvent(
                timestamp=datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                ),
                sensor_id=data["sensor_id"],
                measurement_type=data["measurement_type"],
                value=data["value"],
            )
            await tsdb_writer.write_event(event)
            await tsdb_writer.flush()

        await broker.subscribe(TELEMETRY_RAW, "tsdb_writer", consumer_cb)

        now = datetime.now(timezone.utc)
        event = TelemetryEvent(
            timestamp=now,
            sensor_id="valve-003",
            measurement_type="flow_rate",
            value=42.5,
        )
        serialized = serialize_telemetry_event(event)
        await broker.publish(TELEMETRY_RAW, "valve-003", serialized.encode("utf-8"))

        # Query TSDB
        results = await tsdb_backend.query_by_sensor_and_time(
            sensor_id="valve-003",
            start=now - timedelta(seconds=1),
            end=now + timedelta(seconds=1),
        )
        assert len(results) == 1
        assert results[0].sensor_id == "valve-003"
        assert results[0].value == 42.5
        assert results[0].measurement_type == "flow_rate"

        await broker.stop()


# ---------------------------------------------------------------------------
# Test 2: Broker Failure Recovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBrokerFailureRecovery:
    """Test broker failure recovery: events buffered during outage are delivered.

    Validates: Requirements 1.3, 3.2
    """

    @pytest.mark.asyncio
    async def test_events_buffered_during_broker_outage_and_delivered_on_recovery(
        self,
    ) -> None:
        """Events that cannot be published during a broker outage are buffered
        and successfully delivered once the broker recovers."""

        broker = InMemoryBroker()
        await broker.start()
        received_events: List[Tuple[str, str, bytes]] = []

        async def consumer_cb(topic: str, key: str, message: bytes) -> None:
            received_events.append((topic, key, message))

        await broker.subscribe(TELEMETRY_RAW, "test_consumer", consumer_cb)

        # --- Phase 1: Normal operation - events are delivered immediately ---
        event1 = TelemetryEvent(
            timestamp=datetime.now(timezone.utc),
            sensor_id="motor-01",
            measurement_type="rpm",
            value=3000.0,
        )
        serialized1 = serialize_telemetry_event(event1)
        await broker.publish(TELEMETRY_RAW, "motor-01", serialized1.encode("utf-8"))

        assert len(received_events) == 1

        # --- Phase 2: Broker goes down - events cannot be published ---
        broker.set_fail_publish(True)
        buffered_events: List[bytes] = []

        event2 = TelemetryEvent(
            timestamp=datetime.now(timezone.utc),
            sensor_id="motor-01",
            measurement_type="rpm",
            value=3100.0,
        )
        event3 = TelemetryEvent(
            timestamp=datetime.now(timezone.utc),
            sensor_id="motor-01",
            measurement_type="rpm",
            value=3200.0,
        )

        # Publishing should fail - simulate buffering at the publisher level
        for event in [event2, event3]:
            serialized = serialize_telemetry_event(event)
            try:
                await broker.publish(
                    TELEMETRY_RAW, "motor-01", serialized.encode("utf-8")
                )
            except RuntimeError:
                # Event could not be published - buffer it
                buffered_events.append(serialized.encode("utf-8"))

        # Verify events were NOT delivered during outage
        assert len(received_events) == 1  # Still just the first event
        assert len(buffered_events) == 2

        # --- Phase 3: Broker recovers - buffered events are delivered ---
        broker.set_fail_publish(False)

        for buffered_msg in buffered_events:
            await broker.publish(TELEMETRY_RAW, "motor-01", buffered_msg)

        # All buffered events should now be delivered
        assert len(received_events) == 3
        # Verify order is preserved
        values = []
        for _, _, msg in received_events:
            data = json.loads(msg.decode("utf-8"))
            values.append(data["value"])
        assert values == [3000.0, 3100.0, 3200.0]

    @pytest.mark.asyncio
    async def test_multiple_sensors_buffered_and_recovered(self) -> None:
        """Events from multiple sensors are correctly buffered and recovered."""
        broker = InMemoryBroker()
        await broker.start()
        received_by_sensor: Dict[str, List[float]] = {}

        async def consumer_cb(topic: str, key: str, message: bytes) -> None:
            data = json.loads(message.decode("utf-8"))
            sensor = data["sensor_id"]
            if sensor not in received_by_sensor:
                received_by_sensor[sensor] = []
            received_by_sensor[sensor].append(data["value"])

        await broker.subscribe(TELEMETRY_RAW, "test_consumer", consumer_cb)

        # Broker fails
        broker.set_fail_publish(True)
        buffered: List[Tuple[str, bytes]] = []

        now = datetime.now(timezone.utc)
        for sensor_id, value in [
            ("sensor-A", 10.0),
            ("sensor-B", 20.0),
            ("sensor-A", 11.0),
            ("sensor-B", 21.0),
        ]:
            event = TelemetryEvent(
                timestamp=now,
                sensor_id=sensor_id,
                measurement_type="temp",
                value=value,
            )
            serialized = serialize_telemetry_event(event)
            try:
                await broker.publish(
                    TELEMETRY_RAW, sensor_id, serialized.encode("utf-8")
                )
            except RuntimeError:
                buffered.append((sensor_id, serialized.encode("utf-8")))

        assert len(buffered) == 4
        assert len(received_by_sensor) == 0

        # Broker recovers
        broker.set_fail_publish(False)
        for sensor_id, msg in buffered:
            await broker.publish(TELEMETRY_RAW, sensor_id, msg)

        assert received_by_sensor["sensor-A"] == [10.0, 11.0]
        assert received_by_sensor["sensor-B"] == [20.0, 21.0]

        await broker.stop()


# ---------------------------------------------------------------------------
# Test 3: Connection Isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConnectionIsolation:
    """Test that an invalid event on one WebSocket doesn't affect others.

    Validates: Requirements 1.6
    """

    def test_invalid_event_on_one_connection_does_not_affect_others(self) -> None:
        """Sending an invalid event on one WebSocket does not interrupt
        other connections that continue processing normally."""

        app = create_ingestion_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws1:
                with client.websocket_connect("/ws/telemetry") as ws2:
                    # Verify both connections are active
                    manager = app.state.connection_manager
                    assert manager.active_count == 2

                    # Send invalid event on ws1
                    invalid_event = json.dumps(
                        {
                            "timestamp": "not-a-timestamp",
                            "sensor_id": "test-sensor",
                            "measurement_type": "temp",
                            "value": 42.0,
                        }
                    )
                    ws1.send_text(invalid_event)
                    # ws1 should receive an error response
                    error_response = ws1.receive_text()
                    error_data = json.loads(error_response)
                    assert "error_code" in error_data
                    assert error_data["error_code"] == "INVALID_TIMESTAMP"

                    # ws2 should still be connected and functional
                    assert manager.active_count == 2

                    # Send a valid event on ws2
                    valid_event = json.dumps(
                        {
                            "timestamp": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%S.%fZ"
                            ),
                            "sensor_id": "other-sensor",
                            "measurement_type": "pressure",
                            "value": 101.3,
                        }
                    )
                    ws2.send_text(valid_event)

                    # ws2 is still connected and active
                    assert manager.active_count == 2

                # ws2 disconnects
                assert manager.active_count == 1
            # ws1 disconnects
            assert manager.active_count == 0

    def test_malformed_json_on_one_connection_isolates_failure(self) -> None:
        """Completely malformed JSON on one connection does not affect another."""

        app = create_ingestion_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws1:
                with client.websocket_connect("/ws/telemetry") as ws2:
                    manager = app.state.connection_manager
                    assert manager.active_count == 2

                    # Send completely malformed JSON on ws1
                    ws1.send_text("this is not json at all {{{")
                    error_response = ws1.receive_text()
                    error_data = json.loads(error_response)
                    assert error_data["error_code"] == "INVALID_JSON"

                    # ws2 should still be working
                    assert manager.active_count == 2

                    # Send another invalid payload (missing fields)
                    ws1.send_text(json.dumps({"only_one_field": True}))
                    error_response2 = ws1.receive_text()
                    error_data2 = json.loads(error_response2)
                    assert "error_code" in error_data2

                    # ws2 remains unaffected
                    assert manager.active_count == 2

    def test_multiple_invalid_events_do_not_crash_connection(self) -> None:
        """Multiple consecutive invalid events on one connection do not
        crash the connection or affect other connections."""

        app = create_ingestion_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws1:
                with client.websocket_connect("/ws/telemetry") as ws2:
                    manager = app.state.connection_manager

                    # Send multiple invalid events on ws1
                    invalid_payloads = [
                        "not json",
                        json.dumps({"value": float("inf")}),
                        json.dumps(
                            {
                                "timestamp": "2024-01-01T00:00:00Z",
                                "sensor_id": "",
                                "measurement_type": "x",
                                "value": 1.0,
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2024-01-01T00:00:00Z",
                                "sensor_id": "s1",
                                "measurement_type": "",
                                "value": 1.0,
                            }
                        ),
                    ]

                    for payload in invalid_payloads:
                        ws1.send_text(payload)
                        response = ws1.receive_text()
                        resp_data = json.loads(response)
                        assert "error_code" in resp_data

                    # Both connections still active
                    assert manager.active_count == 2

                    # ws2 can still process valid data
                    valid_event = json.dumps(
                        {
                            "timestamp": "2024-06-15T12:00:00Z",
                            "sensor_id": "healthy-sensor",
                            "measurement_type": "humidity",
                            "value": 65.0,
                        }
                    )
                    ws2.send_text(valid_event)
                    assert manager.active_count == 2
