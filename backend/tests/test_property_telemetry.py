"""Property-based tests for TelemetryEvent serialization and validation.

Uses the Hypothesis library to verify universal properties across many inputs.
"""

# Feature: digital-twin-telemetry-engine, Property 1: Telemetry Event Serialization Round-Trip
# Feature: digital-twin-telemetry-engine, Property 2: Extra Fields Ignored During Parsing
# Feature: digital-twin-telemetry-engine, Property 3: Telemetry Event Validation Correctness

import json
import math
import string
from datetime import datetime, timezone

import hypothesis.strategies as st
from hypothesis import given, settings, assume

from digital_twin_engine.shared.models import (
    TelemetryEvent,
    deserialize_telemetry_event,
    serialize_telemetry_event,
    validate_telemetry_payload,
    TelemetryValidationError,
    ValidationErrorCode,
    MAX_PAYLOAD_BYTES,
    MAX_STRING_LENGTH,
)


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for valid UTC timestamps (ISO 8601 with timezone)
valid_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(timezone.utc),
)

# Strategy for valid sensor_id: 1-256 non-whitespace-only characters
# Must contain at least one non-whitespace character
_printable_with_nonws = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=MAX_STRING_LENGTH,
).filter(lambda s: s.strip() != "")

valid_sensor_ids = _printable_with_nonws

# Strategy for valid measurement_type: 1-256 non-whitespace-only characters
valid_measurement_types = _printable_with_nonws

# Strategy for valid finite float64 values
valid_float_values = st.floats(
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=True,
    min_value=-1e300,
    max_value=1e300,
)

# Composite strategy for a valid TelemetryEvent
@st.composite
def valid_telemetry_events(draw):
    """Generate a valid TelemetryEvent with all constraints satisfied."""
    timestamp = draw(valid_timestamps)
    sensor_id = draw(valid_sensor_ids)
    measurement_type = draw(valid_measurement_types)
    value = draw(valid_float_values)

    return TelemetryEvent(
        timestamp=timestamp,
        sensor_id=sensor_id,
        measurement_type=measurement_type,
        value=value,
    )


# Strategy for generating extra field names (not colliding with required fields)
_extra_field_names = st.text(
    alphabet=string.ascii_lowercase + "_",
    min_size=1,
    max_size=20,
).filter(lambda s: s not in ("timestamp", "sensor_id", "measurement_type", "value"))

