"""Unit tests for the Simulation REST API endpoints and FailureProbabilityCache.

Tests the simulation router endpoints:
- POST /simulation/what-if — Run a stress-factor simulation (200, 422)
- POST /simulation/maintenance-impact — Simulate maintenance intervention (200, 422)
- GET /engines/{id}/failure-probability — Return cached failure probability (200, 404)

Also tests FailureProbabilityCache populates within expected interval.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 12.1, 12.2, 12.3, 12.4, 12.5
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from digital_twin_engine.api.simulation_api import (
    configure_simulation_services,
    router,
)
from digital_twin_engine.simulation.what_if_simulator import (
    SimulationResult,
    WhatIfSimulator,
)
from digital_twin_engine.simulation.failure_prob_cache import (
    FailureProbabilityCache,
)


# ---------------------------------------------------------------------------
# Helpers — Mock simulation results
# ---------------------------------------------------------------------------


def _make_simulation_result(
    horizon: int = 50,
    rul: Optional[int] = 35,
    ci: Optional[Tuple[int, int]] = (28, 42),
) -> SimulationResult:
    """Create a valid SimulationResult for testing."""
    return SimulationResult(
        trajectory_percentiles={
            5: [0.9 - i * 0.015 for i in range(horizon)],
            25: [0.92 - i * 0.012 for i in range(horizon)],
            50: [0.95 - i * 0.01 for i in range(horizon)],
            75: [0.97 - i * 0.008 for i in range(horizon)],
            95: [0.98 - i * 0.005 for i in range(horizon)],
        },
        rul_estimate=rul,
        rul_confidence_90=ci,
        failure_probability_curve=[min(1.0, i * 0.02) for i in range(horizon)],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_simulator() -> MagicMock:
    """Create a mock WhatIfSimulator that returns valid results."""
    simulator = MagicMock(spec=WhatIfSimulator)
    simulator.simulate_stress_factor.return_value = _make_simulation_result()
    simulator.simulate_scenario.return_value = _make_simulation_result()
    return simulator


@pytest.fixture
def mock_cache() -> Dict[int, dict]:
    """Create a mock cache dict (dict with .get() method, like the API expects)."""
    return {}


@pytest.fixture
def app(mock_simulator: MagicMock, mock_cache: dict) -> FastAPI:
    """Create a minimal FastAPI app with the simulation router."""
    test_app = FastAPI()
    test_app.include_router(router)
    configure_simulation_services(
        what_if_simulator=mock_simulator,
        failure_prob_cache=mock_cache,
    )
    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create an async test client for the simulation API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: POST /simulation/what-if — valid params → 200
# ---------------------------------------------------------------------------


class TestWhatIfValid:
    """Tests for successful what-if simulation (200 responses)."""

    @pytest.mark.asyncio
    async def test_what_if_valid_params_returns_200(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST with valid params returns 200 with correct response shape."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 1.0,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 200
        body = response.json()

        # Verify response shape
        assert "percentiles" in body
        assert "failure_probability_by_cycle" in body
        assert "expected_rul" in body
        assert "confidence_interval_90" in body

        # Verify percentiles structure
        percentiles = body["percentiles"]
        assert "5" in percentiles
        assert "25" in percentiles
        assert "50" in percentiles
        assert "75" in percentiles
        assert "95" in percentiles
        assert len(percentiles["50"]) == 50

        # Verify failure prob is a list
        assert isinstance(body["failure_probability_by_cycle"], list)
        assert len(body["failure_probability_by_cycle"]) == 50

        # Verify RUL fields
        assert body["expected_rul"] == 35
        assert body["confidence_interval_90"] == [28, 42]

    @pytest.mark.asyncio
    async def test_what_if_min_stress_factor(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST with stress_factor=0.5 (minimum) returns 200."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 0.5,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_what_if_max_stress_factor(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST with stress_factor=2.0 (maximum) returns 200."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 2.0,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_what_if_calls_simulator_correctly(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST calls simulate_stress_factor with correct params."""
        await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 42,
                "stress_factor": 1.5,
                "horizon_cycles": 100,
            },
        )
        mock_simulator.simulate_stress_factor.assert_called_once_with(
            engine_id=42,
            stress_factor=1.5,
            horizon_cycles=100,
        )


