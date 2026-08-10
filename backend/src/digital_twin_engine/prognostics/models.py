"""Data models for digital twin prognostics state.

Defines Pydantic models for engine RUL prediction, health index aggregation,
degradation trajectory tracking, and component-level health mapping. All models
include field constraints and validators to ensure data integrity.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SUBSYSTEM_NAMES = ("fan", "lpc", "hpc", "hpt", "lpt", "combustor")
VALID_CLASSIFICATIONS = ("nominal", "degraded", "critical")
RUL_MIN = 0
RUL_MAX = 125


# ---------------------------------------------------------------------------
# SensorBaseline
# ---------------------------------------------------------------------------


class SensorBaseline(BaseModel):
    """Baseline statistics computed from first 10 cycles of operation.

    Used to normalize sensor readings for health index computation and
    RUL prediction. The baseline establishes the nominal operating range
    for each sensor channel.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    sensor_name: str
    mean: float
    std: float = Field(ge=0.0, description="Standard deviation, must be non-negative")
    sample_count: int = Field(gt=0, description="Number of cycles contributing to baseline")

    @field_validator("sensor_name")
    @classmethod
    def validate_sensor_name(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("sensor_name must not be empty or whitespace-only")
        return v


# ---------------------------------------------------------------------------
# EngineRULState
# ---------------------------------------------------------------------------


class EngineRULState(BaseModel):
    """Current RUL computation state for an engine unit.

    Tracks the Remaining Useful Life estimate (in cycles) along with
    metadata about baseline establishment and data completeness.
    """

    model_config = ConfigDict(extra="ignore")

    engine_id: int
    current_rul: int = Field(
        ge=RUL_MIN,
        le=RUL_MAX,
        description="Remaining Useful Life in cycles, clamped to [0, 125]",
    )
    cycle_count: int = Field(ge=0)
    baseline_established: bool
    last_update_cycle: int = Field(ge=0)
    is_incomplete: bool = Field(
        default=False,
        description="True if last cycle had fewer than 14 valid sensors",
    )


# ---------------------------------------------------------------------------
# EngineHealthState
# ---------------------------------------------------------------------------


class EngineHealthState(BaseModel):
    """Current health index state for an engine unit.

    The health index is a composite score (0.0-1.0) summarizing overall
    engine condition based on weighted sensor deviations from baseline.
    """

    model_config = ConfigDict(extra="ignore")

    engine_id: int
    health_index: float = Field(
        ge=0.0,
        le=1.0,
        description="Composite health score, clamped to [0.0, 1.0]",
    )
    cycle_count: int = Field(ge=0)
    is_provisional: bool = Field(
        default=False,
        description="True if fewer than 10 cycles available for baseline",
    )
    last_update_cycle: int = Field(ge=0)


# ---------------------------------------------------------------------------
# SubsystemHealth
# ---------------------------------------------------------------------------


class SubsystemHealth(BaseModel):
    """Health state for a single engine subsystem.

    Maps sensor readings to one of six logical engine subsystems and
    provides a health score with classification.
    """

    model_config = ConfigDict(extra="ignore")

    name: Literal["fan", "lpc", "hpc", "hpt", "lpt", "combustor"] = Field(
        description="Engine subsystem identifier",
    )
    health_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Subsystem health score, clamped to [0.0, 1.0]",
    )
    classification: Literal["nominal", "degraded", "critical"] = Field(
        description="Health classification based on thresholds with hysteresis",
    )
    is_incomplete: bool = Field(
        default=False,
        description="True if fewer than half of mapped sensors provided valid readings",
    )


# ---------------------------------------------------------------------------
# DegradationPoint
# ---------------------------------------------------------------------------


class DegradationPoint(BaseModel):
    """A single point in the degradation trajectory.

    Represents one (cycle, health_index) observation in the engine's
    operational history.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    cycle: int = Field(ge=0)
    health_index: float = Field(
        ge=0.0,
        le=1.0,
        description="Health index at this cycle, clamped to [0.0, 1.0]",
    )


# ---------------------------------------------------------------------------
# EngineSnapshot
# ---------------------------------------------------------------------------


class EngineSnapshot(BaseModel):
    """Full state snapshot for WebSocket reconnection.

    Provides a complete picture of an engine's prognostic state, enabling
    the frontend to restore its display after a WebSocket reconnection
    without requiring a full data replay.
    """

    model_config = ConfigDict(extra="ignore")

    engine_id: int
    rul: EngineRULState
    health: EngineHealthState
    subsystems: List[SubsystemHealth]
    trajectory: List[DegradationPoint]
    degradation_rate: Optional[float] = Field(
        default=None,
        description="Linear degradation rate (slope over last 20 cycles), None if < 20 cycles",
    )
