"""Property-based tests for MonteCarloProjector.

# Feature: digital-twin-v1.3, Properties 7–9

Tests that the MonteCarloProjector produces correct output structure
(5 percentile keys, monotonically ordered values, correct lengths),
monotonically non-decreasing failure probability curves, and consistent
RUL statistics where confidence intervals contain the expected RUL.

**Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7**
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from unittest.mock import MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from digital_twin_engine.prognostics.models import EngineHealthState
from digital_twin_engine.simulation.monte_carlo_projector import (
    CRITICAL_THRESHOLD,
    MonteCarloProjector,
    ProjectionResult,
)


# ---------------------------------------------------------------------------
# Mock Factories
# ---------------------------------------------------------------------------


def _make_mock_health_aggregator(health_index: float) -> MagicMock:
    """Create a mock HealthIndexAggregator that returns a fixed health state.

    Args:
        health_index: The health index value to return (0.0-1.0).

    Returns:
        Mock object with get_health_state(engine_id) returning an EngineHealthState.
    """
    mock = MagicMock()
    mock.get_health_state.return_value = EngineHealthState(
        engine_id=1,
        health_index=health_index,
        cycle_count=100,
        is_provisional=False,
        last_update_cycle=100,
    )
    return mock


def _make_mock_degradation_tracker(
    rate: float,
    trajectory_length: int = 30,
    health_start: float = 1.0,
) -> MagicMock:
    """Create a mock DegradationCurveTracker with deterministic outputs.

    Generates a synthetic linear degradation trajectory and returns
    the specified rate from compute_degradation_rate().

    Args:
        rate: The degradation rate to return (negative = declining health).
        trajectory_length: Number of (cycle, HI) points in the trajectory.
        health_start: Starting health index for trajectory generation.

    Returns:
        Mock object with compute_degradation_rate() and get_trajectory().
    """
    mock = MagicMock()
    mock.compute_degradation_rate.return_value = rate

    # Generate a synthetic linear trajectory with small noise
    trajectory: List[Tuple[int, float]] = []
    abs_rate = abs(rate)
    for i in range(trajectory_length):
        hi = max(0.0, min(1.0, health_start - abs_rate * i))
        trajectory.append((i + 1, hi))

    mock.get_trajectory.return_value = trajectory
    return mock


# ---------------------------------------------------------------------------
# Test Strategies
# ---------------------------------------------------------------------------

# Strategy for current health index (must be in valid range, above critical
# to allow meaningful projection)
health_index_strategy = st.floats(
    min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Strategy for degradation rate (negative = health declining; small realistic values)
degradation_rate_strategy = st.floats(
    min_value=-0.05, max_value=-0.001, allow_nan=False, allow_infinity=False
)

# Strategy for horizon cycles (valid range per API: 1-200, keep small for perf)
horizon_strategy = st.integers(min_value=2, max_value=100)

# Strategy for number of trajectories (keep reasonable for test speed)
num_trajectories_strategy = st.integers(min_value=100, max_value=500)

# Strategy for stress factor (valid range per API: 0.5-2.0)
stress_factor_strategy = st.floats(
    min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Property 7: Projection Output Structure Invariant
# ---------------------------------------------------------------------------


class TestProjectionOutputStructureInvariant:
    """Feature: digital-twin-v1.3, Property 7: Projection Output Structure Invariant

    For any valid engine state with sufficient degradation data, and any valid
    (horizon_cycles, num_trajectories, stress_factor) parameters, the projection
    output SHALL have: (a) exactly 5 percentile keys {5, 25, 50, 75, 95},
    (b) each percentile array has length == horizon_cycles, (c) at every cycle
    index, p5 <= p25 <= p50 <= p75 <= p95, and (d) all values are in [0.0, 1.0].

    **Validates: Requirements 4.3, 4.4**
    """

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_output_has_exactly_5_percentile_keys(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """Output percentiles dict has exactly keys {5, 25, 50, 75, 95}."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        assert set(result.percentiles.keys()) == {5, 25, 50, 75, 95}, (
            f"Expected percentile keys {{5, 25, 50, 75, 95}}, "
            f"got {set(result.percentiles.keys())}"
        )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_each_percentile_array_has_correct_length(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """Each percentile array has length == horizon_cycles."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        for pct, values in result.percentiles.items():
            assert len(values) == horizon_cycles, (
                f"Percentile {pct}: expected length {horizon_cycles}, "
                f"got {len(values)}"
            )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_percentiles_are_monotonically_ordered_at_each_cycle(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """At every cycle index, p5 <= p25 <= p50 <= p75 <= p95."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        for i in range(horizon_cycles):
            p5 = result.percentiles[5][i]
            p25 = result.percentiles[25][i]
            p50 = result.percentiles[50][i]
            p75 = result.percentiles[75][i]
            p95 = result.percentiles[95][i]

            assert p5 <= p25 <= p50 <= p75 <= p95, (
                f"Cycle {i}: percentile ordering violated: "
                f"p5={p5}, p25={p25}, p50={p50}, p75={p75}, p95={p95}"
            )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_all_percentile_values_in_valid_range(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """All percentile values are in [0.0, 1.0]."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        for pct, values in result.percentiles.items():
            for i, v in enumerate(values):
                assert 0.0 <= v <= 1.0, (
                    f"Percentile {pct}, cycle {i}: value {v} out of range [0.0, 1.0]"
                )


# ---------------------------------------------------------------------------
# Property 8: Failure Probability Monotonicity
# ---------------------------------------------------------------------------


class TestFailureProbabilityMonotonicity:
    """Feature: digital-twin-v1.3, Property 8: Failure Probability Monotonicity

    For any projection result, the failure_probability_by_cycle array SHALL be
    monotonically non-decreasing (each element >= the previous), have length ==
    horizon_cycles, and all values SHALL be in [0.0, 1.0].

    **Validates: Requirements 4.5**
    """

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_failure_probability_is_monotonically_non_decreasing(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """failure_probability_by_cycle is monotonically non-decreasing."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        fp = result.failure_probability_by_cycle
        for i in range(1, len(fp)):
            assert fp[i] >= fp[i - 1], (
                f"Failure probability decreased at cycle {i}: "
                f"fp[{i-1}]={fp[i-1]}, fp[{i}]={fp[i]}"
            )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_failure_probability_has_correct_length(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """failure_probability_by_cycle has length == horizon_cycles."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        assert len(result.failure_probability_by_cycle) == horizon_cycles, (
            f"Expected failure_probability length {horizon_cycles}, "
            f"got {len(result.failure_probability_by_cycle)}"
        )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_failure_probability_values_in_valid_range(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """All failure_probability_by_cycle values are in [0.0, 1.0]."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        for i, v in enumerate(result.failure_probability_by_cycle):
            assert 0.0 <= v <= 1.0, (
                f"Failure probability at cycle {i}: value {v} out of range [0.0, 1.0]"
            )


# ---------------------------------------------------------------------------
# Property 9: RUL Statistics Consistency
# ---------------------------------------------------------------------------


class TestRULStatisticsConsistency:
    """Feature: digital-twin-v1.3, Property 9: RUL Statistics Consistency

    For any projection result where expected_rul is not None and
    confidence_interval_90 is not None, the relationship
    confidence_interval_90[0] <= expected_rul <= confidence_interval_90[1]
    SHALL hold.

    **Validates: Requirements 4.6, 4.7**
    """

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_expected_rul_within_confidence_interval(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """When expected_rul and ci_90 are not None, ci[0] <= rul <= ci[1]."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        # Only verify when both are non-None
        if result.expected_rul is not None and result.confidence_interval_90 is not None:
            ci_low, ci_high = result.confidence_interval_90
            assert ci_low <= result.expected_rul <= ci_high, (
                f"RUL consistency violated: ci_low={ci_low}, "
                f"expected_rul={result.expected_rul}, ci_high={ci_high}"
            )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        num_trajectories=num_trajectories_strategy,
        stress_factor=stress_factor_strategy,
    )
    @settings(max_examples=100)
    def test_rul_and_ci_are_both_none_or_both_present(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        num_trajectories: int,
        stress_factor: float,
    ) -> None:
        """expected_rul and confidence_interval_90 are either both None or both present."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)
        projector = MonteCarloProjector(mock_hia, mock_dct)

        result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            num_trajectories=num_trajectories,
            stress_factor=stress_factor,
        )

        # Both should be None or both should be non-None
        if result.expected_rul is None:
            assert result.confidence_interval_90 is None, (
                f"expected_rul is None but confidence_interval_90 is "
                f"{result.confidence_interval_90}"
            )
        else:
            assert result.confidence_interval_90 is not None, (
                f"expected_rul is {result.expected_rul} but "
                f"confidence_interval_90 is None"
            )
