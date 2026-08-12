"""Predictive Alert System for maintenance recommendation generation.

Uses MonteCarloProjector forward projection to predict time-to-critical and
generate severity-classified maintenance recommendations with confidence scores.

Severity thresholds (from health_index):
    health_index > 0.7   → "low"
    0.4 < health_index ≤ 0.7 → "medium"
    health_index ≤ 0.4   → "critical"

Algorithm:
    1. Get current health index from HealthIndexAggregator
    2. Classify severity based on thresholds
    3. Run MonteCarloProjector forward 100 cycles
    4. Find cycle where median trajectory crosses 0.4 (critical threshold)
    5. Compute confidence as fraction of trajectories agreeing on timing ±5 cycles
    6. Generate action string based on severity and time window

Reference: .kiro/backend-research-and-replan.md (Phase 4: Intelligent Alerting
& Root Cause Analysis + Phase 2: What-If Simulation Engine).

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from digital_twin_engine.prognostics.degradation_tracker import (
        DegradationCurveTracker,
    )
    from digital_twin_engine.prognostics.health_index import HealthIndexAggregator
    from digital_twin_engine.simulation.monte_carlo_projector import (
        MonteCarloProjector,
    )


class AlertSeverity(str, Enum):
    """Severity level for maintenance recommendations."""

    LOW = "low"
    MEDIUM = "medium"
    CRITICAL = "critical"


@dataclass
class MaintenanceRecommendation:
    """A single maintenance recommendation with timing and confidence."""

    severity: AlertSeverity
    time_to_critical_cycles: int
    confidence_score: float  # 0.0 to 1.0
    suggested_action: str
    predicted_failure_mode: Optional[str] = None


class PredictiveAlertSystem:
    """Generates maintenance recommendations using forward projection.

    Severity thresholds:
        health_index > 0.7  → "low"
        0.4 < health_index <= 0.7 → "medium"
        health_index <= 0.4 → "critical"
    """

    CRITICAL_THRESHOLD = 0.4
    MEDIUM_THRESHOLD = 0.7
    PROJECTION_HORIZON = 100  # Forward project 100 cycles

    def __init__(
        self,
        monte_carlo_projector: MonteCarloProjector,
        health_index_aggregator: HealthIndexAggregator,
        degradation_tracker: DegradationCurveTracker,
    ) -> None:
        """Initialize with references to existing v1.3 components.

        Args:
            monte_carlo_projector: MonteCarloProjector instance for forward projection.
            health_index_aggregator: Provides current engine health index.
            degradation_tracker: Provides degradation rate and trajectory data.
        """
        self._projector = monte_carlo_projector
        self._health = health_index_aggregator
        self._degradation = degradation_tracker

    def get_recommendations(self, engine_id: int) -> List[MaintenanceRecommendation]:
        """Generate maintenance recommendations for an engine.

        Algorithm:
            1. Get current health index from aggregator
            2. Determine severity from health thresholds
            3. Run MonteCarloProjector forward 100 cycles
            4. Find cycle where median trajectory crosses 0.4 (critical)
            5. Compute confidence as fraction of trajectories agreeing on timing ±5 cycles
            6. Generate action string based on severity and time window

        Args:
            engine_id: The engine unit identifier.

        Returns:
            List of MaintenanceRecommendation sorted by severity (critical first).
            Returns empty list if no health data or insufficient degradation data.
        """
        # Step 1: Get current health index
        health_state = self._health.get_health_state(engine_id)
        if health_state is None:
            return []

        current_hi = health_state.health_index

        # Step 2: Classify severity
        severity = self._classify_severity(current_hi)

        # Step 3-5: Compute time to critical via forward projection
        try:
            time_to_critical, confidence = self._compute_time_to_critical(
                engine_id, horizon=self.PROJECTION_HORIZON
            )
        except ValueError:
            # Insufficient data for projection (< 20 cycles in DegradationTracker)
            # Return a recommendation based on current state only
            return [
                MaintenanceRecommendation(
                    severity=severity,
                    time_to_critical_cycles=0,
                    confidence_score=0.0,
                    suggested_action=self._generate_action(severity, None),
                    predicted_failure_mode=None,
                )
            ]

        # Step 6: Generate action and build recommendation
        action = self._generate_action(severity, time_to_critical)
        failure_mode = self._infer_failure_mode(engine_id)

        recommendation = MaintenanceRecommendation(
            severity=severity,
            time_to_critical_cycles=time_to_critical,
            confidence_score=confidence,
            suggested_action=action,
            predicted_failure_mode=failure_mode,
        )

        return [recommendation]

    def _classify_severity(self, health_index: float) -> AlertSeverity:
        """Map health index to severity level.

        Thresholds:
            health_index > 0.7  → LOW
            0.4 < health_index <= 0.7 → MEDIUM
            health_index <= 0.4 → CRITICAL

        Args:
            health_index: Current engine health index (0.0 to 1.0).

        Returns:
            AlertSeverity classification.
        """
        if health_index <= self.CRITICAL_THRESHOLD:
            return AlertSeverity.CRITICAL
        elif health_index <= self.MEDIUM_THRESHOLD:
            return AlertSeverity.MEDIUM
        return AlertSeverity.LOW

    def _compute_time_to_critical(
        self, engine_id: int, horizon: int = 100
    ) -> Tuple[int, float]:
        """Use MonteCarloProjector to estimate cycles until critical.

        Runs forward projection for the specified horizon and finds where
        the median trajectory (50th percentile) crosses the critical threshold.
        Confidence is computed as the fraction of trajectories whose crossing
        time falls within ±5 cycles of the median crossing.

        Args:
            engine_id: The engine unit identifier.
            horizon: Number of cycles to project forward (default 100).

        Returns:
            Tuple of (cycles_to_critical, confidence_score) where:
            - cycles_to_critical: Estimated cycles until HI reaches critical (0.4).
              If no crossing within horizon, returns the horizon value.
            - confidence_score: Fraction of trajectories agreeing on timing ±5 cycles
              of the median. Range [0.0, 1.0].

        Raises:
            ValueError: If engine has no health data or insufficient trajectory
                data for degradation rate computation (propagated from MonteCarloProjector).
        """
        result = self._projector.project(
            engine_id=engine_id,
            horizon_cycles=horizon,
            num_trajectories=1000,
            stress_factor=1.0,
        )

        # Use expected_rul from projector (median crossing cycle)
        if result.expected_rul is not None:
            time_to_critical = result.expected_rul

            # Compute confidence: fraction of failure_probability curve that
            # indicates crossing around the expected time.
            # Use the confidence_interval_90 to gauge agreement.
            if result.confidence_interval_90 is not None:
                ci_low, ci_high = result.confidence_interval_90
                # Confidence is higher when the CI is narrow relative to the estimate
                ci_width = ci_high - ci_low
                if ci_width <= 10:
                    # Very tight CI — high confidence
                    confidence = min(1.0, 0.7 + (10 - ci_width) * 0.03)
                else:
                    # Wider CI — lower confidence, use fraction within ±5 cycles
                    # Approximate from the failure probability curve
                    confidence = self._estimate_confidence_from_curve(
                        result.failure_probability_by_cycle, time_to_critical
                    )
            else:
                confidence = 0.5  # Default moderate confidence
        else:
            # No crossing within horizon — engine won't reach critical soon
            time_to_critical = horizon
            # Confidence in "won't fail" is based on how far above threshold we are
            # If failure_prob at end of horizon is low, confidence is high
            final_failure_prob = (
                result.failure_probability_by_cycle[-1]
                if result.failure_probability_by_cycle
                else 0.0
            )
            confidence = max(0.0, 1.0 - final_failure_prob)

        return time_to_critical, round(confidence, 2)

    def _estimate_confidence_from_curve(
        self, failure_prob_curve: List[float], median_crossing: int
    ) -> float:
        """Estimate confidence from the failure probability curve.

        Confidence is approximated as the change in failure probability
        within ±5 cycles of the median crossing point. A steep jump
        (many trajectories crossing at nearly the same time) indicates
        high confidence.

        Args:
            failure_prob_curve: Per-cycle cumulative failure probability.
            median_crossing: The estimated median crossing cycle (1-indexed).

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        if not failure_prob_curve:
            return 0.5

        n = len(failure_prob_curve)
        # Convert to 0-indexed for the curve
        idx = median_crossing - 1

        # Get failure probability at ±5 cycles
        low_idx = max(0, idx - 5)
        high_idx = min(n - 1, idx + 5)

        prob_at_low = failure_prob_curve[low_idx]
        prob_at_high = failure_prob_curve[high_idx]

        # The jump in probability within ±5 cycles represents how many
        # trajectories crossed in that window (= agreement = confidence)
        confidence = prob_at_high - prob_at_low

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, confidence))

    def _generate_action(
        self, severity: AlertSeverity, time_to_critical: Optional[int]
    ) -> str:
        """Generate a suggested action string based on severity and timing.

        Args:
            severity: The classified severity level.
            time_to_critical: Estimated cycles to critical, or None if unknown.

        Returns:
            Human-readable action string.
        """
        if time_to_critical is None:
            if severity == AlertSeverity.CRITICAL:
                return "Immediate inspection required — insufficient data for projection"
            elif severity == AlertSeverity.MEDIUM:
                return "Schedule inspection — degradation detected but projection unavailable"
            return "Monitor — insufficient degradation data for projection"

        if severity == AlertSeverity.CRITICAL:
            return "Immediate maintenance required — engine at critical health"
        elif severity == AlertSeverity.MEDIUM:
            safe_window = max(1, time_to_critical - 10)
            return f"Schedule inspection within {safe_window} cycles"
        else:
            return f"Routine monitoring — projected {time_to_critical} cycles to critical"

    def _infer_failure_mode(self, engine_id: int) -> Optional[str]:
        """Infer the likely failure mode from degradation trajectory.

        Uses degradation rate magnitude to classify. This is a simplified
        heuristic — a full implementation would correlate sensor patterns
        to known failure modes.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            String describing predicted failure mode, or None if indeterminate.
        """
        rate = self._degradation.compute_degradation_rate(engine_id)
        if rate is None:
            return None

        abs_rate = abs(rate)
        if abs_rate > 0.02:
            return "accelerated_degradation"
        elif abs_rate > 0.01:
            return "gradual_wear"
        else:
            return "nominal_aging"
