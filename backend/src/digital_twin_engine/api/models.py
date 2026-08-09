"""API response models for the Digital Twin Telemetry Engine REST endpoints.

Defines Pydantic models for structured JSON responses returned by the
API Gateway endpoints.

Requirements: 7.1, 7.2, 7.3, 7.7
"""

from __future__ import annotations

from datetime import datetime
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
