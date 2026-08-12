"""Property-based tests for v1.4 backend modules.

# Feature: digital-twin-v1.4

Property-based tests using Hypothesis to validate universal invariants
of the v1.4 backend intelligence modules.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Dict, List

import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from digital_twin_engine.alerting.predictive_alerts import (
    AlertSeverity,
    PredictiveAlertSystem,
)
from digital_twin_engine.alerting.root_cause import (
    RootCauseAnalyzer,
)
from digital_twin_engine.benchmarking.benchmark_runner import (
    LiveBenchmarkRunner,
)
from digital_twin_engine.benchmarking.latency_profiler import (
    LatencyProfiler,
)
from digital_twin_engine.benchmarking.throughput_monitor import (
    ThroughputMonitor,
)


# ---------------------------------------------------------------------------
# Property 2: PredictiveAlertSystem — Severity Classification
# ---------------------------------------------------------------------------


class TestSeverityClassification:
    """**Validates: Requirements 2.3, 2.4, 2.5**

    Property 2: Severity Classification

    ∀ health_index: float ∈ [0.0, 1.0]
      health_index > 0.7  → severity = "low"
      0.4 < health_index ≤ 0.7 → severity = "medium"
      health_index ≤ 0.4 → severity = "critical"
    """

    @given(health_index=st.floats(0.0, 1.0))
    @settings(max_examples=500)
    def test_severity_classification(self, health_index: float) -> None:
        """Severity classification matches threshold boundaries for all health values."""
        system = PredictiveAlertSystem(
            monte_carlo_projector=None,
            health_index_aggregator=None,
            degradation_tracker=None,
        )

        result = system._classify_severity(health_index)

        if health_index <= 0.4:
            assert result == AlertSeverity.CRITICAL
        elif health_index <= 0.7:
            assert result == AlertSeverity.MEDIUM
        else:
            assert result == AlertSeverity.LOW


# ---------------------------------------------------------------------------
# Property 3: LiveBenchmarkRunner — Correction Gain Percentage
# ---------------------------------------------------------------------------


class TestCorrectionGainProperty:
    """**Validates: Requirements 3.2**

    Property 3: Correction Gain Percentage

    ∀ raw_errors: List[float], corrected_errors: List[float] (same length, len ≥ 1)
      raw_rmse = sqrt(mean(raw_errors²))
      corrected_rmse = sqrt(mean(corrected_errors²))
      correction_gain_pct = (raw_rmse - corrected_rmse) / raw_rmse * 100

    When raw_rmse = 0, gain is reported as 0.0 (guard against division by zero).
    """

    @given(
        raw_errors=st.lists(
            st.floats(-100, 100, allow_nan=False), min_size=1
        ),
        corrected_errors=st.lists(
            st.floats(-100, 100, allow_nan=False), min_size=1
        ),
    )
    @settings(max_examples=200)
    def test_correction_gain_formula(
        self, raw_errors: list[float], corrected_errors: list[float]
    ) -> None:
        """Correction gain pct matches the formula for all valid error lists.

        We feed raw_errors and corrected_errors of the same length into the
        LiveBenchmarkRunner and verify the reported correction_gain_pct matches
        the expected formula: (raw_rmse - corrected_rmse) / raw_rmse * 100.
        """
        # Both lists must have the same length for paired samples
        n = min(len(raw_errors), len(corrected_errors))
        assume(n >= 1)

        raw_errors = raw_errors[:n]
        corrected_errors = corrected_errors[:n]

        # Feed data into the runner
        runner = LiveBenchmarkRunner()
        for raw_err, corr_err in zip(raw_errors, corrected_errors):
            # We set ground_truth_rul = 0 so that:
            #   raw_prediction - ground_truth = raw_err  => raw_prediction = raw_err
            #   corrected_prediction - ground_truth = corr_err => corrected_prediction = corr_err
            runner.record(
                raw_prediction=raw_err,
                corrected_prediction=corr_err,
                ground_truth_rul=0.0,
                confidence_lower=-1000.0,
                confidence_upper=1000.0,
            )

        metrics = runner.get_metrics()

        # Compute expected values independently
        expected_raw_rmse = math.sqrt(sum(e * e for e in raw_errors) / n)
        expected_corrected_rmse = math.sqrt(
            sum(e * e for e in corrected_errors) / n
        )

        if expected_raw_rmse > 0:
            expected_gain = (
                (expected_raw_rmse - expected_corrected_rmse)
                / expected_raw_rmse
                * 100.0
            )
        else:
            expected_gain = 0.0

        # Verify RMSE values match
        assert metrics.raw_rmse == pytest.approx(
            expected_raw_rmse, rel=1e-9, abs=1e-12
        )
        assert metrics.corrected_rmse == pytest.approx(
            expected_corrected_rmse, rel=1e-9, abs=1e-12
        )

        # Verify correction gain percentage matches the formula
        assert metrics.correction_gain_pct == pytest.approx(
            expected_gain, rel=1e-9, abs=1e-12
        )

        # Verify sample count
        assert metrics.sample_count == n

    @given(
        corrected_errors=st.lists(
            st.floats(-100, 100, allow_nan=False), min_size=1
        ),
    )
    @settings(max_examples=100)
    def test_correction_gain_zero_when_raw_rmse_zero(
        self, corrected_errors: list[float]
    ) -> None:
        """When raw_rmse = 0 (all raw predictions perfect), gain is 0.0.

        This guards against division by zero in the formula.
        """
        runner = LiveBenchmarkRunner()
        for corr_err in corrected_errors:
            # raw_prediction == ground_truth => raw_error = 0
            runner.record(
                raw_prediction=50.0,
                corrected_prediction=50.0 + corr_err,
                ground_truth_rul=50.0,
                confidence_lower=-1000.0,
                confidence_upper=1000.0,
            )

        metrics = runner.get_metrics()

        # raw_rmse should be 0 since all raw errors are 0
        assert metrics.raw_rmse == pytest.approx(0.0, abs=1e-12)
        # correction_gain_pct should be 0.0 (not NaN or infinity)
        assert metrics.correction_gain_pct == pytest.approx(0.0, abs=1e-12)
        assert math.isfinite(metrics.correction_gain_pct)


# ---------------------------------------------------------------------------
# Property 1: RootCauseAnalyzer — Sigma Deviation Computation
# ---------------------------------------------------------------------------


class TestSigmaDeviationComputation:
    """Feature: digital-twin-v1.4, Property 1: Sigma Deviation Computation

    For any non-trivial innovation history (len >= 2) and a current innovation
    magnitude, analyze_anomaly must return contributions where each
    sigma_deviation = innovation_magnitude / std(sensor_history) and the list
    is sorted by sigma_deviation in descending order.

    Division by zero (std=0) returns sigma_deviation=0.

    **Validates: Requirements 1.5**
    """

    @given(
        history=st.lists(st.floats(0.1, 100), min_size=2),
        innovation=st.floats(0.01, 50),
    )
    @settings(max_examples=200)
    def test_sigma_deviation_equals_innovation_over_std(
        self,
        history: List[float],
        innovation: float,
    ) -> None:
        """sigma_deviation = innovation / std(history) for each sensor."""
        analyzer = RootCauseAnalyzer()
        engine_id = 1
        sensor_name = "test_sensor"

        # Record history for the sensor
        for mag in history:
            analyzer.record_innovation(engine_id, sensor_name, mag)

        # Trigger anomaly analysis
        result = analyzer.analyze_anomaly(
            engine_id, {sensor_name: innovation}
        )

        assert len(result.contributions) == 1
        contribution = result.contributions[0]

        # Compute expected sigma deviation
        expected_std = float(np.std(history))
        if expected_std < 1e-12:
            expected_sigma = 0.0
        else:
            expected_sigma = innovation / expected_std

        assert abs(contribution.sigma_deviation - expected_sigma) < 1e-9, (
            f"sigma_deviation mismatch: got {contribution.sigma_deviation}, "
            f"expected {expected_sigma} (innovation={innovation}, "
            f"std(history)={expected_std})"
        )

    @given(
        histories=st.fixed_dictionaries({
            "sensor_a": st.lists(st.floats(0.1, 100), min_size=2),
            "sensor_b": st.lists(st.floats(0.1, 100), min_size=2),
            "sensor_c": st.lists(st.floats(0.1, 100), min_size=2),
        }),
        innovations=st.fixed_dictionaries({
            "sensor_a": st.floats(0.01, 50),
            "sensor_b": st.floats(0.01, 50),
            "sensor_c": st.floats(0.01, 50),
        }),
    )
    @settings(max_examples=200)
    def test_contributions_sorted_descending_by_sigma_deviation(
        self,
        histories: Dict[str, List[float]],
        innovations: Dict[str, float],
    ) -> None:
        """Contributions list is sorted by sigma_deviation in descending order."""
        analyzer = RootCauseAnalyzer()
        engine_id = 1

        # Record history for each sensor
        for sensor_name, hist in histories.items():
            for mag in hist:
                analyzer.record_innovation(engine_id, sensor_name, mag)

        # Trigger anomaly analysis with all sensors
        result = analyzer.analyze_anomaly(engine_id, innovations)

        assert len(result.contributions) == 3

        # Verify descending sort order
        sigma_values = [c.sigma_deviation for c in result.contributions]
        for i in range(len(sigma_values) - 1):
            assert sigma_values[i] >= sigma_values[i + 1], (
                f"Contributions not sorted descending: "
                f"sigma[{i}]={sigma_values[i]} < sigma[{i+1}]={sigma_values[i+1]}"
            )

    @given(
        constant_value=st.floats(0.1, 100),
        history_len=st.integers(min_value=2, max_value=50),
        innovation=st.floats(0.01, 50),
    )
    @settings(max_examples=100)
    def test_constant_history_yields_zero_sigma(
        self,
        constant_value: float,
        history_len: int,
        innovation: float,
    ) -> None:
        """When all history values are identical (std=0), sigma_deviation = 0.0."""
        analyzer = RootCauseAnalyzer()
        engine_id = 1
        sensor_name = "constant_sensor"

        # Record identical values (std will be 0)
        for _ in range(history_len):
            analyzer.record_innovation(engine_id, sensor_name, constant_value)

        result = analyzer.analyze_anomaly(
            engine_id, {sensor_name: innovation}
        )

        assert len(result.contributions) == 1
        assert result.contributions[0].sigma_deviation == 0.0, (
            f"Expected sigma_deviation=0.0 for constant history, "
            f"got {result.contributions[0].sigma_deviation}"
        )


# ---------------------------------------------------------------------------
# Property 4: LatencyProfiler — Monotonic Percentiles
# ---------------------------------------------------------------------------


class TestMonotonicPercentiles:
    """**Validates: Requirements 4.2**

    Property 4: Monotonic Percentiles

    ∀ measurements: List[float] (len ≥ 1, all values ≥ 0)
      p50 ≤ p95 ≤ p99

    This is a mathematical invariant of percentile computation — if violated,
    the implementation is incorrect.
    """

    @given(
        measurements=st.lists(
            st.floats(0, 1000, allow_nan=False), min_size=1, max_size=1000
        )
    )
    @settings(max_examples=500)
    def test_percentiles_are_monotonically_non_decreasing(
        self, measurements: List[float]
    ) -> None:
        """p50 ≤ p95 ≤ p99 for any set of latency measurements."""
        profiler = LatencyProfiler()

        # Directly inject measurements into the profiler's internal deque
        # to test get_metrics() percentile computation in isolation.
        for m in measurements:
            profiler._measurements.append(m)

        metrics = profiler.get_metrics()

        assert metrics.p50_ms <= metrics.p95_ms, (
            f"Monotonicity violated: p50={metrics.p50_ms} > p95={metrics.p95_ms}"
        )
        assert metrics.p95_ms <= metrics.p99_ms, (
            f"Monotonicity violated: p95={metrics.p95_ms} > p99={metrics.p99_ms}"
        )
        assert metrics.sample_count == min(len(measurements), profiler.WINDOW_SIZE)

    @given(
        measurements=st.lists(
            st.floats(0, 1000, allow_nan=False), min_size=1, max_size=1000
        )
    )
    @settings(max_examples=200)
    def test_percentiles_within_measurement_range(
        self, measurements: List[float]
    ) -> None:
        """All percentiles are bounded by [min(measurements), max(measurements)]."""
        profiler = LatencyProfiler()

        for m in measurements:
            profiler._measurements.append(m)

        metrics = profiler.get_metrics()

        min_val = min(measurements)
        max_val = max(measurements)

        assert metrics.p50_ms >= min_val - 1e-9, (
            f"p50={metrics.p50_ms} below min={min_val}"
        )
        assert metrics.p99_ms <= max_val + 1e-9, (
            f"p99={metrics.p99_ms} above max={max_val}"
        )


# ---------------------------------------------------------------------------
# Property 5: ThroughputMonitor — Rate Computation Correctness
# ---------------------------------------------------------------------------


class TestRateComputationCorrectness:
    """**Validates: Requirements 4.3, 4.4**

    Property 5: Rate Computation Correctness

    ∀ timestamps: List[float], window_seconds: float > 0, now: float
      count_in_window = |{t ∈ timestamps : t ≥ now - window_seconds}|
      rate = count_in_window / window_seconds
      AND events with timestamp < (now - window_seconds) are excluded
    """

    @given(
        relative_timestamps=st.lists(
            st.floats(0, 100, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=100,
        ),
        now_offset=st.floats(0, 100, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_rate_equals_count_in_window_over_window_seconds(
        self,
        relative_timestamps: List[float],
        now_offset: float,
    ) -> None:
        """rate = count_in_window / window_seconds for any timestamps and now.

        The deque must be sorted ascending (as in production where time.time()
        is appended sequentially) for the left-eviction logic to work correctly.
        """
        monitor = ThroughputMonitor()
        window_seconds = monitor.WINDOW_SECONDS  # 10.0

        # Use a fixed base time and compute absolute timestamps
        base_time = 1000.0
        now = base_time + now_offset

        # Sort timestamps to match production behavior (appended in order)
        sorted_timestamps = sorted(relative_timestamps)

        # Create a deque with sorted absolute timestamps
        timestamps = deque(base_time + t for t in sorted_timestamps)

        # Compute expected rate manually
        cutoff = now - window_seconds
        count_in_window = sum(1 for t in timestamps if t >= cutoff)
        expected_rate = count_in_window / window_seconds

        # Call _compute_rate with a copy (since it mutates the deque)
        test_deque: deque[float] = deque(timestamps)
        actual_rate = monitor._compute_rate(test_deque, now)

        assert actual_rate == pytest.approx(expected_rate, rel=1e-9, abs=1e-12), (
            f"Rate mismatch: got {actual_rate}, expected {expected_rate} "
            f"(count_in_window={count_in_window}, window={window_seconds})"
        )

    @given(
        relative_timestamps=st.lists(
            st.floats(0, 100, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=100,
        ),
        now_offset=st.floats(0, 100, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_old_timestamps_evicted_from_deque(
        self,
        relative_timestamps: List[float],
        now_offset: float,
    ) -> None:
        """Timestamps older than (now - window_seconds) are removed from the deque.

        The deque must be sorted ascending (as in production where time.time()
        is appended sequentially) for the left-eviction logic to work correctly.
        """
        monitor = ThroughputMonitor()
        window_seconds = monitor.WINDOW_SECONDS  # 10.0

        base_time = 1000.0
        now = base_time + now_offset
        cutoff = now - window_seconds

        # Sort timestamps to match production behavior (appended in order)
        sorted_timestamps = sorted(relative_timestamps)

        # Build deque with sorted absolute timestamps
        test_deque: deque[float] = deque(base_time + t for t in sorted_timestamps)

        # Call _compute_rate which evicts old entries
        monitor._compute_rate(test_deque, now)

        # After eviction, all remaining timestamps should be >= cutoff
        for t in test_deque:
            assert t >= cutoff, (
                f"Timestamp {t} should have been evicted (cutoff={cutoff})"
            )

    @given(
        count=st.integers(min_value=0, max_value=200),
    )
    @settings(max_examples=100)
    def test_all_events_in_window_produces_count_over_window(
        self,
        count: int,
    ) -> None:
        """When all timestamps are within the window, rate = count / window_seconds."""
        monitor = ThroughputMonitor()
        window_seconds = monitor.WINDOW_SECONDS

        now = 1000.0
        # All timestamps within the window (between now-5 and now)
        test_deque: deque[float] = deque(
            now - 5.0 + (i * 0.01) for i in range(count)
        )

        actual_rate = monitor._compute_rate(test_deque, now)

        if count == 0:
            assert actual_rate == 0.0
        else:
            expected_rate = count / window_seconds
            assert actual_rate == pytest.approx(expected_rate, rel=1e-9, abs=1e-12)
