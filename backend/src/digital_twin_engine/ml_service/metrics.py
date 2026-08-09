"""Prometheus metrics for the ML Service.

Defines counters and histograms for monitoring ML Service throughput
and inference performance. Exposes metrics via a standalone HTTP server
on a configurable port (default 9090) since the ML Service is not a
FastAPI application.

Requirements: 9.3, 9.5, 9.6
"""

from __future__ import annotations

import os

from prometheus_client import Counter, Histogram, start_http_server

# Counter: Total messages (telemetry batches) processed by the ML Service.
messages_processed_total = Counter(
    "ml_messages_processed_total",
    "Total messages processed by the ML Service",
)

# Histogram: Time in seconds to generate a prediction (inference latency).
inference_latency_seconds = Histogram(
    "inference_latency_seconds",
    "Time to generate a prediction",
)


def start_metrics_server() -> None:
    """Start the standalone Prometheus metrics HTTP server.

    Reads the ML_METRICS_PORT environment variable (default 9090) and
    starts a lightweight HTTP server exposing /metrics for Prometheus scraping.
    """
    port = int(os.environ.get("ML_METRICS_PORT", "9090"))
    start_http_server(port)
