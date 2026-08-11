"""Property-based tests for InnovationStatsTracker autocorrelation.

Property 5: Innovation autocorrelation matches Pearson correlation

**Validates: Requirements 5.3, 5.4**
"""

from __future__ import annotations

import math

import hypothesis.strategies as st
from hypothesis import given, settings, assume, HealthCheck
import pytest

from digital_twin_engine.correction.correction_metrics_tracker import (
    InnovationStatsTracker,
)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Innovation sequences of length >= 10 with reasonable float values
innovation_sequence_strategy = st.lists(
    st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    min_size=10,
    max_size=150,
)


# ---------------------------------------------------------------------------
# Helper: Manual Pearson correlation computation
# ---------------------------------------------------------------------------


def manual_pearson_correlation(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation coefficient between two sequences."""
    assert len(x) == len(y)
    m = len(x)
    mean_x = sum(x) / m
    mean_y = sum(y) / m
    cov_xy = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(m)) / m
    std_x = (sum((xi - mean_x) ** 2 for xi in x) / m) ** 0.5
    std_y = (sum((yi - mean_y) ** 2 for yi in y) / m) ** 0.5

    if std_x < 1e-10 or std_y < 1e-10:
        return 0.0
    return cov_xy / (std_x * std_y)


# ===========================================================================
# Property 5: Innovation autocorrelation matches Pearson correlation
# **Validates: Requirements 5.3, 5.4**
# ===========================================================================


class TestProperty5InnovationAutocorrelation:
    """The InnovationStatsTracker SHALL compute autocorrelation_lag1 as the
    Pearson correlation coefficient between the innovation sequence and its
    lag-1 shifted version, and whiteness_test_passed as
    |autocorrelation_lag1| < 2/sqrt(sample_count).

    **Validates: Requirements 5.3, 5.4**
    """

    @given(innovations=innovation_sequence_strategy)
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    def test_autocorrelation_matches_pearson_correlation(self, innovations: list[float]):
        """autocorrelation_lag1 matches Pearson correlation between seq[:-1] and seq[1:]."""
        # Ensure not all values are identical (which would give std=0)
        assume(len(set(innovations)) > 1)

        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for val in innovations:
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)

        # Manual computation: Pearson correlation between innovations[:-1] and innovations[1:]
        x = innovations[:-1]
        y = innovations[1:]
        expected_autocorr = manual_pearson_correlation(x, y)

        actual_autocorr = stats["autocorrelation_lag1"]
        assert actual_autocorr is not None, "autocorrelation_lag1 should not be None for n >= 10"

        assert abs(actual_autocorr - expected_autocorr) < 1e-9, (
            f"autocorrelation_lag1 mismatch: got {actual_autocorr:.12f}, "
            f"expected {expected_autocorr:.12f}, diff={abs(actual_autocorr - expected_autocorr):.2e}"
        )

    @given(innovations=innovation_sequence_strategy)
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    def test_mean_innovation_correct(self, innovations: list[float]):
        """mean_innovation equals the arithmetic mean of all recorded values."""
        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for val in innovations:
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)
        n = len(innovations)
        expected_mean = sum(innovations) / n

        assert stats["mean_innovation"] is not None
        assert abs(stats["mean_innovation"] - expected_mean) < 1e-9, (
            f"mean_innovation mismatch: got {stats['mean_innovation']:.12f}, "
            f"expected {expected_mean:.12f}"
        )

    @given(innovations=innovation_sequence_strategy)
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    def test_std_innovation_correct(self, innovations: list[float]):
        """std_innovation equals the population standard deviation of all recorded values."""
        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for val in innovations:
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)
        n = len(innovations)
        mean_val = sum(innovations) / n
        expected_std = (sum((x - mean_val) ** 2 for x in innovations) / n) ** 0.5

        assert stats["std_innovation"] is not None
        assert abs(stats["std_innovation"] - expected_std) < 1e-9, (
            f"std_innovation mismatch: got {stats['std_innovation']:.12f}, "
            f"expected {expected_std:.12f}"
        )

    @given(innovations=innovation_sequence_strategy)
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    def test_whiteness_test_matches_threshold(self, innovations: list[float]):
        """whiteness_test_passed = (|autocorrelation_lag1| < 2/sqrt(sample_count))."""
        assume(len(set(innovations)) > 1)

        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for val in innovations:
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)
        n = len(innovations)

        autocorr = stats["autocorrelation_lag1"]
        assert autocorr is not None

        threshold = 2.0 / (n ** 0.5)
        expected_whiteness = abs(autocorr) < threshold

        assert stats["whiteness_test_passed"] == expected_whiteness, (
            f"whiteness_test_passed mismatch: got {stats['whiteness_test_passed']}, "
            f"expected {expected_whiteness}. "
            f"|autocorr|={abs(autocorr):.6f}, threshold={threshold:.6f}, n={n}"
        )

    @given(innovations=innovation_sequence_strategy)
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    def test_sample_count_matches_records(self, innovations: list[float]):
        """sample_count matches the number of recorded values."""
        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for val in innovations:
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)
        assert stats["sample_count"] == len(innovations), (
            f"sample_count mismatch: got {stats['sample_count']}, expected {len(innovations)}"
        )

    @given(
        n=st.integers(min_value=0, max_value=9),
        val=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_insufficient_samples_returns_null(self, n: int, val: float):
        """When sample_count < 10, statistical fields are null."""
        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for _ in range(n):
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)

        assert stats["autocorrelation_lag1"] is None
        assert stats["mean_innovation"] is None
        assert stats["std_innovation"] is None
        assert stats["whiteness_test_passed"] is None
        assert stats["sample_count"] == n

    def test_max_history_truncation(self):
        """When more than max_history (200) entries are recorded, only the last 200 are kept."""
        tracker = InnovationStatsTracker(max_history=200)
        sensor_id = "test-sensor"

        # Record 250 entries
        values = [float(i) for i in range(250)]
        for val in values:
            tracker.record(sensor_id, val)

        stats = tracker.get_stats(sensor_id)

        # Only last 200 should be kept
        assert stats["sample_count"] == 200, (
            f"Expected sample_count=200 after recording 250 entries, got {stats['sample_count']}"
        )

        # Verify mean is computed over the last 200 entries (values 50..249)
        expected_values = values[-200:]
        expected_mean = sum(expected_values) / 200
        assert abs(stats["mean_innovation"] - expected_mean) < 1e-9, (
            f"mean_innovation should be based on last 200 entries: "
            f"got {stats['mean_innovation']:.6f}, expected {expected_mean:.6f}"
        )

    @given(
        constant_val=st.floats(
            min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
        n=st.integers(min_value=10, max_value=50),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_constant_sequence_autocorrelation_zero(self, constant_val: float, n: int):
        """When all values are identical (std_x=0 or std_y=0), autocorrelation returns 0.0."""
        tracker = InnovationStatsTracker()
        sensor_id = "test-sensor"

        for _ in range(n):
            tracker.record(sensor_id, constant_val)

        stats = tracker.get_stats(sensor_id)

        assert stats["autocorrelation_lag1"] == 0.0, (
            f"Expected autocorrelation_lag1=0.0 for constant sequence, "
            f"got {stats['autocorrelation_lag1']}"
        )
