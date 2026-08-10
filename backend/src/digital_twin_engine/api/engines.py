"""Engine snapshot API endpoint.

Provides GET /api/engines/{engine_id}/snapshot for retrieving the latest
prognostic state of an engine, enabling the frontend to restore display
after a WebSocket reconnection without requiring full data replay.

Requirements: 8.5
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

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


def configure_engine_services(
    rul_predictor: Any = None,
    health_index_aggregator: Any = None,
    component_health_mapper: Any = None,
    degradation_tracker: Any = None,
) -> None:
    """Configure the service references for the engine snapshot endpoint.

    Called during application startup to wire the prognostic services
    into the API layer.

    Args:
        rul_predictor: RULPredictor instance providing get_engine_state().
        health_index_aggregator: HealthIndexAggregator providing get_health_state().
        component_health_mapper: ComponentHealthMapper providing get_subsystem_health().
        degradation_tracker: DegradationCurveTracker providing get_trajectory()
            and compute_degradation_rate().
    """
    global _rul_predictor, _health_index_aggregator
    global _component_health_mapper, _degradation_tracker

    _rul_predictor = rul_predictor
    _health_index_aggregator = health_index_aggregator
    _component_health_mapper = component_health_mapper
    _degradation_tracker = degradation_tracker


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
    """Get degradation trajectory from the tracker."""
    if _degradation_tracker is not None:
        raw_trajectory = _degradation_tracker.get_trajectory(engine_id)
        return [
            DegradationPoint(cycle=cycle, health_index=hi)
            for cycle, hi in raw_trajectory
        ]

    return []


def _get_degradation_rate(engine_id: int) -> Optional[float]:
    """Get degradation rate from the tracker."""
    if _degradation_tracker is not None:
        return _degradation_tracker.compute_degradation_rate(engine_id)

    return None
