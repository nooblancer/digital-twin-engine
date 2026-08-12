"""Benchmark and Performance Metrics API endpoints.

Provides endpoints for live benchmarking and performance monitoring:
- GET /metrics/benchmark — Live accuracy metrics (RMSE, MAE, correction gain)
    comparing EnKF-corrected RUL predictions against C-MAPSS ground truth.
- GET /metrics/performance — Latency percentiles and throughput rates for
    the ingestion-to-correction pipeline.

Requirements: 3.4, 4.2, 4.4
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from digital_twin_engine.api.models import (
    BenchmarkMetricsResponse,
    LatencyMetricsModel,
    PerformanceMetricsResponse,
    ThroughputMetricsModel,
)
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("benchmark_api")

router = APIRouter(prefix="/metrics", tags=["benchmark"])

# Service references — set during app startup via configure_benchmark_services()
_benchmark_runner: Any = None
_latency_profiler: Any = None
_throughput_monitor: Any = None


def configure_benchmark_services(
    benchmark_runner: Any = None,
    latency_profiler: Any = None,
    throughput_monitor: Any = None,
) -> None:
    """Configure the service references for the benchmark API endpoints.

    Called during application startup to wire the LiveBenchmarkRunner,
    LatencyProfiler, and ThroughputMonitor instances into the API layer.

    Args:
        benchmark_runner: LiveBenchmarkRunner instance providing get_metrics().
        latency_profiler: LatencyProfiler instance providing get_metrics().
        throughput_monitor: ThroughputMonitor instance providing get_metrics().
    """
    global _benchmark_runner, _latency_profiler, _throughput_monitor
    _benchmark_runner = benchmark_runner
    _latency_profiler = latency_profiler
    _throughput_monitor = throughput_monitor


@router.get(
    "/benchmark",
    response_model=BenchmarkMetricsResponse,
)
async def get_benchmark_metrics() -> Any:
    """Get live benchmark accuracy metrics.

    Returns RMSE and MAE for both raw ML predictions and EnKF-corrected
    predictions, along with the correction gain percentage and confidence
    interval coverage percentage.

    Always returns HTTP 200. Returns zeros when no samples have been
    recorded yet.

    Requirements: 3.4
    """
    if _benchmark_runner is None:
        # No benchmark runner configured — return zeros
        return BenchmarkMetricsResponse(
            raw_rmse=0.0,
            corrected_rmse=0.0,
            raw_mae=0.0,
            corrected_mae=0.0,
            correction_gain_pct=0.0,
            confidence_coverage_pct=0.0,
            sample_count=0,
        )

    metrics = _benchmark_runner.get_metrics()

    return BenchmarkMetricsResponse(
        raw_rmse=metrics.raw_rmse,
        corrected_rmse=metrics.corrected_rmse,
        raw_mae=metrics.raw_mae,
        corrected_mae=metrics.corrected_mae,
        correction_gain_pct=metrics.correction_gain_pct,
        confidence_coverage_pct=metrics.confidence_coverage_pct,
        sample_count=metrics.sample_count,
    )


@router.get(
    "/performance",
    response_model=PerformanceMetricsResponse,
)
async def get_performance_metrics() -> Any:
    """Get latency and throughput performance metrics.

    Returns latency percentiles (p50, p95, p99) from the LatencyProfiler
    and throughput rates (events/sec, predictions/sec, corrections/sec)
    from the ThroughputMonitor.

    Always returns HTTP 200. Returns zeros when no measurements have been
    recorded yet or when profiler/monitor are not configured.

    Requirements: 4.2, 4.4
    """
    # Get latency metrics
    if _latency_profiler is None:
        latency = LatencyMetricsModel(
            p50_ms=0.0, p95_ms=0.0, p99_ms=0.0, sample_count=0
        )
    else:
        latency_data = _latency_profiler.get_metrics()
        latency = LatencyMetricsModel(
            p50_ms=latency_data.p50_ms,
            p95_ms=latency_data.p95_ms,
            p99_ms=latency_data.p99_ms,
            sample_count=latency_data.sample_count,
        )

    # Get throughput metrics
    if _throughput_monitor is None:
        throughput = ThroughputMetricsModel(
            events_per_second=0.0,
            predictions_per_second=0.0,
            corrections_per_second=0.0,
        )
    else:
        throughput_data = _throughput_monitor.get_metrics()
        throughput = ThroughputMetricsModel(
            events_per_second=throughput_data.events_per_second,
            predictions_per_second=throughput_data.predictions_per_second,
            corrections_per_second=throughput_data.corrections_per_second,
        )

    return PerformanceMetricsResponse(
        latency=latency,
        throughput=throughput,
    )
