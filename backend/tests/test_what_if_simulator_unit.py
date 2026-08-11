"""Unit tests for WhatIfSimulator class.

Tests named scenario structure, maintenance_reset behavior (reset_fraction=0
equals normal, reset_fraction=1.0 resets to near-full health), and invalid
scenario rejection with helpful error messages.

Validates: Requirements 5.1–5.6
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from digital_twin_engine.prognostics.models import EngineHealthState
from digital_twin_engine.simulation.monte_carlo_projector import (
    CRITICAL_THRESHOLD,
    MonteCarloProjector,
)
from digital_twin_engine.simulation.what_if_simulator import (
    SCENARIO_STRESS_MAP,
    VALID_SCENARIOS,
    SimulationResult,
    WhatIfSimulator,
)


# ---------------------------------------------------------------------------
# Helpers — Mock Setup
# ---------------------------------------------------------------------------


def _make_simulator(
    health_index: float = 0.85,
    degradation_rate: float = -0.005,
    trajectory_length: int = 30,
) -> WhatIfSimulator:
    """Create a WhatIfSimulator with mocked prognostics dependencies.

    Args:
        health_index: Current health index for the mock engine.
        degradation_rate: Slope returned by compute_degradation_rate.
        trajectory_length: Number of points in get_trajectory().

    Returns:
        WhatIfSimulator wrapping a MonteCarloProjector with mocked deps.
    """
    mock_health_agg = MagicMock()
    mock_health_agg.get_health_state.return_value = EngineHealthState(
        engine_id=1,
        health_index=health_index,
        cycle_count=trajectory_length,
        is_provisional=False,
        last_update_cycle=trajectory_length,
    )

    mock_deg_tracker = MagicMock()
    mock_deg_tracker.compute_degradation_rate.return_value = degradation_rate

    # Build a realistic trajectory: linearly degrading from ~1.0 with some noise
    trajectory = []
    hi = 1.0
    rng = np.random.default_rng(42)
    for cycle in range(1, trajectory_length + 1):
        hi += degradation_rate + rng.normal(0, 0.001)
        hi = max(0.0, min(1.0, hi))
        trajectory.append((cycle, hi))
    mock_deg_tracker.get_trajectory.return_value = trajectory

    projector = MonteCarloProjector(
        health_index_aggregator=mock_health_agg,
        degradation_tracker=mock_deg_tracker,
    )

    return WhatIfSimulator(projector=projector)


# ---------------------------------------------------------------------------
# Tests: Named Scenarios Return Expected Structure (Requirement 5.5)
# ---------------------------------------------------------------------------


class TestNamedScenarioStructure:
    """Verify each named scenario returns a well-formed SimulationResult."""

    @pytest.mark.parametrize("scenario", ["normal", "high_stress", "low_stress"])
    def test_scenario_returns_simulation_result(self, scenario: str) -> None:
        """Each non-maintenance scenario returns a SimulationResult with
        all required fields populated.
        """
        simulator = _make_simulator()
        result = simulator.simulate_scenario(engine_id=1, scenario=scenario)

        assert isinstance(result, SimulationResult)
        assert isinstance(result.trajectory_percentiles, dict)
        assert isinstance(result.failure_probability_curve, list)

    @pytest.mark.parametrize("scenario", ["normal", "high_stress", "low_stress"])
    def test_scenario_has_correct_percentile_keys(self, scenario: str) -> None:
        """Each scenario result has exactly the 5 percentile keys (5, 25, 50, 75, 95)."""
        simulator = _make_simulator()
        result = simulator.simulate_scenario(engine_id=1, scenario=scenario)

        assert set(result.trajectory_percentiles.keys()) == {5, 25, 50, 75, 95}

    @pytest.mark.parametrize("scenario", ["normal", "high_stress", "low_stress"])
    def test_scenario_percentile_arrays_match_horizon(self, scenario: str) -> None:
        """Each percentile array has length equal to horizon_cycles."""
        horizon = 30
        simulator = _make_simulator()
        result = simulator.simulate_scenario(
            engine_id=1, scenario=scenario, horizon_cycles=horizon
        )

        for pct_key, values in result.trajectory_percentiles.items():
            assert len(values) == horizon, (
                f"Percentile {pct_key} has length {len(values)}, expected {horizon}"
            )

    @pytest.mark.parametrize("scenario", ["normal", "high_stress", "low_stress"])
    def test_scenario_failure_prob_length_matches_horizon(self, scenario: str) -> None:
        """Failure probability curve has length equal to horizon_cycles."""
        horizon = 40
        simulator = _make_simulator()
        result = simulator.simulate_scenario(
            engine_id=1, scenario=scenario, horizon_cycles=horizon
        )

        assert len(result.failure_probability_curve) == horizon

    def test_maintenance_reset_returns_simulation_result(self) -> None:
        """maintenance_reset scenario returns a valid SimulationResult."""
        simulator = _make_simulator()
        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=50,
            maintenance_at_cycle=25,
            reset_fraction=0.5,
        )

        assert isinstance(result, SimulationResult)
        assert set(result.trajectory_percentiles.keys()) == {5, 25, 50, 75, 95}
        # Combined length should be full horizon
        for pct_key, values in result.trajectory_percentiles.items():
            assert len(values) == 50, (
                f"Percentile {pct_key} has length {len(values)}, expected 50"
            )

    def test_maintenance_reset_failure_prob_length(self) -> None:
        """maintenance_reset failure probability curve spans full horizon."""
        simulator = _make_simulator()
        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=50,
            maintenance_at_cycle=25,
            reset_fraction=0.5,
        )

        assert len(result.failure_probability_curve) == 50


# ---------------------------------------------------------------------------
# Tests: maintenance_reset with reset_fraction=0 (Requirement 5.4)
# ---------------------------------------------------------------------------


class TestMaintenanceResetFractionZero:
    """Verify reset_fraction=0 produces results equivalent to normal scenario.

    When reset_fraction=0, the maintenance event has no effect — health index
    is not restored at all: new_HI = old_HI + (1.0 - old_HI) * 0 = old_HI.
    The combined trajectory should closely match a normal projection.
    """

    def test_reset_fraction_zero_median_similar_to_normal(self) -> None:
        """reset_fraction=0 median trajectory should be close to normal scenario.

        Since reset_fraction=0 means no health recovery, the after-maintenance
        projection starts from the same HI it would have degraded to anyway.
        Due to random sampling, we compare medians within a tolerance.
        """
        np.random.seed(100)
        simulator = _make_simulator()
        result_normal = simulator.simulate_scenario(
            engine_id=1, scenario="normal", horizon_cycles=50
        )

        np.random.seed(100)
        simulator2 = _make_simulator()
        result_reset_zero = simulator2.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=50,
            maintenance_at_cycle=25,
            reset_fraction=0.0,
        )

        # The before-maintenance portion (first 25 cycles) should be very similar
        # since both use stress_factor=1.0
        normal_median_before = result_normal.trajectory_percentiles[50][:25]
        reset_median_before = result_reset_zero.trajectory_percentiles[50][:25]

        # With same seed, these should be identical
        np.testing.assert_allclose(
            normal_median_before,
            reset_median_before,
            atol=0.001,
            err_msg="Before-maintenance portion should match normal scenario",
        )

    def test_reset_fraction_zero_no_health_jump(self) -> None:
        """reset_fraction=0 should not show a health index jump at the reset point.

        The median at the maintenance cycle boundary should be continuous
        (no sudden increase) because no health is restored.
        """
        np.random.seed(200)
        simulator = _make_simulator(health_index=0.80, degradation_rate=-0.008)
        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=50,
            maintenance_at_cycle=25,
            reset_fraction=0.0,
        )

        # The median at cycle 25 (before maintenance) and cycle 26 (after) should
        # be very close — no jump because reset_fraction=0 means no recovery
        median_at_25 = result.trajectory_percentiles[50][24]  # 0-indexed
        median_at_26 = result.trajectory_percentiles[50][25]

        # After should be <= before (continued degradation, no recovery)
        assert median_at_26 <= median_at_25 + 0.01, (
            f"Median at cycle 26 ({median_at_26:.4f}) should not jump above "
            f"cycle 25 ({median_at_25:.4f}) with reset_fraction=0"
        )


# ---------------------------------------------------------------------------
# Tests: maintenance_reset with reset_fraction=1.0 (Requirement 5.4)
# ---------------------------------------------------------------------------


class TestMaintenanceResetFractionOne:
    """Verify reset_fraction=1.0 resets health to near 1.0.

    Formula: new_HI = old_HI + (1.0 - old_HI) * 1.0 = 1.0
    So with reset_fraction=1.0, the engine should be fully restored.
    """

    def test_reset_fraction_one_shows_health_jump(self) -> None:
        """reset_fraction=1.0 should produce a visible health recovery.

        The median trajectory after the maintenance cycle should be
        significantly higher than just before maintenance.
        """
        np.random.seed(300)
        simulator = _make_simulator(health_index=0.75, degradation_rate=-0.01)
        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=50,
            maintenance_at_cycle=20,
            reset_fraction=1.0,
        )

        # Median just before maintenance (cycle 20, 0-indexed = 19)
        median_before = result.trajectory_percentiles[50][19]
        # Median just after maintenance (cycle 21, 0-indexed = 20)
        median_after = result.trajectory_percentiles[50][20]

        # After full reset, health should jump significantly upward
        assert median_after > median_before, (
            f"After full reset, median should jump up. "
            f"Before: {median_before:.4f}, After: {median_after:.4f}"
        )

    def test_reset_fraction_one_resets_to_near_full_health(self) -> None:
        """reset_fraction=1.0 resets HI to ~1.0, so the post-maintenance
        trajectory should start near 1.0.

        Formula: new_HI = old_HI + (1.0 - old_HI) * 1.0 = 1.0
        """
        np.random.seed(400)
        simulator = _make_simulator(health_index=0.70, degradation_rate=-0.01)
        result = simulator.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=40,
            maintenance_at_cycle=15,
            reset_fraction=1.0,
        )

        # The first cycle after maintenance (cycle 16, 0-indexed = 15)
        # should be close to 1.0 because reset_hi = old + (1-old)*1.0 = 1.0
        # Then one cycle of degradation applies, so it will be slightly below 1.0
        median_after_reset = result.trajectory_percentiles[50][15]

        # Should be near 1.0 (allowing for one cycle of degradation from 1.0)
        assert median_after_reset > 0.95, (
            f"After full reset, median should be near 1.0 but got {median_after_reset:.4f}"
        )

    def test_reset_fraction_one_extends_rul(self) -> None:
        """Full maintenance reset should produce a longer RUL than no maintenance.

        When health is fully restored, the engine should have more cycles
        before reaching the critical threshold compared to normal degradation.
        """
        np.random.seed(500)
        simulator = _make_simulator(health_index=0.65, degradation_rate=-0.012)
        result_normal = simulator.simulate_scenario(
            engine_id=1, scenario="normal", horizon_cycles=50
        )

        np.random.seed(500)
        simulator2 = _make_simulator(health_index=0.65, degradation_rate=-0.012)
        result_maint = simulator2.simulate_scenario(
            engine_id=1,
            scenario="maintenance_reset",
            horizon_cycles=50,
            maintenance_at_cycle=10,
            reset_fraction=1.0,
        )

        # After full maintenance, the final failure probability should be lower
        # because the engine was restored to health
        final_fp_normal = result_normal.failure_probability_curve[-1]
        final_fp_maint = result_maint.failure_probability_curve[-1]

        assert final_fp_maint < final_fp_normal, (
            f"Maintenance should reduce final failure probability. "
            f"Normal: {final_fp_normal:.4f}, After maintenance: {final_fp_maint:.4f}"
        )


# ---------------------------------------------------------------------------
# Tests: Invalid Scenario Raises ValueError (Requirement 5.6)
# ---------------------------------------------------------------------------


class TestInvalidScenarioRejection:
    """Verify invalid scenario names raise ValueError with helpful message."""

    def test_invalid_scenario_raises_valueerror(self) -> None:
        """An unrecognized scenario name raises ValueError."""
        simulator = _make_simulator()

        with pytest.raises(ValueError):
            simulator.simulate_scenario(engine_id=1, scenario="turbo_mode")

    def test_invalid_scenario_error_message_includes_scenario_name(self) -> None:
        """The error message includes the invalid scenario that was provided."""
        simulator = _make_simulator()

        with pytest.raises(ValueError, match="turbo_mode"):
            simulator.simulate_scenario(engine_id=1, scenario="turbo_mode")

    def test_invalid_scenario_error_message_lists_valid_options(self) -> None:
        """The error message lists the valid scenario options for guidance."""
        simulator = _make_simulator()

        with pytest.raises(ValueError, match="Valid scenarios"):
            simulator.simulate_scenario(engine_id=1, scenario="invalid_thing")

    @pytest.mark.parametrize(
        "bad_scenario",
        ["", "NORMAL", "High_Stress", "maintenance-reset", "stress_test", "reset"],
    )
    def test_various_invalid_scenarios_rejected(self, bad_scenario: str) -> None:
        """Various typos and wrong-case variants are all rejected."""
        simulator = _make_simulator()

        with pytest.raises(ValueError, match="Invalid scenario"):
            simulator.simulate_scenario(engine_id=1, scenario=bad_scenario)

    def test_valid_scenarios_do_not_raise(self) -> None:
        """All valid scenarios execute without raising ValueError."""
        simulator = _make_simulator()

        for scenario in VALID_SCENARIOS:
            # Should not raise — just verify no exception
            if scenario == "maintenance_reset":
                result = simulator.simulate_scenario(
                    engine_id=1,
                    scenario=scenario,
                    maintenance_at_cycle=10,
                    reset_fraction=0.5,
                )
            else:
                result = simulator.simulate_scenario(engine_id=1, scenario=scenario)
            assert isinstance(result, SimulationResult)
