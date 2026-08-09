"""Shared data models for the Digital Twin Telemetry Engine.

Defines all core data structures used across pipeline components:
- TelemetryEvent: Incoming sensor telemetry payload
- StateVector: Estimated state at a point in time
- Prediction: ML model output
- EnKFState: Per-sensor ensemble Kalman filter state
- HealthStatus / ComponentStatus: System health reporting
- EngineConfig: Global engine configuration
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Validation error codes
# ---------------------------------------------------------------------------

class ValidationErrorCode(str, Enum):
    """Machine-readable error codes for telemetry event validation failures."""

    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_SENSOR_ID = "INVALID_SENSOR_ID"
    INVALID_MEASUREMENT_TYPE = "INVALID_MEASUREMENT_TYPE"
    INVALID_VALUE = "INVALID_VALUE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_JSON = "INVALID_JSON"


class TelemetryValidationError(Exception):
    """Raised when a telemetry event payload fails validation."""

    def __init__(self, code: ValidationErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code.value}: {message}")


# ---------------------------------------------------------------------------
# TelemetryEvent
# ---------------------------------------------------------------------------

MAX_PAYLOAD_BYTES = 4096
MAX_STRING_LENGTH = 256


class TelemetryEvent(BaseModel):
    """A single telemetry measurement from a sensor.

    Validation constraints:
    - timestamp: Valid ISO 8601 UTC datetime
    - sensor_id: 1-256 characters, not whitespace-only
    - measurement_type: 1-256 characters, not whitespace-only
    - value: Finite float64 (no NaN, Inf, -Inf)
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    timestamp: datetime
    sensor_id: str
    measurement_type: str
    value: float

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except (ValueError, TypeError) as exc:
                raise TelemetryValidationError(
                    ValidationErrorCode.INVALID_TIMESTAMP,
                    "Timestamp must be valid ISO 8601 UTC format",
                ) from exc
            if dt.tzinfo is None:
                raise TelemetryValidationError(
                    ValidationErrorCode.INVALID_TIMESTAMP,
                    "Timestamp must include UTC timezone indicator",
                )
            return dt
        if isinstance(v, datetime):
            return v
        raise TelemetryValidationError(
            ValidationErrorCode.INVALID_TIMESTAMP,
            "Timestamp must be a string in ISO 8601 UTC format",
        )

    @field_validator("sensor_id")
    @classmethod
    def validate_sensor_id(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_SENSOR_ID,
                "sensor_id must not be empty or whitespace-only",
            )
        if len(v) > MAX_STRING_LENGTH:
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_SENSOR_ID,
                f"sensor_id must not exceed {MAX_STRING_LENGTH} characters",
            )
        return v

    @field_validator("measurement_type")
    @classmethod
    def validate_measurement_type(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_MEASUREMENT_TYPE,
                "measurement_type must not be empty or whitespace-only",
            )
        if len(v) > MAX_STRING_LENGTH:
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_MEASUREMENT_TYPE,
                f"measurement_type must not exceed {MAX_STRING_LENGTH} characters",
            )
        return v

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, v: Any) -> float:
        if isinstance(v, bool):
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_VALUE,
                "value must be a finite numeric value, not a boolean",
            )
        if not isinstance(v, (int, float)):
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_VALUE,
                "value must be a finite numeric value",
            )
        fv = float(v)
        if not math.isfinite(fv):
            raise TelemetryValidationError(
                ValidationErrorCode.INVALID_VALUE,
                "value must be finite (NaN and Infinity are not allowed)",
            )
        return fv


# ---------------------------------------------------------------------------
# TelemetryEvent JSON serialization helpers
# ---------------------------------------------------------------------------

