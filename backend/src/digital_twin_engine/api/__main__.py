"""Entrypoint for the API Gateway service.

Launches the FastAPI REST API server that provides endpoints for querying
sensor state, history, predictions, and pipeline health.
"""

import asyncio
import os

import uvicorn

from digital_twin_engine.shared.logging import get_logger

logger = get_logger("api_gateway_main")


def main() -> None:
    """Start the API Gateway server."""
    api_port = int(os.environ.get("API_PORT", "8000"))
    broker_type = os.environ.get("BROKER_TYPE", "kafka")
    broker_url = os.environ.get("BROKER_URL", "kafka:29092")
    tsdb_type = os.environ.get("TSDB_TYPE", "influxdb")

    # The API gateway app is configured at module level in api/app.py
    # For Docker deployment, we use environment variables to set up backends
    os.environ.setdefault("BROKER_TYPE", broker_type)
    os.environ.setdefault("BROKER_URL", broker_url)
    os.environ.setdefault("TSDB_TYPE", tsdb_type)

    logger.info(
        "API Gateway starting",
        port=api_port,
        broker_type=broker_type,
        broker_url=broker_url,
        tsdb_type=tsdb_type,
    )

    uvicorn.run(
        "digital_twin_engine.api.app:app",
        host="0.0.0.0",
        port=api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
