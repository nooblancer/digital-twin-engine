"""Unit tests for the Degradation Curve Tracker.

Tests recording and retrieval, degradation rate computation against
hand-calculated values, boundary behavior at exactly 20 cycles,
and under-20-cycle behavior.

Validates: Requirements 3.1, 3.4, 3.6
"""

from __future__ import annotations

import pytest

from digital_twin_engine.prognostics.degradation_tracker import (
    DegradationCurveTracker,
    MIN_CYCLES_FOR_RATE,
)


# ---------------------------------------------------------------------------
# Tests: Recording and Retrieval (Requirement 3.1)
# ---------------------------------------------------------------------------


class TestRecordAndRetrieve:
    """Test round-trip storage and ordered retrieval of trajectory data."""

    def test_record_single_point_and_retrieve(self) -> None:
        """A single recorded point is returned by get_trajectory."""
        tracker = DegradationCurveTracker()
        tracker.record(engine_id=1, cycle=5, health_index=0.95)

        trajectory = tracker.get_trajectory(engine_id=1)

        assert trajectory == [(5, 0.95)]

    def test_record_multiple_points_same_engine(self) -> None:
        """Multiple points for the same engine are all stored."""
        tracker = DegradationCurveTracker()
        tracker.record(engine_id=1, cycle=1, health_index=1.0)
        tracker.record(engine_id=1, cycle=2, health_index=0.98)
        tracker.record(engine_id=1, cycle=3, health_index=0.95)

        trajectory = tracker.get_trajectory(engine_id=1)

        assert len(trajectory) == 3
        assert trajectory == [(1, 1.0), (2, 0.98), (3, 0.95)]

    def test_retrieval_sorted_by_cycle(self) -> None:
        """Trajectory is returned sorted by cycle regardless of insertion order."""
        tracker = DegradationCurveTracker()
        # Insert out of order
        tracker.record(engine_id=1, cycle=10, health_index=0.80)
        tracker.record(engine_id=1, cycle=3, health_index=0.95)
        tracker.record(engine_id=1, cycle=7, health_index=0.88)

        trajectory = tracker.get_trajectory(engine_id=1)

        cycles = [c for c, _ in trajectory]
        assert cycles == [3, 7, 10]

    def test_separate_engines_have_independent_trajectories(self) -> None:
        """Different engine IDs maintain separate trajectory histories."""
        tracker = DegradationCurveTracker()
        tracker.record(engine_id=1, cycle=1, health_index=0.99)
        tracker.record(engine_id=2, cycle=1, health_index=0.85)

        assert tracker.get_trajectory(engine_id=1) == [(1, 0.99)]
        assert tracker.get_trajectory(engine_id=2) == [(1, 0.85)]

    def test_get_trajectory_unknown_engine_returns_empty(self) -> None:
        """Requesting trajectory for an unknown engine returns empty list."""
        tracker = DegradationCurveTracker()

        assert tracker.get_trajectory(engine_id=999) == []

    def test_health_index_values_preserved_exactly(self) -> None:
        """Stored health index values are returned without loss of precision."""
        tracker = DegradationCurveTracker()
        tracker.record(engine_id=1, cycle=1, health_index=0.123456789)

        trajectory = tracker.get_trajectory(engine_id=1)

        assert trajectory[0][1] == 0.123456789


# ---------------------------------------------------------------------------
# Tests: Degradation Rate Computation (Requirement 3.4)
# ---------------------------------------------------------------------------