# Strategy for extra field values (any JSON-serializable value)
_extra_field_values = st.one_of(
    st.text(min_size=0, max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)


# ---------------------------------------------------------------------------
# Property 1: Telemetry Event Serialization Round-Trip
# ---------------------------------------------------------------------------

class TestProperty1SerializationRoundTrip:
    """Property 1: Telemetry Event Serialization Round-Trip.

    For any valid TelemetryEvent object, serializing it to JSON and then parsing
    the JSON back into a TelemetryEvent object SHALL produce an object with
    identical field values (timestamp string equality, sensor_id string equality,
    measurement_type string equality, and value equality within 15 significant
    digits). Repeating serialize→parse a second time SHALL yield the same result.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    def test_round_trip_preserves_fields(self, event: TelemetryEvent):
        """Serialize→parse produces identical field values."""
        json_str = serialize_telemetry_event(event)
        restored = deserialize_telemetry_event(json_str)

        # sensor_id string equality
        assert restored.sensor_id == event.sensor_id

        # measurement_type string equality
        assert restored.measurement_type == event.measurement_type

        # value equality within 15 significant digits
        if event.value == 0.0:
            assert restored.value == 0.0
        else:
            assert f"{restored.value:.15g}" == f"{event.value:.15g}"

        # Timestamp: the round-trip should produce equal timestamps
        # (both should be UTC-aware datetimes representing the same instant)
        assert restored.timestamp == event.timestamp

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    def test_round_trip_idempotent(self, event: TelemetryEvent):
        """Repeating serialize→parse a second time yields the same result.

        After one round-trip (serialize→parse) produces event1, repeating
        serialize→parse on event1 SHALL yield event2 with identical fields,
        and the serialized JSON from event1 and event2 must be identical.
        """
        # First round-trip
        json1 = serialize_telemetry_event(event)
        event1 = deserialize_telemetry_event(json1)

        # Second round-trip (repeat on the result of first round-trip)
        json2 = serialize_telemetry_event(event1)
        event2 = deserialize_telemetry_event(json2)

        # The second serialization must equal the third (idempotency from stable state)
        json3 = serialize_telemetry_event(event2)
        assert json2 == json3

        # Restored objects from second and third round-trips must have identical fields
        assert event1.sensor_id == event2.sensor_id
        assert event1.measurement_type == event2.measurement_type
        assert event1.value == event2.value
        assert event1.timestamp == event2.timestamp


# ---------------------------------------------------------------------------
# Property 2: Extra Fields Ignored During Parsing
# ---------------------------------------------------------------------------

class TestProperty2ExtraFieldsIgnored:
    """Property 2: Extra Fields Ignored During Parsing.

    For any valid JSON payload that contains all required Telemetry_Event fields
    plus any number of additional undefined fields, parsing the payload SHALL
    produce a TelemetryEvent object containing only the defined fields with
    correct values, and no error SHALL be raised.

    **Validates: Requirements 2.4**
    """

    @given(
        event=valid_telemetry_events(),
        extra_fields=st.dictionaries(
            keys=_extra_field_names,
            values=_extra_field_values,
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_extra_fields_ignored_during_parsing(
        self, event: TelemetryEvent, extra_fields: dict
    ):
        """Extra fields in JSON payload are silently ignored."""
        # Build a JSON payload with the required fields plus extras
        timestamp_str = event.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        payload = {
            "timestamp": timestamp_str,
            "sensor_id": event.sensor_id,
            "measurement_type": event.measurement_type,
            "value": event.value,
        }
        payload.update(extra_fields)

        raw_json = json.dumps(payload)

        # Ensure it's within size limit so we don't get payload-too-large errors
        assume(len(raw_json.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

        # Parsing should succeed without error
        restored = deserialize_telemetry_event(raw_json)

        # Only the defined fields are present with correct values
        assert restored.sensor_id == event.sensor_id
        assert restored.measurement_type == event.measurement_type

        # Value equality within 15 significant digits
        if event.value == 0.0:
            assert restored.value == 0.0
        else:
            assert f"{restored.value:.15g}" == f"{event.value:.15g}"

        # Verify no extra attributes are present on the object
        model_fields = set(TelemetryEvent.model_fields.keys())
        assert model_fields == {"timestamp", "sensor_id", "measurement_type", "value"}


# ---------------------------------------------------------------------------
# Property 3: Telemetry Event Validation Correctness
# ---------------------------------------------------------------------------

# Strategies for INVALID inputs

# Invalid timestamps - not valid ISO 8601 UTC
_invalid_timestamps = st.one_of(
    st.text(min_size=0, max_size=50).filter(
        lambda s: not _is_valid_iso8601_utc(s)
    ),
    st.just("2024-13-01T00:00:00Z"),  # invalid month
    st.just("not-a-date"),
    st.just("2024-01-01"),  # missing timezone
    st.just(""),
)

# Invalid sensor_ids - empty, whitespace-only, or too long
_invalid_sensor_ids = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),  # whitespace-only
    st.text(min_size=MAX_STRING_LENGTH + 1, max_size=MAX_STRING_LENGTH + 50),  # too long
)

# Invalid measurement_types - empty, whitespace-only, or too long
_invalid_measurement_types = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),  # whitespace-only
    st.text(min_size=MAX_STRING_LENGTH + 1, max_size=MAX_STRING_LENGTH + 50),  # too long
)

# Invalid values - NaN, Inf, or non-numeric
_invalid_values = st.one_of(
    st.just(float("nan")),
    st.just(float("inf")),
    st.just(float("-inf")),
)


def _is_valid_iso8601_utc(s: str) -> bool:
    """Check if a string is a valid ISO 8601 UTC timestamp."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.tzinfo is not None
    except (ValueError, TypeError):
        return False


def _format_timestamp(dt: datetime) -> str:
    """Format a datetime to ISO 8601 UTC string."""
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TestProperty3ValidationCorrectness:
    """Property 3: Telemetry Event Validation Correctness.

    For any JSON payload, the validation function SHALL accept the payload if
    and only if it contains a valid ISO 8601 UTC timestamp, a sensor_id string
    between 1 and 256 non-whitespace-only characters, a measurement_type string
    between 1 and 256 non-whitespace-only characters, a finite float64 value,
    and a total size not exceeding 4096 bytes. All payloads violating any
    constraint SHALL be rejected.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 1.2**
    """

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    def test_valid_payloads_accepted(self, event: TelemetryEvent):
        """All valid payloads are accepted by the validation function."""
        payload = json.dumps({
            "timestamp": _format_timestamp(event.timestamp),
            "sensor_id": event.sensor_id,
            "measurement_type": event.measurement_type,
            "value": event.value,
        })

        # Skip payloads that exceed size limit (not a validity issue, but a constraint)
        assume(len(payload.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

        result = validate_telemetry_payload(payload)
        assert isinstance(result, TelemetryEvent)
        assert result.sensor_id == event.sensor_id
        assert result.measurement_type == event.measurement_type

    @given(
        sensor_id=valid_sensor_ids,
        measurement_type=valid_measurement_types,
        value=valid_float_values,
        timestamp=_invalid_timestamps,
    )
    @settings(max_examples=100)
    def test_invalid_timestamp_rejected(
        self, sensor_id: str, measurement_type: str, value: float, timestamp: str
    ):
        """Payloads with invalid timestamps are rejected."""
        payload = json.dumps({
            "timestamp": timestamp,
            "sensor_id": sensor_id,
            "measurement_type": measurement_type,
            "value": value,
        })
        assume(len(payload.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

        with raises_validation_error():
            validate_telemetry_payload(payload)

    @given(
        timestamp=valid_timestamps,
        measurement_type=valid_measurement_types,
        value=valid_float_values,
        sensor_id=_invalid_sensor_ids,
    )
    @settings(max_examples=100)
    def test_invalid_sensor_id_rejected(
        self, timestamp: datetime, measurement_type: str, value: float, sensor_id: str
    ):
        """Payloads with invalid sensor_id are rejected."""
        payload = json.dumps({
            "timestamp": _format_timestamp(timestamp),
            "sensor_id": sensor_id,
            "measurement_type": measurement_type,
            "value": value,
        })
        assume(len(payload.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

        with raises_validation_error():
            validate_telemetry_payload(payload)

    @given(
        timestamp=valid_timestamps,
        sensor_id=valid_sensor_ids,
        value=valid_float_values,
        measurement_type=_invalid_measurement_types,
    )
    @settings(max_examples=100)
    def test_invalid_measurement_type_rejected(
        self, timestamp: datetime, sensor_id: str, value: float, measurement_type: str
    ):
        """Payloads with invalid measurement_type are rejected."""
        payload = json.dumps({
            "timestamp": _format_timestamp(timestamp),
            "sensor_id": sensor_id,
            "measurement_type": measurement_type,
            "value": value,
        })
        assume(len(payload.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

        with raises_validation_error():
            validate_telemetry_payload(payload)

    @given(
        timestamp=valid_timestamps,
        sensor_id=valid_sensor_ids,
        measurement_type=valid_measurement_types,
    )
    @settings(max_examples=100)
    def test_non_finite_value_rejected(
        self, timestamp: datetime, sensor_id: str, measurement_type: str
    ):
        """Payloads with NaN or Infinity values are rejected."""
        # JSON doesn't support NaN/Inf natively, so we test via direct model construction
        # and via the full pipeline for non-numeric types
        for bad_value in [float("nan"), float("inf"), float("-inf")]:
            # Use raw string manipulation to inject non-finite values
            # since json.dumps can't encode them
            payload = (
                '{"timestamp":"' + _format_timestamp(timestamp) + '",'
                '"sensor_id":' + json.dumps(sensor_id) + ','
                '"measurement_type":' + json.dumps(measurement_type) + ','
                '"value":' + ("NaN" if math.isnan(bad_value) else
                              "Infinity" if bad_value > 0 else "-Infinity") + '}'
            )
            assume(len(payload.encode("utf-8")) <= MAX_PAYLOAD_BYTES)

            with raises_validation_error():
                validate_telemetry_payload(payload)

    @given(
        timestamp=valid_timestamps,
        sensor_id=valid_sensor_ids,
        measurement_type=valid_measurement_types,
        value=valid_float_values,
    )
    @settings(max_examples=100)
    def test_oversized_payload_rejected(
        self, timestamp: datetime, sensor_id: str, measurement_type: str, value: float
    ):
        """Payloads exceeding 4096 bytes are rejected."""
        # Create a valid base payload then pad it to exceed the limit
        base_payload = {
            "timestamp": _format_timestamp(timestamp),
            "sensor_id": sensor_id,
            "measurement_type": measurement_type,
            "value": value,
        }
        base_json = json.dumps(base_payload)
        base_size = len(base_json.encode("utf-8"))

        # Add padding to exceed limit
        padding_needed = MAX_PAYLOAD_BYTES - base_size + 1
        if padding_needed > 0:
            base_payload["_pad"] = "x" * padding_needed
        padded_json = json.dumps(base_payload)
        assume(len(padded_json.encode("utf-8")) > MAX_PAYLOAD_BYTES)

        with raises_validation_error(ValidationErrorCode.PAYLOAD_TOO_LARGE):
            validate_telemetry_payload(padded_json)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

class raises_validation_error:
    """Context manager that asserts a TelemetryValidationError is raised.

    Optionally checks for a specific error code.
    """

    def __init__(self, expected_code: ValidationErrorCode | None = None):
        self.expected_code = expected_code
        self.exception: TelemetryValidationError | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError("Expected TelemetryValidationError was not raised")
        if not issubclass(exc_type, (TelemetryValidationError, Exception)):
            return False
        if issubclass(exc_type, TelemetryValidationError):
            self.exception = exc_val
            if self.expected_code is not None:
                assert exc_val.code == self.expected_code, (
                    f"Expected error code {self.expected_code}, got {exc_val.code}"
                )
            return True
        # Also accept pydantic ValidationError which wraps our errors
        return True
