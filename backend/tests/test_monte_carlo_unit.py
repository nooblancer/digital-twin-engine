"""Unit tests for MonteCarloProjector class.

Tests performance constraints, error handling for missing data, and
stress_factor behavior (wider confidence bands at higher stress).

Validates: Requirements 4.1–4.9
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from digital_twin_engine.prognostics.models import EngineHealthState
from digital_twin_engine.simulation.monte_carlo_projector import (
    CRITICAL_THRESHOLD,
    MonteCarloProjector,
    ProjectionResult,
)


# ---------------------------------------------------------------------------
# Helpers — Mock Setup
# ---------------------------------------------------------------------------


def _make_projector(
    health_index: float = 0.85,
    degradation_rate: float = -0.005,
    trajectory_length: int = 30,
) -> MonteCarloProjector:
    """Create a MonteCarloProjector with mocked dependencies.

    Args:
        health_index: Current health index for the mock engine.
        degradation_rate: Slope returned by compute_degradation_rate
            (negative = degrading).
        trajectory_length: Number of points in get_trajectory().
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
    for cycle in range(1, trajectory_length + 1):
        hi += degradation_rate + np.random.normal(0, 0.001)
        hi = max(0.0, min(1.0, hi))
        trajectory.append((cycle, hi))
    mock_deg_tracker.get_trajectory.return_value = trajectory

    return MonteCarloProjector(
        health_index_aggregator=mock_health_agg,
        degradation_tracker=mock_deg_tracker,
    )


# ---------------------------------------------------------------------------
# Tests: Performance (Requirement 4.8)
# ---------------------------------------------------------------------------


class TestMonteCarloPerformance:
    """Verify MonteCarloProjector meets the <50ms performance constraint."""

    def test_project_completes_under_50ms_default_params(self) -> None:
        """project() with default params (1000 trajectories, 50 cycles) < 50ms.

        This is the critical performance requirement (Req 4.8): pure NumPy
        vectorized operations must complete within 50ms.
        """
        projector = _make_projector(health_index=0.85, degradation_rate=-0.005)

        # Warm up NumPy (first call may allocate)
        projector.project(engine_id=1, horizon_cycles=50, num_trajectories=1000)

        # Time the actual call
        start = time.perf_counter()
        result = projector.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=1.0,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50.0, (
            f"project() took {elapsed_ms:.1f}ms, exceeds 50ms budget"
        )
        # Sanity check result is valid
        assert isinstance(result, ProjectionResult)
        assert len(result.percentiles) == 5


# ---------------------------------------------------------------------------
# Tests: ValueError — No Health Data (Requirement 4.9)
# ---------------------------------------------------------------------------


