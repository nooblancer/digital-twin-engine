"""API response models for the Digital Twin Telemetry Engine REST endpoints.

Defines Pydantic models for structured JSON responses returned by the
API Gateway endpoints.

Requirements: 7.1, 7.2, 7.3, 7.7, 1.2, 2.1, 3.4, 4.2, 4.4
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CurrentStateResponse(BaseModel):
    """Response for GET /sensors/{sensor_id}/state/current."""

    sensor_id: str
    timestamp: str
    state_vector: List[float]
    ensemble_spread: float
    anomaly_flag: bool


class PaginationMetadata(BaseModel):
    """Pagination metadata included in history responses."""

    total_count: int
    offset: int
    limit: int


class HistoryStateEntry(BaseModel):
    """A single corrected state entry in history results."""

    timestamp: str
    state_vector: List[float]
    ensemble_spread: float
    anomaly_flag: bool


class HistoryResponse(BaseModel):
    """Response for GET /sensors/{sensor_id}/state/history."""

    sensor_id: str
    results: List[HistoryStateEntry]
    pagination: PaginationMetadata


class PredictedStateEntry(BaseModel):
    """A single predicted state entry."""

    timestamp: str
    state_vector: List[float]
    model_used: str
    prediction_horizon_seconds: float


class PredictedResponse(BaseModel):
    """Response for GET /sensors/{sensor_id}/state/predicted."""

    sensor_id: str
    predictions: List[PredictedStateEntry]


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error_code: str
    message: str


# --- v1.4 Response Models ---


class SensorContributionModel(BaseModel):
    """A single sensor's contribution to an anomaly.

    Requirements: 1.2
    """

    sensor_name: str
    innovation_magnitude: float
    sigma_deviation: float


class AnomalyAnalysisResponse(BaseModel):
    """Response for GET /engines/{engine_id}/anomaly-analysis.

    Requirements: 1.2, 1.3
    """

    engine_id: int
    anomaly_active: bool
    timestamp: Optional[str] = None
    contributions: List[SensorContributionModel] = []


class AlertSeverityEnum(str, Enum):
    """Severity levels for predictive maintenance alerts.

    Requirements: 2.1
    """

    LOW = "low"
    MEDIUM = "medium"
    CRITICAL = "critical"


class MaintenanceRecommendationModel(BaseModel):
    """A single maintenance recommendation with timing and confidence.

    Requirements: 2.1
    """

    severity: AlertSeverityEnum
    time_to_critical_cycles: int
    confidence_score: float
    suggested_action: str
    predicted_failure_mode: Optional[str] = None


class MaintenanceRecommendationsResponse(BaseModel):
    """Response for GET /engines/{engine_id}/maintenance-recommendations.

    Requirements: 2.1
    """

    engine_id: int
    recommendations: List[MaintenanceRecommendationModel] = []


class BenchmarkMetricsResponse(BaseModel):
    """Response for GET /metrics/benchmark.

    Requirements: 3.4
    """

    raw_rmse: float
    corrected_rmse: float
    raw_mae: float
    corrected_mae: float
    correction_gain_pct: float
    confidence_coverage_pct: float
    sample_count: int


class LatencyMetricsModel(BaseModel):
    """Latency percentile metrics.

    Requirements: 4.2
    """

    p50_ms: float
    p95_ms: float
    p99_ms: float
    sample_count: int


class ThroughputMetricsModel(BaseModel):
    """Throughput rate metrics as rolling averages.

    Requirements: 4.4
    """

    events_per_second: float
    predictions_per_second: float
    corrections_per_second: float


class PerformanceMetricsResponse(BaseModel):
    """Response for GET /metrics/performance.

    Requirements: 4.2, 4.4
    """

    latency: LatencyMetricsModel
    throughput: ThroughputMetricsModel


# --- v2.0 Fleet Response Models ---


class EnginePairSimilarityModel(BaseModel):
    """Pairwise similarity score between two engines' degradation signatures.

    Requirements: 1.1, 1.2
    """

    engine_a: int
    engine_b: int
    similarity_score: float


class PatternClusterModel(BaseModel):
    """A cluster of engines sharing similar degradation patterns.

    Requirements: 1.1, 1.3, 1.7
    """

    cluster_id: int
    engine_ids: List[int]
    pairwise_similarities: List[EnginePairSimilarityModel]
    dominant_failure_mode: str


class FleetPatternResponseModel(BaseModel):
    """Response for GET /api/fleet/patterns.

    Requirements: 1.1, 1.2, 1.3, 1.5, 1.7
    """

    clusters: List[PatternClusterModel] = []
    insufficient_data_engines: List[int] = []
    total_engines: int
    eligible_engines: int


class FleetStatsResponseModel(BaseModel):
    """Response for GET /api/fleet/stats.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """

    total_engines: int
    nominal_count: int
    degraded_count: int
    critical_count: int
    calibrating_count: int
    average_fleet_health_index: Optional[float] = None
    predicted_maintenance_events: int
    horizon_cycles: int