def _format_timestamp(dt: datetime) -> str:
    """Format datetime to ISO 8601 UTC string with microsecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _float_to_repr(value: float) -> str:
    """Convert a float64 to a string preserving up to 15 significant digits."""
    return f"{value:.15g}"


def serialize_telemetry_event(event: TelemetryEvent) -> str:
    """Serialize a TelemetryEvent to JSON preserving float64 precision to 15 significant digits.

    The output is deterministic: serialize→parse→serialize produces identical JSON.
    """
    obj = {
        "timestamp": _format_timestamp(event.timestamp),
        "sensor_id": event.sensor_id,
        "measurement_type": event.measurement_type,
        "value": event.value,
    }
    # Use a custom encoder to preserve float precision
    return json.dumps(obj, cls=_PrecisionEncoder, separators=(",", ":"))


def deserialize_telemetry_event(raw_json: str) -> TelemetryEvent:
    """Parse a JSON string into a TelemetryEvent, ignoring extra fields.

    Raises TelemetryValidationError with specific error codes on validation failure.
    """
    try:
        data = json.loads(raw_json, parse_float=_precise_float)
    except json.JSONDecodeError as exc:
        raise TelemetryValidationError(
            ValidationErrorCode.INVALID_JSON,
            f"Payload is not valid JSON: {exc}",
        ) from exc

    # Check required fields
    for field_name, error_code in [
        ("timestamp", ValidationErrorCode.INVALID_TIMESTAMP),
        ("sensor_id", ValidationErrorCode.INVALID_SENSOR_ID),
        ("measurement_type", ValidationErrorCode.INVALID_MEASUREMENT_TYPE),
        ("value", ValidationErrorCode.INVALID_VALUE),
    ]:
        if field_name not in data:
            raise TelemetryValidationError(
                ValidationErrorCode.MISSING_FIELD,
                f"Missing required field: {field_name}",
            )

    return TelemetryEvent(**data)


def _precise_float(s: str) -> float:
    """Parse a float string maintaining full float64 precision."""
    return float(s)


class _PrecisionEncoder(json.JSONEncoder):
    """JSON encoder that preserves float64 values to 15 significant digits."""

    def default(self, o: Any) -> Any:
        return super().default(o)

    def encode(self, o: Any) -> str:
        return self._encode_value(o)

    def _encode_value(self, o: Any) -> str:
        if isinstance(o, dict):
            items = []
            for k, v in o.items():
                items.append(f"{json.dumps(k)}:{self._encode_value(v)}")
            return "{" + ",".join(items) + "}"
        if isinstance(o, list):
            return "[" + ",".join(self._encode_value(item) for item in o) + "]"
        if isinstance(o, float):
            return _float_to_repr(o)
        if isinstance(o, bool):
            return "true" if o else "false"
        if isinstance(o, int):
            return str(o)
        if isinstance(o, str):
            return json.dumps(o)
        if o is None:
            return "null"
        return json.dumps(o)


# ---------------------------------------------------------------------------
# Payload size validation
# ---------------------------------------------------------------------------

def validate_payload_size(raw_json: str | bytes) -> None:
    """Check that the raw JSON payload does not exceed the 4096-byte limit.

    Raises TelemetryValidationError with PAYLOAD_TOO_LARGE if the limit is exceeded.
    """
    if isinstance(raw_json, str):
        size = len(raw_json.encode("utf-8"))
    else:
        size = len(raw_json)
    if size > MAX_PAYLOAD_BYTES:
        raise TelemetryValidationError(
            ValidationErrorCode.PAYLOAD_TOO_LARGE,
            f"Payload size {size} bytes exceeds maximum of {MAX_PAYLOAD_BYTES} bytes",
        )


def validate_telemetry_payload(raw_json: str | bytes) -> TelemetryEvent:
    """Full validation pipeline: size check → parse → schema validation.

    Returns a validated TelemetryEvent if all constraints are met.
    Raises TelemetryValidationError with a specific error code otherwise.
    """
    if isinstance(raw_json, bytes):
        raw_str = raw_json.decode("utf-8")
    else:
        raw_str = raw_json

    validate_payload_size(raw_str)
    return deserialize_telemetry_event(raw_str)


# ---------------------------------------------------------------------------
# StateVector
# ---------------------------------------------------------------------------

class StateVector(BaseModel):
    """Estimated state of a sensor at a point in time."""

    model_config = ConfigDict(extra="ignore")

    sensor_id: str
    timestamp: datetime
    values: List[float]
    ensemble_spread: float
    anomaly_flag: bool
    source: str  # "prediction" or "correction"

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in ("prediction", "correction"):
            raise ValueError("source must be 'prediction' or 'correction'")
        return v


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

class Prediction(BaseModel):
    """ML model prediction output for a sensor."""

    model_config = ConfigDict(extra="ignore")

    sensor_id: str
    prediction_timestamp: datetime
    prediction_horizon_seconds: float
    state_vector: List[float]
    model_used: str  # "ensemble", "lstm_only", "xgboost_only"
    ensemble_weights: Dict[str, float]


# ---------------------------------------------------------------------------
# EnKFState
# ---------------------------------------------------------------------------

class EnKFState:
    """Per-sensor Ensemble Kalman Filter state.

    This is not a Pydantic model because it holds numpy arrays.
    """

    def __init__(
        self,
        sensor_id: str,
        ensemble_members: np.ndarray,
        observation_noise_cov: np.ndarray,
        last_update_timestamp: datetime,
        iteration_count: int = 0,
        anomaly_threshold: float = 3.0,
    ) -> None:
        if ensemble_members.ndim != 2:
            raise ValueError("ensemble_members must be 2-dimensional (N_ensemble x state_dim)")
        if ensemble_members.shape[0] < 50:
            raise ValueError(
                f"ensemble_members must have at least 50 members, got {ensemble_members.shape[0]}"
            )
        self.sensor_id = sensor_id
        self.ensemble_members = ensemble_members
        self.observation_noise_cov = observation_noise_cov
        self.last_update_timestamp = last_update_timestamp
        self.iteration_count = iteration_count
        self.anomaly_threshold = anomaly_threshold

    @property
    def ensemble_size(self) -> int:
        return self.ensemble_members.shape[0]

    @property
    def state_dim(self) -> int:
        return self.ensemble_members.shape[1]


# ---------------------------------------------------------------------------
# HealthStatus and ComponentStatus
# ---------------------------------------------------------------------------

class ComponentStatus(str, Enum):
    """Operational status of a pipeline component."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class HealthStatus(BaseModel):
    """Aggregated pipeline health status."""

    model_config = ConfigDict(extra="ignore")

    overall_status: ComponentStatus
    components: Dict[str, ComponentStatus]
    timestamp: datetime


