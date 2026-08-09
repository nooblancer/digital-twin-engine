"""Unit tests for the WebSocket Broadcast Manager.

Tests the WebSocketBroadcastManager class:
- Client connection and disconnection
- Broadcasting messages to all connected clients
- Graceful handling of client disconnection during broadcast
- Message format: {"type": "<topic_type>", "payload": {...}}

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> WebSocketBroadcastManager:
    """Create a fresh WebSocketBroadcastManager instance."""
    return WebSocketBroadcastManager()


def _make_mock_websocket() -> AsyncMock:
    """Create a mock WebSocket that behaves like a FastAPI WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for WebSocketBroadcastManager.connect()."""

    async def test_connect_accepts_websocket(self, manager: WebSocketBroadcastManager):
        """Connect should call accept() on the websocket."""
        ws = _make_mock_websocket()
        await manager.connect(ws)
        ws.accept.assert_awaited_once()

    async def test_connect_adds_to_active_connections(
        self, manager: WebSocketBroadcastManager
    ):
        """Connect should add the websocket to the active connections set."""
        ws = _make_mock_websocket()
        await manager.connect(ws)
        assert ws in manager.active_connections

    async def test_connect_multiple_clients(self, manager: WebSocketBroadcastManager):
        """Multiple clients can connect simultaneously."""
        ws1 = _make_mock_websocket()
        ws2 = _make_mock_websocket()
        ws3 = _make_mock_websocket()

        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.connect(ws3)

        assert len(manager.active_connections) == 3
        assert ws1 in manager.active_connections
        assert ws2 in manager.active_connections
        assert ws3 in manager.active_connections


# ---------------------------------------------------------------------------
# Disconnection tests
# ---------------------------------------------------------------------------


class TestDisconnect:
    """Tests for WebSocketBroadcastManager.disconnect()."""

    async def test_disconnect_removes_from_active_connections(
        self, manager: WebSocketBroadcastManager
    ):
        """Disconnect should remove the client from active connections."""
        ws = _make_mock_websocket()
        await manager.connect(ws)
        assert ws in manager.active_connections

        await manager.disconnect(ws)
        assert ws not in manager.active_connections

    async def test_disconnect_unknown_client_is_safe(
        self, manager: WebSocketBroadcastManager
    ):
        """Disconnecting an unknown client should not raise."""
        ws = _make_mock_websocket()
        # Never connected, but disconnect should not raise
        await manager.disconnect(ws)
        assert len(manager.active_connections) == 0

    async def test_disconnect_does_not_affect_other_clients(
        self, manager: WebSocketBroadcastManager
    ):
        """Disconnecting one client should not affect others."""
        ws1 = _make_mock_websocket()
        ws2 = _make_mock_websocket()

        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.disconnect(ws1)

        assert ws1 not in manager.active_connections
        assert ws2 in manager.active_connections


# ---------------------------------------------------------------------------
# Broadcast tests
# ---------------------------------------------------------------------------


class TestBroadcast:
    """Tests for WebSocketBroadcastManager.broadcast()."""

    async def test_broadcast_sends_to_all_clients(
        self, manager: WebSocketBroadcastManager
    ):
        """Broadcast should send the message to all connected clients."""
        ws1 = _make_mock_websocket()
        ws2 = _make_mock_websocket()

        await manager.connect(ws1)
        await manager.connect(ws2)

        payload = {"sensor_id": "sensor-1", "value": 42.0}
        await manager.broadcast("correction", payload)

        expected = json.dumps({"type": "correction", "payload": payload})
        ws1.send_text.assert_awaited_once_with(expected)
        ws2.send_text.assert_awaited_once_with(expected)

    async def test_broadcast_message_format(self, manager: WebSocketBroadcastManager):
        """Broadcast message should have correct JSON format."""
        ws = _make_mock_websocket()
        await manager.connect(ws)

        payload = {"key": "value", "number": 123}
        await manager.broadcast("telemetry", payload)

        sent_text = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_text)
        assert parsed == {"type": "telemetry", "payload": payload}

    async def test_broadcast_correction_type(self, manager: WebSocketBroadcastManager):
        """Broadcast with 'correction' type should format correctly."""
        ws = _make_mock_websocket()
        await manager.connect(ws)

        payload = {"sensor_id": "s1", "corrected_state_vector": [1.0, 2.0]}
        await manager.broadcast("correction", payload)

        sent_text = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_text)
        assert parsed["type"] == "correction"
        assert parsed["payload"] == payload

    async def test_broadcast_prediction_type(self, manager: WebSocketBroadcastManager):
        """Broadcast with 'prediction' type should format correctly."""
        ws = _make_mock_websocket()
        await manager.connect(ws)

        payload = {"sensor_id": "s1", "predicted_state": [3.0, 4.0]}
        await manager.broadcast("prediction", payload)

        sent_text = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_text)
        assert parsed["type"] == "prediction"
        assert parsed["payload"] == payload

    async def test_broadcast_anomaly_type(self, manager: WebSocketBroadcastManager):
        """Broadcast with 'anomaly' type should format correctly."""
        ws = _make_mock_websocket()
        await manager.connect(ws)

        payload = {"sensor_id": "s1", "anomaly_score": 0.95}
        await manager.broadcast("anomaly", payload)

        sent_text = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_text)
        assert parsed["type"] == "anomaly"
        assert parsed["payload"] == payload

    async def test_broadcast_telemetry_type(self, manager: WebSocketBroadcastManager):
        """Broadcast with 'telemetry' type should format correctly."""
        ws = _make_mock_websocket()
        await manager.connect(ws)

        payload = {"sensor_id": "s1", "raw_values": [10.0, 20.0]}
        await manager.broadcast("telemetry", payload)

        sent_text = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_text)
        assert parsed["type"] == "telemetry"
        assert parsed["payload"] == payload

    async def test_broadcast_no_clients_does_nothing(
        self, manager: WebSocketBroadcastManager
    ):
        """Broadcasting with no clients should not raise."""
        # Should not raise
        await manager.broadcast("correction", {"test": True})

    async def test_broadcast_removes_failed_client(
        self, manager: WebSocketBroadcastManager
    ):
        """If sending to a client fails, that client should be removed."""
        ws_good = _make_mock_websocket()
        ws_bad = _make_mock_websocket()
        ws_bad.send_text.side_effect = RuntimeError("Connection closed")

        await manager.connect(ws_good)
        await manager.connect(ws_bad)

        payload = {"test": True}
        await manager.broadcast("correction", payload)

        # The good client should have received the message
        expected = json.dumps({"type": "correction", "payload": payload})
        ws_good.send_text.assert_awaited_once_with(expected)

        # The bad client should be removed
        assert ws_bad not in manager.active_connections
        assert ws_good in manager.active_connections

    async def test_broadcast_continues_after_client_failure(
        self, manager: WebSocketBroadcastManager
    ):
        """A failing client should not prevent other clients from receiving."""
        ws1 = _make_mock_websocket()
        ws2 = _make_mock_websocket()
        ws3 = _make_mock_websocket()
        ws2.send_text.side_effect = RuntimeError("Connection closed")

        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.connect(ws3)

        payload = {"data": "test"}
        await manager.broadcast("telemetry", payload)

        expected = json.dumps({"type": "telemetry", "payload": payload})
        ws1.send_text.assert_awaited_once_with(expected)
        ws3.send_text.assert_awaited_once_with(expected)

        # ws2 removed, others still connected
        assert ws2 not in manager.active_connections
        assert ws1 in manager.active_connections
        assert ws3 in manager.active_connections


# ---------------------------------------------------------------------------
# WebSocket endpoint integration tests
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    """Tests for the /ws/telemetry WebSocket endpoint integration."""

    async def test_gateway_has_ws_manager(self):
        """APIGateway should have a ws_manager property."""
        from digital_twin_engine.api.app import APIGateway

        gateway = APIGateway()
        assert gateway.ws_manager is not None
        assert isinstance(gateway.ws_manager, WebSocketBroadcastManager)
