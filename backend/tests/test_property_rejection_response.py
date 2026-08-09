"""Property-based tests for invalid event rejection response format and logging.

Uses the Hypothesis library to verify that any invalid telemetry event
produces a correct rejection response and log entry.

# Feature: digital-twin-telemetry-engine, Property 4: Invalid Event Rejection Produces Correct Response and Log
"""

# Feature: digital-twin-telemetry-engine, Property 4: Invalid Event Rejection Produces Correct Response and Log

import json
import string
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import hypothesis.strategies as st
from hypothesis import given, settings, assume
import pytest

from digital_twin_engine.shared.models import (
    MAX_PAYLOAD_BYTES,
    MAX_STRING_LENGTH,
    TelemetryValidationError,
    ValidationErrorCode,
    validate_telemetry_payload,
)
from digital_twin_engine.ingestion.server import create_app, _extract_sensor_id
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies for INVALID payloads
# ---------------------------------------------------------------------------

# Strategy for valid sensor_ids (used in payloads where sensor_id is parseable)
_valid_sensor_ids = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=64,
).filter(lambda s: s.strip() != "")

# Strategy for valid measurement types
_valid_measurement_types = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=64,
).filter(lambda s: s.strip() != "")

# Strategy for valid finite float values
_valid_float_values = st.floats(
    allow_nan=False,
    allow_infinity=False,
    min_value=-1e100,
    max_value=1e100,
)

# Strategy for valid timestamps
_valid_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(timezone.utc),
)


def _format_timestamp(dt: datetime) -> str:
    """Format datetime to ISO 8601 UTC string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --- Invalid timestamp strategies ---
_invalid_timestamps = st.one_of(
    st.just("not-a-timestamp"),
    st.just("2024-13-01T00:00:00Z"),
    st.just(""),
    st.just("12345"),
    st.text(
        alphabet=string.ascii_letters + string.digits + "-:",
        min_size=1,
        max_size=30,
    ).filter(lambda s: not _is_valid_iso8601(s)),
)

# --- Invalid sensor_id strategies ---
_invalid_sensor_ids = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),  # whitespace-only
    st.text(min_size=MAX_STRING_LENGTH + 1, max_size=MAX_STRING_LENGTH + 20),  # too long
)

# --- Invalid measurement_type strategies ---
_invalid_measurement_types = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),  # whitespace-only
    st.text(min_size=MAX_STRING_LENGTH + 1, max_size=MAX_STRING_LENGTH + 20),  # too long
)


def _is_valid_iso8601(s: str) -> bool:
    """Check if a string is a valid ISO 8601 UTC timestamp."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.tzinfo is not None
    except (ValueError, TypeError):
        return False


