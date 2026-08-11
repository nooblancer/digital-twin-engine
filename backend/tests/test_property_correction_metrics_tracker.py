"""Property-based tests for CorrectionMetricsTracker statistics.

Uses the Hypothesis library to verify that the tracker computes correct RMSE, MAE,
improvement percentage, R², and sample count across randomly generated input sequences.

**Validates: Requirements 2.2, 2.3, 2.4, 2.5, 2.6**
"""

from __future__ import annotations

import math

import hypothesis.strategies as st
from hypothesis import given, settings, assume, HealthCheck

from digital_twin_engine.correction.correction_metrics_tracker import (
    CorrectionMetricsTracker,
)


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def correction_triples(draw, min_length=2, max_length=50):
    """Generate a list of (raw_prediction, observed_value, corrected_value) triples.

    Values are bounded floats to avoid overflow in squared-error computations.
    """
    n = draw(st.integers(min_value=min_length, max_value=max_length))
    triples = []
    for _ in range(n):
        raw = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        observed = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        corrected = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        triples.append((raw, observed, corrected))
    return triples


@st.composite
def correction_triples_varying_observed(draw, min_length=3, max_length=50):
    """Generate triples where observed values are NOT all identical (ss_tot > 0).

    This ensures R² is computable (denominator is non-zero).
    """
    n = draw(st.integers(min_value=min_length, max_value=max_length))
    triples = []
    for _ in range(n):
        raw = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        observed = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        corrected = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        triples.append((raw, observed, corrected))

    # Ensure observed values are not all the same
    observed_vals = [t[1] for t in triples]
    assume(len(set(observed_vals)) > 1)
    return triples


# ===========================================================================
# Property 4: CorrectionMetricsTracker computes correct statistics
# **Validates: Requirements 2.2, 2.3, 2.4, 2.5, 2.6**
# ===========================================================================


