"""Unit tests for ThroughputMonitor.

Tests record_event/record_prediction/record_correction rates,
rolling window behavior, and the performance endpoint.

Requirements: 4.3, 4.4, 4.6
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.benchmarking.throughput_monitor import (
    ThroughputMetrics,
    ThroughputMonitor,
)
from digital_twin_engine.benchmarking.latency_profiler import LatencyProfiler
from digital_twin_engine.api.benchmark import (
    configure_benchmark_services,
    router,
)


class TestThroughputMonitorEmpty:
    """Test empty state returns zeros."""

    def test_get_metrics_empty_returns_zeros(self) -> None:
        """get_metrics with no recordings returns all zeros."""
        tm = ThroughputMonitor()
        m = tm.get_metrics()
        assert m.events_per_second == 0.0
        assert m.predictions_per_second == 0.0
        assert m.corrections_per_second == 0.0


class TestThroughputMonitorRecording:
    """Test individual record methods and rate computation."""

    def test_record_event_increases_rate(self) -> None:
        """Recording events within the window produces non-zero rate."""
        tm = ThroughputMonitor()
        now = time.time()

        # Simulate 50 events within the window
        with patch("time.time", return_value=now):
            for _ in range(50):
                tm.record_event()

        with patch("time.time", return_value=now):
            m = tm.get_metrics()
        # 50 events / 10.0 seconds window = 5.0 events/sec
        assert m.events_per_second == pytest.approx(5.0)

    def test_record_prediction_increases_rate(self) -> None:
        """Recording predictions within the window produces non-zero rate."""
        tm = ThroughputMonitor()
        now = time.time()

        with patch("time.time", return_value=now):
            for _ in range(30):
                tm.record_prediction()

        with patch("time.time", return_value=now):
            m = tm.get_metrics()
        # 30 / 10.0 = 3.0
        assert m.predictions_per_second == pytest.approx(3.0)

    def test_record_correction_increases_rate(self) -> None:
        """Recording corrections within the window produces non-zero rate."""
        tm = ThroughputMonitor()
        now = time.time()

        with patch("time.time", return_value=now):
            for _ in range(20):
                tm.record_correction()

        with patch("time.time", return_value=now):
            m = tm.get_metrics()
        # 20 / 10.0 = 2.0
        assert m.corrections_per_second == pytest.approx(2.0)

    def test_all_three_rates_independent(self) -> None:
        """Each counter tracks independently."""
        tm = ThroughputMonitor()
        now = time.time()

        with patch("time.time", return_value=now):
            for _ in range(100):
                tm.record_event()
            for _ in range(50):
                tm.record_prediction()
            for _ in range(25):
                tm.record_correction()

        with patch("time.time", return_value=now):
            m = tm.get_metrics()

        assert m.events_per_second == pytest.approx(10.0)
        assert m.predictions_per_second == pytest.approx(5.0)
        assert m.corrections_per_second == pytest.approx(2.5)


class TestThroughputMonitorWindowEviction:
    """Test rolling window evicts old timestamps."""

    def test_old_events_evicted(self) -> None:
        """Events older than WINDOW_SECONDS are evicted."""
        tm = ThroughputMonitor()
        old_time = time.time()

        # Record events at old_time
        with patch("time.time", return_value=old_time):
            for _ in range(100):
                tm.record_event()

        # Query at old_time + 11s (past the 10s window)
        future = old_time + 11.0
        with patch("time.time", return_value=future):
            m = tm.get_metrics()

        # All events should be evicted
        assert m.events_per_second == 0.0

    def test_mixed_old_and_new_events(self) -> None:
        """Only recent events within window are counted."""
        tm = ThroughputMonitor()
        old_time = time.time()

        # Record 50 events at old_time
        with patch("time.time", return_value=old_time):
            for _ in range(50):
                tm.record_event()

        # Record 30 events at old_time + 8s (still within window when queried at +9)
        with patch("time.time", return_value=old_time + 8.0):
            for _ in range(30):
                tm.record_event()

        # Query at old_time + 11s: only the 30 recent events remain
        with patch("time.time", return_value=old_time + 11.0):
            m = tm.get_metrics()

        # 30 events / 10.0 = 3.0
        assert m.events_per_second == pytest.approx(3.0)

    def test_window_seconds_is_10(self) -> None:
        """Confirm WINDOW_SECONDS class constant is 10.0."""
        assert ThroughputMonitor.WINDOW_SECONDS == 10.0


class TestThroughputMetricsDataclass:
    """Test ThroughputMetrics dataclass."""

    def test_dataclass_fields(self) -> None:
        """ThroughputMetrics has expected fields."""
        m = ThroughputMetrics(
            events_per_second=100.0,
            predictions_per_second=80.0,
            corrections_per_second=75.0,
        )
        assert m.events_per_second == 100.0
        assert m.predictions_per_second == 80.0
        assert m.corrections_per_second == 75.0


# ---------------------------------------------------------------------------
# Performance Endpoint Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def performance_app() -> FastAPI:
    """Create a minimal FastAPI app with the benchmark router and real services."""
    app = FastAPI()
    app.include_router(router)

    lp = LatencyProfiler()
    tm = ThroughputMonitor()

    # Record some data so metrics are non-zero
    lp.start_span("s:1")
    lp.end_span("s:1")

    now = time.time()
    with patch("time.time", return_value=now):
        tm.record_event()
        tm.record_prediction()
        tm.record_correction()

    configure_benchmark_services(
        benchmark_runner=None,
        latency_profiler=lp,
        throughput_monitor=tm,
    )
    return app


@pytest.fixture
def unconfigured_app() -> FastAPI:
    """Create app with no profiler/monitor configured (returns zeros)."""
    app = FastAPI()
    app.include_router(router)
    configure_benchmark_services(
        benchmark_runner=None,
        latency_profiler=None,
        throughput_monitor=None,
    )
    return app


@pytest.fixture
async def client(performance_app: FastAPI) -> AsyncClient:
    """Create async test client for performance endpoint."""
    transport = ASGITransport(app=performance_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def unconfigured_client(unconfigured_app: FastAPI) -> AsyncClient:
    """Create async test client with no services configured."""
    transport = ASGITransport(app=unconfigured_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestPerformanceEndpoint:
    """Test GET /metrics/performance endpoint."""

    @pytest.mark.asyncio
    async def test_returns_200(self, client: AsyncClient) -> None:
        """Endpoint returns HTTP 200."""
        response = await client.get("/metrics/performance")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_nested_structure(self, client: AsyncClient) -> None:
        """Response contains nested latency and throughput objects."""
        response = await client.get("/metrics/performance")
        body = response.json()

        assert "latency" in body
        assert "throughput" in body

        # Latency fields
        latency = body["latency"]
        assert "p50_ms" in latency
        assert "p95_ms" in latency
        assert "p99_ms" in latency
        assert "sample_count" in latency

        # Throughput fields
        throughput = body["throughput"]
        assert "events_per_second" in throughput
        assert "predictions_per_second" in throughput
        assert "corrections_per_second" in throughput

    @pytest.mark.asyncio
    async def test_latency_metrics_reflect_data(self, client: AsyncClient) -> None:
        """Latency metrics reflect recorded span data."""
        response = await client.get("/metrics/performance")
        body = response.json()

        latency = body["latency"]
        assert latency["sample_count"] == 1
        assert latency["p50_ms"] >= 0

    @pytest.mark.asyncio
    async def test_unconfigured_returns_zeros(
        self, unconfigured_client: AsyncClient
    ) -> None:
        """When no services configured, returns zeros."""
        response = await unconfigured_client.get("/metrics/performance")
        assert response.status_code == 200
        body = response.json()

        latency = body["latency"]
        assert latency["p50_ms"] == 0.0
        assert latency["p95_ms"] == 0.0
        assert latency["p99_ms"] == 0.0
        assert latency["sample_count"] == 0

        throughput = body["throughput"]
        assert throughput["events_per_second"] == 0.0
        assert throughput["predictions_per_second"] == 0.0
        assert throughput["corrections_per_second"] == 0.0
