"""Fleet-Pattern-Enhanced Maintenance Recommendation Engine (v2.0).

EXTENDS the existing PredictiveAlertSystem (in alerting/predictive_alerts.py)
with fleet-wide pattern recognition to produce confidence-boosted, failure-mode-
specific maintenance recommendations.

The existing PredictiveAlertSystem already provides:
    - _classify_severity() — health index → severity level
    - _infer_failure_mode() — degradation rate → failure mode string
    - _compute_time_to_critical() — forward projection → cycles to critical
    - get_recommendations() — full recommendation pipeline

This module wraps PredictiveAlertSystem and enhances its output by:
    1. Querying FleetPatternRecognizer for cluster membership of the target engine
    2. Boosting confidence scores using pairwise similarity to cluster centroids
    3. Reporting all matching failure modes when engine matches multiple clusters
    4. Falling back to "unknown_pattern" when similarity < 0.7 to all clusters

Confidence Scoring Limitation (Model-Relative):
    Confidence values are RELATIVE to the model's own predictions, NOT calibrated
    against ground truth labels. The "ground truth proxy" is the RUL predictor's
    estimate — itself an approximation. Confidence should be interpreted as
    "model agreement strength" rather than "probability of being correct."
    This is documented here and in the dataclass docstring per design requirements.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from digital_twin_engine.prognostics.fleet_patterns import (
    FAILURE_MODE_LOOKUP,
    FleetPatternRecognizer,
)
from digital_twin_engine.shared.logging import get_logger

if TYPE_CHECKING:
    from digital_twin_engine.alerting.predictive_alerts import PredictiveAlertSystem

logger = get_logger("maintenance_recommendation_engine")


# ---------------------------------------------------------------------------
# Failure Mode Lookup (hardcoded per design)
# ---------------------------------------------------------------------------

# Maps failure_mode key → recommended maintenance action.
# Reuses the FAILURE_MODE_LOOKUP from fleet_patterns.py for consistency.
FAILURE_MODE_ACTIONS: Dict[str, str] = {
    entry["failure_mode"]: entry["recommended_action"]  # type: ignore[misc]
    for entry in FAILURE_MODE_LOOKUP
}

# Ordered list of known failure modes (excluding unknown_pattern)
KNOWN_FAILURE_MODES = [
    "hpc_degradation",
    "fan_blade_erosion",
    "bearing_wear",
    "combustor_hotspot",
]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class MaintenanceRecommendation:
    """A single fleet-pattern-enhanced maintenance recommendation.

    Confidence Scoring (Model-Relative):
        The confidence field represents the degree of agreement between the
        engine's degradation signature and known fleet-wide failure patterns.
        It is NOT a calibrated probability of correctness. Ground truth is
        approximated via the RUL predictor's internal estimate — itself a
        model output. Interpret confidence as "model agreement strength":
            - High confidence (>0.8): Strong match to a known fleet pattern
            - Medium confidence (0.5-0.8): Partial match or emerging pattern
            - Low confidence (<0.5): Weak match, possibly novel degradation

    Attributes:
        failure_mode: Identified failure mode from the lookup table.
            One of: hpc_degradation, fan_blade_erosion, bearing_wear,
            combustor_hotspot, unknown_pattern.
        confidence: Model-relative confidence score in [0.0, 1.0].
            Boosted by fleet cluster similarity when a match is found.
        recommended_action: Human-readable maintenance action string.
        contributing_sensors: List of sensor names that contribute to
            the identified pattern (derived from cluster characteristics).
    """

    failure_mode: str
    confidence: float  # 0.0 to 1.0, model-relative (see docstring)
    recommended_action: str
    contributing_sensors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sensor Indicators Mapping (for contributing_sensors field)
# ---------------------------------------------------------------------------

# Maps failure modes to their indicative sensor groups.
# These are the C-MAPSS sensor channels that characterize each failure mode.
FAILURE_MODE_SENSORS: Dict[str, List[str]] = {
    "hpc_degradation": [
        "T30",  # HPC outlet temperature
        "Nc",   # Physical core speed
        "phi",  # HPC efficiency (ratio of HPC outlet to inlet temp)
    ],
    "fan_blade_erosion": [
        "Nf",   # Physical fan speed
        "W31",  # HPT coolant bleed
        "BPR",  # Bypass ratio
    ],
    "bearing_wear": [
        "NRc",  # Corrected core speed
        "NRf",  # Corrected fan speed
        "P30",  # Total pressure at HPC outlet
    ],
    "combustor_hotspot": [
        "T50",  # LPT outlet temperature (proxy for combustor exit)
        "Wf",   # Fuel flow
        "T40",  # HPT outlet temperature (proxy for combustor)
    ],
    "unknown_pattern": [],
}


# ---------------------------------------------------------------------------
# Similarity threshold for cluster matching
# ---------------------------------------------------------------------------

# Engines with max similarity < this threshold to all cluster members
# are classified as "unknown_pattern".
CLUSTER_MATCH_THRESHOLD = 0.7

# Base confidence for recommendations derived from the PredictiveAlertSystem
# (before fleet pattern boosting).
BASE_CONFIDENCE = 0.4

# Maximum confidence boost from fleet pattern similarity.
MAX_SIMILARITY_BOOST = 0.5


# ---------------------------------------------------------------------------
# MaintenanceRecommendationEngine
# ---------------------------------------------------------------------------


class MaintenanceRecommendationEngine:
    """Fleet-pattern-enhanced maintenance recommendation engine.

    Wraps the existing PredictiveAlertSystem and enhances its recommendations
    with fleet-wide pattern recognition data. The engine:

    1. Queries the PredictiveAlertSystem for base recommendations (severity,
       time-to-critical, failure mode from degradation rate heuristic).
    2. Queries the FleetPatternRecognizer for cluster data.
    3. For each cluster the target engine belongs to, emits a recommendation
       with confidence boosted by the engine's average similarity to that cluster.
    4. If the engine matches NO cluster (similarity < 0.7 to all), emits a
       single "unknown_pattern" fallback recommendation.
    5. Sorts all recommendations by confidence descending.

    This class EXTENDS (composes) PredictiveAlertSystem — it does not replace it.
    """

    def __init__(
        self,
        pattern_recognizer: FleetPatternRecognizer,
        predictive_alert_system: PredictiveAlertSystem,
    ) -> None:
        """Initialize with fleet pattern and predictive alert dependencies.

        Args:
            pattern_recognizer: FleetPatternRecognizer instance that provides
                cluster membership and pairwise similarity data.
            predictive_alert_system: Existing PredictiveAlertSystem instance
                that provides base severity/failure-mode/timing recommendations.
        """
        self._pattern_recognizer = pattern_recognizer
        self._predictive_alert_system = predictive_alert_system

    def get_recommendations(self, engine_id: int) -> List[MaintenanceRecommendation]:
        """Generate fleet-pattern-enhanced maintenance recommendations.

        Algorithm:
            1. Get base recommendation from PredictiveAlertSystem
            2. Get fleet clusters from FleetPatternRecognizer
            3. Find clusters containing this engine
            4. For each matching cluster:
               - Compute average similarity of this engine to other members
               - Create recommendation with boosted confidence
            5. If no cluster match: emit "unknown_pattern" fallback
            6. Sort by confidence descending

        Args:
            engine_id: The engine unit identifier. Caller is responsible for
                verifying engine existence (raises 404 if non-existent).

        Returns:
            List of MaintenanceRecommendation sorted by confidence descending.
            Returns empty list if no health data is available for the engine
            (indicating the engine exists but has no degradation data yet).
        """
        # Step 1: Get base recommendations from the existing PredictiveAlertSystem
        base_recs = self._predictive_alert_system.get_recommendations(engine_id)

        # If no base data available (engine has no health data), return empty
        if not base_recs:
            return []

        # Extract base confidence from the predictive alert system
        base_confidence_score = base_recs[0].confidence_score if base_recs else 0.0

        # Step 2: Get fleet clusters
        fleet_response = self._pattern_recognizer.get_clusters()

        # Step 3: Find clusters containing this engine
        matching_clusters = [
            cluster
            for cluster in fleet_response.clusters
            if engine_id in cluster.engine_ids
        ]

        recommendations: List[MaintenanceRecommendation] = []

        if matching_clusters:
            # Step 4: For each matching cluster, emit a recommendation
            for cluster in matching_clusters:
                # Compute average similarity of this engine to other cluster members
                avg_similarity = self._compute_engine_cluster_similarity(
                    engine_id, cluster.engine_ids
                )

                # Boost confidence: base + similarity-weighted boost
                # Confidence = base_confidence + (similarity * MAX_SIMILARITY_BOOST)
                # Clamped to [0.0, 1.0]
                boosted_confidence = min(
                    1.0,
                    BASE_CONFIDENCE + (avg_similarity * MAX_SIMILARITY_BOOST),
                )

                # Also factor in the PredictiveAlertSystem's own confidence
                # Use the higher of base or boosted (fleet pattern only adds value)
                final_confidence = max(boosted_confidence, base_confidence_score)
                final_confidence = min(1.0, final_confidence)

                failure_mode = cluster.dominant_failure_mode
                action = FAILURE_MODE_ACTIONS.get(
                    failure_mode,
                    "General visual inspection + sensor calibration check",
                )
                sensors = FAILURE_MODE_SENSORS.get(failure_mode, [])

                recommendations.append(
                    MaintenanceRecommendation(
                        failure_mode=failure_mode,
                        confidence=round(final_confidence, 4),
                        recommended_action=action,
                        contributing_sensors=list(sensors),
                    )
                )
        else:
            # Step 5: No cluster match — check if engine has ANY similarity
            # to existing clusters above threshold
            best_similarity = self._find_best_cluster_similarity(engine_id)

            if best_similarity >= CLUSTER_MATCH_THRESHOLD:
                # Engine is similar to a cluster but not a member yet
                # (edge case: cluster membership is strict connected-component)
                # Use the base PredictiveAlertSystem failure mode
                base_failure_mode = (
                    base_recs[0].predicted_failure_mode
                    if base_recs and base_recs[0].predicted_failure_mode
                    else "unknown_pattern"
                )
                action = FAILURE_MODE_ACTIONS.get(
                    base_failure_mode,
                    "General visual inspection + sensor calibration check",
                )
                sensors = FAILURE_MODE_SENSORS.get(base_failure_mode, [])

                boosted_confidence = min(
                    1.0,
                    BASE_CONFIDENCE + (best_similarity * MAX_SIMILARITY_BOOST),
                )
                final_confidence = max(boosted_confidence, base_confidence_score)

                recommendations.append(
                    MaintenanceRecommendation(
                        failure_mode=base_failure_mode,
                        confidence=round(min(1.0, final_confidence), 4),
                        recommended_action=action,
                        contributing_sensors=list(sensors),
                    )
                )
            else:
                # True unknown pattern — similarity < 0.7 to ALL clusters
                recommendations.append(
                    MaintenanceRecommendation(
                        failure_mode="unknown_pattern",
                        confidence=round(max(0.1, base_confidence_score * 0.5), 4),
                        recommended_action=(
                            "General visual inspection + sensor calibration check"
                        ),
                        contributing_sensors=[],
                    )
                )

        # Step 6: Sort by confidence descending (Requirement 3.4)
        recommendations.sort(key=lambda r: r.confidence, reverse=True)

        return recommendations

    def _compute_engine_cluster_similarity(
        self, engine_id: int, cluster_engine_ids: List[int]
    ) -> float:
        """Compute average pairwise similarity between engine and cluster members.

        Uses FleetPatternRecognizer.compute_similarity() for each pair.

        Args:
            engine_id: The target engine.
            cluster_engine_ids: Engine IDs in the cluster.

        Returns:
            Average similarity score (0.0-1.0). Returns 0.0 if no other
            members exist in the cluster.
        """
        other_ids = [eid for eid in cluster_engine_ids if eid != engine_id]
        if not other_ids:
            return 0.0

        similarities = [
            self._pattern_recognizer.compute_similarity(engine_id, other_id)
            for other_id in other_ids
        ]

        return sum(similarities) / len(similarities)

    def _find_best_cluster_similarity(self, engine_id: int) -> float:
        """Find the highest average similarity between engine and any cluster.

        Checks all existing clusters and returns the maximum average similarity
        the engine has to any single cluster's members.

        Args:
            engine_id: The target engine.

        Returns:
            Maximum average similarity to any cluster (0.0-1.0).
            Returns 0.0 if no clusters exist.
        """
        fleet_response = self._pattern_recognizer.get_clusters()

        if not fleet_response.clusters:
            return 0.0

        best = 0.0
        for cluster in fleet_response.clusters:
            avg_sim = self._compute_engine_cluster_similarity(
                engine_id, cluster.engine_ids
            )
            if avg_sim > best:
                best = avg_sim

        return best
