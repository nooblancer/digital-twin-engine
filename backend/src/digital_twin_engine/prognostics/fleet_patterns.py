"""Fleet-Wide Pattern Recognition for degradation signature clustering.

Computes pairwise similarity scores between engine degradation rate histories
using Pearson correlation, clusters engines whose similarity exceeds a threshold,
and labels clusters with dominant failure modes from a hardcoded lookup table.

Engines with insufficient data (<10 data points) or still in baseline calibration
(cycle_count <= 10, HI=1.0 is provisional) are excluded from clustering.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from digital_twin_engine.prognostics.degradation_tracker import DegradationCurveTracker
from digital_twin_engine.prognostics.health_index import HealthIndexAggregator
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("fleet_pattern_recognizer")


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class EnginePairSimilarity:
    """Similarity score between two engines' degradation signatures."""

    engine_a: int
    engine_b: int
    similarity_score: float


@dataclass
class PatternCluster:
    """A cluster of engines sharing similar degradation patterns."""

    cluster_id: int
    engine_ids: List[int]
    pairwise_similarities: List[EnginePairSimilarity]
    dominant_failure_mode: str


@dataclass
class FleetPatternResponse:
    """Complete response for fleet pattern recognition."""

    clusters: List[PatternCluster]
    insufficient_data_engines: List[int]
    total_engines: int
    eligible_engines: int


# ---------------------------------------------------------------------------
# Failure Mode Lookup Table
# ---------------------------------------------------------------------------

# Hardcoded failure mode lookup table mapping degradation characteristics
# to known failure modes. Uses degradation rate magnitude ranges as indicators.
FAILURE_MODE_LOOKUP: List[Dict[str, object]] = [
    {
        "failure_mode": "hpc_degradation",
        "description": "High-Pressure Compressor degradation",
        "indicators": "HPC outlet temp trend, core speed deviation",
        "recommended_action": "Compressor wash + blade inspection",
        "rate_threshold": 0.01,  # abs degradation rate > 0.01
    },
    {
        "failure_mode": "fan_blade_erosion",
        "description": "Fan blade erosion",
        "indicators": "Fan speed oscillation, vibration increase",
        "recommended_action": "Fan blade inspection + replacement scheduling",
        "rate_threshold": 0.007,
    },
    {
        "failure_mode": "bearing_wear",
        "description": "Bearing wear",
        "indicators": "Vibration amplitude, oil temp increase",
        "recommended_action": "Bearing replacement at next maintenance window",
        "rate_threshold": 0.005,
    },
    {
        "failure_mode": "combustor_hotspot",
        "description": "Combustor hotspot",
        "indicators": "Exhaust temp asymmetry, fuel flow deviation",
        "recommended_action": "Combustor liner inspection",
        "rate_threshold": 0.003,
    },
    {
        "failure_mode": "unknown_pattern",
        "description": "No known pattern match",
        "indicators": "No cluster match",
        "recommended_action": "General visual inspection + sensor calibration check",
        "rate_threshold": 0.0,
    },
]


# ---------------------------------------------------------------------------
# Fleet Pattern Recognizer
# ---------------------------------------------------------------------------


