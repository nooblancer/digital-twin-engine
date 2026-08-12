"""Unit tests for PredictiveAlertSystem and maintenance-recommendations endpoint.

Tests:
- Severity classification at boundary values (0.4, 0.7) (Requirements 2.3, 2.4, 2.5)
- Endpoint returns 200 with recommendations (Requirement 2.1)
- Endpoint returns 404 for missing engine (Requirement 2.6)
- Integration with MonteCarloProjector mock (Requirement 2.2)

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.alerting.predictive_alerts import (
    AlertSeverity,
    MaintenanceRecommendation,
    PredictiveAlertSystem,
)
from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.engines import configure_engine_services
from digital_twin_engine.prognostics.models import EngineHealthState, EngineRULState
from digital_twin_engine.simulation.monte_carlo_projector import ProjectionResult


# ---------------------------------------------------------------------------
# Mock classes
# ---------------------------------------------------------------------------


class MockHealthIndexAggregator:
    """Mock HealthIndexAggregator that returns configurable health states."""

    def __init__(self, states: Dict[int, Optional[EngineHealthState]]) -> None:
        self._states = states

    def get_health_state(self, engine_id: int) -> Optional[EngineHealthState]:
        return self._states.get(engine_id)


class MockDegradationTracker:
    """Mock DegradationCurveTracker returning configurable rates and trajectories."""

    def __init__(
        self,
        rates: Optional[Dict[int, Optional[float]]] = None,
        trajectories: Optional[Dict[int, List[Tuple[int, float]]]] = None,
    ) -> None:
        self._rates = rates or {}
        self._trajectories = trajectories or {}

    def compute_degradation_rate(self, engine_id: int) -> Optional[float]:
        return self._rates.get(engine_id)

    def get_trajectory(self, engine_id: int) -> List[Tuple[int, float]]:
        return self._trajectories.get(engine_id, [])


class MockMonteCarloProjector:
    """Mock MonteCarloProjector that returns a configurable ProjectionResult."""

    def __init__(
        self,
        results: Optional[Dict[int, ProjectionResult]] = None,
        raise_for: Optional[set] = None,
    ) -> None:
        self._results = results or {}
        self._raise_for = raise_for or set()

    def project(
        self,
        engine_id: int,
        horizon_cycles: int = 50,
        num_trajectories: int = 1000,
        stress_factor: float = 1.0,
    ) -> ProjectionResult:
        if engine_id in self._raise_for:
            raise ValueError(
                f"Insufficient trajectory data for engine {engine_id}"
            )
        if engine_id in self._results:
            return self._results[engine_id]
        # Default result: no crossing within horizon
        return ProjectionResult(
            percentiles={5: [], 25: [], 50: [], 75: [], 95: []},
            failure_probability_by_cycle=[0.0] * horizon_cycles,
            expected_rul=None,
            confidence_interval_90=None,
        )


class MockRULPredictor:
    """Mock RUL Predictor that recognizes specific engines."""

    def __init__(self, known_engines: set) -> None:
        self._known = known_engines

    def get_engine_state(self, engine_id: int) -> EngineRULState:
        if engine_id in self._known:
            return EngineRULState(
                engine_id=engine_id,
                current_rul=100,
                cycle_count=50,
                baseline_established=True,
                last_update_cycle=50,
                is_incomplete=False,
            )
        return EngineRULState(
            engine_id=engine_id,
            current_rul=125,
            cycle_count=0,
            baseline_established=False,
            last_update_cycle=0,
            is_incomplete=False,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_health_state(engine_id: int, health_index: float) -> EngineHealthState:
    """Helper to create an EngineHealthState with given health index."""
    return EngineHealthState(
        engine_id=engine_id,
        health_index=health_index,
        cycle_count=50,
        is_provisional=False,
        last_update_cycle=50,
    )


def _make_projection_result(
    expected_rul: Optional[int] = 42,
    ci_90: Optional[Tuple[int, int]] = (35, 50),
    failure_prob: Optional[List[float]] = None,
) -> ProjectionResult:
    """Create a ProjectionResult with reasonable defaults."""
    horizon = 100
    if failure_prob is None:
        failure_prob = [i / horizon for i in range(horizon)]
    return ProjectionResult(
        percentiles={5: [0.9] * horizon, 25: [0.8] * horizon, 50: [0.7] * horizon, 75: [0.6] * horizon, 95: [0.5] * horizon},
        failure_probability_by_cycle=failure_prob,
        expected_rul=expected_rul,
        confidence_interval_90=ci_90,
    )


# ---------------------------------------------------------------------------
# Test class: Severity Classification
# ---------------------------------------------------------------------------


class TestSeverityClassification:
    """Tests for _classify_severity boundary values.

    Requirements 2.3, 2.4, 2.5:
    - health_index > 0.7 → LOW
    - 0.4 < health_index <= 0.7 → MEDIUM
    - health_index <= 0.4 → CRITICAL
    """

    def _make_system(self) -> PredictiveAlertSystem:
        """Create a PredictiveAlertSystem with minimal mocks."""
        health_agg = MockHealthIndexAggregator({})
        degradation = MockDegradationTracker()
        projector = MockMonteCarloProjector()
        return PredictiveAlertSystem(projector, health_agg, degradation)

    def test_critical_at_exactly_0_4(self):
        """At health_index == 0.4, severity is CRITICAL (Requirement 2.5: at or below 0.4)."""
        system = self._make_system()
        assert system._classify_severity(0.4) == AlertSeverity.CRITICAL

    def test_critical_below_0_4(self):
        """At health_index < 0.4, severity is CRITICAL."""
        system = self._make_system()
        assert system._classify_severity(0.3) == AlertSeverity.CRITICAL
        assert system._classify_severity(0.0) == AlertSeverity.CRITICAL

    def test_medium_just_above_0_4(self):
        """At health_index just above 0.4, severity is MEDIUM (Requirement 2.4)."""
        system = self._make_system()
        assert system._classify_severity(0.41) == AlertSeverity.MEDIUM

    def test_medium_at_exactly_0_7(self):
        """At health_index == 0.7, severity is MEDIUM (between 0.4 and 0.7)."""
        system = self._make_system()
        assert system._classify_severity(0.7) == AlertSeverity.MEDIUM

    def test_low_just_above_0_7(self):
        """At health_index just above 0.7, severity is LOW (Requirement 2.3: above 0.7)."""
        system = self._make_system()
        assert system._classify_severity(0.71) == AlertSeverity.LOW

    def test_low_at_1_0(self):
        """At health_index == 1.0, severity is LOW."""
        system = self._make_system()
        assert system._classify_severity(1.0) == AlertSeverity.LOW


# ---------------------------------------------------------------------------
# Test class: get_recommendations() integration
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    """Tests for PredictiveAlertSystem.get_recommendations().

    Validates integration with MonteCarloProjector and end-to-end
    recommendation generation.
    """

    def test_returns_empty_when_no_health_data(self):
        """Returns empty list when HealthIndexAggregator has no state (Requirement 2.1)."""
        health_agg = MockHealthIndexAggregator({})  # No states
        degradation = MockDegradationTracker()
        projector = MockMonteCarloProjector()
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)
        assert result == []

    def test_returns_recommendation_with_projection(self):
        """Returns recommendation using MonteCarloProjector data (Requirement 2.2)."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.6)}  # MEDIUM severity
        )
        degradation = MockDegradationTracker(rates={1: -0.01})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=42, ci_90=(35, 50))}
        )
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        rec = result[0]
        assert isinstance(rec, MaintenanceRecommendation)
        assert rec.severity == AlertSeverity.MEDIUM
        assert rec.time_to_critical_cycles == 42
        assert 0.0 <= rec.confidence_score <= 1.0
        assert len(rec.suggested_action) > 0

    def test_critical_severity_generates_immediate_action(self):
        """Critical severity generates 'immediate maintenance' action."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.3)}  # CRITICAL
        )
        degradation = MockDegradationTracker(rates={1: -0.03})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=5, ci_90=(3, 8))}
        )
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        rec = result[0]
        assert rec.severity == AlertSeverity.CRITICAL
        assert "immediate" in rec.suggested_action.lower()

    def test_low_severity_generates_monitoring_action(self):
        """Low severity generates 'routine monitoring' action."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.85)}  # LOW
        )
        degradation = MockDegradationTracker(rates={1: -0.005})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=80, ci_90=(70, 90))}
        )
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        rec = result[0]
        assert rec.severity == AlertSeverity.LOW
        assert "monitor" in rec.suggested_action.lower() or "routine" in rec.suggested_action.lower()

    def test_handles_projector_value_error(self):
        """Returns fallback recommendation when projector raises ValueError."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.5)}
        )
        degradation = MockDegradationTracker(rates={1: -0.01})
        projector = MockMonteCarloProjector(raise_for={1})
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        rec = result[0]
        assert rec.severity == AlertSeverity.MEDIUM
        assert rec.time_to_critical_cycles == 0
        assert rec.confidence_score == 0.0

    def test_no_crossing_returns_horizon_as_time_to_critical(self):
        """When no crossing in horizon, time_to_critical equals horizon (Requirement 2.2)."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.95)}
        )
        degradation = MockDegradationTracker(rates={1: -0.001})
        # No crossing: expected_rul is None
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=None, ci_90=None)}
        )
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        rec = result[0]
        assert rec.time_to_critical_cycles == 100  # PROJECTION_HORIZON

    def test_confidence_score_between_0_and_1(self):
        """Confidence score is always in [0.0, 1.0] range (Requirement 2.1)."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.6)}
        )
        degradation = MockDegradationTracker(rates={1: -0.015})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=30, ci_90=(20, 40))}
        )
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        assert 0.0 <= result[0].confidence_score <= 1.0

    def test_infers_failure_mode(self):
        """Failure mode is inferred from degradation rate."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.5)}
        )
        degradation = MockDegradationTracker(rates={1: -0.025})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=20, ci_90=(15, 25))}
        )
        system = PredictiveAlertSystem(projector, health_agg, degradation)

        result = system.get_recommendations(engine_id=1)

        assert len(result) == 1
        assert result[0].predicted_failure_mode == "accelerated_degradation"