# ---------------------------------------------------------------------------
# Tests: POST /simulation/what-if — stress_factor out of range → 422
# ---------------------------------------------------------------------------


class TestWhatIfInvalidStressFactor:
    """Tests for invalid stress_factor (422 responses)."""

    @pytest.mark.asyncio
    async def test_stress_factor_below_min_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST with stress_factor < 0.5 returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 0.4,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stress_factor_above_max_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST with stress_factor > 2.0 returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 2.1,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stress_factor_zero_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST with stress_factor=0 returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 0.0,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stress_factor_negative_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST with negative stress_factor returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": -1.0,
                "horizon_cycles": 50,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: POST /simulation/what-if — horizon_cycles out of range → 422
# ---------------------------------------------------------------------------


class TestWhatIfInvalidHorizon:
    """Tests for invalid horizon_cycles (422 responses)."""

    @pytest.mark.asyncio
    async def test_horizon_zero_returns_422(self, client: AsyncClient) -> None:
        """POST with horizon_cycles=0 returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 1.0,
                "horizon_cycles": 0,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_horizon_negative_returns_422(self, client: AsyncClient) -> None:
        """POST with negative horizon_cycles returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 1.0,
                "horizon_cycles": -5,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_horizon_above_max_returns_422(self, client: AsyncClient) -> None:
        """POST with horizon_cycles > 200 returns 422."""
        response = await client.post(
            "/simulation/what-if",
            json={
                "engine_id": 1,
                "stress_factor": 1.0,
                "horizon_cycles": 201,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: POST /simulation/maintenance-impact — valid params → 200
# ---------------------------------------------------------------------------


class TestMaintenanceImpactValid:
    """Tests for successful maintenance-impact simulation (200 responses)."""

    @pytest.mark.asyncio
    async def test_maintenance_impact_valid_returns_200(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST with valid params returns 200 with correct response shape."""
        response = await client.post(
            "/simulation/maintenance-impact",
            json={
                "engine_id": 1,
                "maintenance_at_cycle": 25,
                "reset_fraction": 0.5,
            },
        )
        assert response.status_code == 200
        body = response.json()

        # Verify response shape
        assert "before_rul" in body
        assert "after_rul" in body
        assert "trajectory_percentiles_before" in body
        assert "trajectory_percentiles_after" in body

        # Verify percentile dicts have expected keys
        assert "50" in body["trajectory_percentiles_before"]
        assert "50" in body["trajectory_percentiles_after"]

    @pytest.mark.asyncio
    async def test_maintenance_impact_zero_reset(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST with reset_fraction=0.0 (no recovery) returns 200."""
        response = await client.post(
            "/simulation/maintenance-impact",
            json={
                "engine_id": 1,
                "maintenance_at_cycle": 10,
                "reset_fraction": 0.0,
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_maintenance_impact_full_reset(
        self, client: AsyncClient, mock_simulator: MagicMock
    ) -> None:
        """POST with reset_fraction=1.0 (full recovery) returns 200."""
        response = await client.post(
            "/simulation/maintenance-impact",
            json={
                "engine_id": 1,
                "maintenance_at_cycle": 30,
                "reset_fraction": 1.0,
            },
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: POST /simulation/maintenance-impact — reset_fraction out of range → 422
# ---------------------------------------------------------------------------


class TestMaintenanceImpactInvalidResetFraction:
    """Tests for invalid reset_fraction (422 responses)."""

    @pytest.mark.asyncio
    async def test_reset_fraction_above_max_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST with reset_fraction > 1.0 returns 422."""
        response = await client.post(
            "/simulation/maintenance-impact",
            json={
                "engine_id": 1,
                "maintenance_at_cycle": 25,
                "reset_fraction": 1.1,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_reset_fraction_negative_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST with negative reset_fraction returns 422."""
        response = await client.post(
            "/simulation/maintenance-impact",
            json={
                "engine_id": 1,
                "maintenance_at_cycle": 25,
                "reset_fraction": -0.1,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: GET /engines/{id}/failure-probability — cached data → 200
# ---------------------------------------------------------------------------


class TestFailureProbabilityCached:
    """Tests for GET failure-probability with cached data (200 responses)."""

    @pytest.mark.asyncio
    async def test_cached_data_returns_200(
        self, client: AsyncClient, mock_cache: dict
    ) -> None:
        """GET with cached data returns 200 with correct response shape."""
        # Pre-populate cache
        mock_cache[1] = {
            "failure_probability_by_cycle": [0.01 * i for i in range(50)],
            "expected_rul": 40,
            "confidence_interval_90": (32, 48),
            "computed_at": "2024-01-15T10:30:00+00:00",
        }

        response = await client.get("/engines/1/failure-probability")
        assert response.status_code == 200
        body = response.json()

        # Verify response shape
        assert body["engine_id"] == 1
        assert "failure_probability_by_cycle" in body
        assert isinstance(body["failure_probability_by_cycle"], list)
        assert len(body["failure_probability_by_cycle"]) == 50
        assert body["expected_rul"] == 40
        assert body["confidence_interval_90"] == [32, 48]
        assert body["computed_at"] == "2024-01-15T10:30:00+00:00"

    @pytest.mark.asyncio
    async def test_cached_data_with_null_rul(
        self, client: AsyncClient, mock_cache: dict
    ) -> None:
        """GET with cached data where RUL is None returns 200."""
        mock_cache[5] = {
            "failure_probability_by_cycle": [0.0] * 50,
            "expected_rul": None,
            "confidence_interval_90": None,
            "computed_at": "2024-01-15T12:00:00+00:00",
        }

        response = await client.get("/engines/5/failure-probability")
        assert response.status_code == 200
        body = response.json()
        assert body["engine_id"] == 5
        assert body["expected_rul"] is None
        assert body["confidence_interval_90"] is None


# ---------------------------------------------------------------------------
# Tests: GET /engines/{id}/failure-probability — no data → 404
# ---------------------------------------------------------------------------


class TestFailureProbabilityNoData:
    """Tests for GET failure-probability with no cached data (404 responses)."""

    @pytest.mark.asyncio
    async def test_uncached_engine_returns_404(
        self, client: AsyncClient, mock_cache: dict
    ) -> None:
        """GET for engine with no cached data returns 404."""
        # Cache is empty — no data for engine 999
        response = await client.get("/engines/999/failure-probability")
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body

    @pytest.mark.asyncio
    async def test_404_includes_descriptive_message(
        self, client: AsyncClient, mock_cache: dict
    ) -> None:
        """GET 404 response includes helpful detail message."""
        response = await client.get("/engines/42/failure-probability")
        assert response.status_code == 404
        body = response.json()
        assert "42" in body["detail"] or "no" in body["detail"].lower()


# ---------------------------------------------------------------------------
# Tests: GET /engines/{id}/failure-probability — cache not configured → 404
# ---------------------------------------------------------------------------


class TestFailureProbabilityNoCacheService:
    """Tests for GET failure-probability when cache service is not configured."""

    @pytest.fixture
    def app_no_cache(self, mock_simulator: MagicMock) -> FastAPI:
        """Create app with no cache service configured."""
        test_app = FastAPI()
        test_app.include_router(router)
        configure_simulation_services(
            what_if_simulator=mock_simulator,
            failure_prob_cache=None,
        )
        return test_app

    @pytest.fixture
    async def client_no_cache(self, app_no_cache: FastAPI) -> AsyncClient:
        """Create client for app without cache."""
        transport = ASGITransport(app=app_no_cache)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_no_cache_configured_returns_404(
        self, client_no_cache: AsyncClient
    ) -> None:
        """GET returns 404 when cache service is None."""
        response = await client_no_cache.get("/engines/1/failure-probability")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests: FailureProbabilityCache populates within expected interval
# ---------------------------------------------------------------------------


class TestFailureProbabilityCachePopulation:
    """Tests that FailureProbabilityCache populates engines within expected interval."""

    @pytest.mark.asyncio
    async def test_cache_populates_on_compute_for_engine(self) -> None:
        """compute_for_engine() stores result in cache for engine with data."""
        # Create mocks for the projector and prognostics components
        mock_projector = MagicMock()
        mock_health_agg = MagicMock()
        mock_deg_tracker = MagicMock()

        # Mock health_states to include engine 1
        mock_health_agg._health_states = {1: MagicMock()}

        # Mock projector to return a valid result
        mock_result = MagicMock()
        mock_result.failure_probability_by_cycle = [0.01 * i for i in range(50)]
        mock_result.expected_rul = 35
        mock_result.confidence_interval_90 = (28, 42)
        mock_projector.project.return_value = mock_result

        cache = FailureProbabilityCache(
            projector=mock_projector,
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        # compute_for_engine should populate the cache
        entry = cache.compute_for_engine(engine_id=1)
        assert entry is not None
        assert entry.engine_id == 1
        assert entry.failure_probability_by_cycle == mock_result.failure_probability_by_cycle
        assert entry.expected_rul == 35
        assert entry.confidence_interval_90 == (28, 42)
        assert entry.computed_at is not None  # ISO timestamp

        # Verify cache dict is populated
        assert 1 in cache.cache
        assert cache.cache[1] is entry

    @pytest.mark.asyncio
    async def test_cache_skips_engine_with_insufficient_data(self) -> None:
        """compute_for_engine() returns None when projector raises ValueError."""
        mock_projector = MagicMock()
        mock_health_agg = MagicMock()
        mock_deg_tracker = MagicMock()

        mock_health_agg._health_states = {1: MagicMock()}
        mock_projector.project.side_effect = ValueError("Insufficient data")

        cache = FailureProbabilityCache(
            projector=mock_projector,
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        entry = cache.compute_for_engine(engine_id=1)
        assert entry is None
        assert 1 not in cache.cache

    @pytest.mark.asyncio
    async def test_cache_background_loop_populates(self) -> None:
        """Background loop populates cache for active engines within interval."""
        mock_projector = MagicMock()
        mock_health_agg = MagicMock()
        mock_deg_tracker = MagicMock()

        # Two active engines
        mock_health_agg._health_states = {1: MagicMock(), 2: MagicMock()}

        # Projector returns valid results
        mock_result = MagicMock()
        mock_result.failure_probability_by_cycle = [0.02 * i for i in range(50)]
        mock_result.expected_rul = 30
        mock_result.confidence_interval_90 = (25, 38)
        mock_projector.project.return_value = mock_result

        cache = FailureProbabilityCache(
            projector=mock_projector,
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        # Start the cache background task
        await cache.start()

        # Wait a short time for the first recomputation to complete
        await asyncio.sleep(0.5)

        # Both engines should be cached
        assert 1 in cache.cache
        assert 2 in cache.cache
        assert cache.cache[1].engine_id == 1
        assert cache.cache[2].engine_id == 2

        # Stop the background task
        await cache.stop()

    @pytest.mark.asyncio
    async def test_cache_start_stop_lifecycle(self) -> None:
        """Cache start/stop lifecycle works correctly."""
        mock_projector = MagicMock()
        mock_health_agg = MagicMock()
        mock_deg_tracker = MagicMock()
        mock_health_agg._health_states = {}

        cache = FailureProbabilityCache(
            projector=mock_projector,
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        # Start is idempotent
        await cache.start()
        await cache.start()  # second call is no-op

        # Stop cleans up
        await cache.stop()
        await cache.stop()  # second call is no-op
