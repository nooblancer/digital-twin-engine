"""Tests for WebSocket event validation and error response handling.

Tests that the ingestion server validates incoming telemetry events,
sends proper error responses on validation failure, logs rejections,
and maintains connection isolation.

Validates: Requirements 1.2, 1.5, 1.6, 1.7
"""

import json

import pytest
from starlette.testclient import TestClient

from digital_twin_engine.ingestion.server import (
    ConnectionManager,
    _extract_sensor_id,
    create_app,
)


# ---------------------------------------------------------------------------
# Helper to build valid/invalid payloads
# ---------------------------------------------------------------------------

VALID_PAYLOAD = json.dumps({
    "timestamp": "2024-01-15T10:30:00.123456Z",
    "sensor_id": "turbine-001-temp",
    "measurement_type": "temperature_celsius",
    "value": 342.17,
})

INVALID_TIMESTAMP_PAYLOAD = json.dumps({
    "timestamp": "not-a-timestamp",
    "sensor_id": "turbine-001-temp",
    "measurement_type": "temperature_celsius",
    "value": 342.17,
})

INVALID_VALUE_NAN_PAYLOAD = json.dumps({
    "timestamp": "2024-01-15T10:30:00.123456Z",
    "sensor_id": "turbine-001-temp",
    "measurement_type": "temperature_celsius",
    "value": float("inf"),
})

EMPTY_SENSOR_ID_PAYLOAD = json.dumps({
    "timestamp": "2024-01-15T10:30:00.123456Z",
    "sensor_id": "",
    "measurement_type": "temperature_celsius",
    "value": 42.0,
})

WHITESPACE_MEASUREMENT_TYPE_PAYLOAD = json.dumps({
    "timestamp": "2024-01-15T10:30:00.123456Z",
    "sensor_id": "sensor-abc",
    "measurement_type": "   ",
    "value": 42.0,
})

MISSING_FIELD_PAYLOAD = json.dumps({
    "timestamp": "2024-01-15T10:30:00.123456Z",
    "sensor_id": "turbine-001-temp",
})

INVALID_JSON_PAYLOAD = "this is not json {{"


# ---------------------------------------------------------------------------
# _extract_sensor_id unit tests
# ---------------------------------------------------------------------------


class TestExtractSensorId:
    """Unit tests for the _extract_sensor_id helper function."""

    def test_extracts_sensor_id_from_valid_json(self) -> None:
        payload = json.dumps({"sensor_id": "turbine-001", "other": "stuff"})
        assert _extract_sensor_id(payload) == "turbine-001"

    def test_returns_none_for_invalid_json(self) -> None:
        assert _extract_sensor_id("not json at all") is None

    def test_returns_none_for_missing_sensor_id(self) -> None:
        payload = json.dumps({"timestamp": "2024-01-15T10:30:00Z"})
        assert _extract_sensor_id(payload) is None

    def test_returns_none_for_non_string_sensor_id(self) -> None:
        payload = json.dumps({"sensor_id": 12345})
        assert _extract_sensor_id(payload) is None

    def test_returns_none_for_non_dict_json(self) -> None:
        payload = json.dumps([1, 2, 3])
        assert _extract_sensor_id(payload) is None


# ---------------------------------------------------------------------------
# Validation error response tests
# ---------------------------------------------------------------------------


