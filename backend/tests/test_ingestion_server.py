"""Tests for the ingestion WebSocket server.

Tests connection management, capacity rejection, metrics emission,
and WebSocket lifecycle handling.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from digital_twin_engine.ingestion.server import (
    ConnectionManager,
    create_app,
    get_connection_manager,
)
from digital_twin_engine.shared.models import EngineConfig


# ---------------------------------------------------------------------------
# ConnectionManager unit tests
# ---------------------------------------------------------------------------


class TestConnectionManager:
    """Unit tests for the ConnectionManager class."""

    def test_initial_state(self) -> None:
        manager = ConnectionManager(max_connections=100)
        assert manager.active_count == 0
        assert manager.max_connections == 100
        assert not manager.is_at_capacity()

    def test_is_at_capacity_with_zero_max(self) -> None:
        manager = ConnectionManager(max_connections=0)
        assert manager.is_at_capacity()

    def test_record_event_received(self) -> None:
        manager = ConnectionManager()
        manager.record_event_received()
        manager.record_event_received()
        metrics = manager.get_and_reset_metrics()
        assert metrics["events_received"] == 2

    def test_record_event_rejected(self) -> None:
        manager = ConnectionManager()
        manager.record_event_rejected()
        metrics = manager.get_and_reset_metrics()
        assert metrics["events_rejected"] == 1

    def test_record_publish_latency(self) -> None:
        manager = ConnectionManager()
        manager.record_publish_latency(10.0)
        manager.record_publish_latency(20.0)
        metrics = manager.get_and_reset_metrics()
        assert metrics["avg_publish_latency_ms"] == 15.0
        assert metrics["publish_count"] == 2

    def test_get_and_reset_metrics_resets_counters(self) -> None:
        manager = ConnectionManager()
        manager.record_event_received()
        manager.record_event_rejected()
        manager.record_publish_latency(5.0)
        # First call returns accumulated values
        metrics = manager.get_and_reset_metrics()
        assert metrics["events_received"] == 1
        # Second call returns zeros
        metrics = manager.get_and_reset_metrics()
        assert metrics["events_received"] == 0
        assert metrics["events_rejected"] == 0
        assert metrics["avg_publish_latency_ms"] == 0.0
        assert metrics["publish_count"] == 0

    def test_metrics_with_no_publishes(self) -> None:
        manager = ConnectionManager()
        metrics = manager.get_and_reset_metrics()
        assert metrics["avg_publish_latency_ms"] == 0.0


# ---------------------------------------------------------------------------
# App creation tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Tests for the FastAPI app factory."""

    def test_create_app_default_config(self) -> None:
        app = create_app()
        assert app is not None
        assert app.state.config.websocket_port == 8080

    def test_create_app_custom_config(self) -> None:
        config = EngineConfig(websocket_port=9090)
        app = create_app(config)
        assert app.state.config.websocket_port == 9090

    def test_create_app_has_websocket_route(self) -> None:
        app = create_app()
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/ws/telemetry" in routes


# ---------------------------------------------------------------------------
# WebSocket endpoint integration tests
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    """Integration tests for the WebSocket telemetry endpoint."""

    def test_websocket_connect_and_disconnect(self) -> None:
        app = create_app()
        manager = app.state.connection_manager
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                assert manager.active_count == 1
            # After disconnect
            assert manager.active_count == 0

    def test_websocket_receive_message(self) -> None:
        app = create_app()
        manager = app.state.connection_manager
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text('{"test": "data"}')
                # Small delay for async processing
                assert manager.active_count == 1

    def test_multiple_connections(self) -> None:
        app = create_app()
        manager = app.state.connection_manager
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws1:
                with client.websocket_connect("/ws/telemetry") as ws2:
                    assert manager.active_count == 2
                assert manager.active_count == 1
            assert manager.active_count == 0


# ---------------------------------------------------------------------------
# Capacity rejection tests
# ---------------------------------------------------------------------------


class TestCapacityRejection:
    """Tests for HTTP 503 capacity rejection."""

    def test_capacity_rejection_returns_503(self) -> None:
        """When at max connections, new WebSocket upgrades get 503."""
        app = create_app()
        manager = app.state.connection_manager
        # Set capacity to 1
        manager._max_connections = 1

        with TestClient(app) as client:
            # First connection succeeds
            with client.websocket_connect("/ws/telemetry") as ws:
                assert manager.active_count == 1
                # Second connection should be rejected via middleware
                # The middleware checks upgrade header, so we test via HTTP
                response = client.get(
                    "/ws/telemetry",
                    headers={"upgrade": "websocket", "connection": "upgrade"},
                )
                assert response.status_code == 503
                assert "Retry-After" in response.headers
                assert response.headers["Retry-After"] == "30"

    def test_existing_connections_maintained_during_capacity(self) -> None:
        """Existing connections continue when capacity is reached."""
        app = create_app()
        manager = app.state.connection_manager
        manager._max_connections = 1

        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                # Connection is active
                assert manager.active_count == 1
                # Send data on existing connection still works
                ws.send_text('{"test": "data"}')


# ---------------------------------------------------------------------------
# Config port validation tests
# ---------------------------------------------------------------------------


class TestPortConfiguration:
    """Tests for configurable port validation."""

    def test_valid_port_min(self) -> None:
        config = EngineConfig(websocket_port=1024)
        app = create_app(config)
        assert app.state.config.websocket_port == 1024

    def test_valid_port_max(self) -> None:
        config = EngineConfig(websocket_port=65535)
        app = create_app(config)
        assert app.state.config.websocket_port == 65535

    def test_invalid_port_below_range(self) -> None:
        with pytest.raises(Exception):
            EngineConfig(websocket_port=1023)

    def test_invalid_port_above_range(self) -> None:
        with pytest.raises(Exception):
            EngineConfig(websocket_port=65536)
