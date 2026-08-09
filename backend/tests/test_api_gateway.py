"""Unit tests for the API Gateway REST endpoints.

Tests the FastAPI application endpoints:
- GET /sensors/{sensor_id}/state/current
- GET /sensors/{sensor_id}/state/history
- GET /sensors/{sensor_id}/state/predicted

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.10
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.state_cache import CachedState, StateCache
from digital_twin_engine.shared.models import Prediction, TelemetryEvent
from digital_twin_engine.tsdb.writer import InMemoryTSDBBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_cache() -> StateCache:
    """Create a state cache with a known sensor."""
    cache = StateCache()
    return cache


@pytest.fixture
def tsdb_backend() -> InMemoryTSDBBackend:
    """Create an in-memory TSDB backend."""
    return InMemoryTSDBBackend()


@pytest.fixture
def gateway(state_cache: StateCache, tsdb_backend: InMemoryTSDBBackend) -> APIGateway:
    """Create an API Gateway instance for testing."""
    return APIGateway(tsdb_backend=tsdb_backend, state_cache=state_cache)


@pytest.fixture
async def client(gateway: APIGateway) -> AsyncClient:
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: GET /sensors/{sensor_id}/state/current
# ---------------------------------------------------------------------------


class TestCurrentState:
    """Tests for the current state endpoint."""

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_sensor(self, client: AsyncClient) -> None:
        """Unknown sensor_id returns HTTP 404."""
        response = await client.get("/sensors/unknown-sensor/state/current")
        assert response.status_code == 404
        body = response.json()
        assert body["error_code"] == "SENSOR_NOT_FOUND"
        assert "unknown-sensor" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_current_state(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Known sensor with cached state returns HTTP 200 with correct data."""
        ts = datetime(2024, 1, 15, 10, 30, 5, 500000, tzinfo=timezone.utc)
        state = CachedState(
            sensor_id="turbine-001-temp",
            timestamp=ts,
            state_vector=[342.3],
            ensemble_spread=0.45,
            anomaly_flag=False,
        )
        gateway.state_cache.update(state)

        response = await client.get("/sensors/turbine-001-temp/state/current")
        assert response.status_code == 200
        body = response.json()
        assert body["sensor_id"] == "turbine-001-temp"
        assert body["timestamp"] == "2024-01-15T10:30:05.500000Z"
        assert body["state_vector"] == [342.3]
        assert body["ensemble_spread"] == 0.45
        assert body["anomaly_flag"] is False

    @pytest.mark.asyncio
    async def test_returns_404_for_known_sensor_no_state(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Known sensor with no corrected state yet returns HTTP 404."""
        gateway.state_cache.register_sensor("turbine-002-temp")
        response = await client.get("/sensors/turbine-002-temp/state/current")
        assert response.status_code == 404
        body = response.json()
        assert body["error_code"] == "NO_STATE_AVAILABLE"


# ---------------------------------------------------------------------------
# Tests: GET /sensors/{sensor_id}/state/history
# ---------------------------------------------------------------------------


class TestHistoryState:
    """Tests for the history endpoint."""

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_sensor(self, client: AsyncClient) -> None:
        """Unknown sensor_id returns HTTP 404."""
        response = await client.get(
            "/sensors/unknown-sensor/state/history",
            params={"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"},
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error_code"] == "SENSOR_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_returns_400_missing_start(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Missing start parameter returns HTTP 400."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={"end": "2024-01-02T00:00:00Z"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "start" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_missing_start_unknown_sensor(
        self, client: AsyncClient
    ) -> None:
        """Missing start parameter returns HTTP 400 even for unknown sensor.

        Validates: Requirements 7.8
        """
        response = await client.get(
            "/sensors/nonexistent-sensor/state/history",
            params={"end": "2024-01-02T00:00:00Z"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "start" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_missing_end(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Missing end parameter returns HTTP 400."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={"start": "2024-01-01T00:00:00Z"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "end" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_missing_end_unknown_sensor(
        self, client: AsyncClient
    ) -> None:
        """Missing end parameter returns HTTP 400 even for unknown sensor.

        Validates: Requirements 7.8
        """
        response = await client.get(
            "/sensors/nonexistent-sensor/state/history",
            params={"start": "2024-01-01T00:00:00Z"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "end" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_invalid_start_format(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Invalid start timestamp format returns HTTP 400."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={"start": "not-a-date", "end": "2024-01-02T00:00:00Z"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "start" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_invalid_end_format(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Invalid end timestamp format returns HTTP 400.

        Validates: Requirements 7.8
        """
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={"start": "2024-01-01T00:00:00Z", "end": "not-a-date"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "end" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_invalid_start_format_unknown_sensor(
        self, client: AsyncClient
    ) -> None:
        """Invalid start timestamp returns HTTP 400 even for unknown sensor.

        Validates: Requirements 7.8
        """
        response = await client.get(
            "/sensors/nonexistent-sensor/state/history",
            params={"start": "not-a-date", "end": "2024-01-02T00:00:00Z"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "start" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_start_after_end(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """start > end returns HTTP 400."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-03T00:00:00Z",
                "end": "2024-01-01T00:00:00Z",
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "start" in body["message"].lower() or "after" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_400_start_after_end_unknown_sensor(
        self, client: AsyncClient
    ) -> None:
        """start > end returns HTTP 400 even for unknown sensor.

        Validates: Requirements 7.6
        """
        response = await client.get(
            "/sensors/nonexistent-sensor/state/history",
            params={
                "start": "2024-01-03T00:00:00Z",
                "end": "2024-01-01T00:00:00Z",
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "start" in body["message"].lower() or "after" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_400_limit_less_than_1(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """limit < 1 returns HTTP 400 with error_code and message."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "limit": 0,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "limit" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_limit_greater_than_1000(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """limit > 1000 returns HTTP 400 with error_code and message."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "limit": 1001,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "limit" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_negative_offset(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """offset < 0 returns HTTP 400 with error_code and message."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "offset": -1,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "offset" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_400_invalid_pagination_unknown_sensor(
        self, client: AsyncClient
    ) -> None:
        """Invalid pagination returns HTTP 400 even for unknown sensor.

        Validates: Requirements 7.9
        """
        response = await client.get(
            "/sensors/nonexistent-sensor/state/history",
            params={
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "limit": 0,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "limit" in body["message"]

        response = await client.get(
            "/sensors/nonexistent-sensor/state/history",
            params={
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "offset": -5,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "offset" in body["message"]

    @pytest.mark.asyncio
    async def test_returns_200_empty_results_no_data_in_range(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Known sensor with no data in time range returns HTTP 200 with empty results."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sensor_id"] == "sensor-a"
        assert body["results"] == []
        assert body["pagination"]["total_count"] == 0
        assert body["pagination"]["offset"] == 0
        assert body["pagination"]["limit"] == 100

    @pytest.mark.asyncio
    async def test_returns_paginated_results(
        self, client: AsyncClient, gateway: APIGateway, tsdb_backend: InMemoryTSDBBackend
    ) -> None:
        """History endpoint returns paginated results from TSDB."""
        gateway.state_cache.register_sensor("sensor-a")

        # Insert test data into TSDB
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = []
        for i in range(5):
            event = TelemetryEvent(
                timestamp=base_time + timedelta(minutes=i),
                sensor_id="sensor-a",
                measurement_type="temperature",
                value=20.0 + i,
            )
            events.append(event)

        await tsdb_backend.write_events(events)

        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T10:10:00Z",
                "limit": 3,
                "offset": 0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sensor_id"] == "sensor-a"
        assert len(body["results"]) == 3
        assert body["pagination"]["total_count"] == 5
        assert body["pagination"]["offset"] == 0
        assert body["pagination"]["limit"] == 3

    @pytest.mark.asyncio
    async def test_pagination_offset(
        self, client: AsyncClient, gateway: APIGateway, tsdb_backend: InMemoryTSDBBackend
    ) -> None:
        """History endpoint respects offset parameter."""
        gateway.state_cache.register_sensor("sensor-a")

        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = []
        for i in range(5):
            event = TelemetryEvent(
                timestamp=base_time + timedelta(minutes=i),
                sensor_id="sensor-a",
                measurement_type="temperature",
                value=20.0 + i,
            )
            events.append(event)

        await tsdb_backend.write_events(events)

        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T10:10:00Z",
                "limit": 2,
                "offset": 3,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 2
        assert body["pagination"]["total_count"] == 5
        assert body["pagination"]["offset"] == 3

    @pytest.mark.asyncio
    async def test_default_pagination(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Default pagination values are limit=100 and offset=0."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get(
            "/sensors/sensor-a/state/history",
            params={
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T10:10:00Z",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pagination"]["limit"] == 100
        assert body["pagination"]["offset"] == 0


# ---------------------------------------------------------------------------
# Tests: GET /sensors/{sensor_id}/state/predicted
# ---------------------------------------------------------------------------


class TestPredictedState:
    """Tests for the predicted state endpoint."""

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_sensor(self, client: AsyncClient) -> None:
        """Unknown sensor_id returns HTTP 404."""
        response = await client.get("/sensors/unknown-sensor/state/predicted")
        assert response.status_code == 404
        body = response.json()
        assert body["error_code"] == "SENSOR_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_returns_empty_predictions(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Known sensor with no predictions returns empty list."""
        gateway.state_cache.register_sensor("sensor-a")
        response = await client.get("/sensors/sensor-a/state/predicted")
        assert response.status_code == 200
        body = response.json()
        assert body["sensor_id"] == "sensor-a"
        assert body["predictions"] == []

    @pytest.mark.asyncio
    async def test_returns_predictions(
        self, client: AsyncClient, gateway: APIGateway
    ) -> None:
        """Known sensor with cached predictions returns them."""
        gateway.state_cache.register_sensor("sensor-a")

        pred = Prediction(
            sensor_id="sensor-a",
            prediction_timestamp=datetime(2024, 1, 15, 10, 30, 5, tzinfo=timezone.utc),
            prediction_horizon_seconds=60.0,
            state_vector=[342.5, 343.1, 343.8],
            model_used="ensemble",
            ensemble_weights={"lstm": 0.6, "xgboost": 0.4},
        )
        gateway.predictions_cache["sensor-a"] = [pred]

        response = await client.get("/sensors/sensor-a/state/predicted")
        assert response.status_code == 200
        body = response.json()
        assert body["sensor_id"] == "sensor-a"
        assert len(body["predictions"]) == 1
        assert body["predictions"][0]["state_vector"] == [342.5, 343.1, 343.8]
        assert body["predictions"][0]["model_used"] == "ensemble"
        assert body["predictions"][0]["prediction_horizon_seconds"] == 60.0


# ---------------------------------------------------------------------------
# Tests: StateCache
# ---------------------------------------------------------------------------


class TestStateCache:
    """Tests for the in-memory state cache."""

    def test_update_and_get_current(self) -> None:
        """Cache stores and retrieves the latest state."""
        cache = StateCache()
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        state = CachedState(
            sensor_id="sensor-a",
            timestamp=ts,
            state_vector=[100.0],
            ensemble_spread=0.5,
            anomaly_flag=False,
        )
        cache.update(state)

        result = cache.get_current("sensor-a")
        assert result is not None
        assert result.sensor_id == "sensor-a"
        assert result.state_vector == [100.0]

    def test_update_keeps_newer_state(self) -> None:
        """Cache keeps the more recent state when updated."""
        cache = StateCache()
        older = CachedState(
            sensor_id="sensor-a",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            state_vector=[100.0],
            ensemble_spread=0.5,
            anomaly_flag=False,
        )
        newer = CachedState(
            sensor_id="sensor-a",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            state_vector=[105.0],
            ensemble_spread=0.3,
            anomaly_flag=True,
        )
        cache.update(older)
        cache.update(newer)

        result = cache.get_current("sensor-a")
        assert result is not None
        assert result.state_vector == [105.0]

    def test_update_does_not_replace_newer_with_older(self) -> None:
        """Cache does not overwrite a newer state with an older one."""
        cache = StateCache()
        newer = CachedState(
            sensor_id="sensor-a",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            state_vector=[105.0],
            ensemble_spread=0.3,
            anomaly_flag=True,
        )
        older = CachedState(
            sensor_id="sensor-a",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            state_vector=[100.0],
            ensemble_spread=0.5,
            anomaly_flag=False,
        )
        cache.update(newer)
        cache.update(older)

        result = cache.get_current("sensor-a")
        assert result is not None
        assert result.state_vector == [105.0]

    def test_unknown_sensor_returns_none(self) -> None:
        """get_current returns None for unknown sensor."""
        cache = StateCache()
        assert cache.get_current("nonexistent") is None

    def test_is_known_sensor(self) -> None:
        """is_known_sensor correctly identifies registered sensors."""
        cache = StateCache()
        assert not cache.is_known_sensor("sensor-a")
        cache.register_sensor("sensor-a")
        assert cache.is_known_sensor("sensor-a")

    def test_update_from_message(self) -> None:
        """update_from_message parses broker message and updates cache."""
        import json

        cache = StateCache()
        payload = json.dumps({
            "sensor_id": "sensor-x",
            "correction_timestamp": "2024-01-15T10:30:05.500000Z",
            "corrected_state_vector": [342.3],
            "ensemble_spread": 0.45,
            "anomaly_flag": False,
        }).encode()

        cache.update_from_message("sensor-x", payload)
        result = cache.get_current("sensor-x")
        assert result is not None
        assert result.sensor_id == "sensor-x"
        assert result.state_vector == [342.3]
        assert result.ensemble_spread == 0.45
