"""Unit tests for shared data models and validation."""

import json
import math
from datetime import datetime, timezone

import numpy as np
import pytest

from digital_twin_engine.shared import (
    ComponentStatus,
    EngineConfig,
    EnKFState,
    HealthStatus,
    Prediction,
    StateVector,
    TelemetryEvent,
    TelemetryValidationError,
    ValidationErrorCode,
    deserialize_telemetry_event,
    serialize_telemetry_event,
    validate_payload_size,
    validate_telemetry_payload,
)


# ---------------------------------------------------------------------------
# TelemetryEvent creation and validation
# ---------------------------------------------------------------------------

class TestTelemetryEventCreation:
    """Tests for valid TelemetryEvent construction."""

    def test_valid_event_from_fields(self):
        event = TelemetryEvent(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, 123456, tzinfo=timezone.utc),
            sensor_id="turbine-001-temp",
            measurement_type="temperature_celsius",
            value=342.17,
        )
        assert event.sensor_id == "turbine-001-temp"
        assert event.measurement_type == "temperature_celsius"
        assert event.value == 342.17

    def test_valid_event_from_iso_string(self):
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00.123456Z",
            sensor_id="s1",
            measurement_type="temp",
            value=1.0,
        )
        assert event.timestamp.tzinfo is not None

    def test_sensor_id_max_length(self):
        """256-char sensor_id is valid."""
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00Z",
            sensor_id="a" * 256,
            measurement_type="temp",
            value=1.0,
        )
        assert len(event.sensor_id) == 256

    def test_value_zero(self):
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00Z",
            sensor_id="s1",
            measurement_type="temp",
            value=0.0,
        )
        assert event.value == 0.0

    def test_value_negative(self):
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00Z",
            sensor_id="s1",
            measurement_type="temp",
            value=-273.15,
        )
        assert event.value == -273.15

    def test_extra_fields_ignored(self):
        """Extra fields in input data are silently ignored."""
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00Z",
            sensor_id="s1",
            measurement_type="temp",
            value=1.0,
            extra_field="ignored",  # type: ignore
        )
        assert not hasattr(event, "extra_field")


