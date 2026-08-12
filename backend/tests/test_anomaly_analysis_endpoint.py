"""Unit tests for the GET /api/engines/{engine_id}/anomaly-analysis endpoint.

Tests:
- Returns 404 for non-existent engine IDs (Requirement 1.4)
- Returns anomaly_active=false when no anomaly recorded (Requirement 1.3)
- Returns ranked sensor contributions with active anomaly (Requirement 1.2)
- Contributions sorted by sigma_deviation descending (Requirement 1.1)

Validates: Requirements 1.2, 1.3, 1.4
"""

from __future__ import annotations

from typing import Dict, Optional

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.engines import configure_engine_services
from digital_twin_engine.alerting.root_cause import RootCauseAnalyzer
from digital_twin_engine.prognostics.models import EngineRULState


class MockRULPredictor:
    """Mock RUL Predictor that recognizes specific engines."""

    def __init__(self, known_engines: set[int]) -> None:
        self._known = known_engines

    def get_engine_state(self, engine_id: int) -> EngineRULState:
        if engine_id in self._known:
            return EngineRULState(
                engine_id=engine_id,
                current_rul=100,
                cycle_count=50,
                baseline_established=True,
                last_update_cycle=50,
                is_incomplete=False,
            )
        return EngineRULState(
            engine_id=engine_id,
            current_rul=125,
            cycle_count=0,
            baseline_established=False,
            last_update_cycle=0,
            is_incomplete=False,
        )


@pytest.fixture
def mock_rul():
    return MockRULPredictor(known_engines={1, 2})


@pytest.fixture
def analyzer_with_history():
    """RootCauseAnalyzer with innovation history for engine 1."""
    analyzer = RootCauseAnalyzer()
    # Record varying history so std != 0
    for i in range(20):
        analyzer.record_innovation(1, "hpc_outlet_temp_total", 1.0 + i * 0.1)
        analyzer.record_innovation(1, "physical_core_speed", 0.5 + i * 0.05)
    return analyzer


@pytest.fixture
def analyzer_with_anomaly(analyzer_with_history):
    """Analyzer that has had an anomaly analyzed for engine 1."""
    analyzer_with_history.analyze_anomaly(
        1,
        {"hpc_outlet_temp_total": 10.0, "physical_core_speed": 2.0},
    )
    return analyzer_with_history


class TestAnomalyAnalysisEndpoint:
    """Tests for GET /api/engines/{engine_id}/anomaly-analysis."""

    @pytest.mark.asyncio
    async def test_404_for_unknown_engine(self, mock_rul):
        """Returns 404 with descriptive message for non-existent engine."""
        configure_engine_services(
            rul_predictor=mock_rul,
            root_cause_analyzer=RootCauseAnalyzer(),
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/999/anomaly-analysis")
            assert resp.status_code == 404
            data = resp.json()
            assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_no_anomaly_returns_inactive(self, mock_rul):
        """Returns anomaly_active=false when no anomaly recorded for engine."""
        configure_engine_services(
            rul_predictor=mock_rul,
            root_cause_analyzer=RootCauseAnalyzer(),
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/anomaly-analysis")
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_id"] == 1
            assert data["anomaly_active"] is False
            assert data["contributions"] == []
            assert data["timestamp"] is None

    @pytest.mark.asyncio
    async def test_active_anomaly_returns_ranked_contributions(
        self, mock_rul, analyzer_with_anomaly
    ):
        """Returns ranked contributions sorted by sigma_deviation descending."""
        configure_engine_services(
            rul_predictor=mock_rul,
            root_cause_analyzer=analyzer_with_anomaly,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/anomaly-analysis")
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_id"] == 1
            assert data["anomaly_active"] is True
            assert data["timestamp"] is not None
            assert len(data["contributions"]) == 2

            # Verify contributions are sorted by sigma_deviation descending
            sigmas = [c["sigma_deviation"] for c in data["contributions"]]
            assert sigmas == sorted(sigmas, reverse=True)

            # Verify each contribution has required fields
            for contrib in data["contributions"]:
                assert "sensor_name" in contrib
                assert "innovation_magnitude" in contrib
                assert "sigma_deviation" in contrib
                assert contrib["innovation_magnitude"] > 0
                assert contrib["sigma_deviation"] >= 0

    @pytest.mark.asyncio
    async def test_no_analyzer_configured_returns_inactive(self, mock_rul):
        """Returns anomaly_active=false when no RootCauseAnalyzer is configured."""
        configure_engine_services(
            rul_predictor=mock_rul,
            root_cause_analyzer=None,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/engines/1/anomaly-analysis")
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_id"] == 1
            assert data["anomaly_active"] is False

    @pytest.mark.asyncio
    async def test_engine_with_no_anomaly_different_from_unknown(
        self, mock_rul, analyzer_with_anomaly
    ):
        """Engine 2 exists but has no anomaly; should return 200 with inactive."""
        configure_engine_services(
            rul_predictor=mock_rul,
            root_cause_analyzer=analyzer_with_anomaly,
        )
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Engine 2 exists (recognized by mock RUL) but no anomaly
            resp = await client.get("/api/engines/2/anomaly-analysis")
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_id"] == 2
            assert data["anomaly_active"] is False
