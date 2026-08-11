"""FastAPI application for the Digital Twin Telemetry Engine API Gateway.

Provides REST endpoints for querying:
- Current corrected state per sensor
- Historical corrected states with pagination
- Predicted future states

Maintains an in-memory cache of latest corrected states updated from the
corrections.state broker topic. Queries TSDB for historical data.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from digital_twin_engine.api.models import (
    CurrentStateResponse,
    ErrorResponse,
    HistoryResponse,
    HistoryStateEntry,
    PaginationMetadata,
    PredictedResponse,
    PredictedStateEntry,
)
from digital_twin_engine.api.state_cache import CachedState, StateCache
from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import Prediction, StateVector
from digital_twin_engine.tsdb.writer import TSDBBackend

logger = get_logger("api_gateway")

# Lazy import to avoid circular imports - routers are included at app creation time
_health_router = None
_source_router = None
_metrics_router = None
_engines_router = None
_correction_metrics_router = None
_fault_injection_router = None
_simulation_router = None


def _get_health_router():
    """Lazily import the health router to avoid circular imports."""
    global _health_router
    if _health_router is None:
        from digital_twin_engine.api.health import router as health_router
        _health_router = health_router
    return _health_router


def _get_source_router():
    """Lazily import the source controller router to avoid circular imports."""
    global _source_router
    if _source_router is None:
        from digital_twin_engine.api.source_controller import router as source_router
        _source_router = source_router
    return _source_router


def _get_metrics_router():
    """Lazily import the metrics router to avoid circular imports."""
    global _metrics_router
    if _metrics_router is None:
        from digital_twin_engine.api.metrics import router as metrics_router
        _metrics_router = metrics_router
    return _metrics_router


def _get_engines_router():
    """Lazily import the engines router to avoid circular imports."""
    global _engines_router
    if _engines_router is None:
        from digital_twin_engine.api.engines import router as engines_router
        _engines_router = engines_router
    return _engines_router


def _get_correction_metrics_router():
    """Lazily import the correction metrics router to avoid circular imports."""
    global _correction_metrics_router
    if _correction_metrics_router is None:
        from digital_twin_engine.api.correction_metrics_api import router as correction_metrics_router
        _correction_metrics_router = correction_metrics_router
    return _correction_metrics_router


def _get_fault_injection_router():
    """Lazily import the fault injection router to avoid circular imports."""
    global _fault_injection_router
    if _fault_injection_router is None:
        from digital_twin_engine.api.fault_injection_api import router as fault_injection_router
        _fault_injection_router = fault_injection_router
    return _fault_injection_router


def _get_simulation_router():
    """Lazily import the simulation router to avoid circular imports."""
    global _simulation_router
    if _simulation_router is None:
        from digital_twin_engine.api.simulation_api import router as simulation_router
        _simulation_router = simulation_router
    return _simulation_router


class APIGateway:
    """API Gateway that serves REST endpoints and manages state cache.

    This class encapsulates the FastAPI application, the in-memory state
    cache, and TSDB query functionality.

    Args:
        tsdb_backend: TSDB backend for historical queries.
        state_cache: In-memory cache for current corrected states.
    """

    def __init__(
        self,
        tsdb_backend: Optional[TSDBBackend] = None,
        state_cache: Optional[StateCache] = None,
    ) -> None:
        self._tsdb_backend = tsdb_backend
        self._state_cache = state_cache or StateCache()
        self._predictions_cache: dict[str, List[Prediction]] = {}
        self._ws_manager = WebSocketBroadcastManager()
        self._app = self._create_app()

    @property
    def app(self) -> FastAPI:
        """The FastAPI application instance."""
        return self._app

    @property
    def state_cache(self) -> StateCache:
        """Access the state cache for external updates."""
        return self._state_cache

    @property
    def predictions_cache(self) -> dict[str, List[Prediction]]:
        """Access the predictions cache for external updates."""
        return self._predictions_cache

    @property
    def ws_manager(self) -> WebSocketBroadcastManager:
        """Access the WebSocket broadcast manager."""
        return self._ws_manager

    def set_tsdb_backend(self, backend: TSDBBackend) -> None:
        """Set or replace the TSDB backend."""
        self._tsdb_backend = backend

    def _create_app(self) -> FastAPI:
        """Create and configure the FastAPI application with all routes."""
        app = FastAPI(
            title="Digital Twin Telemetry Engine API",
            description="REST API for querying sensor states and predictions",
            version="1.0.0",
        )

        # CORS middleware configuration (Requirements 3.1, 3.2, 3.3, 3.4)
        cors_origins = os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://localhost:3001"
        ).split(",")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
            allow_credentials=True,
        )

        # Include health router (from task 9.4)
        app.include_router(_get_health_router())

        # Include source controller router (Requirements 5.1, 5.2, 5.3, 5.4)
        app.include_router(_get_source_router())

        # Include Prometheus metrics router (Requirements 9.1, 9.5)
        app.include_router(_get_metrics_router())

        # Include engines router (Requirements 8.5)
        app.include_router(_get_engines_router())

        # Include correction metrics router (Requirements 3.4, 4.4, 5.6)
        app.include_router(_get_correction_metrics_router())

        # Include fault injection router (Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6)
        app.include_router(_get_fault_injection_router())

        # Include simulation router (Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7)
        app.include_router(_get_simulation_router())

        @app.get(
            "/sensors/{sensor_id}/state/current",
            response_model=CurrentStateResponse,
            responses={404: {"model": ErrorResponse}},
        )
        async def get_current_state(sensor_id: str) -> Any:
            """Get the most recent corrected StateVector for a sensor.

            Returns HTTP 404 if the sensor_id is unknown.
            """
            if not self._state_cache.is_known_sensor(sensor_id):
                return JSONResponse(
                    status_code=404,
                    content={
                        "error_code": "SENSOR_NOT_FOUND",
                        "message": f"No telemetry recorded for sensor_id: {sensor_id}",
                    },
                )

            cached = self._state_cache.get_current(sensor_id)
            if cached is None:
                # Sensor is known but no corrected state yet - still 404
                return JSONResponse(
                    status_code=404,
                    content={
                        "error_code": "NO_STATE_AVAILABLE",
                        "message": f"No corrected state available for sensor_id: {sensor_id}",
                    },
                )

            return CurrentStateResponse(
                sensor_id=cached.sensor_id,
                timestamp=cached.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                state_vector=cached.state_vector,
                ensemble_spread=cached.ensemble_spread,
                anomaly_flag=cached.anomaly_flag,
            )

        @app.get(
            "/sensors/{sensor_id}/state/history",
            response_model=HistoryResponse,
            responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
        )
        async def get_state_history(
            sensor_id: str,
            start: Optional[str] = Query(None, description="Start timestamp (ISO 8601)"),
            end: Optional[str] = Query(None, description="End timestamp (ISO 8601)"),
            limit: Optional[int] = Query(100, description="Page size (1-1000)"),
            offset: Optional[int] = Query(0, description="Offset for pagination"),
        ) -> Any:
            """Get historical corrected StateVectors for a sensor within a time range.

            Returns paginated results ordered chronologically.
            Returns HTTP 404 for unknown sensor_id.
            Returns HTTP 400 for invalid parameters.
            Returns HTTP 200 with empty results for known sensor with no data in range.
            """
            # Validate all request parameters before checking sensor existence.
            # This ensures HTTP 400 is always returned for invalid parameters
            # regardless of whether the sensor_id exists (Requirements 7.6, 7.8, 7.9).

            # Validate pagination parameters
            if limit is not None and (limit < 1 or limit > 1000):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Parameter 'limit' must be between 1 and 1000",
                    },
                )

            if offset is not None and offset < 0:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Parameter 'offset' must be greater than or equal to 0",
                    },
                )

            # Validate start parameter
            if start is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Missing required query parameter: start",
                    },
                )

            # Validate end parameter
            if end is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Missing required query parameter: end",
                    },
                )

            # Parse start timestamp
            start_dt = _parse_iso_timestamp(start)
            if start_dt is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Parameter 'start' is not a valid ISO 8601 timestamp",
                    },
                )

            # Parse end timestamp
            end_dt = _parse_iso_timestamp(end)
            if end_dt is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Parameter 'end' is not a valid ISO 8601 timestamp",
                    },
                )

            # Validate start <= end
            if start_dt > end_dt:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "INVALID_PARAMETER",
                        "message": "Parameter 'start' must not be after 'end'",
                    },
                )

            # Apply defaults if None
            if limit is None:
                limit = 100
            if offset is None:
                offset = 0

            # Check sensor existence (only after all parameters are validated)
            if not self._state_cache.is_known_sensor(sensor_id):
                return JSONResponse(
                    status_code=404,
                    content={
                        "error_code": "SENSOR_NOT_FOUND",
                        "message": f"No telemetry recorded for sensor_id: {sensor_id}",
                    },
                )

            # Query TSDB for historical data
            if self._tsdb_backend is None:
                # No TSDB configured - return empty results
                return HistoryResponse(
                    sensor_id=sensor_id,
                    results=[],
                    pagination=PaginationMetadata(
                        total_count=0,
                        offset=offset,
                        limit=limit,
                    ),
                )

            # Query all matching records from TSDB
            all_records = await self._tsdb_backend.query_by_sensor_and_time(
                sensor_id=sensor_id,
                start=start_dt,
                end=end_dt,
            )

            total_count = len(all_records)

            # Apply pagination
            paginated = all_records[offset : offset + limit]

            results = [
                HistoryStateEntry(
                    timestamp=record.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    state_vector=[record.value],
                    ensemble_spread=0.0,
                    anomaly_flag=False,
                )
                for record in paginated
            ]

            return HistoryResponse(
                sensor_id=sensor_id,
                results=results,
                pagination=PaginationMetadata(
                    total_count=total_count,
                    offset=offset,
                    limit=limit,
                ),
            )

        @app.get(
            "/sensors/{sensor_id}/state/predicted",
            response_model=PredictedResponse,
            responses={404: {"model": ErrorResponse}},
        )
        async def get_predicted_state(sensor_id: str) -> Any:
            """Get predicted future StateVectors for a sensor.

            Returns HTTP 404 if the sensor_id is unknown.
            """
            if not self._state_cache.is_known_sensor(sensor_id):
                return JSONResponse(
                    status_code=404,
                    content={
                        "error_code": "SENSOR_NOT_FOUND",
                        "message": f"No telemetry recorded for sensor_id: {sensor_id}",
                    },
                )

            predictions = self._predictions_cache.get(sensor_id, [])

            entries = [
                PredictedStateEntry(
                    timestamp=p.prediction_timestamp.strftime(
                        "%Y-%m-%dT%H:%M:%S.%fZ"
                    ),
                    state_vector=p.state_vector,
                    model_used=p.model_used,
                    prediction_horizon_seconds=p.prediction_horizon_seconds,
                )
                for p in predictions
            ]

            return PredictedResponse(
                sensor_id=sensor_id,
                predictions=entries,
            )

        @app.websocket("/ws/telemetry")
        async def websocket_telemetry(websocket: WebSocket) -> None:
            """WebSocket endpoint for real-time telemetry broadcasts.

            Accepts a client connection, registers it with the broadcast
            manager, and keeps it alive until the client disconnects.
            """
            await self._ws_manager.connect(websocket)
            try:
                while True:
                    # Keep the connection alive by waiting for incoming messages.
                    # We don't process client messages but need the receive loop
                    # to detect disconnection.
                    await websocket.receive_text()
            except WebSocketDisconnect:
                await self._ws_manager.disconnect(websocket)
            except Exception:
                await self._ws_manager.disconnect(websocket)

        return app


def _parse_iso_timestamp(value: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime.

    Returns None if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def create_app(
    tsdb_backend: Optional[TSDBBackend] = None,
    state_cache: Optional[StateCache] = None,
) -> FastAPI:
    """Create a configured FastAPI application for the API Gateway.

    Args:
        tsdb_backend: Optional TSDB backend for historical queries.
        state_cache: Optional pre-configured state cache.

    Returns:
        A FastAPI application instance ready to serve requests.
    """
    gateway = APIGateway(tsdb_backend=tsdb_backend, state_cache=state_cache)
    return gateway.app


# Module-level default app instance for use by tests and uvicorn
_default_gateway = APIGateway()
app = _default_gateway.app