class TestTelemetryEventValidation:
    """Tests for TelemetryEvent validation rejections."""

    def test_invalid_timestamp_format(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="not-a-date",
                sensor_id="s1",
                measurement_type="temp",
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_TIMESTAMP

    def test_empty_sensor_id(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="",
                measurement_type="temp",
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_SENSOR_ID

    def test_whitespace_only_sensor_id(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="   \t\n  ",
                measurement_type="temp",
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_SENSOR_ID

    def test_sensor_id_too_long(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="a" * 257,
                measurement_type="temp",
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_SENSOR_ID

    def test_empty_measurement_type(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="",
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_MEASUREMENT_TYPE

    def test_whitespace_only_measurement_type(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="   ",
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_MEASUREMENT_TYPE

    def test_measurement_type_too_long(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="x" * 257,
                value=1.0,
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_MEASUREMENT_TYPE

    def test_value_nan(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="temp",
                value=float("nan"),
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_VALUE

    def test_value_infinity(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="temp",
                value=float("inf"),
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_VALUE

    def test_value_negative_infinity(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="temp",
                value=float("-inf"),
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_VALUE

    def test_value_boolean_rejected(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            TelemetryEvent(
                timestamp="2024-01-15T10:30:00Z",
                sensor_id="s1",
                measurement_type="temp",
                value=True,  # type: ignore
            )
        assert exc_info.value.code == ValidationErrorCode.INVALID_VALUE


# ---------------------------------------------------------------------------
# JSON serialization round-trip
# ---------------------------------------------------------------------------

class TestTelemetryEventSerialization:
    """Tests for JSON serialization/deserialization."""

    def test_round_trip_basic(self):
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00.123456Z",
            sensor_id="turbine-001-temp",
            measurement_type="temperature_celsius",
            value=342.17,
        )
        json_str = serialize_telemetry_event(event)
        restored = deserialize_telemetry_event(json_str)
        assert restored.sensor_id == event.sensor_id
        assert restored.measurement_type == event.measurement_type
        assert restored.value == event.value

    def test_round_trip_idempotent(self):
        """serialize→parse→serialize must produce identical JSON."""
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00.123456Z",
            sensor_id="sensor-abc",
            measurement_type="pressure",
            value=101325.12345678901,
        )
        json1 = serialize_telemetry_event(event)
        event2 = deserialize_telemetry_event(json1)
        json2 = serialize_telemetry_event(event2)
        assert json1 == json2

    def test_float_precision_15_digits(self):
        """Float64 values preserved to 15 significant digits."""
        value = 3.141592653589793
        event = TelemetryEvent(
            timestamp="2024-01-15T10:30:00Z",
            sensor_id="s1",
            measurement_type="pi",
            value=value,
        )
        json_str = serialize_telemetry_event(event)
        restored = deserialize_telemetry_event(json_str)
        # Check 15 significant digits are preserved
        assert f"{restored.value:.15g}" == f"{value:.15g}"

    def test_extra_fields_in_json_ignored(self):
        """Extra fields in JSON input are silently discarded."""
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00Z",
            "sensor_id": "s1",
            "measurement_type": "temp",
            "value": 42.0,
            "extra": "should_be_ignored",
            "another": 999,
        })
        event = deserialize_telemetry_event(raw)
        assert event.sensor_id == "s1"
        assert event.value == 42.0

    def test_deserialize_missing_field(self):
        raw = json.dumps({"timestamp": "2024-01-15T10:30:00Z", "sensor_id": "s1"})
        with pytest.raises(TelemetryValidationError) as exc_info:
            deserialize_telemetry_event(raw)
        assert exc_info.value.code == ValidationErrorCode.MISSING_FIELD

    def test_deserialize_invalid_json(self):
        with pytest.raises(TelemetryValidationError) as exc_info:
            deserialize_telemetry_event("{not valid json")
        assert exc_info.value.code == ValidationErrorCode.INVALID_JSON


# ---------------------------------------------------------------------------
# Payload size validation
# ---------------------------------------------------------------------------

class TestPayloadSizeValidation:
    """Tests for the 4096-byte payload limit."""

    def test_valid_size(self):
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00Z",
            "sensor_id": "s1",
            "measurement_type": "temp",
            "value": 1.0,
        })
        validate_payload_size(raw)  # Should not raise

    def test_oversized_payload(self):
        # Use extra fields to push payload over 4096 without violating field constraints
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00Z",
            "sensor_id": "x" * 200,
            "measurement_type": "y" * 200,
            "value": 1.0,
            "padding": "z" * 3700,
        })
        assert len(raw.encode("utf-8")) > 4096
        with pytest.raises(TelemetryValidationError) as exc_info:
            validate_payload_size(raw)
        assert exc_info.value.code == ValidationErrorCode.PAYLOAD_TOO_LARGE

    def test_exactly_4096_bytes(self):
        """Payload of exactly 4096 bytes is valid."""
        base = json.dumps({
            "timestamp": "2024-01-15T10:30:00Z",
            "sensor_id": "s",
            "measurement_type": "t",
            "value": 1.0,
        })
        # Pad sensor_id to make total exactly 4096 bytes
        base_size = len(base.encode("utf-8"))
        # Reconstruct to hit 4096
        padding_needed = 4096 - base_size
        if padding_needed > 0:
            padded = json.dumps({
                "timestamp": "2024-01-15T10:30:00Z",
                "sensor_id": "s" + "x" * padding_needed,
                "measurement_type": "t",
                "value": 1.0,
            })
            # Adjust - just ensure we don't exceed
            while len(padded.encode("utf-8")) > 4096:
                padding_needed -= 1
                padded = json.dumps({
                    "timestamp": "2024-01-15T10:30:00Z",
                    "sensor_id": "s" + "x" * padding_needed,
                    "measurement_type": "t",
                    "value": 1.0,
                })
            validate_payload_size(padded)  # Should not raise


# ---------------------------------------------------------------------------
# Full validation pipeline
# ---------------------------------------------------------------------------

class TestValidateTelemetryPayload:
    """Tests for the combined validation function."""

    def test_valid_payload(self):
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00.123456Z",
            "sensor_id": "turbine-001",
            "measurement_type": "temperature",
            "value": 342.17,
        })
        event = validate_telemetry_payload(raw)
        assert event.sensor_id == "turbine-001"
        assert event.value == 342.17

    def test_rejects_oversized(self):
        # Use extra fields to push payload over 4096 without violating field constraints
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00Z",
            "sensor_id": "x" * 200,
            "measurement_type": "y" * 200,
            "value": 1.0,
            "padding": "z" * 3700,
        })
        assert len(raw.encode("utf-8")) > 4096
        with pytest.raises(TelemetryValidationError) as exc_info:
            validate_telemetry_payload(raw)
        assert exc_info.value.code == ValidationErrorCode.PAYLOAD_TOO_LARGE

    def test_rejects_nan_value(self):
        # JSON doesn't natively support NaN, so we use a string hack
        raw = '{"timestamp":"2024-01-15T10:30:00Z","sensor_id":"s1","measurement_type":"t","value":"not_a_number"}'
        with pytest.raises(TelemetryValidationError):
            validate_telemetry_payload(raw)

    def test_accepts_bytes_input(self):
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00Z",
            "sensor_id": "sensor1",
            "measurement_type": "pressure",
            "value": 101325.0,
        }).encode("utf-8")
        event = validate_telemetry_payload(raw)
        assert event.sensor_id == "sensor1"


# ---------------------------------------------------------------------------
# StateVector
# ---------------------------------------------------------------------------

