"""Simulation REST API endpoints for what-if analysis.

Provides endpoints for running Monte Carlo forward projections and
maintenance impact simulations:
- POST /simulation/what-if — Run a stress-factor simulation, returns percentiles and RUL
- POST /simulation/maintenance-impact — Simulate maintenance intervention, returns before/after
- GET /engines/{engine_id}/failure-probability — Return cached failure probability or 404

The WhatIfSimulator and FailureProbabilityCache are wired via
configure_simulation_services() during app startup, following the same DI
pattern as configure_engine_services() and configure_fault_injector().

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from digital_twin_engine.shared.logging import get_logger

logger = get_logger("simulation_api")

router = APIRouter(tags=["simulation"])

# Module-level service references — set during app startup via configure_simulation_services()
_what_if_simulator: Any = None
_failure_prob_cache: Any = None


def configure_simulation_services(
    what_if_simulator: Any = None,
    failure_prob_cache: Any = None,
) -> None:
    """Wire simulation services into this router.

    Called during application startup to provide the shared WhatIfSimulator
    and FailureProbabilityCache instances.

    Args:
        what_if_simulator: WhatIfSimulator instance for running projections.
        failure_prob_cache: FailureProbabilityCache instance for cached results.
    """
    global _what_if_simulator, _failure_prob_cache
    _what_if_simulator = what_if_simulator
    _failure_prob_cache = failure_prob_cache


# --- Pydantic request/response models ---


class WhatIfRequest(BaseModel):
    """Request body for POST /simulation/what-if."""

    engine_id: int
    stress_factor: float = Field(
        ge=0.5, le=2.0, description="Degradation rate std multiplier (0.5 to 2.0)"
    )
    horizon_cycles: int = Field(
        ge=1, le=200, description="Number of future cycles to project (1 to 200)"
    )


class WhatIfResponse(BaseModel):
    """Response body for POST /simulation/what-if."""

    percentiles: Dict[str, List[float]]
    failure_probability_by_cycle: List[float]
    expected_rul: Optional[int]
    confidence_interval_90: Optional[Tuple[int, int]]


class MaintenanceImpactRequest(BaseModel):
    """Request body for POST /simulation/maintenance-impact."""

    engine_id: int
    maintenance_at_cycle: int = Field(
        ge=1, description="Cycle at which maintenance occurs"
    )
    reset_fraction: float = Field(
        ge=0.0, le=1.0, description="Fraction of lost health to recover (0.0 to 1.0)"
    )


class MaintenanceImpactResponse(BaseModel):
    """Response body for POST /simulation/maintenance-impact."""

    before_rul: Optional[int]
    after_rul: Optional[int]
    trajectory_percentiles_before: Dict[str, List[float]]
    trajectory_percentiles_after: Dict[str, List[float]]


class FailureProbabilityResponse(BaseModel):
    """Response body for GET /engines/{engine_id}/failure-probability."""

    engine_id: int
    failure_probability_by_cycle: List[float]
    expected_rul: Optional[int]
    confidence_interval_90: Optional[Tuple[int, int]]
    computed_at: str


# --- Endpoints ---


@router.post("/simulation/what-if", status_code=200, response_model=WhatIfResponse)
async def simulate_what_if(request: WhatIfRequest) -> WhatIfResponse:
    """Run a what-if simulation with a given stress factor.

    Accepts engine_id, stress_factor [0.5, 2.0], and horizon_cycles [1, 200].
    Returns trajectory percentiles, failure probability curve, expected RUL,
    and 90% confidence interval.

    Returns 422 for out-of-range parameters (Pydantic validation).
    Returns 404 if engine has no health/degradation data.

    Requirements: 6.1, 6.2, 6.3
    """
    try:
        result = _what_if_simulator.simulate_stress_factor(
            engine_id=request.engine_id,
            stress_factor=request.stress_factor,
            horizon_cycles=request.horizon_cycles,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Convert integer percentile keys to strings for JSON serialization
    percentiles = {str(k): v for k, v in result.trajectory_percentiles.items()}

    return WhatIfResponse(
        percentiles=percentiles,
        failure_probability_by_cycle=result.failure_probability_curve,
        expected_rul=result.rul_estimate,
        confidence_interval_90=result.rul_confidence_90,
    )


@router.post(
    "/simulation/maintenance-impact",
    status_code=200,
    response_model=MaintenanceImpactResponse,
)
async def simulate_maintenance_impact(
    request: MaintenanceImpactRequest,
) -> MaintenanceImpactResponse:
    """Simulate maintenance intervention impact on engine health.

    Accepts engine_id, maintenance_at_cycle, and reset_fraction [0.0, 1.0].
    Returns before/after RUL and trajectory percentiles.

    Returns 422 for out-of-range parameters (Pydantic validation).
    Returns 404 if engine has no health/degradation data.

    Requirements: 6.4, 6.5
    """
    # Compute "before" — normal projection (no maintenance)
    try:
        before_result = _what_if_simulator.simulate_scenario(
            engine_id=request.engine_id,
            scenario="normal",
            horizon_cycles=request.maintenance_at_cycle + 50,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Compute "after" — maintenance reset scenario
    try:
        after_result = _what_if_simulator.simulate_scenario(
            engine_id=request.engine_id,
            scenario="maintenance_reset",
            horizon_cycles=request.maintenance_at_cycle + 50,
            maintenance_at_cycle=request.maintenance_at_cycle,
            reset_fraction=request.reset_fraction,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Convert integer percentile keys to strings for JSON
    before_percentiles = {
        str(k): v for k, v in before_result.trajectory_percentiles.items()
    }
    after_percentiles = {
        str(k): v for k, v in after_result.trajectory_percentiles.items()
    }

    return MaintenanceImpactResponse(
        before_rul=before_result.rul_estimate,
        after_rul=after_result.rul_estimate,
        trajectory_percentiles_before=before_percentiles,
        trajectory_percentiles_after=after_percentiles,
    )


@router.get(
    "/engines/{engine_id}/failure-probability",
    status_code=200,
    response_model=FailureProbabilityResponse,
    responses={404: {"description": "Engine not found or no data available"}},
)
async def get_failure_probability(engine_id: int) -> Any:
    """Get cached failure probability for an engine.

    Returns the precomputed failure probability curve, expected RUL,
    confidence interval, and computation timestamp.

    Returns 404 if no cached data exists for the engine.

    Requirements: 6.6, 6.7
    """
    if _failure_prob_cache is None:
        raise HTTPException(
            status_code=404,
            detail=f"No failure probability data available for engine {engine_id}. "
            f"Cache service is not configured.",
        )

    cached = _failure_prob_cache.get(engine_id)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"No failure probability data available for engine {engine_id}. "
            f"Engine may not exist or has insufficient degradation data.",
        )

    return FailureProbabilityResponse(
        engine_id=engine_id,
        failure_probability_by_cycle=cached["failure_probability_by_cycle"],
        expected_rul=cached.get("expected_rul"),
        confidence_interval_90=cached.get("confidence_interval_90"),
        computed_at=cached["computed_at"],
    )
