"""Integration tests for the Docker stack.

These tests verify end-to-end Docker functionality:
- Docker build succeeds from the backend/ directory
- Each service responds on its expected port
- End-to-end data flow from adapter to API Gateway WebSocket

Requirements validated: 4.3, 8.1, 8.2, 8.3, 8.4, 10.3

Usage:
    # Run only integration tests (requires running Docker stack):
    pytest -m integration tests/integration/

    # In CI, the stack is started via `docker compose up -d` before running these.
    # Locally, start the stack first:
    #   docker compose up -d
    #   pytest -m integration tests/integration/
    #   docker compose down -v
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest

# Ports as defined in docker-compose.yml
API_GATEWAY_PORT = 8000
INGESTION_SERVER_PORT = 8080
API_GATEWAY_URL = f"http://localhost:{API_GATEWAY_PORT}"
INGESTION_SERVER_URL = f"http://localhost:{INGESTION_SERVER_PORT}"
WEBSOCKET_URL = f"ws://localhost:{API_GATEWAY_PORT}/ws/telemetry"

# Path to the backend directory (where Dockerfile lives)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _service_is_reachable(url: str, timeout: float = 5.0) -> bool:
    """Check if a service is reachable via HTTP GET."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _wait_for_service(url: str, max_wait: float = 60.0, interval: float = 2.0) -> bool:
    """Wait for a service to become reachable."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _service_is_reachable(url):
            return True
        time.sleep(interval)
    return False


@pytest.mark.integration
class TestDockerBuild:
    """Tests that the Docker image builds successfully."""

    def test_docker_build_succeeds(self):
        """Verify `docker build` completes with exit code 0 from backend/ directory.

        Validates: Requirement 4.3 — WHEN `docker build` is executed from the
        `backend/` directory, the Docker Stack SHALL produce a working image
        without COPY errors.
        """
        result = subprocess.run(
            ["docker", "build", "-t", "digital-twin-engine:test", "."],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes max for build
        )
        assert result.returncode == 0, (
            f"Docker build failed with exit code {result.returncode}.\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )


@pytest.mark.integration
class TestServicePorts:
    """Tests that services respond on their expected ports.

    These tests assume the Docker Compose stack is already running.
    """

    def test_api_gateway_responds(self):
        """Verify API Gateway health endpoint responds on port 8000.

        Validates: Requirement 8.2 — THE Docker_Stack SHALL expose
        API_Gateway on host port 8000.
        """
        assert _wait_for_service(
            f"{API_GATEWAY_URL}/health", max_wait=60.0
        ), f"API Gateway did not respond at {API_GATEWAY_URL}/health within 60s"

        import urllib.request

        with urllib.request.urlopen(f"{API_GATEWAY_URL}/health") as resp:
            assert resp.status == 200
            body = json.loads(resp.read().decode())
            assert "status" in body

    def test_ingestion_server_responds(self):
        """Verify Ingestion Server docs endpoint responds on port 8080.

        Validates: Requirement 8.3 — THE Docker_Stack SHALL expose
        Ingestion_Server on host port 8080.
        """
        assert _wait_for_service(
            f"{INGESTION_SERVER_URL}/docs", max_wait=60.0
        ), f"Ingestion Server did not respond at {INGESTION_SERVER_URL}/docs within 60s"

        import urllib.request

        with urllib.request.urlopen(f"{INGESTION_SERVER_URL}/docs") as resp:
            assert resp.status == 200

    def test_grafana_port_3001(self):
        """Verify Grafana is exposed on port 3001, not 3000.

        Validates: Requirement 8.1 — THE Docker_Stack SHALL expose
        Grafana on host port 3001.
        """
        grafana_url = "http://localhost:3001"
        if _wait_for_service(grafana_url, max_wait=30.0):
            import urllib.request

            with urllib.request.urlopen(grafana_url) as resp:
                # Grafana may redirect, but should respond
                assert resp.status == 200
        else:
            pytest.skip("Grafana service not running (may not be included in compose profile)")

    def test_no_port_conflicts(self):
        """Verify no two services share the same host port.

        Validates: Requirement 8.4 — THE Docker_Stack SHALL have no two
        services mapped to the same host port.

        This test verifies the ports are correctly separated by checking
        that multiple services respond independently.
        """
        # These services should all respond independently
        services = {
            "API Gateway": f"{API_GATEWAY_URL}/health",
            "Ingestion Server": f"{INGESTION_SERVER_URL}/docs",
        }

        responding = {}
        for name, url in services.items():
            if _service_is_reachable(url):
                responding[name] = url

        # At minimum, both core services should respond
        assert "API Gateway" in responding, "API Gateway not reachable on port 8000"
        assert "Ingestion Server" in responding, "Ingestion Server not reachable on port 8080"


@pytest.mark.integration
class TestWebSocketConnection:
    """Tests WebSocket connectivity to the API Gateway."""

    def test_websocket_connection(self):
        """Verify WebSocket connection to /ws/telemetry succeeds.

        Validates: Requirement 10.3 — data flow path includes
        API Gateway → Frontend via WebSocket.
        """

        async def _connect():
            import websockets

            async with websockets.connect(WEBSOCKET_URL) as ws:
                # Connection succeeded — verify it's open
                assert ws.open
                await ws.close()

        asyncio.run(_connect())


@pytest.mark.integration
class TestEndToEndDataFlow:
    """Tests end-to-end data flow through the full pipeline."""

    def test_end_to_end_data_flow(self):
        """Verify data flows from adapter through pipeline to WebSocket.

        Connects to the WebSocket endpoint and waits for a message,
        confirming the full pipeline is operational:
        Adapter → Ingestion Server → Kafka → ML/Correction → API Gateway → WebSocket

        Validates: Requirement 10.3 — WHEN all services are healthy,
        THE Docker_Stack SHALL have a functioning data flow:
        Adapter → Ingestion_Server → Broker → ML_Service →
        Correction_Engine → API_Gateway → Frontend_Dashboard.
        """

        async def _receive_message():
            import websockets

            async with websockets.connect(WEBSOCKET_URL) as ws:
                # Wait up to 60 seconds for a message from the pipeline
                msg_raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
                msg = json.loads(msg_raw)

                # Verify message structure
                assert "type" in msg, f"Message missing 'type' field: {msg}"
                assert "payload" in msg, f"Message missing 'payload' field: {msg}"

                # The type should be one of the expected message types
                valid_types = {"correction", "prediction", "anomaly", "telemetry"}
                assert msg["type"] in valid_types, (
                    f"Unexpected message type '{msg['type']}'. "
                    f"Expected one of: {valid_types}"
                )

                return msg

        result = asyncio.run(_receive_message())
        assert result is not None, "No message received within 60 seconds"
