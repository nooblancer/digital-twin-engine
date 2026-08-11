"""Monte Carlo forward projection for engine health index.

Projects engine health forward by sampling degradation rates from the fitted
distribution (from DegradationCurveTracker) and projecting health index forward
using pure NumPy vectorized operations. No neural network or ML model inference.

Algorithm:
    1. Get current health index from HealthIndexAggregator
    2. Compute degradation rate mean (from DegradationCurveTracker slope)
    3. Compute degradation rate std (from trajectory residuals, floor at 5% of mean)
    4. Sample N degradation rates: Normal(|rate_mean|, rate_std * stress_factor)
    5. Project forward vectorized: HI[t+1] = HI[t] - sampled_rate
    6. Compute percentiles across trajectories at each step
    7. Compute failure probability per cycle (fraction crossing threshold)
    8. Compute RUL statistics from crossing distribution

Performance: <50ms for 1000 trajectories x 50 steps (pure NumPy vectorized).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from digital_twin_engine.prognostics.degradation_tracker import (
        DegradationCurveTracker,
    )
    from digital_twin_engine.prognostics.health_index import HealthIndexAggregator

# Health index value below which engine is considered in critical condition
CRITICAL_THRESHOLD = 0.4


@dataclass
class ProjectionResult:
    """Result of a Monte Carlo forward projection.

    Attributes:
        percentiles: Dict mapping percentile level (5, 25, 50, 75, 95) to
            a list of health index values at each projected cycle.
        failure_probability_by_cycle: Per-cycle cumulative probability that
            health index has crossed CRITICAL_THRESHOLD by that cycle.
        expected_rul: Median cycle at which health index crosses the threshold,
            or None if no trajectories cross within the horizon.
        confidence_interval_90: Tuple (5th percentile RUL, 95th percentile RUL)
            across trajectories that cross the threshold, or None.
    """

    percentiles: Dict[int, List[float]]
    failure_probability_by_cycle: List[float]
    expected_rul: Optional[int]
    confidence_interval_90: Optional[Tuple[int, int]]


class MonteCarloProjector:
    """Project engine health forward by sampling from degradation parameters.

    Uses the fitted degradation rate (from DegradationCurveTracker) and its
    uncertainty to generate trajectories. Pure NumPy math — no LSTM/XGBoost
    inference needed.

    The projector obtains:
    - Current health index from HealthIndexAggregator.get_health_state()
    - Fitted degradation rate (slope) from DegradationCurveTracker.compute_degradation_rate()
    - Rate uncertainty from trajectory residuals via DegradationCurveTracker.get_trajectory()
    """

    def __init__(
        self,
        health_index_aggregator: HealthIndexAggregator,
        degradation_tracker: DegradationCurveTracker,
    ) -> None:
        """Initialize the projector with references to prognostics components.

        Args:
            health_index_aggregator: Provides current engine health index.
            degradation_tracker: Provides fitted degradation rate and trajectory.
        """
        self._health_aggregator = health_index_aggregator
        self._degradation_tracker = degradation_tracker

    def project(
        self,
        engine_id: int,
        horizon_cycles: int = 50,
        num_trajectories: int = 1000,
        stress_factor: float = 1.0,
    ) -> ProjectionResult:
        """Run Monte Carlo forward projection for an engine.

        Samples degradation rates from Normal(|rate_mean|, rate_std * stress_factor),
        projects health index forward vectorized, computes percentiles, failure
        probabilities, and RUL statistics.

        Args:
            engine_id: Engine to project.
            horizon_cycles: Number of future cycles to project (1-200).
            num_trajectories: Number of sampled trajectories (default 1000).
            stress_factor: Multiplier on degradation rate std (0.5-2.0).
                Higher values produce wider uncertainty fans.

        Returns:
            ProjectionResult with percentiles, failure probabilities, and RUL stats.

        Raises:
            ValueError: If engine has no health data or insufficient trajectory
                data for degradation rate computation.
        """
        # Step 1: Get current health index
        health_state = self._health_aggregator.get_health_state(engine_id)
        if health_state is None:
            raise ValueError(f"No health data for engine {engine_id}")
        current_hi = health_state.health_index

        # Step 2: Get degradation rate (slope is negative for degrading engines)
        rate_mean = self._degradation_tracker.compute_degradation_rate(engine_id)
        if rate_mean is None:
            raise ValueError(
                f"Insufficient trajectory data to compute degradation rate "
                f"for engine {engine_id} (need at least 20 cycles)"
            )

        # Use absolute value — we subtract rate from HI each step
        abs_rate_mean = abs(rate_mean)

        # Step 3: Compute rate std from trajectory residuals
        rate_std = self._compute_rate_std(engine_id, abs_rate_mean)

        # Step 4: Sample degradation rates (vectorized)
        # Shape: (num_trajectories,)
        sampled_rates = np.random.normal(
            abs_rate_mean,
            rate_std * stress_factor,
            size=num_trajectories,
        )
        # Clamp to non-negative (engines don't heal spontaneously)
        sampled_rates = np.maximum(sampled_rates, 0.0)

        # Step 5: Project forward (fully vectorized)
        # Shape: (num_trajectories, horizon_cycles + 1)
        trajectories = np.empty((num_trajectories, horizon_cycles + 1))
        trajectories[:, 0] = current_hi
        for t in range(horizon_cycles):
            trajectories[:, t + 1] = trajectories[:, t] - sampled_rates

        # Clamp to [0, 1]
        np.clip(trajectories, 0.0, 1.0, out=trajectories)

        # Step 6: Compute percentiles (exclude initial point — only projected cycles)
        projection = trajectories[:, 1:]  # shape (num_trajectories, horizon_cycles)
        percentiles: Dict[int, List[float]] = {
            5: np.percentile(projection, 5, axis=0).tolist(),
            25: np.percentile(projection, 25, axis=0).tolist(),
            50: np.percentile(projection, 50, axis=0).tolist(),
            75: np.percentile(projection, 75, axis=0).tolist(),
            95: np.percentile(projection, 95, axis=0).tolist(),
        }

        # Step 7: Failure probability by cycle
        # Fraction of trajectories that have crossed CRITICAL_THRESHOLD by each cycle.
        # Once crossed, stays crossed (cumulative).
        crossed = projection <= CRITICAL_THRESHOLD
        crossed_cumulative = np.maximum.accumulate(crossed, axis=1)
        failure_prob: List[float] = crossed_cumulative.mean(axis=0).tolist()

        # Step 8: RUL statistics from crossing distribution
        expected_rul, ci_90 = self._compute_rul_stats(trajectories, horizon_cycles)

        return ProjectionResult(
            percentiles=percentiles,
            failure_probability_by_cycle=failure_prob,
            expected_rul=expected_rul,
            confidence_interval_90=ci_90,
        )

    def _compute_rate_std(self, engine_id: int, rate_mean: float) -> float:
        """Compute standard deviation of degradation rate from trajectory residuals.

        Computes cycle-to-cycle health index differences from the stored
        trajectory and takes the standard deviation. This measures the
        noise in the degradation process — how variable the per-cycle
        health loss is.

        The result is floored at 5% of the mean rate to avoid degenerate
        zero-variance projections that would collapse all trajectories to
        a single line.

        Args:
            engine_id: The engine unit identifier.
            rate_mean: Absolute value of the mean degradation rate.

        Returns:
            Standard deviation of the degradation rate, floored at 5% of mean.
        """
        trajectory = self._degradation_tracker.get_trajectory(engine_id)

        if len(trajectory) < 20:
            # Not enough data — use 20% of mean as default uncertainty
            return abs(rate_mean) * 0.2

        # Compute cycle-to-cycle health index differences
        hi_values = np.array([hi for _, hi in trajectory])
        diffs = np.diff(hi_values)

        # Rate std is the std of the absolute differences
        # (they should be ~constant for linear degradation)
        rate_std = float(np.std(np.abs(diffs)))

        # Floor at 5% of mean to avoid degenerate zero-variance projections
        return max(rate_std, abs(rate_mean) * 0.05)

    def _compute_rul_stats(
        self, trajectories: np.ndarray, horizon_cycles: int
    ) -> Tuple[Optional[int], Optional[Tuple[int, int]]]:
        """Compute RUL median and 90% confidence interval from crossing distribution.

        Finds the first cycle where each trajectory crosses CRITICAL_THRESHOLD.
        Computes the median crossing cycle (expected RUL) and the 5th/95th
        percentiles of the crossing distribution (90% CI).

        Args:
            trajectories: Array of shape (num_trajectories, horizon_cycles + 1)
                containing the full projected health index values.
            horizon_cycles: Number of projected cycles.

        Returns:
            Tuple of (expected_rul, confidence_interval_90) where:
            - expected_rul is the median cycle at which HI crosses threshold
            - confidence_interval_90 is (5th percentile, 95th percentile)
            Both are None if no trajectories cross within the horizon.
        """
        # Work with projected portion only (excluding initial HI)
        projection = trajectories[:, 1:]  # shape (N, horizon_cycles)

        # For each trajectory, find first cycle where HI <= CRITICAL_THRESHOLD
        # Use vectorized approach: argmax on boolean array finds first True
        crossed = projection <= CRITICAL_THRESHOLD

        # any() along axis=1 tells which trajectories cross at all
        any_crossed = crossed.any(axis=1)

        if not any_crossed.any():
            # No trajectories cross threshold within horizon
            return None, None

        # argmax on boolean array gives index of first True per row
        # Only meaningful for rows that actually cross
        first_crossing = crossed.argmax(axis=1)  # shape (N,)

        # Filter to only trajectories that actually cross
        crossing_cycles = first_crossing[any_crossed] + 1  # +1 for 1-indexed cycles

        expected_rul = int(np.median(crossing_cycles))
        ci_low = int(np.percentile(crossing_cycles, 5))
        ci_high = int(np.percentile(crossing_cycles, 95))

        return expected_rul, (ci_low, ci_high)