def _is_invalid_json(s: str) -> bool:
    """Check if a string is NOT valid JSON."""
    try:
        json.loads(s)
        return False
    except (json.JSONDecodeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Composite strategies that generate invalid payloads
# ---------------------------------------------------------------------------

@st.composite
def invalid_payload_with_parseable_sensor_id(draw):
    """Generate an invalid payload where the sensor_id is still parseable from JSON.

    Covers: invalid timestamp, invalid value (NaN/Inf), invalid measurement_type.
    """
    sensor_id = draw(_valid_sensor_ids)
    measurement_type = draw(_valid_measurement_types)
    value = draw(_valid_float_values)

    violation = draw(st.sampled_from([
        "invalid_timestamp",
        "invalid_value",
        "invalid_measurement_type",
    ]))

    if violation == "invalid_timestamp":
        timestamp = draw(_invalid_timestamps)
        payload = {
            "timestamp": timestamp,
            "sensor_id": sensor_id,
            "measurement_type": measurement_type,
            "value": value,
        }
        raw = json.dumps(payload)
    elif violation == "invalid_value":
        timestamp = _format_timestamp(draw(_valid_timestamps))
        bad_value = draw(st.sampled_from(["NaN", "Infinity", "-Infinity"]))
        raw = (
            '{"timestamp":' + json.dumps(timestamp) + ','
            '"sensor_id":' + json.dumps(sensor_id) + ','
            '"measurement_type":' + json.dumps(measurement_type) + ','
            '"value":' + bad_value + '}'
        )
    elif violation == "invalid_measurement_type":
        timestamp = _format_timestamp(draw(_valid_timestamps))
        bad_mt = draw(_invalid_measurement_types)
        payload = {
            "timestamp": timestamp,
            "sensor_id": sensor_id,
            "measurement_type": bad_mt,
            "value": value,
        }
        raw = json.dumps(payload)

    assume(len(raw.encode("utf-8")) <= MAX_PAYLOAD_BYTES)
    return raw, sensor_id, violation


@st.composite
def invalid_payload_any(draw):
    """Generate any kind of invalid payload (with or without parseable sensor_id).

    Covers all validation failure categories:
    - invalid_timestamp
    - invalid_value (NaN/Inf)
    - invalid_measurement_type (empty/whitespace-only)
    - invalid_sensor_id (empty/whitespace-only/too long)
    - missing_field
    - invalid_json
    - oversized_payload (exceeds 4096 bytes)
    """
    violation = draw(st.sampled_from([
        "invalid_timestamp",
        "invalid_value",
        "invalid_measurement_type",
        "invalid_sensor_id",
        "missing_field",
        "invalid_json",
        "oversized_payload",
    ]))

    if violation == "invalid_json":
        raw = draw(st.one_of(
            st.just("not json at all"),
            st.just("{broken json"),
            st.just("{{{{"),
            st.text(min_size=1, max_size=50).filter(_is_invalid_json),
        ))
        expected_sensor_id = None
    elif violation == "missing_field":
        timestamp = _format_timestamp(draw(_valid_timestamps))
        sensor_id = draw(_valid_sensor_ids)
        # Missing measurement_type or value
        field_to_keep = draw(st.sampled_from(["measurement_type", "value"]))
        payload = {"timestamp": timestamp, "sensor_id": sensor_id}
        if field_to_keep == "measurement_type":
            payload["measurement_type"] = draw(_valid_measurement_types)
        else:
            payload["value"] = draw(_valid_float_values)
        raw = json.dumps(payload)
        expected_sensor_id = sensor_id
    elif violation == "invalid_sensor_id":
        timestamp = _format_timestamp(draw(_valid_timestamps))
        bad_sensor_id = draw(_invalid_sensor_ids)
        payload = {
            "timestamp": timestamp,
            "sensor_id": bad_sensor_id,
            "measurement_type": draw(_valid_measurement_types),
            "value": draw(_valid_float_values),
        }
        raw = json.dumps(payload)
        expected_sensor_id = bad_sensor_id if isinstance(bad_sensor_id, str) else None
    elif violation == "invalid_timestamp":
        sensor_id = draw(_valid_sensor_ids)
        payload = {
            "timestamp": draw(_invalid_timestamps),
            "sensor_id": sensor_id,
            "measurement_type": draw(_valid_measurement_types),
            "value": draw(_valid_float_values),
        }
        raw = json.dumps(payload)
        expected_sensor_id = sensor_id
    elif violation == "invalid_value":
        sensor_id = draw(_valid_sensor_ids)
        timestamp = _format_timestamp(draw(_valid_timestamps))
        bad_value = draw(st.sampled_from(["NaN", "Infinity", "-Infinity"]))
        raw = (
            '{"timestamp":' + json.dumps(timestamp) + ','
            '"sensor_id":' + json.dumps(sensor_id) + ','
            '"measurement_type":' + json.dumps(draw(_valid_measurement_types)) + ','
            '"value":' + bad_value + '}'
        )
        expected_sensor_id = sensor_id
    elif violation == "invalid_measurement_type":
        sensor_id = draw(_valid_sensor_ids)
        timestamp = _format_timestamp(draw(_valid_timestamps))
        payload = {
            "timestamp": timestamp,
            "sensor_id": sensor_id,
            "measurement_type": draw(_invalid_measurement_types),
            "value": draw(_valid_float_values),
        }
        raw = json.dumps(payload)
        expected_sensor_id = sensor_id
    elif violation == "oversized_payload":
        sensor_id = draw(_valid_sensor_ids)
        timestamp = _format_timestamp(draw(_valid_timestamps))
        # Generate a payload that exceeds 4096 bytes by using a long measurement_type
        padding_size = MAX_PAYLOAD_BYTES + 100
        long_mt = "x" * padding_size
        payload = {
            "timestamp": timestamp,
            "sensor_id": sensor_id,
            "measurement_type": long_mt,
            "value": draw(_valid_float_values),
        }
        raw = json.dumps(payload)
        expected_sensor_id = sensor_id
        # Ensure it's actually oversized
        assume(len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES)
        return raw, expected_sensor_id, violation

    # For non-oversized violations, ensure within size limit
    if violation != "oversized_payload":
        assume(len(raw.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

    return raw, expected_sensor_id, violation


# ---------------------------------------------------------------------------
# Helper: simulate server rejection logic (mirrors server.py handler)
# ---------------------------------------------------------------------------

def _build_rejection_response(raw_payload: str) -> dict | None:
    """Simulate the server's rejection response building logic.

    This mirrors the logic in the WebSocket handler to validate that the
    response format is always correct for any invalid payload.
    """
    sensor_id = _extract_sensor_id(raw_payload)
    rejected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    try:
        validate_telemetry_payload(raw_payload)
        return None  # Valid payload, no rejection
    except TelemetryValidationError as val_err:
        return {
            "error_code": val_err.code.value,
            "message": val_err.message,
            "sensor_id": sensor_id,
            "rejected_at": rejected_at,
        }


# ---------------------------------------------------------------------------
# Property 4: Invalid Event Rejection Produces Correct Response and Log
# ---------------------------------------------------------------------------


class TestProperty4InvalidEventRejectionResponse:
    """Property 4: Invalid Event Rejection Produces Correct Response and Log.

    For any Telemetry_Event that fails schema validation, the rejection response
    SHALL contain a machine-readable error_code field and a human-readable message
    field, AND the system SHALL emit a log entry containing the sensor_id
    (if parseable), the rejection timestamp, and the specific validation error.

    **Validates: Requirements 1.5, 1.7**
    """

    @given(data=invalid_payload_any())
    @settings(max_examples=50)
    def test_rejection_response_contains_error_code_and_message(self, data):
        """For any invalid payload, the rejection response SHALL contain error_code and message.

        The error_code is machine-readable (one of the defined ValidationErrorCode values).
        The message is human-readable (non-empty descriptive string).
        """
        raw_payload, expected_sensor_id, violation = data

        response = _build_rejection_response(raw_payload)

        # Must produce a rejection (not None)
        assert response is not None, (
            f"Expected rejection for violation={violation} but got None"
        )

        # Response SHALL contain a machine-readable error_code field
        assert "error_code" in response
        assert isinstance(response["error_code"], str)
        assert len(response["error_code"]) > 0

        # error_code must be one of the defined ValidationErrorCode enum values
        valid_codes = {e.value for e in ValidationErrorCode}
        assert response["error_code"] in valid_codes, (
            f"error_code '{response['error_code']}' not in {valid_codes}"
        )

        # Response SHALL contain a human-readable message field
        assert "message" in response
        assert isinstance(response["message"], str)
        assert len(response["message"]) > 0

    @given(data=invalid_payload_with_parseable_sensor_id())
    @settings(max_examples=50)
    def test_rejection_response_includes_sensor_id_when_parseable(self, data):
        """When sensor_id is parseable from the payload, it appears in the response."""
        raw_payload, expected_sensor_id, violation = data

        response = _build_rejection_response(raw_payload)
        assert response is not None

        # sensor_id should match what's extractable from the raw JSON
        assert "sensor_id" in response
        assert response["sensor_id"] == expected_sensor_id

    @given(data=invalid_payload_any())
    @settings(max_examples=50)
    def test_rejection_response_includes_rejection_timestamp(self, data):
        """Rejection response includes a rejected_at timestamp in ISO 8601 UTC."""
        raw_payload, _, violation = data

        response = _build_rejection_response(raw_payload)
        assert response is not None

        assert "rejected_at" in response
        rejected_at = response["rejected_at"]
        assert isinstance(rejected_at, str)
        assert rejected_at.endswith("Z")

        # Must be a parseable ISO 8601 timestamp
        dt = datetime.fromisoformat(rejected_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    @given(data=invalid_payload_with_parseable_sensor_id())
    @settings(max_examples=50, deadline=None)
    def test_log_entry_emitted_with_required_fields(self, data):
        """System SHALL emit log entry with sensor_id, rejection timestamp, and validation error.

        Uses the WebSocket server to verify the full flow including logging.
        Mocks the publisher's broker connection to avoid Kafka connection hangs
        during Hypothesis iterations.
        """
        raw_payload, expected_sensor_id, violation = data

        captured_calls = []

        def capture_warning(*args, **kwargs):
            captured_calls.append(("warning", args, kwargs))

        with patch("digital_twin_engine.ingestion.server.logger") as mock_logger, \
             patch("digital_twin_engine.ingestion.publisher.TelemetryPublisher._connect_kafka", return_value=None), \
             patch("digital_twin_engine.ingestion.publisher.TelemetryPublisher._connect_redis", return_value=None), \
             patch("digital_twin_engine.ingestion.publisher.TelemetryPublisher._disconnect", return_value=None):
            mock_logger.warning = capture_warning
            mock_logger.info = MagicMock()
            mock_logger.error = MagicMock()
            mock_logger.debug = MagicMock()

            app = create_app()

            with TestClient(app) as client:
                with client.websocket_connect("/ws/telemetry") as ws:
                    ws.send_text(raw_payload)
                    ws.receive_text()  # consume error response

        # Find rejection log entries
        rejection_logs = [
            call for call in captured_calls
            if call[1] and "rejected" in str(call[1][0]).lower()
        ]
        assert len(rejection_logs) >= 1, (
            f"No rejection log entry found for violation={violation}. "
            f"Captured warning calls: {[(c[1], list(c[2].keys())) for c in captured_calls]}"
        )

        log_call = rejection_logs[0]
        log_kwargs = log_call[2]

        # Log SHALL contain sensor_id (if parseable)
        assert "sensor_id" in log_kwargs, (
            f"Log entry missing 'sensor_id'. Keys: {list(log_kwargs.keys())}"
        )
        assert log_kwargs["sensor_id"] == expected_sensor_id

        # Log SHALL contain rejection timestamp
        assert "rejected_at" in log_kwargs, (
            f"Log entry missing 'rejected_at'. Keys: {list(log_kwargs.keys())}"
        )
        rejected_at = log_kwargs["rejected_at"]
        assert isinstance(rejected_at, str)
        assert rejected_at.endswith("Z")

        # Log SHALL contain the specific validation error
        has_error_info = (
            "validation_error" in log_kwargs
            or "error_code" in log_kwargs
        )
        assert has_error_info, (
            f"Log entry missing validation error details. Keys: {list(log_kwargs.keys())}"
        )