class TestCorrectionMetricsTrackerStatistics:
    """The CorrectionMetricsTracker SHALL compute correct RMSE, MAE, improvement
    percentage, R², and sample count for any sequence of recorded triples.

    **Validates: Requirements 2.2, 2.3, 2.4, 2.5, 2.6**
    """

    @given(triples=correction_triples(min_length=2, max_length=50))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rmse_computation_matches_formula(self, triples):
        """raw_rmse = sqrt(mean((raw - observed)²)), corrected_rmse = sqrt(mean((corrected - observed)²))."""
        tracker = CorrectionMetricsTracker()
        for raw, observed, corrected in triples:
            tracker.record("sensor-1", raw, observed, corrected)

        metrics = tracker.get_metrics()
        n = len(triples)

        # Compute expected RMSE independently
        raw_errors_sq = [(raw - observed) ** 2 for raw, observed, _ in triples]
        corrected_errors_sq = [(corrected - observed) ** 2 for _, observed, corrected in triples]

        expected_raw_rmse = math.sqrt(sum(raw_errors_sq) / n)
        expected_corrected_rmse = math.sqrt(sum(corrected_errors_sq) / n)

        assert metrics.raw_rmse is not None
        assert metrics.corrected_rmse is not None
        assert abs(metrics.raw_rmse - expected_raw_rmse) < 1e-9, (
            f"raw_rmse mismatch: got {metrics.raw_rmse}, expected {expected_raw_rmse}"
        )
        assert abs(metrics.corrected_rmse - expected_corrected_rmse) < 1e-9, (
            f"corrected_rmse mismatch: got {metrics.corrected_rmse}, expected {expected_corrected_rmse}"
        )

    @given(triples=correction_triples(min_length=2, max_length=50))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_mae_computation_matches_formula(self, triples):
        """raw_mae = mean(|raw - observed|), corrected_mae = mean(|corrected - observed|)."""
        tracker = CorrectionMetricsTracker()
        for raw, observed, corrected in triples:
            tracker.record("sensor-1", raw, observed, corrected)

        metrics = tracker.get_metrics()
        n = len(triples)

        # Compute expected MAE independently
        raw_abs_errors = [abs(raw - observed) for raw, observed, _ in triples]
        corrected_abs_errors = [abs(corrected - observed) for _, observed, corrected in triples]

        expected_raw_mae = sum(raw_abs_errors) / n
        expected_corrected_mae = sum(corrected_abs_errors) / n

        assert metrics.raw_mae is not None
        assert metrics.corrected_mae is not None
        assert abs(metrics.raw_mae - expected_raw_mae) < 1e-9, (
            f"raw_mae mismatch: got {metrics.raw_mae}, expected {expected_raw_mae}"
        )
        assert abs(metrics.corrected_mae - expected_corrected_mae) < 1e-9, (
            f"corrected_mae mismatch: got {metrics.corrected_mae}, expected {expected_corrected_mae}"
        )

    @given(triples=correction_triples(min_length=2, max_length=50))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_improvement_percentage_matches_formula(self, triples):
        """improvement = (raw_rmse − corrected_rmse) / raw_rmse × 100."""
        tracker = CorrectionMetricsTracker()
        for raw, observed, corrected in triples:
            tracker.record("sensor-1", raw, observed, corrected)

        metrics = tracker.get_metrics()
        n = len(triples)

        # Compute expected improvement independently
        raw_errors_sq = [(raw - observed) ** 2 for raw, observed, _ in triples]
        corrected_errors_sq = [(corrected - observed) ** 2 for _, observed, corrected in triples]
        raw_rmse = math.sqrt(sum(raw_errors_sq) / n)
        corrected_rmse = math.sqrt(sum(corrected_errors_sq) / n)

        if raw_rmse > 0:
            expected_improvement = (raw_rmse - corrected_rmse) / raw_rmse * 100.0
        else:
            expected_improvement = 0.0

        assert metrics.improvement_percentage is not None
        assert abs(metrics.improvement_percentage - expected_improvement) < 1e-9, (
            f"improvement mismatch: got {metrics.improvement_percentage}, expected {expected_improvement}"
        )

    @given(triples=correction_triples(min_length=2, max_length=50))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_sample_count_matches_records(self, triples):
        """sample_count matches the number of recorded triples."""
        tracker = CorrectionMetricsTracker()
        for raw, observed, corrected in triples:
            tracker.record("sensor-1", raw, observed, corrected)

        metrics = tracker.get_metrics()
        assert metrics.sample_count == len(triples), (
            f"sample_count mismatch: got {metrics.sample_count}, expected {len(triples)}"
        )

    @given(triples=correction_triples_varying_observed(min_length=3, max_length=50))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_r_squared_computation_when_ss_tot_positive(self, triples):
        """R² = 1 - SS_res/SS_tot when ss_tot > 0."""
        tracker = CorrectionMetricsTracker()
        for raw, observed, corrected in triples:
            tracker.record("sensor-1", raw, observed, corrected)

        metrics = tracker.get_metrics()
        n = len(triples)

        # Compute expected R² independently
        observed_vals = [t[1] for t in triples]
        obs_mean = sum(observed_vals) / n
        ss_tot = sum((o - obs_mean) ** 2 for o in observed_vals)

        # ss_tot > 0 guaranteed by the strategy (assume not all same)
        assert ss_tot > 0

        ss_res_raw = sum((raw - observed) ** 2 for raw, observed, _ in triples)
        ss_res_corr = sum((corrected - observed) ** 2 for _, observed, corrected in triples)

        expected_raw_r2 = 1.0 - (ss_res_raw / ss_tot)
        expected_corr_r2 = 1.0 - (ss_res_corr / ss_tot)

        assert metrics.raw_r_squared is not None
        assert metrics.corrected_r_squared is not None
        assert abs(metrics.raw_r_squared - expected_raw_r2) < 1e-9, (
            f"raw_r_squared mismatch: got {metrics.raw_r_squared}, expected {expected_raw_r2}"
        )
        assert abs(metrics.corrected_r_squared - expected_corr_r2) < 1e-9, (
            f"corrected_r_squared mismatch: got {metrics.corrected_r_squared}, expected {expected_corr_r2}"
        )

    @given(
        constant_observed=st.sampled_from([0.0, 1.0, -1.0, 2.0, 4.0, 8.0, 16.0, 0.5, 0.25, 100.0]),
        n=st.integers(min_value=2, max_value=20),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_r_squared_null_when_ss_tot_zero(self, constant_observed, n):
        """R² is null when all observed values are identical (ss_tot = 0).

        Uses exact float values (powers of 2 and small integers) to ensure
        sum(N copies) / N == original without floating-point rounding error.
        """
        tracker = CorrectionMetricsTracker()
        for i in range(n):
            # All observed values are the same constant
            raw = constant_observed + float(i + 1)  # Different raw values
            corrected = constant_observed + float(i + 1) * 0.5  # Different corrected values
            tracker.record("sensor-1", raw, constant_observed, corrected)

        metrics = tracker.get_metrics()
        assert metrics.raw_r_squared is None, (
            f"raw_r_squared should be None when ss_tot=0, got {metrics.raw_r_squared}"
        )
        assert metrics.corrected_r_squared is None, (
            f"corrected_r_squared should be None when ss_tot=0, got {metrics.corrected_r_squared}"
        )

    @given(
        raw=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        observed=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        corrected=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_null_metrics_when_fewer_than_2_samples(self, raw, observed, corrected):
        """Metrics are null when sample_count < 2."""
        tracker = CorrectionMetricsTracker()

        # Zero samples
        metrics = tracker.get_metrics()
        assert metrics.raw_rmse is None
        assert metrics.corrected_rmse is None
        assert metrics.raw_mae is None
        assert metrics.corrected_mae is None
        assert metrics.improvement_percentage is None
        assert metrics.sample_count == 0

        # One sample
        tracker.record("sensor-1", raw, observed, corrected)
        metrics = tracker.get_metrics()
        assert metrics.raw_rmse is None
        assert metrics.corrected_rmse is None
        assert metrics.raw_mae is None
        assert metrics.corrected_mae is None
        assert metrics.improvement_percentage is None
        assert metrics.sample_count == 1

    @given(triples=correction_triples(min_length=2, max_length=30))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_multi_sensor_aggregation(self, triples):
        """Metrics aggregate correctly across multiple sensors."""
        tracker = CorrectionMetricsTracker()

        # Split triples across two sensors
        mid = len(triples) // 2
        for raw, observed, corrected in triples[:mid]:
            tracker.record("sensor-A", raw, observed, corrected)
        for raw, observed, corrected in triples[mid:]:
            tracker.record("sensor-B", raw, observed, corrected)

        metrics = tracker.get_metrics()
        n = len(triples)

        # Compute expected from ALL triples (aggregated)
        raw_errors_sq = [(raw - observed) ** 2 for raw, observed, _ in triples]
        corrected_errors_sq = [(corrected - observed) ** 2 for _, observed, corrected in triples]

        expected_raw_rmse = math.sqrt(sum(raw_errors_sq) / n)
        expected_corrected_rmse = math.sqrt(sum(corrected_errors_sq) / n)

        assert metrics.sample_count == n
        assert metrics.raw_rmse is not None
        assert abs(metrics.raw_rmse - expected_raw_rmse) < 1e-9, (
            f"Multi-sensor raw_rmse mismatch: got {metrics.raw_rmse}, expected {expected_raw_rmse}"
        )
        assert abs(metrics.corrected_rmse - expected_corrected_rmse) < 1e-9, (
            f"Multi-sensor corrected_rmse mismatch: got {metrics.corrected_rmse}, expected {expected_corrected_rmse}"
        )
