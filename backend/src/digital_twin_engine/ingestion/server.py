"""WebSocket server for high-frequency telemetry ingestion.

Implements the Ingestion_Server component:
- FastAPI application with WebSocket endpoint at ws://host:{port}/ws/telemetry
- Connection lifecycle management (accept, track, disconnect/drop within 5s)
- Configurable port (1024-65535) from EngineConfig
- Capacity rejection (HTTP 503 + Retry-After) when connection limit exceeded
- Telemetry event validation with error response on failure
- Structured metrics emission at intervals ≤15s

Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.9, 9.1, 9.5, 9.6
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocketState

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import (
    EngineConfig,
    TelemetryValidationError,
    validate_telemetry_payload,
)
from digital_twin_engine.ingestion.publisher import (
    BackpressureError,
    BrokerType,
    TelemetryPublisher,
)
from digital_twin_engine.ingestion.metrics import events_ingested_total, router as metrics_router


logger = get_logger("ingestion_server")


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections with capacity enforcement.

    Tracks all active connections and provides metrics for observability.
    Enforces a maximum connection limit to protect existing connections
    under load (Requirement 9.5, 9.6).
    """

    def __init__(self, max_connections: int = 10_000) -> None:
        self._active_connections: Set[WebSocket] = set()
        self._max_connections = max_connections
        self._lock = asyncio.Lock()

        # Metrics counters
        self._events_received: int = 0
        self._events_rejected: int = 0
        self._total_publish_latency_ms: float = 0.0
        self._publish_count: int = 0

    @property
    def active_count(self) -> int:
        """Number of currently active WebSocket connections."""
        return len(self._active_connections)

    @property
    def max_connections(self) -> int:
        """Maximum allowed concurrent connections."""
        return self._max_connections

    def is_at_capacity(self) -> bool:
        """Check if the server has reached its connection capacity."""
        return len(self._active_connections) >= self._max_connections

    async def accept(self, websocket: WebSocket) -> bool:
        """Accept a WebSocket connection if capacity allows.

        Returns True if the connection was accepted, False if at capacity.
        """
        async with self._lock:
            if self.is_at_capacity():
                return False
            await websocket.accept()
            self._active_connections.add(websocket)
            logger.info(
                "WebSocket connection accepted",
                active_connections=len(self._active_connections),
            )
            return True

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection from the active set and release resources.

        Must complete within 5 seconds (Requirement 1.9).
        """
        async with self._lock:
            self._active_connections.discard(websocket)
        logger.info(
            "WebSocket connection closed",
            active_connections=self.active_count,
        )

    def record_event_received(self) -> None:
        """Record that a telemetry event was received."""
        self._events_received += 1

    def record_event_rejected(self) -> None:
        """Record that a telemetry event was rejected."""
        self._events_rejected += 1

    def record_publish_latency(self, latency_ms: float) -> None:
        """Record the latency of publishing an event to the broker."""
        self._total_publish_latency_ms += latency_ms
        self._publish_count += 1

    def get_and_reset_metrics(self) -> dict:
        """Get current metrics and reset counters for the next interval.

        Returns a dictionary of metrics suitable for structured logging.
        """
        avg_latency = (
            self._total_publish_latency_ms / self._publish_count
            if self._publish_count > 0
            else 0.0
        )
        metrics = {
            "active_connection_count": self.active_count,
            "events_received": self._events_received,
            "events_rejected": self._events_rejected,
            "avg_publish_latency_ms": round(avg_latency, 3),
            "publish_count": self._publish_count,
        }
        # Reset counters
        self._events_received = 0
        self._events_rejected = 0
        self._total_publish_latency_ms = 0.0
        self._publish_count = 0
        return metrics


# ---------------------------------------------------------------------------
# Metrics Emission Task
# ---------------------------------------------------------------------------

_metrics_task: asyncio.Task | None = None


async def _emit_metrics_loop(manager: ConnectionManager, interval: float = 15.0) -> None:
    """Background task that emits structured metrics at configured intervals.

    Emits at intervals ≤15 seconds (Requirement 8.4):
    - active_connection_count
    - events_received_per_second
    - events_rejected_per_second
    - publish_latency_ms
    """
    while True:
        await asyncio.sleep(interval)
        metrics = manager.get_and_reset_metrics()
        # Compute per-second rates
        events_received_per_second = metrics["events_received"] / interval
        events_rejected_per_second = metrics["events_rejected"] / interval
        logger.info(
            "Ingestion metrics",
            active_connection_count=metrics["active_connection_count"],
            events_received_per_second=round(events_received_per_second, 2),
            events_rejected_per_second=round(events_rejected_per_second, 2),
            publish_latency_ms=metrics["avg_publish_latency_ms"],
        )


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------

# Global connection manager instance (set during app creation)
_connection_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    if _connection_manager is None:
        raise RuntimeError("Connection manager not initialized. Call create_app() first.")
    return _connection_manager


def create_app(config: EngineConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application for telemetry ingestion.

    Args:
        config: Engine configuration. Uses defaults if not provided.

    Returns:
        Configured FastAPI application with WebSocket endpoint.
    """
    global _connection_manager, _metrics_task

    if config is None:
        config = EngineConfig()

    manager = ConnectionManager(max_connections=10_000)
    _connection_manager = manager

    # Create the telemetry publisher
    broker_type = getattr(config, "broker_type", BrokerType.KAFKA)
    broker_url = getattr(config, "broker_url", "localhost:9092")
    publisher = TelemetryPublisher(
        broker_type=broker_type if isinstance(broker_type, BrokerType) else BrokerType(broker_type),
        broker_url=broker_url,
        max_buffer_size=config.max_buffer_size,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage application lifecycle: start/stop metrics emission and publisher."""
        global _metrics_task
        # Start publisher
        await publisher.start()
        _metrics_task = asyncio.create_task(_emit_metrics_loop(manager, interval=15.0))
        logger.info(
            "Ingestion server started",
            port=config.websocket_port,
            max_connections=manager.max_connections,
        )
        yield
        # Shutdown: cancel metrics task and stop publisher
        if _metrics_task is not None:
            _metrics_task.cancel()
            try:
                await _metrics_task
            except asyncio.CancelledError:
                pass
        await publisher.stop()
        logger.info("Ingestion server stopped")

    app = FastAPI(
        title="Digital Twin Telemetry Ingestion Server",
        lifespan=lifespan,
    )

    # Include Prometheus metrics router (Requirements 9.2, 9.5)
    app.include_router(metrics_router)

    # Store config and manager on app state for access in routes
    app.state.config = config
    app.state.connection_manager = manager
    app.state.publisher = publisher

    # ------------------------------------------------------------------
    # Capacity rejection middleware
    # ------------------------------------------------------------------

    @app.middleware("http")
    async def capacity_check_middleware(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        """Reject new WebSocket upgrade requests with 503 when at capacity.

        Only applies to the WebSocket telemetry endpoint. Existing connections
        are maintained without degradation (Requirement 9.5, 9.6).
        """
        # Check if this is a WebSocket upgrade request to our endpoint
        if (
            request.url.path == "/ws/telemetry"
            and request.headers.get("upgrade", "").lower() == "websocket"
            and manager.is_at_capacity()
        ):
            logger.warning(
                "Connection rejected: at capacity",
                active_connections=manager.active_count,
                max_connections=manager.max_connections,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service at capacity",
                    "message": "Maximum concurrent connections reached. Retry later.",
                    "active_connections": manager.active_count,
                    "max_connections": manager.max_connections,
                },
                headers={"Retry-After": "30"},
            )
        return await call_next(request)

    # ------------------------------------------------------------------
    # WebSocket endpoint
    # ------------------------------------------------------------------

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry(websocket: WebSocket) -> None:
        """WebSocket endpoint for telemetry event ingestion.

        Handles the full connection lifecycle:
        1. Accept connection (if under capacity)
        2. Track in active connections set
        3. Receive, validate, and process messages
        4. Send error response on validation failure (Requirement 1.5)
        5. Log rejected events with details (Requirement 1.7)
        6. Isolate failures per connection (Requirement 1.6)
        7. Handle disconnect/drop within 5 seconds (Requirement 1.9)
        """
        # Accept with capacity check
        accepted = await manager.accept(websocket)
        if not accepted:
            # Close with 1013 (Try Again Later) code if somehow got past middleware
            await websocket.close(code=1013, reason="Server at capacity")
            return

        try:
            while True:
                # Receive messages - this will raise WebSocketDisconnect on close
                data = await websocket.receive_text()
                manager.record_event_received()

                # Validate the incoming telemetry payload
                try:
                    event = validate_telemetry_payload(data)
                    # Valid event - increment Prometheus counter (Requirement 9.5)
                    events_ingested_total.inc()
                    # Publish to the message broker
                    try:
                        latency_ms = await publisher.publish(event)
                        manager.record_publish_latency(latency_ms)
                    except BackpressureError:
                        # Buffer full - reject with backpressure signal
                        manager.record_event_rejected()
                        error_response = {
                            "error_code": "BACKPRESSURE",
                            "message": "Server buffer full. Try again later.",
                            "sensor_id": event.sensor_id,
                            "rejected_at": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%S.%fZ"
                            ),
                        }
                        await websocket.send_text(json.dumps(error_response))
                        logger.warning(
                            "Event rejected due to backpressure",
                            sensor_id=event.sensor_id,
                            buffer_size=publisher.buffer_size,
                        )
                except TelemetryValidationError as val_err:
                    # Validation failed - send error response and log rejection
                    manager.record_event_rejected()

                    # Extract sensor_id from payload if possible
                    sensor_id = _extract_sensor_id(data)
                    rejected_at = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S.%fZ"
                    )

                    # Build error response (Requirement 1.5)
                    error_response = {
                        "error_code": val_err.code.value,
                        "message": val_err.message,
                        "sensor_id": sensor_id,
                        "rejected_at": rejected_at,
                    }
                    await websocket.send_text(json.dumps(error_response))

                    # Log the rejection (Requirement 1.7)
                    logger.warning(
                        "Telemetry event rejected",
                        sensor_id=sensor_id,
                        rejected_at=rejected_at,
                        error_code=val_err.code.value,
                        validation_error=val_err.message,
                    )
        except WebSocketDisconnect:
            # Normal disconnect - release resources within 5 seconds
            await _release_connection(manager, websocket)
        except Exception as exc:
            # Unexpected error/drop - release resources within 5 seconds
            # Isolation: this only affects THIS connection (Requirement 1.6)
            logger.error(
                "WebSocket connection error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await _release_connection(manager, websocket)

    return app


def _extract_sensor_id(raw_data: str) -> str | None:
    """Best-effort extraction of sensor_id from a raw JSON payload.

    Returns the sensor_id string if the payload is valid JSON containing
    a 'sensor_id' field, otherwise returns None.
    """
    try:
        parsed = json.loads(raw_data)
        if isinstance(parsed, dict):
            sid = parsed.get("sensor_id")
            if isinstance(sid, str):
                return sid
    except (json.JSONDecodeError, TypeError):
        pass
    return None


async def _release_connection(manager: ConnectionManager, websocket: WebSocket) -> None:
    """Release all resources for a connection within 5 seconds.

    Implements Requirement 1.9: resource release within 5 seconds of
    connection close or unexpected drop.
    """
    try:
        async with asyncio.timeout(5.0):
            await manager.disconnect(websocket)
            # Close the WebSocket if still open
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
    except asyncio.TimeoutError:
        # Force cleanup if 5-second deadline exceeded
        logger.error(
            "Connection resource release exceeded 5-second deadline",
        )
        # Still remove from tracking even if close failed
        manager._active_connections.discard(websocket)
    except Exception as exc:
        # Ensure cleanup happens even if close fails
        logger.error(
            "Error during connection cleanup",
            error=str(exc),
        )
        manager._active_connections.discard(websocket)