class FleetPatternRecognizer:
    """Computes pairwise similarity and clusters engines by degradation signature.

    Uses Pearson correlation on degradation rate histories to identify groups
    of engines exhibiting similar degradation patterns. Threshold-based
    agglomerative clustering groups engines whose pairwise similarity exceeds
    the configured threshold (default 0.7).

    Engines in baseline calibration period (cycle_count <= baseline_cycles) or
    with insufficient data points (< min_data_points) are excluded from
    clustering and reported in the insufficient_data list.
    """

    FLOAT_TOLERANCE = 1e-12  # Near-zero std threshold (per v1.4 RootCauseAnalyzer pattern)

    def __init__(
        self,
        degradation_tracker: DegradationCurveTracker,
        health_index_aggregator: HealthIndexAggregator,
        similarity_threshold: float = 0.7,
        min_data_points: int = 10,
        baseline_cycles: int = 10,
    ) -> None:
        """Initialize the Fleet Pattern Recognizer.

        Args:
            degradation_tracker: Provides degradation rate histories per engine.
            health_index_aggregator: Provides health state and cycle count for
                baseline period checks.
            similarity_threshold: Minimum Pearson correlation to include a pair
                in a cluster. Default 0.7.
            min_data_points: Minimum number of data points required for an
                engine to be eligible for clustering. Default 10.
            baseline_cycles: Number of initial cycles considered baseline
                calibration (HI=1.0 is provisional). Default 10.
        """
        self._degradation_tracker = degradation_tracker
        self._health_index_aggregator = health_index_aggregator
        self._similarity_threshold = similarity_threshold
        self._min_data_points = min_data_points
        self._baseline_cycles = baseline_cycles

    def compute_similarity(self, engine_a: int, engine_b: int) -> float:
        """Compute Pearson correlation between two engines' degradation histories.

        Uses numpy.corrcoef() with a pre-check: if either engine's degradation
        rate history has std < FLOAT_TOLERANCE (1e-12), returns 0.0 to avoid
        division-by-near-zero producing NaN or Inf values.

        The correlation is computed on the health index values from the
        degradation trajectories. Only the overlapping portion (by minimum
        length) is used.

        Args:
            engine_a: First engine ID.
            engine_b: Second engine ID.

        Returns:
            Pearson correlation coefficient in [0.0, 1.0] (absolute value),
            or 0.0 if either series has near-zero standard deviation or
            insufficient overlap.
        """
        series_a = self._get_degradation_series(engine_a)
        series_b = self._get_degradation_series(engine_b)

        if series_a is None or series_b is None:
            return 0.0

        # Use the minimum length for alignment
        min_len = min(len(series_a), len(series_b))
        if min_len < 2:
            return 0.0

        arr_a = np.array(series_a[:min_len], dtype=np.float64)
        arr_b = np.array(series_b[:min_len], dtype=np.float64)

        # Pre-check: if either series has near-zero std, return 0.0
        # This avoids division-by-near-zero producing NaN/Inf (Req 1.8)
        if np.std(arr_a) < self.FLOAT_TOLERANCE:
            return 0.0
        if np.std(arr_b) < self.FLOAT_TOLERANCE:
            return 0.0

        # Compute Pearson correlation via numpy.corrcoef()
        corr_matrix = np.corrcoef(arr_a, arr_b)
        correlation = corr_matrix[0, 1]

        # Handle NaN (can occur if corrcoef encounters numerical issues)
        if np.isnan(correlation) or np.isinf(correlation):
            return 0.0

        # Return absolute value of correlation (both positive and negative
        # correlation indicate similar degradation patterns)
        return float(abs(correlation))

    def get_clusters(self) -> FleetPatternResponse:
        """Return all clusters with membership, scores, and failure modes.

        Implements threshold-based agglomerative clustering using connected
        components: engines are in the same cluster if ALL pairs in the cluster
        have similarity > threshold.

        Excludes engines in baseline period (cycle_count <= baseline_cycles)
        and engines with fewer than min_data_points degradation records.

        Returns:
            FleetPatternResponse containing clusters, insufficient engines,
            and fleet counts.
        """
        # Get all tracked engine IDs
        all_engine_ids = self._get_all_engine_ids()
        total_engines = len(all_engine_ids)

        # Determine eligible vs insufficient engines
        eligible_engines: List[int] = []
        insufficient_engines: List[int] = []

        for engine_id in all_engine_ids:
            if self._is_in_baseline(engine_id):
                insufficient_engines.append(engine_id)
            elif not self._has_sufficient_data(engine_id):
                insufficient_engines.append(engine_id)
            else:
                eligible_engines.append(engine_id)

        # Edge case: fewer than 2 eligible engines (Req 1.5)
        if len(eligible_engines) < 2:
            return FleetPatternResponse(
                clusters=[],
                insufficient_data_engines=sorted(insufficient_engines),
                total_engines=total_engines,
                eligible_engines=len(eligible_engines),
            )

        # Compute pairwise similarities for all eligible engine pairs
        pair_similarities: List[EnginePairSimilarity] = []
        n = len(eligible_engines)

        for i in range(n):
            for j in range(i + 1, n):
                engine_a = eligible_engines[i]
                engine_b = eligible_engines[j]
                sim = self.compute_similarity(engine_a, engine_b)

                if sim > self._similarity_threshold:
                    pair_similarities.append(
                        EnginePairSimilarity(
                            engine_a=engine_a,
                            engine_b=engine_b,
                            similarity_score=sim,
                        )
                    )

        # Build clusters using connected components (agglomerative clustering)
        clusters = self._build_clusters(eligible_engines, pair_similarities)

        return FleetPatternResponse(
            clusters=clusters,
            insufficient_data_engines=sorted(insufficient_engines),
            total_engines=total_engines,
            eligible_engines=len(eligible_engines),
        )

    def get_insufficient_engines(self) -> List[int]:
        """Return engine IDs excluded due to insufficient data OR baseline period.

        Returns:
            Sorted list of engine IDs that are either in baseline calibration
            (cycle_count <= baseline_cycles) or have fewer than min_data_points
            degradation records.
        """
        all_engine_ids = self._get_all_engine_ids()
        insufficient: List[int] = []

        for engine_id in all_engine_ids:
            if self._is_in_baseline(engine_id):
                insufficient.append(engine_id)
            elif not self._has_sufficient_data(engine_id):
                insufficient.append(engine_id)

        return sorted(insufficient)

    def _is_in_baseline(self, engine_id: int) -> bool:
        """Check if engine is still in baseline calibration (HI=1.0 provisional).

        Uses health_index_aggregator to check the engine's cycle count.
        An engine is in baseline if cycle_count <= baseline_cycles.

        The baseline_established flag in HealthIndexAggregator uses strict
        greater-than (cycle_count > BASELINE_CYCLES), meaning engines with
        exactly baseline_cycles cycles are still in baseline.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            True if engine is in baseline calibration period.
        """
        health_state = self._health_index_aggregator.get_health_state(engine_id)
        if health_state is None:
            # No health state means engine hasn't been processed yet
            return True

        return health_state.cycle_count <= self._baseline_cycles

    def _has_sufficient_data(self, engine_id: int) -> bool:
        """Check if engine has enough degradation data points for clustering.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            True if engine has >= min_data_points in its trajectory.
        """
        trajectory = self._degradation_tracker.get_trajectory(engine_id)
        return len(trajectory) >= self._min_data_points

    def _get_degradation_series(self, engine_id: int) -> Optional[List[float]]:
        """Get the health index time series for an engine.

        Returns the health index values from the degradation trajectory,
        ordered by cycle.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            List of health index values, or None if no data exists.
        """
        trajectory = self._degradation_tracker.get_trajectory(engine_id)
        if not trajectory:
            return None

        # trajectory is List[Tuple[int, float]] — (cycle, health_index)
        return [hi for _, hi in trajectory]

    def _get_all_engine_ids(self) -> List[int]:
        """Get all engine IDs currently tracked by the degradation tracker.

        Returns:
            List of all engine IDs with trajectory data.
        """
        # Access the internal _trajectories dict of DegradationCurveTracker
        return list(self._degradation_tracker._trajectories.keys())

    def _build_clusters(
        self,
        eligible_engines: List[int],
        pair_similarities: List[EnginePairSimilarity],
    ) -> List[PatternCluster]:
        """Build clusters using connected components from above-threshold pairs.

        Uses a simple connected-components algorithm: two engines are in the
        same cluster if there exists a path of above-threshold similarity
        pairs connecting them.

        Args:
            eligible_engines: List of engine IDs eligible for clustering.
            pair_similarities: List of above-threshold similarity pairs.

        Returns:
            List of PatternCluster objects.
        """
        if not pair_similarities:
            return []

        # Build adjacency representation using union-find
        parent: Dict[int, int] = {eid: eid for eid in eligible_engines}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # Path compression
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Union all engines connected by above-threshold similarity
        for pair in pair_similarities:
            union(pair.engine_a, pair.engine_b)

        # Group engines by their root representative
        cluster_map: Dict[int, List[int]] = {}
        for eid in eligible_engines:
            root = find(eid)
            if root not in cluster_map:
                cluster_map[root] = []
            cluster_map[root].append(eid)

        # Filter: only keep groups with 2+ engines
        clusters: List[PatternCluster] = []
        cluster_id = 0

        for _root, engine_ids in sorted(cluster_map.items()):
            if len(engine_ids) < 2:
                continue

            # Collect pairwise similarities within this cluster
            cluster_pairs = [
                p
                for p in pair_similarities
                if p.engine_a in engine_ids and p.engine_b in engine_ids
            ]

            # Determine dominant failure mode from cluster characteristics
            failure_mode = self._infer_failure_mode(engine_ids)

            clusters.append(
                PatternCluster(
                    cluster_id=cluster_id,
                    engine_ids=sorted(engine_ids),
                    pairwise_similarities=cluster_pairs,
                    dominant_failure_mode=failure_mode,
                )
            )
            cluster_id += 1

        return clusters

    def _infer_failure_mode(self, engine_ids: List[int]) -> str:
        """Infer the dominant failure mode for a cluster of engines.

        Uses the average degradation rate magnitude across the cluster's engines
        to match against the failure mode lookup table thresholds.

        Args:
            engine_ids: List of engine IDs in the cluster.

        Returns:
            The failure mode string from the lookup table.
        """
        # Compute average absolute degradation rate for the cluster
        rates: List[float] = []
        for engine_id in engine_ids:
            rate = self._degradation_tracker.compute_degradation_rate(engine_id)
            if rate is not None:
                rates.append(abs(rate))

        if not rates:
            return "unknown_pattern"

        avg_rate = sum(rates) / len(rates)

        # Match against lookup table (ordered from highest to lowest threshold)
        for entry in FAILURE_MODE_LOOKUP:
            threshold = entry["rate_threshold"]
            if isinstance(threshold, (int, float)) and avg_rate >= threshold:
                return str(entry["failure_mode"])

        return "unknown_pattern"
