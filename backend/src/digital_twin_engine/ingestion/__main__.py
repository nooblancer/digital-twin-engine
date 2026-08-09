"""Entrypoint for the Ingestion Server service.

Launches the FastAPI WebSocket server with configuration from environment variables.
"""

import os

import uvicorn

from digital_twin_engine.ingestion.publisher import BrokerType
from digital_twin_engine.shared.models import EngineConfig


def main() -> None:
    """Start the ingestion server using environment-based configuration."""
    config = EngineConfig(
        websocket_port=int(os.environ.get("WEBSOCKET_PORT", "8080")),
        max_buffer_size=int(os.environ.get("MAX_BUFFER_SIZE", "10000")),
        broker_publish_timeout_ms=int(os.environ.get("BROKER_PUBLISH_TIMEOUT_MS", "5000")),
    )

    # Attach broker configuration as extra attributes for the server factory
    config.broker_type = os.environ.get("BROKER_TYPE", "kafka")  # type: ignore[attr-defined]
    config.broker_url = os.environ.get("BROKER_URL", "kafka:29092")  # type: ignore[attr-defined]

    from digital_twin_engine.ingestion.server import create_app

    app = create_app(config)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.websocket_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
