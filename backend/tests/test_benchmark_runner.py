"""Unit tests for LiveBenchmarkRunner and GET /metrics/benchmark endpoint.

Validates the benchmark runner's record/get_metrics behavior including
RMSE, MAE, correction gain, confidence coverage, zero-sample case,
and rolling window behavior. Also validates the benchmark API endpoint
returns 200 with correct response schema.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import math

import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.benchmark import configure_benchmark_services
from digital_twin_engine.benchmarking.benchmark_runner import (
    BenchmarkMetrics,
    LiveBenchmarkRunner,
)


class TestLiveBenchmarkRunnerZeroSamples:
    """Test zero-sample edge case."""

    def test_get_metrics_returns_all_zeros_when_empty(self) -> None:
        runner = LiveBenchmarkRunner()
        metrics = runner.get_metrics()

        assert metrics.raw_rmse == 0.0
        assert metrics.corrected_rmse == 0.0
        assert metrics.raw_mae == 0.0
        assert metrics.corrected_mae == 0.0
        assert metrics.correction_gain_pct == 0.0
        assert metrics.confidence_coverage_pct == 0.0
        assert metrics.sample_count == 0


class TestLiveBenchmarkRunnerSingleSample:
    """Test with a single recorded sample."""

    def test_single_sample_rmse_equals_absolute_error(self) -> None:
        runner = LiveBenchmarkRunner()
        runner.record(
            raw_prediction=120.0,
            corrected_prediction=115.0,
            ground_truth_rul=112.0,
            confidence_lower=108.0,
            confidence_upper=122.0,
        )
        metrics = runner.get_metrics()

        # Raw error: 120 - 112 = 8; RMSE = sqrt(64/1) = 8
        assert metrics.raw_rmse == pytest.approx(8.0)
        # Corrected error: 115 - 112 = 3; RMSE = sqrt(9/1) = 3
        assert metrics.corrected_rmse == pytest.approx(3.0)
        # MAE same as absolute error for single sample
        assert metrics.raw_mae == pytest.approx(8.0)
        assert metrics.corrected_mae == pytest.approx(3.0)
        assert metrics.sample_count == 1

    def test_single_sample_correction_gain(self) -> None:
        runner = LiveBenchmarkRunner()
        runner.record(
            raw_prediction=120.0,
            corrected_prediction=115.0,
            ground_truth_rul=112.0,
            confidence_lower=108.0,
            confidence_upper=122.0,
        )
        metrics = runner.get_metrics()

        # correction_gain = (8 - 3) / 8 * 100 = 62.5
        assert metrics.correction_gain_pct == pytest.approx(62.5)

    def test_single_sample_coverage_hit(self) -> None:
        runner = LiveBenchmarkRunner()
        runner.record(
            raw_prediction=120.0,
            corrected_prediction=115.0,
            ground_truth_rul=112.0,
            confidence_lower=108.0,
            confidence_upper=122.0,
        )
        metrics = runner.get_metrics()

        # 112 is within [108, 122] -> hit -> 100%
        assert metrics.confidence_coverage_pct == pytest.approx(100.0)

    def test_single_sample_coverage_miss(self) -> None:
        runner = LiveBenchmarkRunner()
        runner.record(
            raw_prediction=120.0,
            corrected_prediction=115.0,
            ground_truth_rul=130.0,  # Outside CI [108, 122]
            confidence_lower=108.0,
            confidence_upper=122.0,
        )
        metrics = runner.get_metrics()

        assert metrics.confidence_coverage_pct == pytest.approx(0.0)


class TestLiveBenchmarkRunnerMultipleSamples:
    """Test with multiple samples for aggregate computation."""

    def test_multiple_samples_rmse(self) -> None:
        runner = LiveBenchmarkRunner()
        # Sample 1: raw error = 10, corrected error = 5
        runner.record(120.0, 115.0, 110.0, 100.0, 125.0)
        # Sample 2: raw error = -4, corrected error = -2
        runner.record(106.0, 108.0, 110.0, 100.0, 125.0)

        metrics = runner.get_metrics()

        # Raw RMSE: sqrt((100 + 16) / 2) = sqrt(58) ≈ 7.616
        assert metrics.raw_rmse == pytest.approx(math.sqrt(58.0))
        # Corrected RMSE: sqrt((25 + 4) / 2) = sqrt(14.5) ≈ 3.808
        assert metrics.corrected_rmse == pytest.approx(math.sqrt(14.5))
        assert metrics.sample_count == 2

    def test_multiple_samples_mae(self) -> None:
        runner = LiveBenchmarkRunner()
        runner.record(120.0, 115.0, 110.0, 100.0, 125.0)
        runner.record(106.0, 108.0, 110.0, 100.0, 125.0)

        metrics = runner.get_metrics()

        # Raw MAE: (10 + 4) / 2 = 7.0
        assert metrics.raw_mae == pytest.approx(7.0)
        # Corrected MAE: (5 + 2) / 2 = 3.5
        assert metrics.corrected_mae == pytest.approx(3.5)

    def test_coverage_partial(self) -> None:
        runner = LiveBenchmarkRunner()
        # Hit: 110 in [100, 125]
        runner.record(120.0, 115.0, 110.0, 100.0, 125.0)
        # Miss: 130 not in [100, 125]
        runner.record(120.0, 115.0, 130.0, 100.0, 125.0)

        metrics = runner.get_metrics()

        # 1 hit out of 2 = 50%
        assert metrics.confidence_coverage_pct == pytest.approx(50.0)


class TestLiveBenchmarkRunnerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_perfect_prediction_zero_rmse(self) -> None:
        runner = LiveBenchmarkRunner()
        runner.record(100.0, 100.0, 100.0, 95.0, 105.0)

        metrics = runner.get_metrics()

        assert metrics.raw_rmse == pytest.approx(0.0)
        assert metrics.corrected_rmse == pytest.approx(0.0)
        assert metrics.correction_gain_pct == pytest.approx(0.0)

    def test_correction_gain_zero_when_raw_rmse_zero(self) -> None:
        runner = LiveBenchmarkRunner()
        # Raw prediction exactly matches truth
        runner.record(100.0, 105.0, 100.0, 95.0, 110.0)

        metrics = runner.get_metrics()

        # raw_rmse = 0, so correction_gain_pct should be 0 (not division by zero)
        assert metrics.raw_rmse == pytest.approx(0.0)
        assert metrics.correction_gain_pct == pytest.approx(0.0)

    def test_negative_correction_gain_when_corrected_worse(self) -> None:
        runner = LiveBenchmarkRunner()
        # Corrected is worse: corrected error = 20, raw error = 5
        runner.record(105.0, 120.0, 100.0, 95.0, 125.0)

        metrics = runner.get_metrics()

        # correction_gain = (5 - 20) / 5 * 100 = -300
        assert metrics.correction_gain_pct == pytest.approx(-300.0)

    def test_coverage_boundary_inclusive(self) -> None:
        runner = LiveBenchmarkRunner()
        # Exactly at lower bound
        runner.record(120.0, 115.0, 100.0, 100.0, 125.0)
        # Exactly at upper bound
        runner.record(120.0, 115.0, 125.0, 100.0, 125.0)

        metrics = runner.get_metrics()

        # Both should be hits (inclusive bounds)
        assert metrics.confidence_coverage_pct == pytest.approx(100.0)

    def test_rolling_window_caps_at_max_samples(self) -> None:
        runner = LiveBenchmarkRunner()

        # Record more than MAX_SAMPLES
        for i in range(5010):
            runner.record(110.0, 105.0, 100.0, 95.0, 115.0)

        metrics = runner.get_metrics()

        # Should cap at MAX_SAMPLES
        assert metrics.sample_count == 5000

    def test_rolling_window_evicts_old_samples(self) -> None:
        runner = LiveBenchmarkRunner()

        # Fill with samples where coverage misses (truth outside CI)
        for _ in range(5000):
            runner.record(110.0, 105.0, 200.0, 95.0, 115.0)

        # Now record samples where coverage hits
        for _ in range(5000):
            runner.record(110.0, 105.0, 100.0, 95.0, 115.0)

        metrics = runner.get_metrics()

        # All old miss samples should be evicted; only hits remain
        assert metrics.confidence_coverage_pct == pytest.approx(100.0)


class TestBenchmarkEndpoint:
    """Tests for GET /metrics/benchmark API endpoint.

    Validates: Requirements 3.4
    """

    @pytest.mark.asyncio
    async def test_endpoint_returns_200_with_zeros_when_no_runner(self) -> None:
        """Returns 200 with all-zero metrics when no benchmark runner configured."""
        configure_benchmark_services(benchmark_runner=None)
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics/benchmark")
            assert resp.status_code == 200
            data = resp.json()
            assert data["raw_rmse"] == 0.0
            assert data["corrected_rmse"] == 0.0
            assert data["raw_mae"] == 0.0
            assert data["corrected_mae"] == 0.0
            assert data["correction_gain_pct"] == 0.0
            assert data["confidence_coverage_pct"] == 0.0
            assert data["sample_count"] == 0

    @pytest.mark.asyncio
    async def test_endpoint_returns_200_with_zeros_when_runner_empty(self) -> None:
        """Returns 200 with all-zero metrics when runner has no recorded samples."""
        runner = LiveBenchmarkRunner()
        configure_benchmark_services(benchmark_runner=runner)
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics/benchmark")
            assert resp.status_code == 200
            data = resp.json()
            assert data["raw_rmse"] == 0.0
            assert data["corrected_rmse"] == 0.0
            assert data["sample_count"] == 0

    @pytest.mark.asyncio
    async def test_endpoint_returns_200_with_valid_metrics(self) -> None:
        """Returns 200 with computed metrics when samples have been recorded."""
        runner = LiveBenchmarkRunner()
        runner.record(
            raw_prediction=120.0,
            corrected_prediction=115.0,
            ground_truth_rul=112.0,
            confidence_lower=108.0,
            confidence_upper=122.0,
        )
        runner.record(
            raw_prediction=106.0,
            corrected_prediction=108.0,
            ground_truth_rul=110.0,
            confidence_lower=100.0,
            confidence_upper=125.0,
        )
        configure_benchmark_services(benchmark_runner=runner)
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics/benchmark")
            assert resp.status_code == 200
            data = resp.json()

            # Verify response has all required fields
            assert "raw_rmse" in data
            assert "corrected_rmse" in data
            assert "raw_mae" in data
            assert "corrected_mae" in data
            assert "correction_gain_pct" in data
            assert "confidence_coverage_pct" in data
            assert "sample_count" in data

            # Verify non-zero values
            assert data["sample_count"] == 2
            assert data["raw_rmse"] > 0
            assert data["corrected_rmse"] > 0

            # Verify correction gain is computed correctly
            expected_gain = (data["raw_rmse"] - data["corrected_rmse"]) / data["raw_rmse"] * 100
            assert data["correction_gain_pct"] == pytest.approx(expected_gain)

    @pytest.mark.asyncio
    async def test_endpoint_response_schema_complete(self) -> None:
        """Response matches BenchmarkMetricsResponse schema with correct types."""
        runner = LiveBenchmarkRunner()
        runner.record(100.0, 95.0, 90.0, 85.0, 105.0)
        configure_benchmark_services(benchmark_runner=runner)
        gateway = APIGateway()
        transport = ASGITransport(app=gateway.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics/benchmark")
            assert resp.status_code == 200
            data = resp.json()

            # All fields are numeric
            assert isinstance(data["raw_rmse"], (int, float))
            assert isinstance(data["corrected_rmse"], (int, float))
            assert isinstance(data["raw_mae"], (int, float))
            assert isinstance(data["corrected_mae"], (int, float))
            assert isinstance(data["correction_gain_pct"], (int, float))
            assert isinstance(data["confidence_coverage_pct"], (int, float))
            assert isinstance(data["sample_count"], int)
