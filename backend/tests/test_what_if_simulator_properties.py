"""Property-based tests for WhatIfSimulator.

# Feature: digital-twin-v1.3, Properties 10–12

Tests that the WhatIfSimulator correctly maps named scenarios to stress
factors, rejects invalid scenario names, and that maintenance resets
improve health at the reset point.

**Validates: Requirements 5.1–5.6**
"""

from __future__ import annotations

from typing import List, Tuple
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from digital_twin_engine.prognostics.models import EngineHealthState
from digital_twin_engine.simulation.monte_carlo_projector import (
    CRITICAL_THRESHOLD,
    MonteCarloProjector,
    ProjectionResult,
)
from digital_twin_engine.simulation.what_if_simulator import (
    SCENARIO_STRESS_MAP,
    VALID_SCENARIOS,
    SimulationResult,
    WhatIfSimulator,
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

# Strategy for current health index (above critical to allow meaningful projection)
health_index_strategy = st.floats(
    min_value=0.55, max_value=0.95, allow_nan=False, allow_infinity=False
)

# Strategy for degradation rate (negative = health declining; small realistic values)
degradation_rate_strategy = st.floats(
    min_value=-0.03, max_value=-0.002, allow_nan=False, allow_infinity=False
)

# Strategy for horizon cycles (valid range, keep small for test speed)
horizon_strategy = st.integers(min_value=10, max_value=80)

# Strategy for named scenarios (excluding maintenance_reset for Property 10)
scenario_strategy = st.sampled_from(["normal", "high_stress", "low_stress"])

# Strategy for invalid scenario names (random strings not in valid set)
invalid_scenario_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
).filter(lambda s: s not in VALID_SCENARIOS)

