"""Data source switching endpoint for the API Gateway.

Provides POST /source to activate different telemetry data source adapters.
Tracks the currently active source and validates source names against the
set of available/supported sources.

Requirements: 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from digital_twin_engine.shared.logging import get_logger

logger = get_logger("source_controller")

router = APIRouter()

# Set of recognized data source names
AVAILABLE_SOURCES: set[str] = {"cmapss_replay"}

# Module-level state tracking the currently active source
_active_source: Optional[str] = None


class SourceRequest(BaseModel):
    """Request body for POST /source."""

    source: str


class SourceResponse(BaseModel):
    """Successful response for POST /source."""

    status: str
    source: str


class SourceErrorResponse(BaseModel):
    """Error response for POST /source when source is unknown."""

    error: str


def get_active_source() -> Optional[str]:
    """Return the currently active data source name, or None if none is active."""
    return _active_source


def reset_active_source() -> None:
    """Reset the active source to None (useful for testing)."""
    global _active_source
    _active_source = None


@router.post("/source", responses={400: {"model": SourceErrorResponse}})
async def activate_source(request: SourceRequest) -> SourceResponse:
    """Activate a data source adapter by name.

    Args:
        request: JSON body containing the source name to activate.

    Returns:
        HTTP 200 with status and source name on success.
        HTTP 400 with error message listing available sources on unknown name.
    """
    global _active_source

    source_name = request.source

    if source_name not in AVAILABLE_SOURCES:
        available_list = ", ".join(sorted(AVAILABLE_SOURCES))
        error_msg = f"Unknown source '{source_name}'. Available: {available_list}"
        logger.warning("source_activation_failed", source=source_name, error=error_msg)
        from fastapi.responses import JSONResponse

        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": error_msg},
        )

    _active_source = source_name
    logger.info("source_activated", source=source_name)

    return SourceResponse(status="active", source=source_name)
