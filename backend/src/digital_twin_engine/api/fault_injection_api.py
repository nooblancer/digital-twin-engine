"""Fault Injection REST API endpoints.

Provides endpoints for injecting, listing, and clearing sensor faults:
- POST /sensors/inject-fault — Create a fault injection, returns 201
- DELETE /sensors/inject-fault — Clear all active injections, returns 200
- GET /sensors/active-faults — List all active faults, returns 200

The FaultInjector singleton is wired via configure_fault_injector() during
app startup, following the same DI pattern as configure_engine_services().

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

from typing import Any, List, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from digital_twin_engine.shared.logging import get_logger

logger = get_logger("fault_injection_api")

router = APIRouter(prefix="/sensors", tags=["fault-injection"])

# Module-level reference — set during app startup via configure_fault_injector()
_fault_injector: Any = None


def configure_fault_injector(injector: Any) -> None:
    """Wire the FaultInjector singleton into this router.

    Called during application startup to provide the shared FaultInjector
    instance that is also used by the CMAPSSReplayAdapter.

    Args:
        injector: FaultInjector instance for managing fault injections.
    """
    global _fault_injector
    _fault_injector = injector


# --- Pydantic request/response models ---


class InjectFaultRequest(BaseModel):
    """Request body for POST /sensors/inject-fault."""

    sensor_id: str
    fault_type: Literal["spike", "drift", "dropout", "noise"]
    magnitude: float = Field(gt=0, description="Fault intensity, must be > 0")
    duration_cycles: int = Field(gt=0, description="Number of cycles, must be > 0")


class InjectFaultResponse(BaseModel):
    """Response body for POST /sensors/inject-fault."""

    injection_id: str


class ClearFaultsResponse(BaseModel):
    """Response body for DELETE /sensors/inject-fault."""

    message: str


class ActiveFaultItem(BaseModel):
    """A single active fault injection in the list response."""

    injection_id: str
    sensor_id: str
    fault_type: str
    magnitude: float
    remaining_cycles: int
    duration_cycles: int


# --- Endpoints ---


@router.post("/inject-fault", status_code=201, response_model=InjectFaultResponse)
async def inject_fault(request: InjectFaultRequest) -> InjectFaultResponse:
    """Create a new fault injection on a sensor.

    Accepts sensor_id, fault_type, magnitude, and duration_cycles.
    Returns 201 with the unique injection_id.
    Returns 422 for invalid parameters (Pydantic validation).

    Requirements: 2.1, 2.2, 2.3, 2.4
    """
    injection_id = _fault_injector.inject(
        sensor_id=request.sensor_id,
        fault_type=request.fault_type,
        magnitude=request.magnitude,
        duration_cycles=request.duration_cycles,
    )
    logger.info(
        "Fault injected: %s on %s (%s, magnitude=%.2f, duration=%d)",
        injection_id,
        request.sensor_id,
        request.fault_type,
        request.magnitude,
        request.duration_cycles,
    )
    return InjectFaultResponse(injection_id=injection_id)


@router.delete("/inject-fault", status_code=200, response_model=ClearFaultsResponse)
async def clear_all_faults() -> ClearFaultsResponse:
    """Clear all active fault injections.

    Returns 200 with a confirmation message.

    Requirements: 2.5
    """
    _fault_injector.clear_all()
    logger.info("All fault injections cleared")
    return ClearFaultsResponse(message="All fault injections cleared")


@router.get("/active-faults", status_code=200, response_model=List[ActiveFaultItem])
async def get_active_faults() -> List[ActiveFaultItem]:
    """List all currently active fault injections.

    Returns 200 with a JSON array of active injections.

    Requirements: 2.6
    """
    active = _fault_injector.get_active()
    return [ActiveFaultItem(**fault) for fault in active]
