"""Prometheus metrics for the API Gateway.

Defines and exposes counters and gauges for monitoring API Gateway health
and throughput. Provides a /metrics endpoint for Prometheus scraping.

Requirements: 9.1, 9.5
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

# Counter: Total messages processed by the API Gateway, labeled by broker topic.
messages_processed_total = Counter(
    "messages_processed_total",
    "Total messages processed by the API Gateway",
    ["topic"],
)

# Gauge: Number of currently active WebSocket connections.
ws_connections_active = Gauge(
    "ws_connections_active",
    "Number of active WebSocket connections to the API Gateway",
)


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics in text format for scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