# Strategy for reset_fraction (must be > 0 for Property 12)
reset_fraction_strategy = st.floats(
    min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Property 10: Scenario Stress Factor Mapping
# ---------------------------------------------------------------------------


class TestScenarioStressFactorMapping:
    """Feature: digital-twin-v1.3, Property 10: Scenario Stress Factor Mapping

    For any of the named scenarios ("normal", "high_stress", "low_stress"),
    calling simulate_scenario SHALL produce results consistent with invoking
    the projector at the mapped stress factor (1.0, 1.5, 0.5 respectively).
    Specifically, the trajectory_percentiles SHALL be statistically
    indistinguishable from a direct projector call with that stress_factor.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        scenario=scenario_strategy,
    )
    @settings(max_examples=100)
    def test_scenario_produces_results_matching_mapped_stress_factor(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        scenario: str,
    ) -> None:
        """Named scenario results match direct projector call with mapped stress factor.

        We use a fixed random seed to ensure both calls (simulate_scenario and
        direct projector.project) produce identical results, confirming that
        the simulator passes through the correct stress factor.
        """
        import numpy as np

        expected_stress = SCENARIO_STRESS_MAP[scenario]

        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)

        projector = MonteCarloProjector(mock_hia, mock_dct)
        simulator = WhatIfSimulator(projector)

        # Call simulate_scenario with a fixed seed
        np.random.seed(42)
        scenario_result = simulator.simulate_scenario(
            engine_id=1,
            scenario=scenario,
            horizon_cycles=horizon_cycles,
        )

        # Call projector directly with the mapped stress factor and same seed
        np.random.seed(42)
        direct_result = projector.project(
            engine_id=1,
            horizon_cycles=horizon_cycles,
            stress_factor=expected_stress,
        )

        # The trajectory_percentiles should be identical (same seed, same stress)
        for pct in [5, 25, 50, 75, 95]:
            for i in range(horizon_cycles):
                assert scenario_result.trajectory_percentiles[pct][i] == direct_result.percentiles[pct][i], (
                    f"Scenario '{scenario}' (stress={expected_stress}): "
                    f"percentile {pct} at cycle {i} differs: "
                    f"scenario={scenario_result.trajectory_percentiles[pct][i]}, "
                    f"direct={direct_result.percentiles[pct][i]}"
                )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        horizon_cycles=horizon_strategy,
        scenario=scenario_strategy,
    )
    @settings(max_examples=100)
    def test_scenario_result_has_correct_structure(
        self,
        health_index: float,
        rate: float,
        horizon_cycles: int,
        scenario: str,
    ) -> None:
        """Named scenario result has all expected fields populated."""
        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)

        projector = MonteCarloProjector(mock_hia, mock_dct)
        simulator = WhatIfSimulator(projector)

        result = simulator.simulate_scenario(
            engine_id=1,
            scenario=scenario,
            horizon_cycles=horizon_cycles,
        )

        # Check structure
        assert set(result.trajectory_percentiles.keys()) == {5, 25, 50, 75, 95}
        for pct in [5, 25, 50, 75, 95]:
            assert len(result.trajectory_percentiles[pct]) == horizon_cycles
        assert len(result.failure_probability_curve) == horizon_cycles


# ---------------------------------------------------------------------------
# Property 11: Invalid Scenario Rejection
# ---------------------------------------------------------------------------


class TestInvalidScenarioRejection:
    """Feature: digital-twin-v1.3, Property 11: Invalid Scenario Rejection

    For any string that is not in {"normal", "high_stress", "low_stress",
    "maintenance_reset"}, calling simulate_scenario with that string as the
    scenario parameter SHALL raise a ValueError.

    **Validates: Requirements 5.6**
    """

    @given(invalid_scenario=invalid_scenario_strategy)
    @settings(max_examples=100)
    def test_invalid_scenario_raises_value_error(
        self,
        invalid_scenario: str,
    ) -> None:
        """Any string not in VALID_SCENARIOS raises ValueError."""
        import pytest

        mock_hia = _make_mock_health_aggregator(0.8)
        mock_dct = _make_mock_degradation_tracker(-0.01)

        projector = MonteCarloProjector(mock_hia, mock_dct)
        simulator = WhatIfSimulator(projector)

        with pytest.raises(ValueError) as exc_info:
            simulator.simulate_scenario(
                engine_id=1,
                scenario=invalid_scenario,
                horizon_cycles=50,
            )

        # Verify error message mentions valid scenarios
        error_msg = str(exc_info.value)
        assert "Invalid scenario" in error_msg or "Valid scenarios" in error_msg, (
            f"ValueError message does not mention invalid/valid scenarios: {error_msg}"
        )

    @given(invalid_scenario=invalid_scenario_strategy)
    @settings(max_examples=100)
    def test_invalid_scenario_error_lists_valid_options(
        self,
        invalid_scenario: str,
    ) -> None:
        """ValueError message includes the list of valid scenario names."""
        import pytest

        mock_hia = _make_mock_health_aggregator(0.8)
        mock_dct = _make_mock_degradation_tracker(-0.01)

        projector = MonteCarloProjector(mock_hia, mock_dct)
        simulator = WhatIfSimulator(projector)

        with pytest.raises(ValueError) as exc_info:
            simulator.simulate_scenario(
                engine_id=1,
                scenario=invalid_scenario,
                horizon_cycles=50,
            )

        error_msg = str(exc_info.value)
        # Check that at least some valid scenarios are mentioned in the error
        assert "normal" in error_msg or "high_stress" in error_msg, (
            f"ValueError message does not list valid scenarios: {error_msg}"
        )


# ---------------------------------------------------------------------------
# Property 12: Maintenance Reset Improves Health at Reset Point
# ---------------------------------------------------------------------------


class TestMaintenanceResetImprovesHealth:
    """Feature: digital-twin-v1.3, Property 12: Maintenance Reset Improves Health at Reset Point

    For any engine with degradation data, and any maintenance_at_cycle and
    reset_fraction > 0, the median trajectory value immediately after the
    maintenance cycle SHALL be greater than the median value immediately
    before the maintenance cycle.

    **Validates: Requirements 5.4**
    """

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        reset_fraction=reset_fraction_strategy,
    )
    @settings(max_examples=100)
    def test_maintenance_reset_improves_median_health_at_reset_point(
        self,
        health_index: float,
        rate: float,
        reset_fraction: float,
    ) -> None:
        """Median trajectory after maintenance > median before maintenance at reset point.

        We use a fixed horizon and maintenance_at_cycle to ensure there are
        enough cycles before and after maintenance for a meaningful comparison.
        """
        horizon_cycles = 40
        maintenance_at_cycle = 20

        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)

        projector = MonteCarloProjector(mock_hia, mock_dct)
        simulator = WhatIfSimulator(projector)

        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=horizon_cycles,
            maintenance_at_cycle=maintenance_at_cycle,
            reset_fraction=reset_fraction,
        )

        # The median (p50) just before maintenance = index maintenance_at_cycle - 1
        # The median (p50) just after maintenance = index maintenance_at_cycle
        median_before = result.trajectory_percentiles[50][maintenance_at_cycle - 1]
        median_after = result.trajectory_percentiles[50][maintenance_at_cycle]

        assert median_after > median_before, (
            f"Maintenance reset did not improve health at reset point: "
            f"median_before={median_before:.6f}, median_after={median_after:.6f}, "
            f"reset_fraction={reset_fraction:.3f}, health_index={health_index:.3f}, "
            f"rate={rate:.6f}"
        )

    @given(
        health_index=health_index_strategy,
        rate=degradation_rate_strategy,
        reset_fraction=reset_fraction_strategy,
        maintenance_at_cycle=st.integers(min_value=5, max_value=30),
    )
    @settings(max_examples=100)
    def test_maintenance_reset_preserves_trajectory_length(
        self,
        health_index: float,
        rate: float,
        reset_fraction: float,
        maintenance_at_cycle: int,
    ) -> None:
        """Maintenance reset result has combined trajectory of correct total length."""
        horizon_cycles = maintenance_at_cycle + 15  # Ensure remaining_cycles > 0

        mock_hia = _make_mock_health_aggregator(health_index)
        mock_dct = _make_mock_degradation_tracker(rate)

        projector = MonteCarloProjector(mock_hia, mock_dct)
        simulator = WhatIfSimulator(projector)

        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=horizon_cycles,
            maintenance_at_cycle=maintenance_at_cycle,
            reset_fraction=reset_fraction,
        )

        # Combined trajectory should have exactly horizon_cycles entries
        for pct in [5, 25, 50, 75, 95]:
            assert len(result.trajectory_percentiles[pct]) == horizon_cycles, (
                f"Percentile {pct}: expected length {horizon_cycles}, "
                f"got {len(result.trajectory_percentiles[pct])}"
            )