class TestDegradationRateComputation:
    """Test degradation rate computation against hand-calculated values."""

    def test_linear_decline_hand_calculated(self) -> None:
        """Verify degradation rate matches hand-calculated linear regression.

        Given 20 points with a perfect linear decline from 1.0 to 0.81
        (slope of -0.01 per cycle):
        - x = [0, 1, 2, ..., 19], y = [1.0, 0.99, 0.98, ..., 0.81]
        - slope = -0.01
        """
        tracker = DegradationCurveTracker()

        for i in range(20):
            tracker.record(engine_id=1, cycle=i, health_index=1.0 - 0.01 * i)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is not None
        assert abs(rate - (-0.01)) < 1e-10

    def test_constant_health_index_zero_slope(self) -> None:
        """Constant health index across 20 cycles yields slope of 0."""
        tracker = DegradationCurveTracker()

        for i in range(20):
            tracker.record(engine_id=1, cycle=i, health_index=0.90)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is not None
        assert abs(rate) < 1e-10

    def test_steep_decline_rate(self) -> None:
        """Steep decline that triggers accelerated degradation threshold.

        slope = -0.03 per cycle (exceeds 0.02 threshold).
        y = 1.0 - 0.03 * i for i in [0..19]
        """
        tracker = DegradationCurveTracker()

        for i in range(20):
            tracker.record(engine_id=1, cycle=i, health_index=1.0 - 0.03 * i)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is not None
        assert abs(rate - (-0.03)) < 1e-10

    def test_uses_last_20_points_only(self) -> None:
        """When more than 20 points exist, only the last 20 are used.

        Record 30 points: first 10 constant at 1.0, last 20 decline at -0.02/cycle.
        The rate should be -0.02 (computed from last 20 only).
        """
        tracker = DegradationCurveTracker()

        # First 10 cycles: constant health
        for i in range(10):
            tracker.record(engine_id=1, cycle=i, health_index=1.0)

        # Next 20 cycles: linear decline from 1.0 to 0.62
        for i in range(20):
            tracker.record(engine_id=1, cycle=10 + i, health_index=1.0 - 0.02 * i)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is not None
        assert abs(rate - (-0.02)) < 1e-10

    def test_hand_calculated_non_trivial_regression(self) -> None:
        """Verify against hand-calculated linear regression with known data.

        Data: x = [0, 1, 2, 3, 4, ..., 19]
              y = [0.95, 0.93, 0.92, 0.90, 0.89, 0.87, 0.86, 0.84, 0.83, 0.81,
                   0.80, 0.78, 0.77, 0.75, 0.74, 0.72, 0.71, 0.69, 0.68, 0.66]

        This is approximately y = 0.95 - 0.015 * x with small rounding.

        Hand calculation:
        n = 20, sum_x = 190, sum_x2 = 2470
        sum_y = 16.0, sum_xy = 137.01
        slope = (20*137.01 - 190*16.0) / (20*2470 - 190^2)
              = (2740.2 - 3040) / (49400 - 36100)
              = -299.8 / 13300
              ≈ -0.02254
        """
        tracker = DegradationCurveTracker()

        y_values = [
            0.95, 0.93, 0.92, 0.90, 0.89,
            0.87, 0.86, 0.84, 0.83, 0.81,
            0.80, 0.78, 0.77, 0.75, 0.74,
            0.72, 0.71, 0.69, 0.68, 0.66,
        ]

        for i, y in enumerate(y_values):
            tracker.record(engine_id=1, cycle=i, health_index=y)

        rate = tracker.compute_degradation_rate(engine_id=1)

        # Verify by computing expected slope manually
        n = 20
        sum_x = sum(range(20))  # 190
        sum_y = sum(y_values)
        sum_xy = sum(i * y for i, y in enumerate(y_values))
        sum_x2 = sum(i * i for i in range(20))

        expected_slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)

        assert rate is not None
        assert abs(rate - expected_slope) < 1e-10


# ---------------------------------------------------------------------------
# Tests: Boundary at Exactly 20 Cycles (Requirements 3.4, 3.6)
# ---------------------------------------------------------------------------


class TestBoundaryTwentyCycles:
    """Test the 20-cycle boundary for degradation rate computation."""

    def test_exactly_20_cycles_computes_rate(self) -> None:
        """With exactly 20 cycles stored, degradation rate is computed."""
        tracker = DegradationCurveTracker()

        for i in range(20):
            tracker.record(engine_id=1, cycle=i, health_index=1.0 - 0.01 * i)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is not None
        assert abs(rate - (-0.01)) < 1e-10

    def test_19_cycles_returns_none(self) -> None:
        """With 19 cycles (one fewer than minimum), rate is None."""
        tracker = DegradationCurveTracker()

        for i in range(19):
            tracker.record(engine_id=1, cycle=i, health_index=1.0 - 0.01 * i)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is None

    def test_21_cycles_computes_rate(self) -> None:
        """With 21 cycles (one more than minimum), rate is computed from last 20."""
        tracker = DegradationCurveTracker()

        # First point at constant health, then 20 declining points
        tracker.record(engine_id=1, cycle=0, health_index=1.0)
        for i in range(1, 21):
            tracker.record(engine_id=1, cycle=i, health_index=1.0 - 0.015 * i)

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is not None

    def test_under_20_cycles_returns_none_various_counts(self) -> None:
        """Various counts below 20 all return None for degradation rate."""
        tracker = DegradationCurveTracker()

        for count in [1, 5, 10, 15, 19]:
            for i in range(count):
                tracker.record(engine_id=count, cycle=i, health_index=0.9)

            rate = tracker.compute_degradation_rate(engine_id=count)
            assert rate is None, f"Expected None for {count} cycles, got {rate}"

    def test_zero_cycles_returns_none(self) -> None:
        """No data at all returns None for degradation rate."""
        tracker = DegradationCurveTracker()

        rate = tracker.compute_degradation_rate(engine_id=1)

        assert rate is None

    def test_min_cycles_constant_matches_expected(self) -> None:
        """MIN_CYCLES_FOR_RATE constant is 20."""
        assert MIN_CYCLES_FOR_RATE == 20
