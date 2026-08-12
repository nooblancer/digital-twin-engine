"""Benchmarking package for digital twin engine performance monitoring.

Provides live accuracy benchmarking against C-MAPSS ground truth,
end-to-end latency profiling, and throughput rate monitoring.
Modules:
    - benchmark_runner: Continuously computes RMSE/MAE of corrected vs raw predictions.
    - latency_profiler: Tracks ingestion-to-correction latency percentiles.
    - throughput_monitor: Tracks events/predictions/corrections per second rates.
"""

__all__: list[str] = [
    "LatencyProfiler",
    "LatencyMetrics",
]

from digital_twin_engine.benchmarking.latency_profiler import (  # noqa: E402
    LatencyMetrics,
    LatencyProfiler,
)
