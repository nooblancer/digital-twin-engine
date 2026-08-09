"""Prometheus metrics for the Ingestion Server.

Defines and exposes counters for monitoring ingestion throughput.
Provides a /metrics endpoint for Prometheus scraping.

Requirements: 9.2, 9.5
"""

from __future__ import annotations

from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

# Counter: Total telemetry events ingested by the Ingestion Server.
events_ingested_total = Counter(
    "events_ingested_total",
    "Total telemetry events ingested by the Ingestion Server",
)


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics in text format for scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
