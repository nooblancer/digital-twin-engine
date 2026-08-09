"""Unit tests for the /health endpoint.

Tests the health endpoint, component health check logic, and overall
status aggregation.

Validates: Requirements 8.1, 8.2, 8.3
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import create_app
from digital_twin_engine.api.health import (
    COMPONENT_NAMES,
    clear_health_checks,
    compute_overall_status,
    register_health_check,
    unregister_health_check,
)
from digital_twin_engine.shared.models import ComponentStatus


@pytest.fixture(autouse=True)
def _reset_health_checks():
    """Reset health checks before and after each test."""
    clear_health_checks()
    yield
    clear_health_checks()


@pytest.fixture
async def client():
    """Async HTTP client for testing the FastAPI app."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# compute_overall_status unit tests
# ---------------------------------------------------------------------------


class TestComputeOverallStatus:
    """Test the overall status aggregation logic."""

    def test_all_healthy(self):
        statuses = {name: ComponentStatus.HEALTHY for name in COMPONENT_NAMES}
        assert compute_overall_status(statuses) == ComponentStatus.HEALTHY

    def test_all_down(self):
        statuses = {name: ComponentStatus.DOWN for name in COMPONENT_NAMES}
        assert compute_overall_status(statuses) == ComponentStatus.DOWN

    def test_one_degraded_rest_healthy(self):
        statuses = {name: ComponentStatus.HEALTHY for name in COMPONENT_NAMES}
        statuses["tsdb"] = ComponentStatus.DEGRADED
        assert compute_overall_status(statuses) == ComponentStatus.DEGRADED

    def test_one_down_rest_healthy(self):
        statuses = {name: ComponentStatus.HEALTHY for name in COMPONENT_NAMES}
        statuses["ml_service"] = ComponentStatus.DOWN
        assert compute_overall_status(statuses) == ComponentStatus.DEGRADED

    def test_mixed_degraded_and_down(self):
        statuses = {
            "ingestion_server": ComponentStatus.DEGRADED,
            "message_broker": ComponentStatus.DOWN,
            "tsdb": ComponentStatus.HEALTHY,
            "ml_service": ComponentStatus.DOWN,
            "correction_engine": ComponentStatus.DEGRADED,
        }
        assert compute_overall_status(statuses) == ComponentStatus.DEGRADED

    def test_all_degraded(self):
        statuses = {name: ComponentStatus.DEGRADED for name in COMPONENT_NAMES}
        assert compute_overall_status(statuses) == ComponentStatus.DEGRADED

    def test_empty_dict_returns_down(self):
        assert compute_overall_status({}) == ComponentStatus.DOWN


# ---------------------------------------------------------------------------
# Health check registration tests
# ---------------------------------------------------------------------------


class TestHealthCheckRegistration:
    """Test registering and unregistering health checks."""

    def test_register_valid_component(self):
        async def check():
            return ComponentStatus.HEALTHY

        register_health_check("tsdb", check)
        # No error raised

    def test_register_invalid_component_raises(self):
        async def check():
            return ComponentStatus.HEALTHY

        with pytest.raises(ValueError, match="Unknown component"):
            register_health_check("unknown_component", check)

    def test_unregister_existing(self):
        async def check():
            return ComponentStatus.HEALTHY

        register_health_check("tsdb", check)
        unregister_health_check("tsdb")
        # No error, unregistering non-existent is also fine

    def test_unregister_nonexistent_no_error(self):
        unregister_health_check("tsdb")  # Should not raise


# ---------------------------------------------------------------------------
# Health endpoint integration tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Test the GET /health endpoint."""

    async def test_all_components_healthy(self, client):
        """All components healthy → overall healthy."""
        for name in COMPONENT_NAMES:

            async def healthy_check():
                return ComponentStatus.HEALTHY

            register_health_check(name, healthy_check)

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()

        assert data["overall_status"] == "healthy"
        for name in COMPONENT_NAMES:
            assert data["components"][name] == "healthy"
        assert "timestamp" in data

    async def test_no_checks_registered_all_down(self, client):
        """No health checks registered → all down → overall down."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()

        assert data["overall_status"] == "down"
        for name in COMPONENT_NAMES:
            assert data["components"][name] == "down"

    async def test_timeout_reports_degraded(self, client):
        """Component that times out (>3s) is reported as degraded."""

        async def slow_check():
            await asyncio.sleep(10)  # Will be cancelled by timeout
            return ComponentStatus.HEALTHY

        # Register all as healthy except one that times out
        for name in COMPONENT_NAMES:
            if name == "message_broker":
                register_health_check(name, slow_check)
            else:

                async def healthy():
                    return ComponentStatus.HEALTHY

                register_health_check(name, healthy)

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()

        assert data["components"]["message_broker"] == "degraded"
        assert data["overall_status"] == "degraded"

    async def test_error_reports_degraded(self, client):
        """Component that raises an error is reported as degraded."""

        async def erroring_check():
            raise ConnectionError("Cannot connect to service")

        for name in COMPONENT_NAMES:
            if name == "tsdb":
                register_health_check(name, erroring_check)
            else:

                async def healthy():
                    return ComponentStatus.HEALTHY

                register_health_check(name, healthy)

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()

        assert data["components"]["tsdb"] == "degraded"
        assert data["overall_status"] == "degraded"

    async def test_response_contains_timestamp(self, client):
        """Response includes an ISO 8601 timestamp."""
        response = await client.get("/health")
        data = response.json()

        ts = data["timestamp"]
        # Should be parseable as a datetime
        parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        assert parsed is not None

    async def test_all_components_present_in_response(self, client):
        """All 5 components are always present in the response."""
        response = await client.get("/health")
        data = response.json()

        assert set(data["components"].keys()) == set(COMPONENT_NAMES)

    async def test_component_reports_down_explicitly(self, client):
        """A component can explicitly report itself as down."""

        async def down_check():
            return ComponentStatus.DOWN

        for name in COMPONENT_NAMES:
            register_health_check(name, down_check)

        response = await client.get("/health")
        data = response.json()

        assert data["overall_status"] == "down"
        for name in COMPONENT_NAMES:
            assert data["components"][name] == "down"
