"""Correction Metrics REST API endpoints.

Provides endpoints for querying EnKF correction observability metrics:
- GET /metrics/accuracy — RMSE, MAE, R² for raw vs corrected predictions
- GET /metrics/confidence — Per-engine 95% confidence intervals
- GET /metrics/innovation-stats — Innovation autocorrelation and whiteness test

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.5, 5.6
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from digital_twin_engine.correction.enkf import accuracy_tracker, innovation_tracker
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("correction_metrics_api")

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Confidence cache — updated by broker subscriber on each correction event.
# Maps sensor_id to confidence record dict.
_confidence_cache: dict[str, dict[str, Any]] = {}


def update_confidence_cache(
    engine_id: int,
    sensor_id: str,
    confidence_band_95: list[float],
    ensemble_spread: float,
    last_update_timestamp: str,
) -> None:
    """Update the confidence cache with the latest correction data.

    Called by the EnKF pipeline after each correction to keep confidence
    data available for the REST endpoint.
    """
    _confidence_cache[sensor_id] = {
        "engine_id": engine_id,
        "sensor_id": sensor_id,
        "confidence_band_95": confidence_band_95,
        "ensemble_spread": ensemble_spread,
        "last_update_timestamp": last_update_timestamp,
    }


@router.get("/accuracy")
async def get_accuracy_metrics() -> dict[str, Any]:
    """Return RMSE/MAE/R² comparing raw vs corrected predictions.

    Always returns HTTP 200. Returns null for metric fields when
    fewer than 2 samples have been recorded.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    """
    metrics = accuracy_tracker.get_metrics()
    return {
        "raw_rmse": metrics.raw_rmse,
        "raw_mae": metrics.raw_mae,
        "raw_r_squared": metrics.raw_r_squared,
        "corrected_rmse": metrics.corrected_rmse,
        "corrected_mae": metrics.corrected_mae,
        "corrected_r_squared": metrics.corrected_r_squared,
        "improvement_percentage": metrics.improvement_percentage,
        "sample_count": metrics.sample_count,
    }


@router.get("/confidence")
async def get_confidence_metrics() -> list[dict[str, Any]]:
    """Return current 95% confidence intervals per engine.

    Only includes engines with correction data.
    Always returns HTTP 200.

    Requirements: 4.1, 4.2, 4.3, 4.4
    """
    return list(_confidence_cache.values())


@router.get("/innovation-stats")
async def get_innovation_stats() -> list[dict[str, Any]]:
    """Return innovation autocorrelation and whiteness test per sensor.

    Returns null fields for sensors with fewer than 10 samples.
    Always returns HTTP 200.

    Requirements: 5.1, 5.2, 5.5, 5.6
    """
    return innovation_tracker.get_all_stats()
