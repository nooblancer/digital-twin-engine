"""Integration tests for end-to-end digital twin data pipeline.

Tests the full data flow through the digital twin services:
1. corrections.state → RUL Predictor → WebSocket rul_update emission
2. corrections.state → Health Index Aggregator → WebSocket health_index_update emission
3. Snapshot endpoint returns correct aggregated state from all services

Uses InMemoryBrokerBackend and a capture-based WebSocket manager mock.

Validates: Requirements 8.1, 8.2, 8.3, 8.5
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Tuple

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.engines import configure_engine_services
from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.memory_backend import InMemoryBrokerBackend
from digital_twin_engine.broker.topics import CORRECTIONS_STATE
from digital_twin_engine.prognostics.component_health import ComponentHealthMapper
from digital_twin_engine.prognostics.degradation_tracker import DegradationCurveTracker
from digital_twin_engine.prognostics.health_index import (
    ALL_SENSORS,
    HealthIndexAggregator,
)
from digital_twin_engine.prognostics.rul_predictor import RULPredictor

# Mark all tests in this module as not requiring Docker infrastructure.
# They use InMemoryBrokerBackend and in-process FastAPI test client.
pytestmark = pytest.mark.no_docker


# ---------------------------------------------------------------------------
# Capture WebSocket Manager - records all broadcasts for assertion
# ---------------------------------------------------------------------------


class CaptureWebSocketManager:
    """A mock WebSocket manager that captures broadcast calls for testing.

    Records all broadcast calls as (message_type, payload) tuples so tests
    can assert on the messages that would have been sent to connected clients.
    """

    def __init__(self) -> None:
        self.broadcasts: List[Tuple[str, Dict[str, Any]]] = []

    async def broadcast(self, message_type: str, payload: dict) -> None:
        """Capture a broadcast call."""
        self.broadcasts.append((message_type, payload))

    def get_messages_of_type(self, message_type: str) -> List[Dict[str, Any]]:
        """Return all captured payloads for a given message type."""
        return [p for t, p in self.broadcasts if t == message_type]

    def clear(self) -> None:
        """Clear all captured broadcasts."""
        self.broadcasts.clear()


# ---------------------------------------------------------------------------
# Helper: Publish simulated correction state messages
# ---------------------------------------------------------------------------


def _build_correction_message(sensor_id: str, value: float, cycle: int) -> bytes:
    """Build a JSON correction message matching the expected format.

    Args:
        sensor_id: Full sensor ID (e.g., "engine-001-hpc_outlet_temp_total").
        value: The corrected sensor value.
        cycle: The cycle number.

    Returns:
        JSON-encoded bytes payload.
    """
    payload = {
        "sensor_id": sensor_id,
        "corrected_state_vector": [value],
        "cycle": cycle,
    }
    return json.dumps(payload).encode()


async def _publish_full_cycle(
    broker: InMemoryBrokerBackend,
    engine_id: int,
    cycle: int,
    base_value: float = 500.0,
    deviation_factor: float = 0.0,
) -> None:
    """Publish a full cycle of 21 sensor readings for an engine.

    Args:
        broker: The broker to publish messages to.
        engine_id: The engine unit ID (integer).
        cycle: The cycle number.
        base_value: Base sensor value (all sensors get this value).
        deviation_factor: Multiplier for adding deviation from base.
            0.0 means nominal values, higher means more degradation.
    """
    for i, sensor_name in enumerate(ALL_SENSORS):
        # Each sensor gets a slightly different value to be realistic.
        # A small cycle-dependent jitter ensures baseline std > 0 so
        # the RUL predictor's piecewise-linear model can function.
        jitter = (cycle % 5) * 0.1  # Small variation across baseline cycles
        value = base_value + (i * 10.0) + jitter + (deviation_factor * i * 5.0)
        sensor_key = f"engine-{engine_id:03d}-{sensor_name}"
        message = _build_correction_message(sensor_key, value, cycle)
        await broker.publish(CORRECTIONS_STATE, sensor_key, message)


async def _drain_broker_tasks(broker: InMemoryBrokerBackend) -> None:
    """Wait for all pending broker delivery tasks to complete."""
    # Give the event loop time to process all scheduled tasks
    for _ in range(10):
        await asyncio.sleep(0.01)
        # Wait for any pending tasks in the broker
        if hasattr(broker, "_pending_tasks"):
            pending = [t for t in broker._pending_tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            else:
                break


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def broker() -> InMemoryBrokerBackend:
    """Create an InMemoryBrokerBackend for testing."""
    return InMemoryBrokerBackend()


@pytest.fixture
def ws_manager() -> CaptureWebSocketManager:
    """Create a capture WebSocket manager for testing."""
    return CaptureWebSocketManager()


@pytest.fixture
def rul_predictor(
    broker: InMemoryBrokerBackend, ws_manager: CaptureWebSocketManager
) -> RULPredictor:
    """Create a RUL Predictor wired to the test broker and WS manager."""
    return RULPredictor(broker=broker, ws_manager=ws_manager)  # type: ignore


@pytest.fixture
def health_aggregator(
    broker: InMemoryBrokerBackend, ws_manager: CaptureWebSocketManager
) -> HealthIndexAggregator:
    """Create a Health Index Aggregator wired to the test broker and WS manager."""
    return HealthIndexAggregator(broker=broker, ws_manager=ws_manager)  # type: ignore


@pytest.fixture
def component_mapper(
    broker: InMemoryBrokerBackend, ws_manager: CaptureWebSocketManager
) -> ComponentHealthMapper:
    """Create a Component Health Mapper wired to the test broker and WS manager."""
    return ComponentHealthMapper(broker=broker, ws_manager=ws_manager)  # type: ignore


@pytest.fixture
def degradation_tracker(
    ws_manager: CaptureWebSocketManager,
) -> DegradationCurveTracker:
    """Create a Degradation Curve Tracker wired to the WS manager."""
    return DegradationCurveTracker(ws_manager=ws_manager)  # type: ignore


@pytest.fixture(autouse=True)
def _cleanup_services():
    """Reset global service references after each test."""
    yield
    configure_engine_services(
        rul_predictor=None,
        health_index_aggregator=None,
        component_health_mapper=None,
        degradation_tracker=None,
    )


# ---------------------------------------------------------------------------
# Integration Tests: RUL Pipeline
# ---------------------------------------------------------------------------


class TestRULPipeline:
    """Integration tests for corrections.state → RUL Predictor → WebSocket."""

    @pytest.mark.asyncio
    async def test_rul_update_emitted_after_full_cycle(
        self,
        broker: InMemoryBrokerBackend,
        rul_predictor: RULPredictor,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """Full pipeline: publish correction messages, verify rul_update emission.

        After publishing enough cycles to establish baseline (10 cycles) and
        one additional cycle, the RUL Predictor should emit rul_update messages.

        Validates: Requirements 8.1, 8.3
        """
        await broker.start()
        await rul_predictor.start()

        # Publish 11 cycles of nominal data to establish baseline + get RUL
        for cycle in range(11):
            await _publish_full_cycle(broker, engine_id=1, cycle=cycle)
            await _drain_broker_tasks(broker)

        # Need one more message to trigger cycle finalization of cycle 10
        # (cycle boundary detection happens when a sensor repeats)
        await _publish_full_cycle(broker, engine_id=1, cycle=11)
        await _drain_broker_tasks(broker)

        # Verify rul_update messages were emitted
        rul_messages = ws_manager.get_messages_of_type("rul_update")
        assert len(rul_messages) > 0, "Expected rul_update WebSocket messages"

        # Check payload structure
        last_rul = rul_messages[-1]
        assert "engine_id" in last_rul
        assert "rul_cycles" in last_rul
        assert "cycle_number" in last_rul
        assert "is_urgent" in last_rul
        assert last_rul["engine_id"] == 1
        assert 0 <= last_rul["rul_cycles"] <= 125


    @pytest.mark.asyncio
    async def test_rul_max_when_within_baseline(
        self,
        broker: InMemoryBrokerBackend,
        rul_predictor: RULPredictor,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """RUL should be 125 when sensor readings remain within 1 std dev.

        After baseline is established, if all sensors stay at nominal values,
        the RUL should remain at 125 (maximum).

        Validates: Requirements 8.1, 8.3
        """
        await broker.start()
        await rul_predictor.start()

        # Publish 12 cycles of identical data (deviation = 0)
        for cycle in range(12):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization of last cycle
        await _publish_full_cycle(broker, engine_id=1, cycle=12)
        await _drain_broker_tasks(broker)

        # Check RUL state directly
        state = rul_predictor.get_engine_state(1)
        assert state.current_rul == 125

    @pytest.mark.asyncio
    async def test_rul_urgent_attention_emitted(
        self,
        broker: InMemoryBrokerBackend,
        rul_predictor: RULPredictor,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """When RUL drops below 30, urgent_attention message should be emitted.

        Validates: Requirements 8.1, 8.3
        """
        await broker.start()
        await rul_predictor.start()

        # Establish baseline with nominal data
        for cycle in range(10):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Now publish cycles with extreme deviation to drive RUL down
        for cycle in range(10, 20):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle,
                base_value=500.0, deviation_factor=50.0,
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization
        await _publish_full_cycle(
            broker, engine_id=1, cycle=20, base_value=500.0, deviation_factor=50.0
        )
        await _drain_broker_tasks(broker)

        # Check for urgent_attention messages
        urgent_messages = ws_manager.get_messages_of_type("urgent_attention")
        assert len(urgent_messages) > 0, "Expected urgent_attention messages when RUL < 30"
        assert urgent_messages[-1]["engine_id"] == 1


# ---------------------------------------------------------------------------
# Integration Tests: Health Index Pipeline
# ---------------------------------------------------------------------------


class TestHealthIndexPipeline:
    """Integration tests for corrections.state → Health Index Aggregator → WebSocket."""

    @pytest.mark.asyncio
    async def test_health_index_update_emitted_after_full_cycle(
        self,
        broker: InMemoryBrokerBackend,
        health_aggregator: HealthIndexAggregator,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """Full pipeline: publish correction messages, verify health_index_update.

        Validates: Requirements 8.2, 8.3
        """
        await broker.start()
        await health_aggregator.start()

        # Publish 2 cycles of data (health index computed from first cycle onward)
        for cycle in range(2):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization of last cycle
        await _publish_full_cycle(broker, engine_id=1, cycle=2)
        await _drain_broker_tasks(broker)

        # Verify health_index_update messages were emitted
        hi_messages = ws_manager.get_messages_of_type("health_index_update")
        assert len(hi_messages) > 0, "Expected health_index_update WebSocket messages"

        # Check payload structure
        last_hi = hi_messages[-1]
        assert "engine_id" in last_hi
        assert "health_index" in last_hi
        assert "cycle_number" in last_hi
        assert "is_provisional" in last_hi
        assert last_hi["engine_id"] == 1
        assert 0.0 <= last_hi["health_index"] <= 1.0


    @pytest.mark.asyncio
    async def test_health_index_provisional_flag(
        self,
        broker: InMemoryBrokerBackend,
        health_aggregator: HealthIndexAggregator,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """Health index should be provisional when < 10 cycles.

        Validates: Requirements 8.2, 8.3
        """
        await broker.start()
        await health_aggregator.start()

        # Publish only 3 cycles (< 10 = provisional)
        for cycle in range(3):
            await _publish_full_cycle(
                broker, engine_id=2, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization
        await _publish_full_cycle(broker, engine_id=2, cycle=3)
        await _drain_broker_tasks(broker)

        # Verify provisional flag
        hi_messages = ws_manager.get_messages_of_type("health_index_update")
        engine_2_messages = [m for m in hi_messages if m["engine_id"] == 2]
        assert len(engine_2_messages) > 0
        # All messages for < 10 cycles should be provisional
        assert all(m["is_provisional"] is True for m in engine_2_messages)

    @pytest.mark.asyncio
    async def test_health_index_critical_alert_emitted(
        self,
        broker: InMemoryBrokerBackend,
        health_aggregator: HealthIndexAggregator,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """When health index drops below 0.4, critical_health_alert is emitted.

        Validates: Requirements 8.2, 8.3
        """
        await broker.start()
        await health_aggregator.start()

        # Establish baseline with nominal data
        for cycle in range(10):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Publish cycles with extreme deviation to drive HI below 0.4
        for cycle in range(10, 15):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle,
                base_value=500.0, deviation_factor=30.0,
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization
        await _publish_full_cycle(
            broker, engine_id=1, cycle=15, base_value=500.0, deviation_factor=30.0
        )
        await _drain_broker_tasks(broker)

        # Check for critical health alert
        alerts = ws_manager.get_messages_of_type("critical_health_alert")
        assert len(alerts) > 0, "Expected critical_health_alert when HI < 0.4"
        assert alerts[-1]["engine_id"] == 1
        assert alerts[-1]["health_index"] < 0.4


# ---------------------------------------------------------------------------
# Integration Tests: Snapshot Endpoint
# ---------------------------------------------------------------------------


class TestSnapshotEndpoint:
    """Integration tests for GET /api/engines/{engine_id}/snapshot with real services."""

    @pytest.mark.asyncio
    async def test_snapshot_returns_aggregated_state(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """Snapshot endpoint returns correct state after processing cycles.

        Wires up all services, processes cycles through the broker, then
        verifies the snapshot endpoint returns correct aggregated state.

        Validates: Requirements 8.5
        """
        # Create all services wired to same broker and WS manager
        rul_pred = RULPredictor(broker=broker, ws_manager=ws_manager)  # type: ignore
        health_agg = HealthIndexAggregator(broker=broker, ws_manager=ws_manager)  # type: ignore
        deg_tracker = DegradationCurveTracker(ws_manager=ws_manager)  # type: ignore
        comp_mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)  # type: ignore

        # Configure the API endpoint to use these service instances
        configure_engine_services(
            rul_predictor=rul_pred,
            health_index_aggregator=health_agg,
            component_health_mapper=comp_mapper,
            degradation_tracker=deg_tracker,
        )

        # Start all services
        await broker.start()
        await rul_pred.start()
        await health_agg.start()
        await comp_mapper.start()

        # Publish 12 cycles of nominal data for engine 1
        for cycle in range(12):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization of the last cycle
        await _publish_full_cycle(broker, engine_id=1, cycle=12)
        await _drain_broker_tasks(broker)

        # Manually record degradation data (the health aggregator doesn't
        # automatically feed into the degradation tracker in this test setup)
        health_state = health_agg.get_health_state(1)
        if health_state is not None:
            for c in range(12):
                deg_tracker.record(1, c, 1.0 - c * 0.005)

        # Create API client
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/engines/1/snapshot")

        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert data["engine_id"] == 1
        assert "rul" in data
        assert "health" in data
        assert "subsystems" in data
        assert "trajectory" in data
        assert "degradation_rate" in data

        # Verify RUL state
        assert data["rul"]["engine_id"] == 1
        assert 0 <= data["rul"]["current_rul"] <= 125
        assert data["rul"]["cycle_count"] > 0

        # Verify health state
        assert data["health"]["engine_id"] == 1
        assert 0.0 <= data["health"]["health_index"] <= 1.0

        # Verify trajectory has data points
        assert len(data["trajectory"]) > 0
        for point in data["trajectory"]:
            assert "cycle" in point
            assert "health_index" in point

    @pytest.mark.asyncio
    async def test_snapshot_404_for_unknown_engine(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """Snapshot returns 404 for engine with no processed data.

        Validates: Requirements 8.5
        """
        # Create services but don't process any data
        rul_pred = RULPredictor(broker=broker, ws_manager=ws_manager)  # type: ignore
        health_agg = HealthIndexAggregator(broker=broker, ws_manager=ws_manager)  # type: ignore
        deg_tracker = DegradationCurveTracker(ws_manager=ws_manager)  # type: ignore
        comp_mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)  # type: ignore

        configure_engine_services(
            rul_predictor=rul_pred,
            health_index_aggregator=health_agg,
            component_health_mapper=comp_mapper,
            degradation_tracker=deg_tracker,
        )

        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/engines/999/snapshot")

        assert response.status_code == 404


    @pytest.mark.asyncio
    async def test_snapshot_multiple_engines(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
    ) -> None:
        """Snapshot correctly isolates per-engine state.

        Validates: Requirements 8.5
        """
        rul_pred = RULPredictor(broker=broker, ws_manager=ws_manager)  # type: ignore
        health_agg = HealthIndexAggregator(broker=broker, ws_manager=ws_manager)  # type: ignore
        deg_tracker = DegradationCurveTracker(ws_manager=ws_manager)  # type: ignore
        comp_mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)  # type: ignore

        configure_engine_services(
            rul_predictor=rul_pred,
            health_index_aggregator=health_agg,
            component_health_mapper=comp_mapper,
            degradation_tracker=deg_tracker,
        )

        await broker.start()
        await rul_pred.start()
        await health_agg.start()
        await comp_mapper.start()

        # Publish data for engine 1 (nominal)
        for cycle in range(12):
            await _publish_full_cycle(
                broker, engine_id=1, cycle=cycle, base_value=500.0
            )
            await _drain_broker_tasks(broker)

        # Publish data for engine 2 (with deviation)
        for cycle in range(12):
            await _publish_full_cycle(
                broker, engine_id=2, cycle=cycle,
                base_value=500.0, deviation_factor=2.0 if cycle >= 10 else 0.0,
            )
            await _drain_broker_tasks(broker)

        # Trigger finalization for both
        await _publish_full_cycle(broker, engine_id=1, cycle=12)
        await _publish_full_cycle(broker, engine_id=2, cycle=12)
        await _drain_broker_tasks(broker)

        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.get("/api/engines/1/snapshot")
            resp2 = await client.get("/api/engines/2/snapshot")

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data1 = resp1.json()
        data2 = resp2.json()

        assert data1["engine_id"] == 1
        assert data2["engine_id"] == 2

        # Both should have valid RUL and health data
        assert 0 <= data1["rul"]["current_rul"] <= 125
        assert 0 <= data2["rul"]["current_rul"] <= 125
        assert 0.0 <= data1["health"]["health_index"] <= 1.0
        assert 0.0 <= data2["health"]["health_index"] <= 1.0
