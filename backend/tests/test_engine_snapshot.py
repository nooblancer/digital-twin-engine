"""Unit tests for the GET /api/engines/{engine_id}/snapshot endpoint.

Tests the engine snapshot API endpoint for:
- Returning correct EngineSnapshot for a known engine
- Returning 404 for non-existent engine IDs
- Handling partial service data gracefully

Validates: Requirements 8.5
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.engines import configure_engine_services
from digital_twin_engine.prognostics.models import (
    DegradationPoint,
    EngineHealthState,
    EngineRULState,
    SubsystemHealth,
)


# ---------------------------------------------------------------------------
# Mock Services
# ---------------------------------------------------------------------------


class MockRULPredictor:
    """Mock RUL Predictor for testing."""

    def __init__(self) -> None:
        self._states: Dict[int, EngineRULState] = {}

    def add_engine(self, engine_id: int, rul: int = 100, cycle_count: int = 50) -> None:
        self._states[engine_id] = EngineRULState(
            engine_id=engine_id,
            current_rul=rul,
            cycle_count=cycle_count,
            baseline_established=cycle_count >= 10,
            last_update_cycle=cycle_count,
            is_incomplete=False,
        )

    def get_engine_state(self, engine_id: int) -> EngineRULState:
        if engine_id in self._states:
            return self._states[engine_id]
        return EngineRULState(
            engine_id=engine_id,
            current_rul=125,
            cycle_count=0,
            baseline_established=False,
            last_update_cycle=0,
            is_incomplete=False,
        )


class MockHealthIndexAggregator:
    """Mock Health Index Aggregator for testing."""

    def __init__(self) -> None:
        self._states: Dict[int, EngineHealthState] = {}

    def add_engine(
        self, engine_id: int, health_index: float = 0.85, cycle_count: int = 50
    ) -> None:
        self._states[engine_id] = EngineHealthState(
            engine_id=engine_id,
            health_index=health_index,
            cycle_count=cycle_count,
            is_provisional=cycle_count < 10,
            last_update_cycle=cycle_count,
        )

    def get_health_state(self, engine_id: int) -> Optional[EngineHealthState]:
        return self._states.get(engine_id)


class MockComponentHealthMapper:
    """Mock Component Health Mapper for testing."""

    def __init__(self) -> None:
        self._states: Dict[int, Dict[str, SubsystemHealth]] = {}

    def add_engine(self, engine_id: int, subsystems: Optional[Dict[str, SubsystemHealth]] = None) -> None:
        if subsystems is None:
            subsystems = {
                "fan": SubsystemHealth(name="fan", health_score=0.9, classification="nominal", is_incomplete=False),
                "lpc": SubsystemHealth(name="lpc", health_score=0.75, classification="nominal", is_incomplete=False),
                "hpc": SubsystemHealth(name="hpc", health_score=0.5, classification="degraded", is_incomplete=False),
                "hpt": SubsystemHealth(name="hpt", health_score=0.85, classification="nominal", is_incomplete=False),
                "lpt": SubsystemHealth(name="lpt", health_score=0.95, classification="nominal", is_incomplete=False),
                "combustor": SubsystemHealth(name="combustor", health_score=0.3, classification="critical", is_incomplete=False),
            }
        self._states[engine_id] = subsystems

    def get_subsystem_health(self, engine_id: int) -> Optional[Dict[str, SubsystemHealth]]:
        return self._states.get(engine_id)


class MockDegradationTracker:
    """Mock Degradation Curve Tracker for testing."""

    def __init__(self) -> None:
        self._trajectories: Dict[int, List[Tuple[int, float]]] = {}
        self._rates: Dict[int, Optional[float]] = {}

    def add_engine(
        self,
        engine_id: int,
        trajectory: Optional[List[Tuple[int, float]]] = None,
        rate: Optional[float] = None,
    ) -> None:
        if trajectory is None:
            trajectory = [(i, 1.0 - i * 0.01) for i in range(25)]
        self._trajectories[engine_id] = trajectory
        self._rates[engine_id] = rate

    def get_trajectory(self, engine_id: int) -> List[Tuple[int, float]]:
        return self._trajectories.get(engine_id, [])

    def compute_degradation_rate(self, engine_id: int) -> Optional[float]:
        return self._rates.get(engine_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def rul_predictor() -> MockRULPredictor:
    return MockRULPredictor()


@pytest.fixture
def health_aggregator() -> MockHealthIndexAggregator:
    return MockHealthIndexAggregator()


@pytest.fixture
def component_mapper() -> MockComponentHealthMapper:
    return MockComponentHealthMapper()


@pytest.fixture
def degradation_tracker() -> MockDegradationTracker:
    return MockDegradationTracker()


@pytest.fixture
def gateway(
    rul_predictor: MockRULPredictor,
    health_aggregator: MockHealthIndexAggregator,
    component_mapper: MockComponentHealthMapper,
    degradation_tracker: MockDegradationTracker,
) -> APIGateway:
    """Create an API Gateway instance with mocked services."""
    configure_engine_services(
        rul_predictor=rul_predictor,
        health_index_aggregator=health_aggregator,
        component_health_mapper=component_mapper,
        degradation_tracker=degradation_tracker,
    )
    return APIGateway()


@pytest.fixture
async def client(gateway: APIGateway) -> AsyncClient:
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: GET /api/engines/{engine_id}/snapshot
# ---------------------------------------------------------------------------


class TestEngineSnapshot:
    """Tests for the engine snapshot endpoint."""

    @pytest.mark.asyncio
    async def test_snapshot_returns_full_state(
        self,
        client: AsyncClient,
        rul_predictor: MockRULPredictor,
        health_aggregator: MockHealthIndexAggregator,
        component_mapper: MockComponentHealthMapper,
        degradation_tracker: MockDegradationTracker,
    ) -> None:
        """Test that snapshot returns all prognostic state for a known engine."""
        engine_id = 1
        rul_predictor.add_engine(engine_id, rul=80, cycle_count=50)
        health_aggregator.add_engine(engine_id, health_index=0.72, cycle_count=50)
        component_mapper.add_engine(engine_id)
        degradation_tracker.add_engine(engine_id, rate=-0.015)

        response = await client.get(f"/api/engines/{engine_id}/snapshot")

        assert response.status_code == 200
        data = response.json()

        assert data["engine_id"] == engine_id
        assert data["rul"]["current_rul"] == 80
        assert data["rul"]["cycle_count"] == 50
        assert data["rul"]["baseline_established"] is True
        assert data["health"]["health_index"] == 0.72
        assert data["health"]["is_provisional"] is False
        assert len(data["subsystems"]) == 6
        assert len(data["trajectory"]) == 25
        assert data["degradation_rate"] == -0.015

    @pytest.mark.asyncio
    async def test_snapshot_404_for_unknown_engine(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that 404 is returned for an engine with no data."""
        response = await client.get("/api/engines/999/snapshot")

        assert response.status_code == 404
        data = response.json()
        assert "999" in data["detail"]
        assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_snapshot_subsystem_classifications(
        self,
        client: AsyncClient,
        rul_predictor: MockRULPredictor,
        health_aggregator: MockHealthIndexAggregator,
        component_mapper: MockComponentHealthMapper,
        degradation_tracker: MockDegradationTracker,
    ) -> None:
        """Test that subsystem classifications are correctly returned."""
        engine_id = 5
        rul_predictor.add_engine(engine_id)
        health_aggregator.add_engine(engine_id)
        component_mapper.add_engine(engine_id)
        degradation_tracker.add_engine(engine_id)

        response = await client.get(f"/api/engines/{engine_id}/snapshot")

        assert response.status_code == 200
        data = response.json()

        subsystems = {s["name"]: s for s in data["subsystems"]}
        assert subsystems["fan"]["classification"] == "nominal"
        assert subsystems["hpc"]["classification"] == "degraded"
        assert subsystems["combustor"]["classification"] == "critical"

    @pytest.mark.asyncio
    async def test_snapshot_with_no_degradation_rate(
        self,
        client: AsyncClient,
        rul_predictor: MockRULPredictor,
        health_aggregator: MockHealthIndexAggregator,
        component_mapper: MockComponentHealthMapper,
        degradation_tracker: MockDegradationTracker,
    ) -> None:
        """Test snapshot when degradation rate is unavailable (< 20 cycles)."""
        engine_id = 2
        rul_predictor.add_engine(engine_id, cycle_count=15)
        health_aggregator.add_engine(engine_id, cycle_count=15)
        component_mapper.add_engine(engine_id)
        # Short trajectory with no rate
        degradation_tracker.add_engine(
            engine_id,
            trajectory=[(i, 0.95) for i in range(15)],
            rate=None,
        )

        response = await client.get(f"/api/engines/{engine_id}/snapshot")

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_rate"] is None

    @pytest.mark.asyncio
    async def test_snapshot_trajectory_structure(
        self,
        client: AsyncClient,
        rul_predictor: MockRULPredictor,
        health_aggregator: MockHealthIndexAggregator,
        component_mapper: MockComponentHealthMapper,
        degradation_tracker: MockDegradationTracker,
    ) -> None:
        """Test that trajectory points have correct structure."""
        engine_id = 3
        trajectory = [(0, 1.0), (1, 0.98), (2, 0.95), (3, 0.90)]
        rul_predictor.add_engine(engine_id)
        health_aggregator.add_engine(engine_id)
        component_mapper.add_engine(engine_id)
        degradation_tracker.add_engine(engine_id, trajectory=trajectory, rate=None)

        response = await client.get(f"/api/engines/{engine_id}/snapshot")

        assert response.status_code == 200
        data = response.json()

        assert len(data["trajectory"]) == 4
        assert data["trajectory"][0] == {"cycle": 0, "health_index": 1.0}
        assert data["trajectory"][1] == {"cycle": 1, "health_index": 0.98}

    @pytest.mark.asyncio
    async def test_snapshot_engine_only_in_rul_predictor(
        self,
        client: AsyncClient,
        rul_predictor: MockRULPredictor,
    ) -> None:
        """Test snapshot when engine is only known to RUL predictor."""
        engine_id = 10
        rul_predictor.add_engine(engine_id, rul=120, cycle_count=5)

        response = await client.get(f"/api/engines/{engine_id}/snapshot")

        assert response.status_code == 200
        data = response.json()
        assert data["engine_id"] == engine_id
        assert data["rul"]["current_rul"] == 120
        # Health defaults
        assert data["health"]["health_index"] == 1.0
        assert data["health"]["is_provisional"] is True
        # Empty subsystems and trajectory
        assert data["subsystems"] == []
        assert data["trajectory"] == []
        assert data["degradation_rate"] is None