# ---------------------------------------------------------------------------
# Test class: Maintenance Recommendations Endpoint
# ---------------------------------------------------------------------------


class TestMaintenanceRecommendationsEndpoint:
    """Tests for GET /api/engines/{engine_id}/maintenance-recommendations.

    Validates: Requirements 2.1, 2.6
    """

    @pytest.mark.asyncio
    async def test_404_for_unknown_engine(self):
        """Returns 404 with descriptive message for non-existent engine (Requirement 2.6)."""
        configure_engine_services(
            rul_predictor=MockRULPredictor(known_engines={1, 2}),
            predictive_alert_system=None,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/999/maintenance-recommendations")
            assert resp.status_code == 404
            data = resp.json()
            assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_200_with_empty_recommendations_when_no_alert_system(self):
        """Returns 200 with empty list when PredictiveAlertSystem not configured."""
        configure_engine_services(
            rul_predictor=MockRULPredictor(known_engines={1}),
            predictive_alert_system=None,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/maintenance-recommendations")
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_id"] == 1
            assert data["recommendations"] == []

    @pytest.mark.asyncio
    async def test_200_with_recommendations(self):
        """Returns 200 with recommendations from PredictiveAlertSystem (Requirement 2.1)."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.55)}
        )
        degradation = MockDegradationTracker(rates={1: -0.012})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=35, ci_90=(28, 42))}
        )
        alert_system = PredictiveAlertSystem(projector, health_agg, degradation)

        configure_engine_services(
            rul_predictor=MockRULPredictor(known_engines={1}),
            health_index_aggregator=health_agg,
            degradation_tracker=degradation,
            predictive_alert_system=alert_system,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/maintenance-recommendations")
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_id"] == 1
            assert len(data["recommendations"]) >= 1

            rec = data["recommendations"][0]
            assert rec["severity"] == "medium"
            assert rec["time_to_critical_cycles"] == 35
            assert 0.0 <= rec["confidence_score"] <= 1.0
            assert len(rec["suggested_action"]) > 0

    @pytest.mark.asyncio
    async def test_response_contains_all_required_fields(self):
        """Each recommendation has severity, time_to_critical, confidence, action (Requirement 2.1)."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.3)}
        )
        degradation = MockDegradationTracker(rates={1: -0.025})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=10, ci_90=(7, 14))}
        )
        alert_system = PredictiveAlertSystem(projector, health_agg, degradation)

        configure_engine_services(
            rul_predictor=MockRULPredictor(known_engines={1}),
            health_index_aggregator=health_agg,
            degradation_tracker=degradation,
            predictive_alert_system=alert_system,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/maintenance-recommendations")
            assert resp.status_code == 200
            data = resp.json()

            for rec in data["recommendations"]:
                assert "severity" in rec
                assert rec["severity"] in ("low", "medium", "critical")
                assert "time_to_critical_cycles" in rec
                assert isinstance(rec["time_to_critical_cycles"], int)
                assert "confidence_score" in rec
                assert 0.0 <= rec["confidence_score"] <= 1.0
                assert "suggested_action" in rec
                assert isinstance(rec["suggested_action"], str)

    @pytest.mark.asyncio
    async def test_critical_engine_returns_critical_severity(self):
        """Engine with health <= 0.4 returns critical severity in response (Requirement 2.5)."""
        health_agg = MockHealthIndexAggregator(
            {1: _make_health_state(1, 0.35)}
        )
        degradation = MockDegradationTracker(rates={1: -0.03})
        projector = MockMonteCarloProjector(
            results={1: _make_projection_result(expected_rul=8, ci_90=(5, 12))}
        )
        alert_system = PredictiveAlertSystem(projector, health_agg, degradation)

        configure_engine_services(
            rul_predictor=MockRULPredictor(known_engines={1}),
            health_index_aggregator=health_agg,
            degradation_tracker=degradation,
            predictive_alert_system=alert_system,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/maintenance-recommendations")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["recommendations"]) >= 1
            assert data["recommendations"][0]["severity"] == "critical"
