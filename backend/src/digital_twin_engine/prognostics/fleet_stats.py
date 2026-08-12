"""Fleet Statistics Aggregator for fleet-wide health monitoring.

Queries all active engines from HealthIndexAggregator, categorizes them by
health thresholds (nominal/degraded/critical/calibrating), computes the
fleet-wide average health index (excluding calibrating engines), and uses
MonteCarloProjector to count engines predicted to reach critical within a
configurable horizon.

Engines in baseline calibration period (cycle_count <= 10) report a
provisional HI=1.0 that does not reflect real degradation data. These
engines are counted in total_engines but excluded from the health average
and categorized separately as "calibrating."

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from digital_twin_engine.prognostics.health_index import HealthIndexAggregator
    from digital_twin_engine.simulation.monte_carlo_projector import MonteCarloProjector

from digital_twin_engine.shared.logging import get_logger

logger = get_logger("fleet_stats_aggregator")


# ---------------------------------------------------------------------------
# Response Data Class
# ---------------------------------------------------------------------------


@dataclass
class FleetStatsResponse:
    """Aggregate fleet statistics response.

    Attributes:
        total_engines: Total number of engines tracked (includes calibrating).
        nominal_count: Engines with health_index > 0.7 (post-baseline only).
        degraded_count: Engines with 0.4 < health_index <= 0.7 (post-baseline only).
        critical_count: Engines with health_index <= 0.4 (post-baseline only).
        calibrating_count: Engines still in baseline period (cycle_count <= 10).
        average_fleet_health_index: Arithmetic mean of post-baseline engine HIs,
            or None if no post-baseline engines exist.
        predicted_maintenance_events: Count of engines predicted to reach critical
            within the horizon (from MonteCarloProjector).
        horizon_cycles: The projection horizon used (default 50).

    Invariant:
        nominal_count + degraded_count + critical_count + calibrating_count == total_engines
    """

    total_engines: int
    nominal_count: int
    degraded_count: int
    critical_count: int
    calibrating_count: int
    average_fleet_health_index: Optional[float]
    predicted_maintenance_events: int
    horizon_cycles: int


# ---------------------------------------------------------------------------
# Fleet Stats Aggregator
# ---------------------------------------------------------------------------


class FleetStatsAggregator:
    """Aggregates fleet-wide health statistics from engine health states.

    Queries HealthIndexAggregator for all tracked engines, categorizes each
    engine by its health index, computes fleet average (excluding calibrating
    engines), and uses MonteCarloProjector to estimate upcoming maintenance
    events within a configurable horizon.
    """

    BASELINE_CYCLES = 10  # Engines with cycle_count <= this are "calibrating"

    def __init__(
        self,
        health_index_aggregator: "HealthIndexAggregator",
        monte_carlo_projector: "MonteCarloProjector",
    ) -> None:
        """Initialize the Fleet Stats Aggregator.

        Args:
            health_index_aggregator: Provides per-engine health state including
                health_index and cycle_count.
            monte_carlo_projector: Provides forward projection to estimate
                failure probability within a horizon.
        """
        self._health_index_aggregator = health_index_aggregator
        self._monte_carlo_projector = monte_carlo_projector

    def get_stats(self, horizon_cycles: int = 50) -> FleetStatsResponse:
        """Compute aggregate fleet statistics.

        Iterates over all tracked engines, categorizes each by health status,
        computes the fleet-wide average health index (excluding calibrating
        engines whose HI=1.0 is provisional), and counts predicted maintenance
        events using MonteCarloProjector.

        Args:
            horizon_cycles: Number of future cycles for maintenance prediction
                (default 50).

        Returns:
            FleetStatsResponse with counts, average, and predictions.
        """
        # Get all engine IDs from the health index aggregator's internal state
        all_engine_ids = list(self._health_index_aggregator._health_states.keys())

        # Handle empty fleet
        if not all_engine_ids:
            return FleetStatsResponse(
                total_engines=0,
                nominal_count=0,
                degraded_count=0,
                critical_count=0,
                calibrating_count=0,
                average_fleet_health_index=None,
                predicted_maintenance_events=0,
                horizon_cycles=horizon_cycles,
            )

        # Categorize engines
        nominal_count = 0
        degraded_count = 0
        critical_count = 0
        calibrating_count = 0
        post_baseline_health_indices: list[float] = []

        for engine_id in all_engine_ids:
            if self._is_in_baseline(engine_id):
                calibrating_count += 1
            else:
                health_state = self._health_index_aggregator.get_health_state(engine_id)
                if health_state is None:
                    # Shouldn't happen since we got the ID from _health_states,
                    # but handle gracefully
                    calibrating_count += 1
                    continue

                hi = health_state.health_index
                post_baseline_health_indices.append(hi)

                category = self.categorize_engine(hi)
                if category == "nominal":
                    nominal_count += 1
                elif category == "degraded":
                    degraded_count += 1
                else:  # critical
                    critical_count += 1

        total_engines = nominal_count + degraded_count + critical_count + calibrating_count

        # Compute average fleet health index (post-baseline engines only)
        if post_baseline_health_indices:
            average_fleet_health_index = sum(post_baseline_health_indices) / len(
                post_baseline_health_indices
            )
        else:
            average_fleet_health_index = None

        # Count predicted maintenance events using MonteCarloProjector
        predicted_maintenance_events = self._count_predicted_maintenance(
            all_engine_ids, horizon_cycles
        )

        return FleetStatsResponse(
            total_engines=total_engines,
            nominal_count=nominal_count,
            degraded_count=degraded_count,
            critical_count=critical_count,
            calibrating_count=calibrating_count,
            average_fleet_health_index=average_fleet_health_index,
            predicted_maintenance_events=predicted_maintenance_events,
            horizon_cycles=horizon_cycles,
        )

    def categorize_engine(self, health_index: float) -> str:
        """Categorize an engine by its health index value.

        Args:
            health_index: The engine's current health index (0.0-1.0).

        Returns:
            'nominal' if health_index > 0.7,
            'degraded' if 0.4 < health_index <= 0.7,
            'critical' if health_index <= 0.4.
        """
        if health_index > 0.7:
            return "nominal"
        elif health_index > 0.4:
            return "degraded"
        else:
            return "critical"

    def _is_in_baseline(self, engine_id: int) -> bool:
        """Check if engine is still in baseline calibration period.

        An engine is in baseline if its cycle_count <= BASELINE_CYCLES.
        During this period, HI=1.0 is provisional and not reflective of
        actual engine health.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            True if engine is in baseline calibration period.
        """
        health_state = self._health_index_aggregator.get_health_state(engine_id)
        if health_state is None:
            # No health state — treat as calibrating
            return True

        return health_state.cycle_count <= self.BASELINE_CYCLES

    def _count_predicted_maintenance(
        self, engine_ids: list[int], horizon_cycles: int
    ) -> int:
        """Count engines predicted to reach critical within the horizon.

        Uses MonteCarloProjector to project each eligible engine's health
        forward and counts those whose median trajectory crosses the critical
        threshold (0.4) within the specified horizon.

        Only post-baseline engines with sufficient data for projection are
        considered. Engines that fail projection (insufficient data, etc.)
        are silently skipped.

        Args:
            engine_ids: All tracked engine IDs.
            horizon_cycles: Number of future cycles to project.

        Returns:
            Count of engines predicted to reach critical within horizon.
        """
        predicted_count = 0

        for engine_id in engine_ids:
            # Skip engines in baseline — they have no real degradation data
            if self._is_in_baseline(engine_id):
                continue

            try:
                result = self._monte_carlo_projector.project(
                    engine_id=engine_id,
                    horizon_cycles=horizon_cycles,
                )
                # Engine is predicted to need maintenance if expected_rul is
                # not None (meaning trajectories cross critical threshold
                # within the horizon)
                if result.expected_rul is not None:
                    predicted_count += 1
            except (ValueError, KeyError):
                # Engine doesn't have enough data for projection — skip
                logger.debug(
                    "Skipping maintenance prediction for engine",
                    engine_id=engine_id,
                    reason="insufficient_data",
                )
                continue

        return predicted_count
