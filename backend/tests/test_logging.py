"""Tests for the structured logging module.

Validates: Requirements 8.7, 8.8
"""

import json
from datetime import datetime, timezone
from io import StringIO

import pytest
import structlog

from digital_twin_engine.shared.logging import (
    configure_logging,
    correlation_context,
    generate_correlation_id,
    get_correlation_id,
    get_logger,
    set_correlation_id,
)


class _StringIOLogger:
    """A minimal logger that writes to a shared StringIO for test capture."""

    def __init__(self, buffer: StringIO):
        self._buffer = buffer

    def msg(self, message: str) -> None:
        self._buffer.write(message + "\n")

    # structlog may call these aliases
    log = debug = info = warning = error = critical = fatal = msg


def _make_test_config(buffer: StringIO) -> None:
    """Configure structlog to write JSON to a StringIO buffer for testing."""
    from digital_twin_engine.shared.logging import (
        _add_correlation_id,
        _add_severity_level,
        _add_timestamp,
        _rename_event_to_message,
    )

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


@pytest.fixture(autouse=True)
def log_buffer():
    """Provide a fresh StringIO buffer and configure structlog to use it."""
    buffer = StringIO()
    _make_test_config(buffer)
    yield buffer
    structlog.reset_defaults()


def _capture_log(buffer: StringIO, logger, method: str, message: str, **kwargs) -> dict:
    """Log a message and return the parsed JSON entry."""
    buffer.truncate(0)
    buffer.seek(0)
    getattr(logger, method)(message, **kwargs)
    output = buffer.getvalue().strip()
    return json.loads(output)


class TestStructuredLogFormat:
    """Verify requirement 8.7: machine-parseable log with required fields."""

    def test_log_entry_contains_timestamp(self, log_buffer):
        logger = get_logger("test_component")
        entry = _capture_log(log_buffer, logger, "info", "test message")
        assert "timestamp" in entry
        # Verify ISO 8601 UTC format
        ts = datetime.fromisoformat(entry["timestamp"])
        assert ts.tzinfo == timezone.utc

    def test_log_entry_contains_severity_level(self, log_buffer):
        logger = get_logger("test_component")
        entry = _capture_log(log_buffer, logger, "info", "test message")
        assert entry["level"] == "INFO"

    def test_log_entry_contains_component_name(self, log_buffer):
        logger = get_logger("ingestion_server")
        entry = _capture_log(log_buffer, logger, "info", "test message")
        assert entry["component"] == "ingestion_server"

    def test_log_entry_contains_message(self, log_buffer):
        logger = get_logger("test_component")
        entry = _capture_log(log_buffer, logger, "info", "Something happened")
        assert entry["message"] == "Something happened"

    def test_log_is_valid_json(self, log_buffer):
        logger = get_logger("test_component")
        log_buffer.truncate(0)
        log_buffer.seek(0)
        logger.info("json test")
        output = log_buffer.getvalue().strip()
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    @pytest.mark.parametrize(
        "method,expected_level",
        [
            ("debug", "DEBUG"),
            ("info", "INFO"),
            ("warning", "WARN"),
            ("error", "ERROR"),
        ],
    )
    def test_severity_levels(self, log_buffer, method, expected_level):
        logger = get_logger("test_component")
        entry = _capture_log(log_buffer, logger, method, "level test")
        assert entry["level"] == expected_level

    def test_extra_fields_included(self, log_buffer):
        logger = get_logger("test_component")
        entry = _capture_log(log_buffer, logger, "info", "with extras", sensor_id="s1", value=42.5)
        assert entry["sensor_id"] == "s1"
        assert entry["value"] == 42.5


class TestCorrelationId:
    """Verify requirement 8.8: correlation ID propagation."""

    def test_no_correlation_id_by_default(self, log_buffer):
        logger = get_logger("test_component")
        entry = _capture_log(log_buffer, logger, "info", "no correlation")
        assert "correlation_id" not in entry

    def test_correlation_id_in_context(self, log_buffer):
        logger = get_logger("test_component")
        with correlation_context("req-123"):
            entry = _capture_log(log_buffer, logger, "error", "something failed")
        assert entry["correlation_id"] == "req-123"

    def test_correlation_id_cleared_after_context(self, log_buffer):
        logger = get_logger("test_component")
        with correlation_context("req-123"):
            pass
        entry = _capture_log(log_buffer, logger, "info", "after context")
        assert "correlation_id" not in entry

    def test_auto_generated_correlation_id(self, log_buffer):
        logger = get_logger("test_component")
        with correlation_context() as cid:
            entry = _capture_log(log_buffer, logger, "info", "auto id")
            assert entry["correlation_id"] == cid
            assert len(cid) > 0

    def test_nested_correlation_context(self, log_buffer):
        logger = get_logger("test_component")
        with correlation_context("outer"):
            with correlation_context("inner"):
                entry = _capture_log(log_buffer, logger, "info", "nested")
                assert entry["correlation_id"] == "inner"
            entry = _capture_log(log_buffer, logger, "info", "back to outer")
            assert entry["correlation_id"] == "outer"

    def test_set_and_get_correlation_id(self):
        token = set_correlation_id("manual-id")
        assert get_correlation_id() == "manual-id"
        # Cleanup
        set_correlation_id(None)

    def test_generate_correlation_id_unique(self):
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100

    def test_error_log_with_correlation_id(self, log_buffer):
        """Requirement 8.8: error logs include correlation ID."""
        logger = get_logger("correction_engine")
        with correlation_context("event-456"):
            entry = _capture_log(
                log_buffer,
                logger,
                "error",
                "EnKF iteration failed",
                sensor_id="turbine-001",
            )
        assert entry["level"] == "ERROR"
        assert entry["correlation_id"] == "event-456"
        assert entry["component"] == "correction_engine"
        assert entry["sensor_id"] == "turbine-001"


class TestMultipleComponents:
    """Verify that different components get distinct loggers."""

    def test_different_component_names(self, log_buffer):
        logger_a = get_logger("ingestion_server")
        logger_b = get_logger("ml_service")

        entry_a = _capture_log(log_buffer, logger_a, "info", "msg a")
        entry_b = _capture_log(log_buffer, logger_b, "info", "msg b")

        assert entry_a["component"] == "ingestion_server"
        assert entry_b["component"] == "ml_service"
