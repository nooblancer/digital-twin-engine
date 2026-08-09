"""Property-based tests for the structured logging module.

# Feature: digital-twin-telemetry-engine, Property 21: Structured Log Format Invariant

Validates: Requirements 8.7

Property 21: Structured Log Format Invariant
For any log entry emitted by any pipeline component, the log record SHALL be
machine-parseable and contain at minimum: a UTC timestamp in ISO 8601 format,
a severity level (one of DEBUG, INFO, WARN, ERROR), the component name, and
a message string.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import StringIO

import structlog
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from digital_twin_engine.shared.logging import (
    configure_logging,
    correlation_context,
    get_logger,
    _add_correlation_id,
    _add_severity_level,
    _add_timestamp,
    _rename_event_to_message,
)


# ---------------------------------------------------------------------------
# Custom Strategies
# ---------------------------------------------------------------------------

# Strategy for component names: realistic pipeline component identifiers
component_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{2,30}", fullmatch=True)

# Strategy for log levels: the four supported severity levels
log_level_strategy = st.sampled_from(["debug", "info", "warning", "error"])

# Strategy for message strings: non-empty printable text (avoid null bytes)
message_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=200,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

class _StringIOLogger:
    """A minimal logger that writes to a shared StringIO for test capture."""

    def __init__(self, buffer: StringIO):
        self._buffer = buffer

    def msg(self, message: str) -> None:
        self._buffer.write(message + "\n")

    log = debug = info = warning = error = critical = fatal = msg


def _configure_test_logging(buffer: StringIO) -> None:
    """Configure structlog to write JSON to a StringIO buffer for testing."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_timestamp,
            _add_severity_level,
            _add_correlation_id,
            _rename_event_to_message,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=lambda: _StringIOLogger(buffer),
        cache_logger_on_first_use=False,
    )


VALID_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestStructuredLogFormatInvariant:
    """Property 21: Structured Log Format Invariant

    **Validates: Requirements 8.7**

    For any log entry emitted by any pipeline component, the log record SHALL be
    machine-parseable and contain at minimum: a UTC timestamp in ISO 8601 format,
    a severity level (one of DEBUG, INFO, WARN, ERROR), the component name, and
    a message string.
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        component=component_name_strategy,
        level=log_level_strategy,
        message=message_strategy,
    )
    def test_log_entry_is_machine_parseable_with_required_fields(
        self, component: str, level: str, message: str
    ) -> None:
        """Every log entry must be valid JSON containing timestamp, level,
        component, and message fields regardless of input."""
        # Setup
        buffer = StringIO()
        _configure_test_logging(buffer)

        try:
            # Act - emit a log entry
            logger = get_logger(component)
            getattr(logger, level)(message)

            # Get the output
            output = buffer.getvalue().strip()
            assert output, "Log output should not be empty"

            # Property: log entry must be machine-parseable (valid JSON)
            entry = json.loads(output)
            assert isinstance(entry, dict), "Log entry must be a JSON object"

            # Property: must contain UTC timestamp in ISO 8601 format
            assert "timestamp" in entry, "Log entry must contain 'timestamp'"
            ts = datetime.fromisoformat(entry["timestamp"])
            assert ts.tzinfo == timezone.utc, "Timestamp must be UTC"

            # Property: must contain severity level (one of DEBUG, INFO, WARN, ERROR)
            assert "level" in entry, "Log entry must contain 'level'"
            assert entry["level"] in VALID_LEVELS, (
                f"Level must be one of {VALID_LEVELS}, got '{entry['level']}'"
            )

            # Property: must contain component name
            assert "component" in entry, "Log entry must contain 'component'"
            assert entry["component"] == component, (
                f"Component must match, expected '{component}', got '{entry['component']}'"
            )

            # Property: must contain a message string
            assert "message" in entry, "Log entry must contain 'message'"
            assert isinstance(entry["message"], str), "Message must be a string"
            assert entry["message"] == message, (
                f"Message must match the logged text"
            )
        finally:
            structlog.reset_defaults()

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        component=component_name_strategy,
        level=log_level_strategy,
        message=message_strategy,
        extra_key=st.from_regex(r"[a-z][a-z0-9_]{1,15}", fullmatch=True),
        extra_value=st.one_of(st.integers(), st.floats(allow_nan=False), st.text(min_size=1, max_size=50)),
    )
    def test_extra_fields_do_not_break_required_structure(
        self, component: str, level: str, message: str, extra_key: str, extra_value
    ) -> None:
        """Adding arbitrary extra fields must not break the required log structure."""
        # Avoid collisions with required keys
        reserved_keys = {"timestamp", "level", "component", "message", "event", "correlation_id"}
        if extra_key in reserved_keys:
            return  # Skip this example - not interesting

        buffer = StringIO()
        _configure_test_logging(buffer)

        try:
            logger = get_logger(component)
            getattr(logger, level)(message, **{extra_key: extra_value})

            output = buffer.getvalue().strip()
            entry = json.loads(output)

            # Required fields must still be present
            assert "timestamp" in entry
            assert "level" in entry and entry["level"] in VALID_LEVELS
            assert "component" in entry and entry["component"] == component
            assert "message" in entry and entry["message"] == message

            # Extra field should be included
            assert extra_key in entry
        finally:
            structlog.reset_defaults()

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        component=component_name_strategy,
        level=log_level_strategy,
        message=message_strategy,
        correlation_id=st.uuids().map(str),
    )
    def test_correlation_id_does_not_displace_required_fields(
        self, component: str, level: str, message: str, correlation_id: str
    ) -> None:
        """When a correlation ID is active, all required fields must still be present."""
        buffer = StringIO()
        _configure_test_logging(buffer)

        try:
            logger = get_logger(component)
            with correlation_context(correlation_id):
                getattr(logger, level)(message)

            output = buffer.getvalue().strip()
            entry = json.loads(output)

            # All required fields still present
            assert "timestamp" in entry
            ts = datetime.fromisoformat(entry["timestamp"])
            assert ts.tzinfo == timezone.utc
            assert entry["level"] in VALID_LEVELS
            assert entry["component"] == component
            assert entry["message"] == message
            # Correlation ID should also be present
            assert entry["correlation_id"] == correlation_id
        finally:
            structlog.reset_defaults()
