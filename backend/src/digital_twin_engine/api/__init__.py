"""API gateway - RESTful endpoints for state queries and health monitoring."""

from digital_twin_engine.api.app import APIGateway, app, create_app
from digital_twin_engine.api.health import (
    register_health_check,
    unregister_health_check,
    clear_health_checks,
    compute_overall_status,
)

__all__ = [
    "APIGateway",
    "app",
    "create_app",
    "register_health_check",
    "unregister_health_check",
    "clear_health_checks",
    "compute_overall_status",
]
