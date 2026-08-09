"""Prometheus metrics for the Correction Engine.

Defines counters for monitoring Correction Engine throughput and
EnKF iteration activity. Exposes metrics via a standalone HTTP server
on a configurable port (default 9091) since the Correction Engine is not
a FastAPI application.

Requirements: 9.4, 9.5
"""

from __future__ import annotations

import os

from prometheus_client import Counter, start_http_server

# Counter: Total messages processed by the Correction Engine.
messages_processed_total = Counter(
    "correction_messages_processed_total",
    "Total messages processed by the Correction Engine",
)

# Counter: Total EnKF correction iterations completed.
correction_iterations_total = Counter(
    "correction_iterations_total",
    "Total EnKF correction iterations completed",
)


def start_metrics_server() -> None:
    """Start the standalone Prometheus metrics HTTP server.

    Reads the CORRECTION_METRICS_PORT environment variable (default 9091) and
    starts a lightweight HTTP server exposing /metrics for Prometheus scraping.
    """
    port = int(os.environ.get("CORRECTION_METRICS_PORT", "9091"))
    start_http_server(port)
