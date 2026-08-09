"""Structured logging module for the Digital Twin Telemetry Engine.

Provides JSON-formatted structured logging with:
- UTC timestamps in ISO 8601 format
- Severity levels: DEBUG, INFO, WARN, ERROR
- Component name in every log entry
- Correlation ID propagation across components

Usage:
    from digital_twin_engine.shared.logging import get_logger, correlation_context

    logger = get_logger("ingestion_server")
    logger.info("Event received", sensor_id="turbine-001")

    # With correlation ID context
    with correlation_context("req-abc-123"):
        logger.error("Broker unreachable", retry_count=3)

Validates: Requirements 8.7, 8.8
"""

from __future__ import annotations

import contextvars
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog


# Context variable for correlation ID propagation across async boundaries
_correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    """Retrieve the current correlation ID from context."""
    return _correlation_id_var.get()


def set_correlation_id(correlation_id: str | None) -> contextvars.Token[str | None]:
    """Set the correlation ID in context. Returns a token to restore the previous value."""
    return _correlation_id_var.set(correlation_id)


def generate_correlation_id() -> str:
    """Generate a new unique correlation ID."""
    return str(uuid.uuid4())


class correlation_context:
    """Context manager for scoped correlation ID propagation.

    Usage:
        with correlation_context("req-abc-123"):
            logger.info("Processing request")
            # All log entries within this block include correlation_id="req-abc-123"

        # Or auto-generate a correlation ID:
        with correlation_context() as cid:
            logger.info("Processing", correlation_id_generated=cid)
    """

    def __init__(self, correlation_id: str | None = None) -> None:
        self._correlation_id = correlation_id or generate_correlation_id()
        self._token: contextvars.Token[str | None] | None = None

    def __enter__(self) -> str:
        self._token = set_correlation_id(self._correlation_id)
        return self._correlation_id

    def __exit__(self, *_: Any) -> None:
        if self._token is not None:
            _correlation_id_var.reset(self._token)


def _add_timestamp(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add UTC ISO 8601 timestamp to every log entry."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def _add_severity_level(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Normalize the severity level field to uppercase standard values.

    Maps structlog method names to: DEBUG, INFO, WARN, ERROR.
    """
    level_map = {
        "debug": "DEBUG",
        "info": "INFO",
        "warning": "WARN",
        "warn": "WARN",
        "error": "ERROR",
        "critical": "ERROR",
        "fatal": "ERROR",
    }
    raw_level = method_name.lower()
    event_dict["level"] = level_map.get(raw_level, raw_level.upper())
    return event_dict


def _add_correlation_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject correlation ID from context into the log entry if present."""
    correlation_id = get_correlation_id()
    if correlation_id is not None:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def _rename_event_to_message(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Rename structlog's 'event' key to 'message' for clarity."""
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")
    return event_dict


def configure_logging() -> None:
    """Configure structlog for JSON output with required fields.

    Call this once at application startup. After calling, all loggers
    created via get_logger() will emit structured JSON logs.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_timestamp,
            _add_severity_level,
            _add_correlation_id,
            _rename_event_to_message,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str) -> structlog.stdlib.BoundLogger:
    """Create a structured logger bound to a specific component name.

    Args:
        component: The name of the pipeline component (e.g., "ingestion_server",
                   "ml_service", "correction_engine").

    Returns:
        A bound structlog logger with the component name pre-attached.
    """
    return structlog.get_logger(component=component)


# Auto-configure on module import for convenience.
# Components can call configure_logging() again if they need custom settings.
configure_logging()