class TestMonteCarloNoHealthData:
    """Verify ValueError when engine has no health data."""

    def test_raises_valueerror_when_no_health_state(self) -> None:
        """project() raises ValueError when get_health_state returns None."""
        mock_health_agg = MagicMock()
        mock_health_agg.get_health_state.return_value = None

        mock_deg_tracker = MagicMock()

        projector = MonteCarloProjector(
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        with pytest.raises(ValueError, match="No health data for engine"):
            projector.project(engine_id=99)

    def test_error_message_includes_engine_id(self) -> None:
        """The ValueError message identifies the problematic engine."""
        mock_health_agg = MagicMock()
        mock_health_agg.get_health_state.return_value = None

        mock_deg_tracker = MagicMock()

        projector = MonteCarloProjector(
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        with pytest.raises(ValueError, match="42"):
            projector.project(engine_id=42)


# ---------------------------------------------------------------------------
# Tests: ValueError — Insufficient Trajectory Data (Requirement 4.9)
# ---------------------------------------------------------------------------


class TestMonteCarloInsufficientData:
    """Verify ValueError when degradation rate cannot be computed."""

    def test_raises_valueerror_when_degradation_rate_is_none(self) -> None:
        """project() raises ValueError when compute_degradation_rate returns None.

        This happens when the DegradationCurveTracker has fewer than 20 cycles
        of data for the engine.
        """
        mock_health_agg = MagicMock()
        mock_health_agg.get_health_state.return_value = EngineHealthState(
            engine_id=1,
            health_index=0.9,
            cycle_count=5,
            is_provisional=True,
            last_update_cycle=5,
        )

        mock_deg_tracker = MagicMock()
        mock_deg_tracker.compute_degradation_rate.return_value = None

        projector = MonteCarloProjector(
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        with pytest.raises(ValueError, match="Insufficient trajectory data"):
            projector.project(engine_id=1)

    def test_insufficient_data_error_includes_engine_id(self) -> None:
        """The ValueError message includes the engine ID for debugging."""
        mock_health_agg = MagicMock()
        mock_health_agg.get_health_state.return_value = EngineHealthState(
            engine_id=7,
            health_index=0.9,
            cycle_count=10,
            is_provisional=True,
            last_update_cycle=10,
        )

        mock_deg_tracker = MagicMock()
        mock_deg_tracker.compute_degradation_rate.return_value = None

        projector = MonteCarloProjector(
            health_index_aggregator=mock_health_agg,
            degradation_tracker=mock_deg_tracker,
        )

        with pytest.raises(ValueError, match="7"):
            projector.project(engine_id=7)


# ---------------------------------------------------------------------------
# Tests: Stress Factor Behavior (Requirement 4.1)
# ---------------------------------------------------------------------------


class TestMonteCarloStressFactor:
    """Verify stress_factor > 1.0 produces wider confidence bands."""

    def test_higher_stress_produces_wider_confidence_bands(self) -> None:
        """stress_factor=1.5 should produce wider p5-p95 spread than stress_factor=1.0.

        Higher stress_factor multiplies the degradation rate std, causing
        more diverse sampled rates and thus wider percentile fans.
        """
        # Use fixed seed for reproducibility
        np.random.seed(42)
        projector_normal = _make_projector(
            health_index=0.85, degradation_rate=-0.005, trajectory_length=30
        )
        result_normal = projector_normal.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=1.0,
        )

        np.random.seed(42)
        projector_stressed = _make_projector(
            health_index=0.85, degradation_rate=-0.005, trajectory_length=30
        )
        result_stressed = projector_stressed.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=1.5,
        )

        # Compute average spread (p95 - p5) across all cycles
        normal_spread = np.mean(
            np.array(result_normal.percentiles[95])
            - np.array(result_normal.percentiles[5])
        )
        stressed_spread = np.mean(
            np.array(result_stressed.percentiles[95])
            - np.array(result_stressed.percentiles[5])
        )

        assert stressed_spread > normal_spread, (
            f"Stressed spread ({stressed_spread:.4f}) should be wider than "
            f"normal spread ({normal_spread:.4f})"
        )

    def test_stress_factor_2_much_wider_than_1(self) -> None:
        """stress_factor=2.0 should produce noticeably wider bands than 1.0.

        This verifies the stress factor has a meaningful effect on output
        uncertainty, not just a marginal difference.
        """
        np.random.seed(123)
        projector = _make_projector(
            health_index=0.80, degradation_rate=-0.008, trajectory_length=40
        )
        result_baseline = projector.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=1.0,
        )

        np.random.seed(123)
        projector2 = _make_projector(
            health_index=0.80, degradation_rate=-0.008, trajectory_length=40
        )
        result_high = projector2.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=2.0,
        )

        # At the final cycle, the spread should be significantly wider
        final_spread_baseline = (
            result_baseline.percentiles[95][-1]
            - result_baseline.percentiles[5][-1]
        )
        final_spread_high = (
            result_high.percentiles[95][-1] - result_high.percentiles[5][-1]
        )

        assert final_spread_high > final_spread_baseline, (
            f"High stress final spread ({final_spread_high:.4f}) should exceed "
            f"baseline ({final_spread_baseline:.4f})"
        )

    def test_stress_factor_below_1_produces_narrower_bands(self) -> None:
        """stress_factor=0.5 should produce narrower bands than 1.0.

        Lower stress reduces the rate std, concentrating trajectories
        closer to the mean path.
        """
        np.random.seed(456)
        projector = _make_projector(
            health_index=0.85, degradation_rate=-0.005, trajectory_length=30
        )
        result_normal = projector.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=1.0,
        )

        np.random.seed(456)
        projector2 = _make_projector(
            health_index=0.85, degradation_rate=-0.005, trajectory_length=30
        )
        result_low = projector2.project(
            engine_id=1,
            horizon_cycles=50,
            num_trajectories=1000,
            stress_factor=0.5,
        )

        normal_spread = np.mean(
            np.array(result_normal.percentiles[95])
            - np.array(result_normal.percentiles[5])
        )
        low_spread = np.mean(
            np.array(result_low.percentiles[95])
            - np.array(result_low.percentiles[5])
        )

        assert low_spread < normal_spread, (
            f"Low stress spread ({low_spread:.4f}) should be narrower than "
            f"normal spread ({normal_spread:.4f})"
        )
