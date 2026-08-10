"""WebSocket Broadcast Manager for the API Gateway.

Manages connected frontend WebSocket clients and broadcasts real-time
messages to all active connections. Messages are sent in the format:
    {"type": "<topic_type>", "payload": {...}}

Handles client disconnection gracefully — a failing send to one client
does not affect broadcasts to other connected clients.

Supported message types:
    - telemetry: Raw telemetry events
    - prediction: ML prediction state vectors
    - correction: EnKF-corrected state vectors
    - anomaly: Anomaly detection alerts
    - rul_update: Remaining Useful Life estimates per engine
    - health_index_update: Composite health index per engine
    - subsystem_health_update: Per-subsystem health scores and classifications
    - degradation_update: Degradation rate per engine

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 8.1, 8.2, 8.3
"""

from __future__ import annotations

import json
from typing import Any, Dict, Set

from fastapi import WebSocket, WebSocketDisconnect

from digital_twin_engine.api.metrics import ws_connections_active
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("websocket_manager")

# All valid message types that can be broadcast via WebSocket.
# Existing pipeline message types:
#   telemetry, prediction, correction, anomaly
# Digital twin prognostics message types (Requirements 8.1, 8.2, 8.3):
#   rul_update, health_index_update, subsystem_health_update, degradation_update
VALID_MESSAGE_TYPES = frozenset(
    [
        "telemetry",
        "prediction",
        "correction",
        "anomaly",
        "rul_update",
        "health_index_update",
        "subsystem_health_update",
        "degradation_update",
        "urgent_attention",
        "critical_health_alert",
    ]
)


class WebSocketBroadcastManager:
    """Manages connected frontend WebSocket clients and broadcasts messages.

    Maintains a set of active WebSocket connections and provides methods
    to connect, disconnect, and broadcast JSON messages to all clients.

    Broadcast failures to individual clients are caught and the client is
    removed without affecting delivery to other connected clients.
    """

    def __init__(self) -> None:
        self._active_connections: Set[WebSocket] = set()

    @property
    def active_connections(self) -> Set[WebSocket]:
        """The set of currently active WebSocket connections."""
        return self._active_connections

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept and track.
        """
        await websocket.accept()
        self._active_connections.add(websocket)
        ws_connections_active.inc()
        logger.info(
            "WebSocket client connected",
            total_connections=len(self._active_connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active set.

        Args:
            websocket: The WebSocket connection to remove.
        """
        self._active_connections.discard(websocket)
        ws_connections_active.dec()
        logger.info(
            "WebSocket client disconnected",
            total_connections=len(self._active_connections),
        )

    async def broadcast(self, message_type: str, payload: dict) -> None:
        """Broadcast a JSON message to all connected WebSocket clients.

        The message is formatted as:
            {"type": "<message_type>", "payload": {...}}

        If sending to a specific client fails, that client is removed from
        the active set and the broadcast continues to remaining clients.

        Supported message types include both pipeline types (telemetry,
        prediction, correction, anomaly) and digital twin prognostics types
        (rul_update, health_index_update, subsystem_health_update,
        degradation_update, urgent_attention, critical_health_alert).

        Args:
            message_type: The type field for the message (e.g., "correction",
                "prediction", "anomaly", "telemetry", "rul_update",
                "health_index_update", "subsystem_health_update",
                "degradation_update").
            payload: The payload dictionary to include in the message.
        """
        if not self._active_connections:
            return

        if message_type not in VALID_MESSAGE_TYPES:
            logger.warning(
                "Unknown message type broadcast attempted",
                message_type=message_type,
            )

        message = json.dumps({"type": message_type, "payload": payload})
        disconnected: Set[WebSocket] = set()

        for connection in self._active_connections.copy():
            try:
                await connection.send_text(message)
            except Exception as exc:
                logger.warning(
                    "Failed to send to WebSocket client, removing",
                    error=str(exc),
                )
                disconnected.add(connection)

        # Remove all clients that failed during broadcast
        for connection in disconnected:
            self._active_connections.discard(connection)

        if disconnected:
            logger.info(
                "Removed disconnected clients during broadcast",
                removed_count=len(disconnected),
                remaining_connections=len(self._active_connections),
            )
