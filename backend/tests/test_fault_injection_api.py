"""Unit tests for the Fault Injection REST API endpoints.

Tests the fault injection router endpoints:
- POST /sensors/inject-fault — Create a fault injection (201, 422)
- DELETE /sensors/inject-fault — Clear all active injections (200)
- GET /sensors/active-faults — List active faults (200)

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from digital_twin_engine.api.fault_injection_api import (
    configure_fault_injector,
    router,
)
from digital_twin_engine.simulation.fault_injector import FaultInjector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fault_injector() -> FaultInjector:
    """Create a fresh FaultInjector for each test."""
    return FaultInjector()


@pytest.fixture
def app(fault_injector: FaultInjector) -> FastAPI:
    """Create a minimal FastAPI app with the fault injection router."""
    test_app = FastAPI()
    test_app.include_router(router)
    configure_fault_injector(fault_injector)
    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create an async test client for the fault injection API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: POST /sensors/inject-fault — valid params → 201
# ---------------------------------------------------------------------------


class TestInjectFaultValid:
    """Tests for successful fault injection (201 responses)."""

    @pytest.mark.asyncio
    async def test_inject_spike_returns_201(self, client: AsyncClient) -> None:
        """POST with valid spike params returns 201 with injection_id."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-hpc_outlet_temp_total",
                "fault_type": "spike",
                "magnitude": 50.0,
                "duration_cycles": 10,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert "injection_id" in body
        assert isinstance(body["injection_id"], str)
        assert len(body["injection_id"]) > 0

    @pytest.mark.asyncio
    async def test_inject_drift_returns_201(self, client: AsyncClient) -> None:
        """POST with valid drift params returns 201."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-002-temp",
                "fault_type": "drift",
                "magnitude": 10.0,
                "duration_cycles": 20,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert "injection_id" in body

    @pytest.mark.asyncio
    async def test_inject_dropout_returns_201(self, client: AsyncClient) -> None:
        """POST with valid dropout params returns 201."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-003-pressure",
                "fault_type": "dropout",
                "magnitude": 1.0,
                "duration_cycles": 5,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert "injection_id" in body

    @pytest.mark.asyncio
    async def test_inject_noise_returns_201(self, client: AsyncClient) -> None:
        """POST with valid noise params returns 201."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-vibration",
                "fault_type": "noise",
                "magnitude": 5.0,
                "duration_cycles": 15,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert "injection_id" in body


# ---------------------------------------------------------------------------
# Tests: POST /sensors/inject-fault — invalid fault_type → 422
# ---------------------------------------------------------------------------


class TestInjectFaultInvalidType:
    """Tests for invalid fault_type (422 responses)."""

    @pytest.mark.asyncio
    async def test_invalid_fault_type_returns_422(self, client: AsyncClient) -> None:
        """POST with invalid fault_type returns 422."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "invalid_type",
                "magnitude": 10.0,
                "duration_cycles": 5,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_fault_type_returns_422(self, client: AsyncClient) -> None:
        """POST with empty fault_type returns 422."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "",
                "magnitude": 10.0,
                "duration_cycles": 5,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: POST /sensors/inject-fault — magnitude <= 0 → 422
# ---------------------------------------------------------------------------


class TestInjectFaultInvalidMagnitude:
    """Tests for invalid magnitude (422 responses)."""

    @pytest.mark.asyncio
    async def test_magnitude_zero_returns_422(self, client: AsyncClient) -> None:
        """POST with magnitude == 0 returns 422."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "spike",
                "magnitude": 0,
                "duration_cycles": 10,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_magnitude_negative_returns_422(self, client: AsyncClient) -> None:
        """POST with magnitude < 0 returns 422."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "spike",
                "magnitude": -5.0,
                "duration_cycles": 10,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: POST /sensors/inject-fault — duration_cycles <= 0 → 422
# ---------------------------------------------------------------------------


class TestInjectFaultInvalidDuration:
    """Tests for invalid duration_cycles (422 responses)."""

    @pytest.mark.asyncio
    async def test_duration_zero_returns_422(self, client: AsyncClient) -> None:
        """POST with duration_cycles == 0 returns 422."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "spike",
                "magnitude": 10.0,
                "duration_cycles": 0,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_duration_negative_returns_422(self, client: AsyncClient) -> None:
        """POST with duration_cycles < 0 returns 422."""
        response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "spike",
                "magnitude": 10.0,
                "duration_cycles": -1,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: DELETE /sensors/inject-fault → 200 with confirmation
# ---------------------------------------------------------------------------


class TestClearAllFaults:
    """Tests for clearing all faults (200 response)."""

    @pytest.mark.asyncio
    async def test_clear_returns_200_with_message(self, client: AsyncClient) -> None:
        """DELETE returns 200 with confirmation message."""
        response = await client.delete("/sensors/inject-fault")
        assert response.status_code == 200
        body = response.json()
        assert "message" in body
        assert isinstance(body["message"], str)
        assert len(body["message"]) > 0

    @pytest.mark.asyncio
    async def test_clear_removes_active_faults(self, client: AsyncClient) -> None:
        """DELETE removes all previously injected faults."""
        # Inject a fault first
        await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "spike",
                "magnitude": 50.0,
                "duration_cycles": 100,
            },
        )

        # Verify it exists
        response = await client.get("/sensors/active-faults")
        assert response.status_code == 200
        assert len(response.json()) == 1

        # Clear all
        response = await client.delete("/sensors/inject-fault")
        assert response.status_code == 200

        # Verify no faults remain
        response = await client.get("/sensors/active-faults")
        assert response.status_code == 200
        assert len(response.json()) == 0


# ---------------------------------------------------------------------------
# Tests: GET /sensors/active-faults → 200 with array
# ---------------------------------------------------------------------------


class TestGetActiveFaults:
    """Tests for listing active faults (200 response)."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_200(self, client: AsyncClient) -> None:
        """GET with no active faults returns 200 with empty array."""
        response = await client.get("/sensors/active-faults")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 0

    @pytest.mark.asyncio
    async def test_returns_injected_faults(self, client: AsyncClient) -> None:
        """GET returns list of active faults after injection."""
        # Inject a fault
        inject_response = await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-hpc_outlet_temp_total",
                "fault_type": "spike",
                "magnitude": 50.0,
                "duration_cycles": 10,
            },
        )
        injection_id = inject_response.json()["injection_id"]

        # Get active faults
        response = await client.get("/sensors/active-faults")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1

        fault = body[0]
        assert fault["injection_id"] == injection_id
        assert fault["sensor_id"] == "engine-001-hpc_outlet_temp_total"
        assert fault["fault_type"] == "spike"
        assert fault["magnitude"] == 50.0
        assert fault["duration_cycles"] == 10
        assert fault["remaining_cycles"] == 10

    @pytest.mark.asyncio
    async def test_returns_multiple_faults(self, client: AsyncClient) -> None:
        """GET returns all active faults when multiple are injected."""
        # Inject two faults
        await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-001-temp",
                "fault_type": "spike",
                "magnitude": 50.0,
                "duration_cycles": 10,
            },
        )
        await client.post(
            "/sensors/inject-fault",
            json={
                "sensor_id": "engine-002-pressure",
                "fault_type": "noise",
                "magnitude": 5.0,
                "duration_cycles": 20,
            },
        )

        response = await client.get("/sensors/active-faults")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 2
