"""Fleet API endpoints for fleet-wide pattern recognition and statistics.

Provides:
- GET /api/fleet/patterns — Fleet-wide degradation pattern clusters with
    pairwise similarity scores, dominant failure modes, and insufficient
    data engine lists.
- GET /api/fleet/stats — Aggregate fleet health statistics including
    engine categorization (nominal/degraded/critical/calibrating),
    average health index, and predicted maintenance events.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8,
              2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from digital_twin_engine.api.models import (
    EnginePairSimilarityModel,
    FleetPatternResponseModel,
    FleetStatsResponseModel,
    PatternClusterModel,
)
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("api_fleet")

router = APIRouter(prefix="/api/fleet", tags=["fleet"])

# Service references — set during app startup via configure_fleet_services()
_fleet_pattern_recognizer: Any = None
_fleet_stats_aggregator: Any = None


def configure_fleet_services(
    pattern_recognizer: Any = None,
    stats_aggregator: Any = None,
) -> None:
    """Configure the service references for the fleet API endpoints.

    Called during application startup to wire the FleetPatternRecognizer
    and FleetStatsAggregator instances into the API layer.

    Args:
        pattern_recognizer: FleetPatternRecognizer instance providing
            get_clusters() and compute_similarity().
        stats_aggregator: FleetStatsAggregator instance providing get_stats().
    """
    global _fleet_pattern_recognizer, _fleet_stats_aggregator
    _fleet_pattern_recognizer = pattern_recognizer
    _fleet_stats_aggregator = stats_aggregator


@router.get(
    "/patterns",
    response_model=FleetPatternResponseModel,
    responses={503: {"description": "Service unavailable"}},
)
async def get_fleet_patterns() -> Any:
    """Get fleet-wide degradation pattern clusters.

    Returns clusters of engines with similar degradation signatures,
    including pairwise similarity scores, dominant failure modes,
    and a list of engines excluded due to insufficient data or
    baseline calibration period.

    Returns HTTP 503 if the pattern recognition service is not configured.
    Returns HTTP 200 with empty clusters if no engines are tracked or
    fewer than 2 eligible engines exist (valid empty fleet response).

    Requirements: 1.1, 1.2, 1.3, 1.5, 1.7
    """
    if _fleet_pattern_recognizer is None:
        raise HTTPException(
            status_code=503,
            detail="Fleet pattern recognition service is not available.",
        )

    # Get clusters from the FleetPatternRecognizer
    fleet_response = _fleet_pattern_recognizer.get_clusters()

    # Convert dataclass response to Pydantic models
    clusters = [
        PatternClusterModel(
            cluster_id=cluster.cluster_id,
            engine_ids=cluster.engine_ids,
            pairwise_similarities=[
                EnginePairSimilarityModel(
                    engine_a=pair.engine_a,
                    engine_b=pair.engine_b,
                    similarity_score=pair.similarity_score,
                )
                for pair in cluster.pairwise_similarities
            ],
            dominant_failure_mode=cluster.dominant_failure_mode,
        )
        for cluster in fleet_response.clusters
    ]

    return FleetPatternResponseModel(
        clusters=clusters,
        insufficient_data_engines=fleet_response.insufficient_data_engines,
        total_engines=fleet_response.total_engines,
        eligible_engines=fleet_response.eligible_engines,
    )


@router.get(
    "/stats",
    response_model=FleetStatsResponseModel,
    responses={503: {"description": "Service unavailable"}},
)
async def get_fleet_stats() -> Any:
    """Get aggregate fleet health statistics.

    Returns engine counts by health category (nominal/degraded/critical/
    calibrating), the fleet-wide average health index (excluding calibrating
    engines), and predicted maintenance events within a 50-cycle horizon.

    Returns HTTP 503 if the fleet stats service is not configured.
    Returns HTTP 200 with zero counts and null average for an empty fleet.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """
    if _fleet_stats_aggregator is None:
        raise HTTPException(
            status_code=503,
            detail="Fleet statistics service is not available.",
        )

    # Get stats from the FleetStatsAggregator
    stats = _fleet_stats_aggregator.get_stats()

    return FleetStatsResponseModel(
        total_engines=stats.total_engines,
        nominal_count=stats.nominal_count,
        degraded_count=stats.degraded_count,
        critical_count=stats.critical_count,
        calibrating_count=stats.calibrating_count,
        average_fleet_health_index=stats.average_fleet_health_index,
        predicted_maintenance_events=stats.predicted_maintenance_events,
        horizon_cycles=stats.horizon_cycles,
    )