# ---------------------------------------------------------------------------
# EngineConfig
# ---------------------------------------------------------------------------

class EngineConfig(BaseModel):
    """Global engine configuration with validated parameters."""

    model_config = ConfigDict(extra="ignore")

    # Ingestion
    websocket_port: int = Field(default=8080, ge=1024, le=65535)
    max_buffer_size: int = Field(default=10000, ge=1)
    broker_publish_timeout_ms: int = Field(default=5000, ge=1)

    # ML Service
    min_batch_size: int = Field(default=10, ge=10, le=500)
    max_batch_size: int = Field(default=500, ge=1)
    max_batch_wait_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    prediction_horizon_seconds: float = Field(default=60.0, gt=0)
    lstm_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    xgboost_weight: float = Field(default=0.4, ge=0.0, le=1.0)

    # Correction Engine
    ensemble_size: int = Field(default=50, ge=50)
    temporal_tolerance_seconds: float = Field(default=1.0, gt=0)
    anomaly_threshold_sigma: float = Field(default=3.0, ge=1.0, le=10.0)

    # TSDB
    write_batch_size: int = Field(default=100, ge=1)
    write_retry_count: int = Field(default=3, ge=0)
    data_retention_days: int = Field(default=90, ge=1)

    # API
    default_page_size: int = Field(default=100, ge=1)
    max_page_size: int = Field(default=1000, ge=1)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "EngineConfig":
        total = self.lstm_weight + self.xgboost_weight
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(
                f"lstm_weight + xgboost_weight must equal 1.0, got {total}"
            )
        return self

    @model_validator(mode="after")
    def validate_batch_sizes(self) -> "EngineConfig":
        if self.min_batch_size > self.max_batch_size:
            raise ValueError(
                f"min_batch_size ({self.min_batch_size}) must not exceed "
                f"max_batch_size ({self.max_batch_size})"
            )
        return self
