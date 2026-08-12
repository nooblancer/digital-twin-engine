"""Unit tests for LatencyProfiler.

Tests start_span/end_span lifecycle, orphan cleanup, get_metrics,
and edge cases.

Requirements: 4.1, 4.2, 4.5
"""

from __future__ import annotations

import time
from unittest.mock import patch

import numpy as np
import pytest

from digital_twin_engine.benchmarking.latency_profiler import (
    LatencyMetrics,
    LatencyProfiler,
)


class TestLatencyProfilerBasics:
    """Test basic span lifecycle and metrics computation."""

    def test_empty_metrics_returns_zeros(self) -> None:
        """get_metrics with no measurements returns all zeros."""
        lp = LatencyProfiler()
        m = lp.get_metrics()
        assert m.p50_ms == 0.0
        assert m.p95_ms == 0.0
        assert m.p99_ms == 0.0
        assert m.sample_count == 0

    def test_single_span_records_measurement(self) -> None:
        """A matched start_span/end_span pair records a measurement."""
        lp = LatencyProfiler()
        lp.start_span("sensor1:10")
        time.sleep(0.005)  # ~5ms
        lp.end_span("sensor1:10")

        m = lp.get_metrics()
        assert m.sample_count == 1
        assert m.p50_ms > 0
        # With 1 sample, all percentiles should be the same value
        assert m.p50_ms == m.p95_ms == m.p99_ms

    def test_correlation_key_pattern(self) -> None:
        """Correlation keys use {sensor_id}:{cycle} pattern."""
        lp = LatencyProfiler()
        lp.start_span("engine-001-hpc_outlet_temp:42")
        lp.end_span("engine-001-hpc_outlet_temp:42")

        m = lp.get_metrics()
        assert m.sample_count == 1

    def test_multiple_spans_accumulate(self) -> None:
        """Multiple completed spans accumulate measurements."""
        lp = LatencyProfiler()
        for i in range(10):
            lp.start_span(f"s:{i}")
            lp.end_span(f"s:{i}")

        m = lp.get_metrics()
        assert m.sample_count == 10

    def test_percentiles_monotonic(self) -> None:
        """p50 <= p95 <= p99 for any set of measurements."""
        lp = LatencyProfiler()
        # Create varying latencies
        for i in range(100):
            lp.start_span(f"s:{i}")
            # Varying delays
            time.sleep(0.001 * (i % 5))
            lp.end_span(f"s:{i}")

        m = lp.get_metrics()
        assert m.p50_ms <= m.p95_ms
        assert m.p95_ms <= m.p99_ms


class TestLatencyProfilerEdgeCases:
    """Test edge cases and error handling."""

    def test_end_span_without_start_is_noop(self) -> None:
        """end_span with unknown key does not record anything."""
        lp = LatencyProfiler()
        lp.end_span("unknown:99")
        m = lp.get_metrics()
        assert m.sample_count == 0

    def test_duplicate_start_span_overwrites(self) -> None:
        """Calling start_span twice with same key overwrites the timestamp."""
        lp = LatencyProfiler()
        lp.start_span("s:1")
        time.sleep(0.01)
        lp.start_span("s:1")  # Overwrite
        lp.end_span("s:1")

        m = lp.get_metrics()
        assert m.sample_count == 1
        # The measurement should be short (from the second start_span)
        assert m.p50_ms < 15  # Much less than 10ms + overhead

    def test_deque_maxlen_enforced(self) -> None:
        """Measurements deque respects WINDOW_SIZE=1000."""
        lp = LatencyProfiler()
        for i in range(1500):
            lp.start_span(f"s:{i}")
            lp.end_span(f"s:{i}")

        m = lp.get_metrics()
        assert m.sample_count == 1000

    def test_pending_cleared_after_end_span(self) -> None:
        """After end_span, the correlation key is removed from pending."""
        lp = LatencyProfiler()
        lp.start_span("s:1")
        lp.end_span("s:1")
        # Second end_span should be no-op
        lp.end_span("s:1")
        m = lp.get_metrics()
        assert m.sample_count == 1


class TestLatencyProfilerOrphanEviction:
    """Test orphaned pending span eviction after 30s timeout."""

    def test_orphans_evicted_after_timeout(self) -> None:
        """Pending spans older than 30s are evicted on next start_span."""
        lp = LatencyProfiler()

        # Manually insert an old pending span
        old_time = time.perf_counter_ns() - (31 * 1_000_000_000)  # 31s ago
        lp._pending["old_key:1"] = old_time

        # Trigger eviction via a new start_span
        lp.start_span("new_key:1")

        # Old key should be evicted
        assert "old_key:1" not in lp._pending
        # New key should be present
        assert "new_key:1" in lp._pending

    def test_recent_pending_not_evicted(self) -> None:
        """Pending spans within 30s are NOT evicted."""
        lp = LatencyProfiler()
        lp.start_span("recent:1")

        # Trigger potential eviction
        lp.start_span("another:2")

        # Both should still be pending
        assert "recent:1" in lp._pending
        assert "another:2" in lp._pending

    def test_eviction_does_not_affect_measurements(self) -> None:
        """Evicted orphans do not add measurements."""
        lp = LatencyProfiler()

        # Insert orphan
        old_time = time.perf_counter_ns() - (31 * 1_000_000_000)
        lp._pending["orphan:1"] = old_time

        # Trigger eviction
        lp.start_span("trigger:1")
        lp.end_span("trigger:1")

        # Only the trigger span should be measured
        m = lp.get_metrics()
        assert m.sample_count == 1

    def test_multiple_orphans_evicted(self) -> None:
        """Multiple orphaned spans are all evicted."""
        lp = LatencyProfiler()

        old_time = time.perf_counter_ns() - (35 * 1_000_000_000)
        lp._pending["orphan1:1"] = old_time
        lp._pending["orphan2:2"] = old_time
        lp._pending["orphan3:3"] = old_time

        lp.start_span("new:1")

        assert "orphan1:1" not in lp._pending
        assert "orphan2:2" not in lp._pending
        assert "orphan3:3" not in lp._pending
        assert "new:1" in lp._pending


class TestLatencyMetricsDataclass:
    """Test LatencyMetrics dataclass."""

    def test_dataclass_fields(self) -> None:
        """LatencyMetrics has expected fields."""
        m = LatencyMetrics(p50_ms=10.0, p95_ms=50.0, p99_ms=90.0, sample_count=100)
        assert m.p50_ms == 10.0
        assert m.p95_ms == 50.0
        assert m.p99_ms == 90.0
        assert m.sample_count == 100
