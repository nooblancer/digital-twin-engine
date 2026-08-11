"""What-If Simulator for scenario-based engine health projection.

Wraps MonteCarloProjector with named scenarios (normal, high_stress,
low_stress, maintenance_reset) for user-friendly interaction via the
simulation REST API.

Scenarios:
    - "normal": Continue at current degradation rate (stress_factor=1.0)
    - "high_stress": 1.5x degradation rate std (stress_factor=1.5)
    - "low_stress": 0.5x degradation rate std (stress_factor=0.5)
    - "maintenance_reset": Partial health reset at specified cycle, then
      continue projection from the reset value

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

from digital_twin_engine.simulation.monte_carlo_projector import (
    CRITICAL_THRESHOLD,
    MonteCarloProjector,
    ProjectionResult,
)

if TYPE_CHECKING:
    pass

# Valid named scenarios
VALID_SCENARIOS = ("normal", "high_stress", "low_stress", "maintenance_reset")

# Stress factor mapping for non-maintenance scenarios
SCENARIO_STRESS_MAP: Dict[str, float] = {
    "normal": 1.0,
    "high_stress": 1.5,
    "low_stress": 0.5,
}


@dataclass
class SimulationResult:
    """Result of a what-if simulation.

    Attributes:
        trajectory_percentiles: Dict mapping percentile level (5, 25, 50, 75, 95)
            to a list of health index values at each projected cycle.
        rul_estimate: Median cycle at which health index crosses CRITICAL_THRESHOLD,
            or None if no trajectories cross within the horizon.
        rul_confidence_90: Tuple (5th percentile RUL, 95th percentile RUL),
            or None if RUL cannot be estimated.
        failure_probability_curve: Per-cycle cumulative probability that
            health index has crossed CRITICAL_THRESHOLD by that cycle.
    """

    trajectory_percentiles: Dict[int, List[float]]
    rul_estimate: Optional[int]
    rul_confidence_90: Optional[Tuple[int, int]]
    failure_probability_curve: List[float]


class WhatIfSimulator:
    """Simulate engine behavior under different operational conditions.

    Uses MonteCarloProjector internally but exposes scenario-based
    API for user-friendly interaction. Named scenarios map to specific
    stress factors, while simulate_stress_factor() accepts arbitrary
    slider values.
    """

    def __init__(self, projector: MonteCarloProjector) -> None:
        """Initialize the simulator with a MonteCarloProjector.

        Args:
            projector: The MonteCarloProjector instance to use for
                forward health index projection.
        """
        self._projector = projector

    def simulate_scenario(
        self,
        engine_id: int,
        scenario: str,
        horizon_cycles: int = 50,
        maintenance_at_cycle: Optional[int] = None,
        reset_fraction: float = 0.5,
    ) -> SimulationResult:
        """Run a named what-if scenario.

        Args:
            engine_id: Target engine.
            scenario: One of "normal", "high_stress", "low_stress",
                "maintenance_reset".
            horizon_cycles: Forward projection horizon (1-200).
            maintenance_at_cycle: Cycle at which maintenance occurs
                (maintenance_reset only). Defaults to horizon_cycles // 2.
            reset_fraction: How much health is recovered (0.0-1.0,
                maintenance_reset only). 0.0 = no recovery, 1.0 = full reset.

        Returns:
            SimulationResult with trajectory percentiles, RUL estimate,
            and failure probability curve.

        Raises:
            ValueError: If scenario is not one of the valid options.
        """
        if scenario not in VALID_SCENARIOS:
            raise ValueError(
                f"Invalid scenario '{scenario}'. "
                f"Valid scenarios: {list(VALID_SCENARIOS)}"
            )

        if scenario == "maintenance_reset":
            return self._simulate_maintenance_reset(
                engine_id, horizon_cycles, maintenance_at_cycle, reset_fraction
            )

        stress_factor = SCENARIO_STRESS_MAP[scenario]
        result = self._projector.project(
            engine_id=engine_id,
            horizon_cycles=horizon_cycles,
            stress_factor=stress_factor,
        )

        return SimulationResult(
            trajectory_percentiles=result.percentiles,
            rul_estimate=result.expected_rul,
            rul_confidence_90=result.confidence_interval_90,
            failure_probability_curve=result.failure_probability_by_cycle,
        )

    def simulate_stress_factor(
        self,
        engine_id: int,
        stress_factor: float,
        horizon_cycles: int = 50,
    ) -> SimulationResult:
        """Run simulation with an arbitrary stress factor (for slider use).

        Called by the API when the frontend stress slider sends a custom
        stress_factor value. This allows continuous exploration of the
        degradation rate uncertainty space.

        Args:
            engine_id: Target engine.
            stress_factor: Degradation rate std multiplier (0.5-2.0).
                Higher values produce wider uncertainty fans.
            horizon_cycles: Forward projection horizon (1-200).

        Returns:
            SimulationResult with trajectory percentiles, RUL estimate,
            and failure probability curve.
        """
        result = self._projector.project(
            engine_id=engine_id,
            horizon_cycles=horizon_cycles,
            stress_factor=stress_factor,
        )
        return SimulationResult(
            trajectory_percentiles=result.percentiles,
            rul_estimate=result.expected_rul,
            rul_confidence_90=result.confidence_interval_90,
            failure_probability_curve=result.failure_probability_by_cycle,
        )

    def _simulate_maintenance_reset(
        self,
        engine_id: int,
        horizon_cycles: int,
        maintenance_at_cycle: Optional[int],
        reset_fraction: float,
    ) -> SimulationResult:
        """Simulate maintenance intervention that partially restores health.

        Projects normally until maintenance_at_cycle, then resets HI by
        reset_fraction * (1.0 - current_HI) at the maintenance cycle,
        and continues projection from the reset value.

        The reset formula is:
            new_HI = old_HI + (1.0 - old_HI) * reset_fraction

        This models realistic maintenance where:
        - reset_fraction=0.0 → no recovery (same as normal projection)
        - reset_fraction=0.5 → recover half the lost health
        - reset_fraction=1.0 → full reset to HI=1.0

        Args:
            engine_id: Target engine.
            horizon_cycles: Total forward projection horizon.
            maintenance_at_cycle: Cycle at which maintenance occurs.
                Defaults to horizon_cycles // 2 if None.
            reset_fraction: Fraction of lost health to recover (0.0-1.0).

        Returns:
            SimulationResult combining before-maintenance and
            after-maintenance projections.
        """
        if maintenance_at_cycle is None:
            maintenance_at_cycle = horizon_cycles // 2

        # Project before maintenance
        before_result = self._projector.project(
            engine_id=engine_id,
            horizon_cycles=maintenance_at_cycle,
            stress_factor=1.0,
        )

        # Get median HI at maintenance point
        median_at_maint = before_result.percentiles[50][maintenance_at_cycle - 1]
        # Apply reset: new_HI = old_HI + (1.0 - old_HI) * reset_fraction
        reset_hi = median_at_maint + (1.0 - median_at_maint) * reset_fraction

        # Project remaining cycles from reset point
        remaining_cycles = horizon_cycles - maintenance_at_cycle
        if remaining_cycles <= 0:
            return SimulationResult(
                trajectory_percentiles=before_result.percentiles,
                rul_estimate=before_result.expected_rul,
                rul_confidence_90=before_result.confidence_interval_90,
                failure_probability_curve=before_result.failure_probability_by_cycle,
            )

        # Manually project from the reset health index
        # Access projector internals to get degradation parameters
        rate_mean = abs(
            self._projector._degradation_tracker.compute_degradation_rate(engine_id)
        )
        rate_std = self._projector._compute_rate_std(engine_id, rate_mean)

        # Sample degradation rates for the after-maintenance projection
        num_trajectories = 1000
        sampled_rates = np.random.normal(rate_mean, rate_std, size=num_trajectories)
        sampled_rates = np.maximum(sampled_rates, 0.0)

        # Project forward from the reset HI
        after_trajectories = np.zeros((num_trajectories, remaining_cycles + 1))
        after_trajectories[:, 0] = reset_hi
        for t in range(remaining_cycles):
            after_trajectories[:, t + 1] = after_trajectories[:, t] - sampled_rates
        after_trajectories = np.clip(after_trajectories, 0.0, 1.0)

        after_projection = after_trajectories[:, 1:]

        # Combine before + after percentiles
        combined_percentiles: Dict[int, List[float]] = {}
        for pct in [5, 25, 50, 75, 95]:
            before_vals = before_result.percentiles[pct]
            after_vals = np.percentile(after_projection, pct, axis=0).tolist()
            combined_percentiles[pct] = before_vals + after_vals

        # Compute combined failure probability
        before_fp = before_result.failure_probability_by_cycle
        after_crossed = after_projection <= CRITICAL_THRESHOLD
        after_cum = np.maximum.accumulate(after_crossed, axis=1)
        after_fp = after_cum.mean(axis=0).tolist()
        combined_fp = before_fp + after_fp

        # RUL from combined failure probability curve
        # Expected RUL is the first cycle where cumulative failure prob >= 50%
        expected_rul: Optional[int] = None
        ci_90: Optional[Tuple[int, int]] = None
        for i, fp in enumerate(combined_fp):
            if fp >= 0.5 and expected_rul is None:
                expected_rul = i + 1

        return SimulationResult(
            trajectory_percentiles=combined_percentiles,
            rul_estimate=expected_rul,
            rul_confidence_90=ci_90,
            failure_probability_curve=combined_fp,
        )