class TestValidationErrorResponse:
    """Tests that invalid payloads produce correct error responses over WebSocket."""

    def test_invalid_timestamp_returns_error(self) -> None:
        """Invalid timestamp triggers error response with INVALID_TIMESTAMP code."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(INVALID_TIMESTAMP_PAYLOAD)
                response = json.loads(ws.receive_text())

                assert response["error_code"] == "INVALID_TIMESTAMP"
                assert "message" in response
                assert response["sensor_id"] == "turbine-001-temp"
                assert "rejected_at" in response
                # rejected_at should be a valid ISO 8601 timestamp
                assert response["rejected_at"].endswith("Z")

    def test_invalid_value_returns_error(self) -> None:
        """Non-finite value triggers error response with INVALID_VALUE code."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(INVALID_VALUE_NAN_PAYLOAD)
                response = json.loads(ws.receive_text())

                assert response["error_code"] == "INVALID_VALUE"
                assert "message" in response
                assert response["sensor_id"] == "turbine-001-temp"

    def test_empty_sensor_id_returns_error(self) -> None:
        """Empty sensor_id triggers error response with INVALID_SENSOR_ID code."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(EMPTY_SENSOR_ID_PAYLOAD)
                response = json.loads(ws.receive_text())

                assert response["error_code"] == "INVALID_SENSOR_ID"
                assert "message" in response

    def test_whitespace_measurement_type_returns_error(self) -> None:
        """Whitespace-only measurement_type triggers error response."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(WHITESPACE_MEASUREMENT_TYPE_PAYLOAD)
                response = json.loads(ws.receive_text())

                assert response["error_code"] == "INVALID_MEASUREMENT_TYPE"
                assert "message" in response

    def test_missing_required_field_returns_error(self) -> None:
        """Missing required fields trigger error response with MISSING_FIELD code."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(MISSING_FIELD_PAYLOAD)
                response = json.loads(ws.receive_text())

                assert response["error_code"] == "MISSING_FIELD"
                assert "message" in response

    def test_invalid_json_returns_error(self) -> None:
        """Non-JSON payload triggers error response with INVALID_JSON code."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(INVALID_JSON_PAYLOAD)
                response = json.loads(ws.receive_text())

                assert response["error_code"] == "INVALID_JSON"
                assert "message" in response
                # sensor_id should be None since JSON couldn't be parsed
                assert response["sensor_id"] is None

    def test_valid_payload_no_error_response(self) -> None:
        """Valid payloads should not produce any error response."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(VALID_PAYLOAD)
                # For a valid payload, no error is sent back.
                # Send another invalid one to confirm the connection is still alive.
                ws.send_text(INVALID_JSON_PAYLOAD)
                response = json.loads(ws.receive_text())
                assert response["error_code"] == "INVALID_JSON"


# ---------------------------------------------------------------------------
# Error response format tests
# ---------------------------------------------------------------------------


class TestErrorResponseFormat:
    """Tests that error responses contain all required fields in correct format."""

    def test_error_response_has_all_required_fields(self) -> None:
        """Error response must contain error_code, message, sensor_id, rejected_at."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(INVALID_TIMESTAMP_PAYLOAD)
                response = json.loads(ws.receive_text())

                # All four fields must be present
                assert "error_code" in response
                assert "message" in response
                assert "sensor_id" in response
                assert "rejected_at" in response

    def test_rejected_at_is_utc_iso8601(self) -> None:
        """rejected_at field must be in ISO 8601 UTC format ending with Z."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(INVALID_TIMESTAMP_PAYLOAD)
                response = json.loads(ws.receive_text())

                rejected_at = response["rejected_at"]
                assert rejected_at.endswith("Z")
                # Should be parseable as ISO 8601
                from datetime import datetime
                dt = datetime.fromisoformat(rejected_at.replace("Z", "+00:00"))
                assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Connection isolation tests (Requirement 1.6)
# ---------------------------------------------------------------------------


class TestConnectionIsolation:
    """Tests that validation failure on one connection does not affect others."""

    def test_invalid_event_does_not_close_connection(self) -> None:
        """After sending an invalid event, the connection remains open for more events."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                # Send invalid
                ws.send_text(INVALID_TIMESTAMP_PAYLOAD)
                error_resp = json.loads(ws.receive_text())
                assert error_resp["error_code"] == "INVALID_TIMESTAMP"

                # Connection still alive - send valid payload
                ws.send_text(VALID_PAYLOAD)

                # Send another invalid to confirm connection is still active
                ws.send_text(INVALID_JSON_PAYLOAD)
                error_resp2 = json.loads(ws.receive_text())
                assert error_resp2["error_code"] == "INVALID_JSON"

    def test_multiple_connections_isolated(self) -> None:
        """Invalid events on one connection do not affect other connections."""
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws1:
                with client.websocket_connect("/ws/telemetry") as ws2:
                    # Send invalid on ws1
                    ws1.send_text(INVALID_TIMESTAMP_PAYLOAD)
                    error_resp = json.loads(ws1.receive_text())
                    assert error_resp["error_code"] == "INVALID_TIMESTAMP"

                    # ws2 should still work fine
                    ws2.send_text(VALID_PAYLOAD)

                    # ws2 can also send invalid independently
                    ws2.send_text(INVALID_JSON_PAYLOAD)
                    error_resp2 = json.loads(ws2.receive_text())
                    assert error_resp2["error_code"] == "INVALID_JSON"

                    # Both connections still tracked
                    manager = app.state.connection_manager
                    assert manager.active_count == 2


# ---------------------------------------------------------------------------
# Metrics tracking tests
# ---------------------------------------------------------------------------


class TestRejectionMetrics:
    """Tests that rejection events are properly counted in metrics."""

    def test_rejected_event_increments_counter(self) -> None:
        """Rejected events are counted in the metrics."""
        app = create_app()
        manager = app.state.connection_manager
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(INVALID_TIMESTAMP_PAYLOAD)
                ws.receive_text()  # consume error response

                ws.send_text(INVALID_JSON_PAYLOAD)
                ws.receive_text()  # consume error response

        metrics = manager.get_and_reset_metrics()
        assert metrics["events_rejected"] == 2

    def test_valid_event_not_counted_as_rejected(self) -> None:
        """Valid events should not increment the rejection counter."""
        app = create_app()
        manager = app.state.connection_manager
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                ws.send_text(VALID_PAYLOAD)

        metrics = manager.get_and_reset_metrics()
        assert metrics["events_rejected"] == 0
        assert metrics["events_received"] == 1
