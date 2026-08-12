"""Latency Profiler for tracking ingestion-to-correction latency.

Tracks end-to-end latency from sensor data ingestion to corrected state
emission. Instrument by calling start_span() at ingestion and end_span()
at correction publication. Uses correlation by sensor_id + cycle.

Produces p50/p95/p99 percentile metrics over a rolling window of measurements.

Requirements: 4.1, 4.2, 4.5
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Dict

import numpy as np


@dataclass
class LatencyMetrics:
    """Latency percentile snapshot."""

    p50_ms: float
    p95_ms: float
    p99_ms: float
    sample_count: int


class LatencyProfiler:
    """Tracks ingestion-to-correction latency.

    Instrument by calling start_span() at ingestion and end_span() at
    correction publication. Uses correlation by sensor_id + cycle.

    Correlation key pattern: "{sensor_id}:{cycle}"

    Orphaned pending spans (start_span called but end_span never arrives)
    are evicted after 30 seconds to prevent unbounded memory growth.
    """

    WINDOW_SIZE = 1000  # Last N measurements
    ORPHAN_TIMEOUT_NS = 30_000_000_000  # 30 seconds in nanoseconds

    def __init__(self) -> None:
        self._measurements: deque = deque(maxlen=self.WINDOW_SIZE)
        self._pending: Dict[str, int] = {}  # correlation_key -> start_time_ns

    def start_span(self, correlation_key: str) -> None:
        """Mark ingestion start for a sensor event.

        Records the current high-resolution timestamp associated with the
        given correlation key. Also evicts any orphaned pending spans that
        have exceeded the 30-second timeout.

        Args:
            correlation_key: Unique key like "{sensor_id}:{cycle}"
        """
        now = time.perf_counter_ns()
        self._evict_orphans(now)
        self._pending[correlation_key] = now

    def end_span(self, correlation_key: str) -> None:
        """Mark correction completion, recording the latency.

        Computes elapsed time from the matching start_span call and appends
        the measurement (in milliseconds) to the rolling window.

        Args:
            correlation_key: Must match a prior start_span call.
                If no matching start_span exists, the call is a no-op.
        """
        start = self._pending.pop(correlation_key, None)
        if start is not None:
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            self._measurements.append(elapsed_ms)

    def get_metrics(self) -> LatencyMetrics:
        """Compute percentile metrics over the measurement window.

        Returns p50, p95, p99 latency values in milliseconds. If no
        measurements have been recorded, returns zeros.
        """
        if not self._measurements:
            return LatencyMetrics(p50_ms=0.0, p95_ms=0.0, p99_ms=0.0, sample_count=0)

        arr = np.array(self._measurements)
        return LatencyMetrics(
            p50_ms=float(np.percentile(arr, 50)),
            p95_ms=float(np.percentile(arr, 95)),
            p99_ms=float(np.percentile(arr, 99)),
            sample_count=len(self._measurements),
        )

    def _evict_orphans(self, now_ns: int) -> None:
        """Remove pending spans that have exceeded the orphan timeout.

        Called during start_span to prevent unbounded growth of the
        pending dictionary when end_span is never called (e.g., due to
        dropped messages or processing failures).

        Args:
            now_ns: Current time in nanoseconds (from perf_counter_ns).
        """
        cutoff = now_ns - self.ORPHAN_TIMEOUT_NS
        # Collect keys to remove (avoid modifying dict during iteration)
        orphaned_keys = [
            key for key, start_ns in self._pending.items() if start_ns < cutoff
        ]
        for key in orphaned_keys:
            del self._pending[key]