class TestStateVector:
    def test_valid_state_vector(self):
        sv = StateVector(
            sensor_id="turbine-001",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            values=[342.3, 343.1],
            ensemble_spread=0.45,
            anomaly_flag=False,
            source="correction",
        )
        assert sv.source == "correction"

    def test_invalid_source(self):
        with pytest.raises(ValueError):
            StateVector(
                sensor_id="s1",
                timestamp=datetime.now(tz=timezone.utc),
                values=[1.0],
                ensemble_spread=0.1,
                anomaly_flag=False,
                source="invalid",
            )


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

class TestPrediction:
    def test_valid_prediction(self):
        pred = Prediction(
            sensor_id="turbine-001",
            prediction_timestamp=datetime(2024, 1, 15, 10, 30, 5, tzinfo=timezone.utc),
            prediction_horizon_seconds=60.0,
            state_vector=[342.5, 343.1, 343.8],
            model_used="ensemble",
            ensemble_weights={"lstm": 0.6, "xgboost": 0.4},
        )
        assert pred.model_used == "ensemble"
        assert pred.ensemble_weights["lstm"] == 0.6


# ---------------------------------------------------------------------------
# EnKFState
# ---------------------------------------------------------------------------

class TestEnKFState:
    def test_valid_enkf_state(self):
        members = np.random.randn(50, 3)
        noise_cov = np.eye(3) * 0.1
        state = EnKFState(
            sensor_id="turbine-001",
            ensemble_members=members,
            observation_noise_cov=noise_cov,
            last_update_timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            iteration_count=10,
            anomaly_threshold=3.0,
        )
        assert state.ensemble_size == 50
        assert state.state_dim == 3

    def test_rejects_fewer_than_50_members(self):
        members = np.random.randn(49, 3)
        with pytest.raises(ValueError, match="at least 50"):
            EnKFState(
                sensor_id="s1",
                ensemble_members=members,
                observation_noise_cov=np.eye(3),
                last_update_timestamp=datetime.now(tz=timezone.utc),
            )

    def test_rejects_1d_array(self):
        with pytest.raises(ValueError, match="2-dimensional"):
            EnKFState(
                sensor_id="s1",
                ensemble_members=np.ones(100),
                observation_noise_cov=np.eye(1),
                last_update_timestamp=datetime.now(tz=timezone.utc),
            )


# ---------------------------------------------------------------------------
# HealthStatus and ComponentStatus
# ---------------------------------------------------------------------------

class TestHealthStatus:
    def test_all_healthy(self):
        status = HealthStatus(
            overall_status=ComponentStatus.HEALTHY,
            components={
                "ingestion_server": ComponentStatus.HEALTHY,
                "message_broker": ComponentStatus.HEALTHY,
            },
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert status.overall_status == ComponentStatus.HEALTHY

    def test_component_status_values(self):
        assert ComponentStatus.HEALTHY.value == "healthy"
        assert ComponentStatus.DEGRADED.value == "degraded"
        assert ComponentStatus.DOWN.value == "down"


# ---------------------------------------------------------------------------
# EngineConfig
# ---------------------------------------------------------------------------

class TestEngineConfig:
    def test_defaults(self):
        config = EngineConfig()
        assert config.websocket_port == 8080
        assert config.max_buffer_size == 10000
        assert config.ensemble_size == 50
        assert config.anomaly_threshold_sigma == 3.0
        assert config.default_page_size == 100

    def test_valid_custom_config(self):
        config = EngineConfig(
            websocket_port=9090,
            lstm_weight=0.7,
            xgboost_weight=0.3,
            ensemble_size=100,
        )
        assert config.websocket_port == 9090
        assert config.lstm_weight == 0.7

    def test_port_below_range(self):
        with pytest.raises(ValueError):
            EngineConfig(websocket_port=1023)

    def test_port_above_range(self):
        with pytest.raises(ValueError):
            EngineConfig(websocket_port=65536)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="must equal 1.0"):
            EngineConfig(lstm_weight=0.7, xgboost_weight=0.5)

    def test_ensemble_size_below_minimum(self):
        with pytest.raises(ValueError):
            EngineConfig(ensemble_size=49)

    def test_anomaly_threshold_below_range(self):
        with pytest.raises(ValueError):
            EngineConfig(anomaly_threshold_sigma=0.5)

    def test_anomaly_threshold_above_range(self):
        with pytest.raises(ValueError):
            EngineConfig(anomaly_threshold_sigma=10.1)

    def test_batch_wait_below_range(self):
        with pytest.raises(ValueError):
            EngineConfig(max_batch_wait_seconds=0.5)

    def test_batch_wait_above_range(self):
        with pytest.raises(ValueError):
            EngineConfig(max_batch_wait_seconds=61.0)

    def test_min_batch_size_below_range(self):
        with pytest.raises(ValueError):
            EngineConfig(min_batch_size=9)

    def test_min_batch_size_exceeds_max(self):
        with pytest.raises(ValueError, match="min_batch_size"):
            EngineConfig(min_batch_size=500, max_batch_size=100)
