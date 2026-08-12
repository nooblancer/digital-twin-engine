"""Engine API endpoints.

Provides:
- GET /api/engines/{engine_id}/snapshot — retrieve the latest prognostic state
  of an engine for frontend restoration after WebSocket reconnection.
- GET /api/engines/{engine_id}/anomaly-analysis — retrieve root cause analysis
  for the most recent anomaly on an engine.
- GET /api/engines/{engine_id}/maintenance-recommendations — get predictive
  maintenance recommendations for an engine based on forward projection.

Requirements: 8.5, 1.2, 1.3, 1.4, 2.1, 2.6
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException

from digital_twin_engine.api.models import (
    AnomalyAnalysisResponse,
    MaintenanceRecommendationModel,
    MaintenanceRecommendationsResponse,
    SensorContributionModel,
)
from digital_twin_engine.prognostics.models import (
    DegradationPoint,
    EngineHealthState,
    EngineRULState,
    EngineSnapshot,
    SubsystemHealth,
)
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("api_engines")

router = APIRouter(prefix="/api/engines", tags=["engines"])

# Service references — set during app startup via configure_engine_services()
_rul_predictor: Any = None
_health_index_aggregator: Any = None
_component_health_mapper: Any = None
_degradation_tracker: Any = None
_root_cause_analyzer: Any = None
_predictive_alert_system: Any = None


def configure_engine_services(
    rul_predictor: Any = None,
    health_index_aggregator: Any = None,
    component_health_mapper: Any = None,
    degradation_tracker: Any = None,
    root_cause_analyzer: Any = None,
    predictive_alert_system: Any = None,
) -> None:
    """Configure the service references for the engine API endpoints.

    Called during application startup to wire the prognostic services
    and alerting modules into the API layer.

    Args:
        rul_predictor: RULPredictor instance providing get_engine_state().
        health_index_aggregator: HealthIndexAggregator providing get_health_state().
        component_health_mapper: ComponentHealthMapper providing get_subsystem_health().
        degradation_tracker: DegradationCurveTracker providing get_trajectory()
            and compute_degradation_rate().
        root_cause_analyzer: RootCauseAnalyzer instance providing get_latest_analysis().
        predictive_alert_system: PredictiveAlertSystem instance providing
            get_recommendations().
    """
    global _rul_predictor, _health_index_aggregator
    global _component_health_mapper, _degradation_tracker
    global _root_cause_analyzer, _predictive_alert_system

    _rul_predictor = rul_predictor
    _health_index_aggregator = health_index_aggregator
    _component_health_mapper = component_health_mapper
    _degradation_tracker = degradation_tracker
    _root_cause_analyzer = root_cause_analyzer
    _predictive_alert_system = predictive_alert_system


@router.get(
    "/{engine_id}/snapshot",
    response_model=EngineSnapshot,
    responses={404: {"description": "Engine not found"}},
)
async def get_engine_snapshot(engine_id: int) -> Any:
    """Get the latest state snapshot for an engine.

    Returns the full prognostic state including RUL, health index,
    subsystem health, degradation trajectory, and degradation rate.

    This endpoint enables the frontend to restore its display after
    a WebSocket reconnection without requiring a full data replay.

    Args:
        engine_id: The engine unit identifier (integer).

    Returns:
        EngineSnapshot with all prognostic state for the engine.

    Raises:
        HTTPException 404: If the engine_id is not known to any service.
    """
    # Check if any service has data for this engine
    has_data = _engine_exists(engine_id)

    if not has_data:
        raise HTTPException(
            status_code=404,
            detail=f"Engine with id {engine_id} not found. "
            f"No prognostic data has been recorded for this engine.",
        )

    # Gather state from all services
    rul_state = _get_rul_state(engine_id)
    health_state = _get_health_state(engine_id)
    subsystems = _get_subsystem_health(engine_id)
    trajectory = _get_trajectory(engine_id)
    degradation_rate = _get_degradation_rate(engine_id)

    return EngineSnapshot(
        engine_id=engine_id,
        rul=rul_state,
        health=health_state,
        subsystems=subsystems,
        trajectory=trajectory,
        degradation_rate=degradation_rate,
    )


@router.get(
    "/{engine_id}/anomaly-analysis",
    response_model=AnomalyAnalysisResponse,
    responses={404: {"description": "Engine not found"}},
)
async def get_anomaly_analysis(engine_id: int) -> Any:
    """Get root cause analysis for the most recent anomaly on this engine.

    Returns the ranked sensor contributions from the last anomaly event.
    If no anomaly has been recorded, returns anomaly_active=false with an
    empty contributions list.

    Args:
        engine_id: The engine unit identifier (integer).

    Returns:
        AnomalyAnalysisResponse with ranked sensor contributions.

    Raises:
        HTTPException 404: If the engine_id is not known to any service.

    Requirements: 1.2, 1.3, 1.4
    """
    # Check if engine exists via the same logic as the snapshot endpoint
    has_data = _engine_exists(engine_id)

    if not has_data:
        raise HTTPException(
            status_code=404,
            detail=f"Engine with id {engine_id} not found. "
            f"No prognostic data has been recorded for this engine.",
        )

    # If no root cause analyzer is configured, return inactive analysis
    if _root_cause_analyzer is None:
        return AnomalyAnalysisResponse(
            engine_id=engine_id,
            anomaly_active=False,
        )

    # Get the latest analysis from the RootCauseAnalyzer
    analysis = _root_cause_analyzer.get_latest_analysis(engine_id)

    return AnomalyAnalysisResponse(
        engine_id=engine_id,
        anomaly_active=analysis.anomaly_active,
        timestamp=analysis.timestamp,
        contributions=[
            SensorContributionModel(
                sensor_name=c.sensor_name,
                innovation_magnitude=c.innovation_magnitude,
                sigma_deviation=c.sigma_deviation,
            )
            for c in analysis.contributions
        ],
    )


def _engine_exists(engine_id: int) -> bool:
    """Check if any prognostic service has data for the given engine.

    Returns True if any of the configured services recognize the engine_id.
    """
    # Check RUL predictor
    if _rul_predictor is not None:
        state = _rul_predictor.get_engine_state(engine_id)
        # If cycle_count > 0, we have real data
        if state.cycle_count > 0:
            return True

    # Check health index aggregator
    if _health_index_aggregator is not None:
        state = _health_index_aggregator.get_health_state(engine_id)
        if state is not None:
            return True

    # Check component health mapper
    if _component_health_mapper is not None:
        health = _component_health_mapper.get_subsystem_health(engine_id)
        if health is not None:
            return True

    # Check degradation tracker
    if _degradation_tracker is not None:
        trajectory = _degradation_tracker.get_trajectory(engine_id)
        if trajectory:
            return True

    return False


def _get_rul_state(engine_id: int) -> EngineRULState:
    """Get RUL state from the predictor, with fallback defaults."""
    if _rul_predictor is not None:
        return _rul_predictor.get_engine_state(engine_id)

    # Default state when no predictor is configured
    return EngineRULState(
        engine_id=engine_id,
        current_rul=125,
        cycle_count=0,
        baseline_established=False,
        last_update_cycle=0,
        is_incomplete=False,
    )


def _get_health_state(engine_id: int) -> EngineHealthState:
    """Get health state from the aggregator, with fallback defaults."""
    if _health_index_aggregator is not None:
        state = _health_index_aggregator.get_health_state(engine_id)
        if state is not None:
            return state

    # Default state when no aggregator is configured or no data available
    return EngineHealthState(
        engine_id=engine_id,
        health_index=1.0,
        cycle_count=0,
        is_provisional=True,
        last_update_cycle=0,
    )


def _get_subsystem_health(engine_id: int) -> List[SubsystemHealth]:
    """Get subsystem health from the mapper, with fallback defaults."""
    if _component_health_mapper is not None:
        health_dict = _component_health_mapper.get_subsystem_health(engine_id)
        if health_dict is not None:
            return list(health_dict.values())

    # Default: empty list (no subsystem data)
    return []


def _get_trajectory(engine_id: int) -> List[DegradationPoint]:
    """Get degradation trajectory from the tracker.

    Prepends provisional HI=1.0 values for cycles 1 through BASELINE_CYCLES
    (the calibration period) before the real trajectory data. This ensures
    the trajectory reflects requirement 15.6: no false low HI values during
    calibration, only provisional 1.0 followed by real computed values.
    """
    from digital_twin_engine.prognostics.health_index import BASELINE_CYCLES

    if _degradation_tracker is None:
        return []

    raw_trajectory = _degradation_tracker.get_trajectory(engine_id)

    # If no real trajectory data exists yet, check if engine is in baseline
    # period and return provisional entries if so
    if _health_index_aggregator is not None:
        health_state = _health_index_aggregator.get_health_state(engine_id)
        if health_state is not None and health_state.cycle_count > 0:
            # Determine how many provisional cycles to prepend
            # (cycles 1 through min(cycle_count, BASELINE_CYCLES))
            provisional_end = min(health_state.cycle_count, BASELINE_CYCLES)

            # Build provisional entries for cycles 1..provisional_end
            provisional = [
                DegradationPoint(cycle=c, health_index=1.0)
                for c in range(1, provisional_end + 1)
            ]

            # Filter out any real trajectory points that fall within the
            # baseline period (shouldn't happen after task 23.1 fix, but
            # defensive guard per requirement 15.6)
            real_points = [
                DegradationPoint(cycle=cycle, health_index=hi)
                for cycle, hi in raw_trajectory
                if cycle > BASELINE_CYCLES
            ]

            return provisional + real_points

    # Fallback: return raw trajectory as-is (no health aggregator available)
    return [
        DegradationPoint(cycle=cycle, health_index=hi)
        for cycle, hi in raw_trajectory
    ]


def _get_degradation_rate(engine_id: int) -> Optional[float]:
    """Get degradation rate from the tracker."""
    if _degradation_tracker is not None:
        return _degradation_tracker.compute_degradation_rate(engine_id)

    return None


@router.get(
    "/{engine_id}/maintenance-recommendations",
    response_model=MaintenanceRecommendationsResponse,
    responses={404: {"description": "Engine not found"}},
)
async def get_maintenance_recommendations(engine_id: int) -> Any:
    """Get predictive maintenance recommendations for this engine.

    Uses the PredictiveAlertSystem to generate severity-classified
    maintenance recommendations based on forward projection of the
    engine's current degradation state.

    Returns 404 if the engine_id is not known to any service.
    Returns an empty recommendations list if no degradation data is available.

    Args:
        engine_id: The engine unit identifier (integer).

    Returns:
        MaintenanceRecommendationsResponse with engine_id and recommendations list.

    Raises:
        HTTPException 404: If the engine_id is not known to any service.

    Requirements: 2.1, 2.6
    """
    # Check if any service has data for this engine
    if not _engine_exists(engine_id):
        raise HTTPException(
            status_code=404,
            detail=f"Engine with id {engine_id} not found. "
            f"No prognostic data has been recorded for this engine.",
        )

    # If the PredictiveAlertSystem is not configured, return empty recommendations
    if _predictive_alert_system is None:
        return MaintenanceRecommendationsResponse(
            engine_id=engine_id,
            recommendations=[],
        )

    # Get recommendations from the PredictiveAlertSystem
    recommendations = _predictive_alert_system.get_recommendations(engine_id)

    # Convert dataclass results to Pydantic response models
    recommendation_models = [
        MaintenanceRecommendationModel(
            severity=rec.severity.value,
            time_to_critical_cycles=rec.time_to_critical_cycles,
            confidence_score=rec.confidence_score,
            suggested_action=rec.suggested_action,
            predicted_failure_mode=rec.predicted_failure_mode,
        )
        for rec in recommendations
    ]

    return MaintenanceRecommendationsResponse(
        engine_id=engine_id,
        recommendations=recommendation_models,
    )
