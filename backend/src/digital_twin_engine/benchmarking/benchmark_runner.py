"""Live Benchmark Runner — continuous accuracy metrics against C-MAPSS ground truth.

Continuously computes RMSE/MAE of EnKF-corrected RUL predictions vs C-MAPSS
ground truth, producing live accuracy benchmarks. Records
(raw_prediction, corrected_prediction, ground_truth_rul) triples and
computes running accuracy metrics over a rolling window.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass
class BenchmarkMetrics:
    """Snapshot of current benchmark accuracy metrics."""

    raw_rmse: float
    corrected_rmse: float
    raw_mae: float
    corrected_mae: float
    correction_gain_pct: float  # (raw_rmse - corrected_rmse) / raw_rmse * 100
    confidence_coverage_pct: float  # % of true RUL within 95% CI
    sample_count: int


class LiveBenchmarkRunner:
    """Continuously benchmarks prediction accuracy against C-MAPSS ground truth.

    Records (raw_prediction, corrected_prediction, ground_truth_rul) triples
    and computes running accuracy metrics over a rolling window of MAX_SAMPLES.

    Metrics computed:
        - RMSE (raw and corrected): Root Mean Squared Error of predictions vs truth
        - MAE (raw and corrected): Mean Absolute Error of predictions vs truth
        - correction_gain_pct: Percentage improvement of corrected over raw RMSE
        - confidence_coverage_pct: % of true RUL values within the 95% CI band

    Usage:
        runner = LiveBenchmarkRunner()
        runner.record(
            raw_prediction=120.0,
            corrected_prediction=115.0,
            ground_truth_rul=112.0,
            confidence_lower=108.0,
            confidence_upper=122.0,
        )
        metrics = runner.get_metrics()
    """

    MAX_SAMPLES = 5000  # Rolling window size

    def __init__(self) -> None:
        self._raw_errors: deque[float] = deque(maxlen=self.MAX_SAMPLES)
        self._corrected_errors: deque[float] = deque(maxlen=self.MAX_SAMPLES)
        self._coverage_hits: deque[int] = deque(maxlen=self.MAX_SAMPLES)

    def record(
        self,
        raw_prediction: float,
        corrected_prediction: float,
        ground_truth_rul: float,
        confidence_lower: float,
        confidence_upper: float,
    ) -> None:
        """Record a prediction-correction-truth triple after each correction cycle.

        Computes and stores the error between each prediction type and ground truth,
        and whether the ground truth falls within the 95% confidence interval.

        Args:
            raw_prediction: The ML model's raw RUL prediction.
            corrected_prediction: The EnKF-corrected RUL prediction.
            ground_truth_rul: The true RUL from C-MAPSS dataset.
            confidence_lower: Lower bound of 95% confidence interval.
            confidence_upper: Upper bound of 95% confidence interval.
        """
        self._raw_errors.append(raw_prediction - ground_truth_rul)
        self._corrected_errors.append(corrected_prediction - ground_truth_rul)

        # Coverage hit: 1 if ground truth falls within [lower, upper], else 0
        hit = 1 if confidence_lower <= ground_truth_rul <= confidence_upper else 0
        self._coverage_hits.append(hit)

    def get_metrics(self) -> BenchmarkMetrics:
        """Compute and return current benchmark metrics.

        Returns BenchmarkMetrics with zeros if no samples recorded yet.
        """
        n = len(self._raw_errors)

        if n == 0:
            return BenchmarkMetrics(
                raw_rmse=0.0,
                corrected_rmse=0.0,
                raw_mae=0.0,
                corrected_mae=0.0,
                correction_gain_pct=0.0,
                confidence_coverage_pct=0.0,
                sample_count=0,
            )

        # RMSE: sqrt(mean(errors^2))
        raw_rmse = math.sqrt(sum(e * e for e in self._raw_errors) / n)
        corrected_rmse = math.sqrt(sum(e * e for e in self._corrected_errors) / n)

        # MAE: mean(|errors|)
        raw_mae = sum(abs(e) for e in self._raw_errors) / n
        corrected_mae = sum(abs(e) for e in self._corrected_errors) / n

        # Correction gain: (raw_rmse - corrected_rmse) / raw_rmse * 100
        if raw_rmse > 0:
            correction_gain_pct = (raw_rmse - corrected_rmse) / raw_rmse * 100.0
        else:
            correction_gain_pct = 0.0

        # Confidence coverage: percentage of hits
        confidence_coverage_pct = (sum(self._coverage_hits) / n) * 100.0

        return BenchmarkMetrics(
            raw_rmse=raw_rmse,
            corrected_rmse=corrected_rmse,
            raw_mae=raw_mae,
            corrected_mae=corrected_mae,
            correction_gain_pct=correction_gain_pct,
            confidence_coverage_pct=confidence_coverage_pct,
            sample_count=n,
        )
