"""Health endpoint for the API Gateway.

Exposes GET /health that checks all pipeline components
(Ingestion_Server, Message_Broker, TSDB, ML_Service, Correction_Engine)
and reports each as "healthy", "degraded", or "down".

Overall status logic:
- "healthy" if all components are healthy
- "down" if all components are down
- "degraded" otherwise

Each component health check has a 3-second timeout; if it times out or errors,
the component is reported as "degraded". The endpoint responds within 500ms.

Validates: Requirements 8.1, 8.2, 8.3
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable, Coroutine, Dict, Optional

from fastapi import APIRouter

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import ComponentStatus, HealthStatus

logger = get_logger("api_gateway")

# Timeout for individual component health checks (seconds)
HEALTH_CHECK_TIMEOUT_SECONDS = 3.0

# All pipeline components that are checked
COMPONENT_NAMES = [
    "ingestion_server",
    "message_broker",
    "tsdb",
    "ml_service",
    "correction_engine",
]

# Type alias for health check callables
HealthCheckFunc = Callable[[], Coroutine[None, None, ComponentStatus]]

router = APIRouter()

# Registry of health check functions. Each entry maps a component name
# to an async callable that returns a ComponentStatus.
# Services register their health check at startup; if not registered,
# the component is reported as "down".
_health_checks: Dict[str, HealthCheckFunc] = {}


def register_health_check(component_name: str, check_fn: HealthCheckFunc) -> None:
    """Register an async health check function for a pipeline component.

    Args:
        component_name: One of the COMPONENT_NAMES values.
        check_fn: An async callable that returns ComponentStatus.
    """
    if component_name not in COMPONENT_NAMES:
        raise ValueError(
            f"Unknown component '{component_name}'. "
            f"Must be one of: {COMPONENT_NAMES}"
        )
    _health_checks[component_name] = check_fn


def unregister_health_check(component_name: str) -> None:
    """Remove a registered health check (useful for testing)."""
    _health_checks.pop(component_name, None)


def clear_health_checks() -> None:
    """Remove all registered health checks (useful for testing)."""
    _health_checks.clear()


async def _check_component(component_name: str) -> ComponentStatus:
    """Run a single component health check with timeout.

    - If no check is registered, the component is reported as DOWN.
    - If the check times out (>3s) or raises an exception, report DEGRADED.
    - Otherwise, return whatever the check function reports.
    """
    check_fn = _health_checks.get(component_name)
    if check_fn is None:
        return ComponentStatus.DOWN

    try:
        status = await asyncio.wait_for(
            check_fn(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS
        )
        return status
    except asyncio.TimeoutError:
        logger.warning(
            "health_check_timeout",
            component=component_name,
            timeout_seconds=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        return ComponentStatus.DEGRADED
    except Exception as exc:
        logger.warning(
            "health_check_error",
            component=component_name,
            error=str(exc),
        )
        return ComponentStatus.DEGRADED


def compute_overall_status(
    component_statuses: Dict[str, ComponentStatus],
) -> ComponentStatus:
    """Compute overall system status from individual component statuses.

    - "healthy" if ALL components are healthy
    - "down" if ALL components are down
    - "degraded" otherwise (any mix)
    """
    statuses = list(component_statuses.values())

    if not statuses:
        return ComponentStatus.DOWN

    all_healthy = all(s == ComponentStatus.HEALTHY for s in statuses)
    all_down = all(s == ComponentStatus.DOWN for s in statuses)

    if all_healthy:
        return ComponentStatus.HEALTHY
    elif all_down:
        return ComponentStatus.DOWN
    else:
        return ComponentStatus.DEGRADED


@router.get("/health")
async def health_endpoint() -> dict:
    """GET /health - Aggregate health status of all pipeline components.

    Checks all 5 components concurrently with a 3-second timeout per check.
    Returns overall status and per-component status.
    """
    # Run all health checks concurrently
    tasks = {
        name: asyncio.create_task(_check_component(name))
        for name in COMPONENT_NAMES
    }

    component_statuses: Dict[str, ComponentStatus] = {}
    for name, task in tasks.items():
        component_statuses[name] = await task

    overall = compute_overall_status(component_statuses)
    timestamp = datetime.now(timezone.utc)

    health_status = HealthStatus(
        overall_status=overall,
        components=component_statuses,
        timestamp=timestamp,
    )

    return {
        "overall_status": health_status.overall_status.value,
        "components": {
            name: status.value for name, status in health_status.components.items()
        },
        "timestamp": health_status.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
