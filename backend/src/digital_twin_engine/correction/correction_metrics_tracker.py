"""Correction Metrics Tracker and Innovation Statistics Tracker.

Provides two tracker classes for observability of the EnKF correction engine:

1. CorrectionMetricsTracker — Records (raw_prediction, observed_value, corrected_value)
   triples per sensor and computes running RMSE, MAE, R² for both raw and corrected values.

2. InnovationStatsTracker — Tracks innovation magnitude sequences per sensor and computes
   autocorrelation at lag-1 plus a whiteness test to verify the EnKF is properly tuned.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SensorMetrics:
    """Per-sensor accumulated metrics data."""

    raw_errors_squared: list[float] = field(default_factory=list)
    corrected_errors_squared: list[float] = field(default_factory=list)
    raw_abs_errors: list[float] = field(default_factory=list)
    corrected_abs_errors: list[float] = field(default_factory=list)
    observed_values: list[float] = field(default_factory=list)
    raw_predictions: list[float] = field(default_factory=list)
    corrected_values: list[float] = field(default_factory=list)
    sample_count: int = 0


@dataclass
class AccuracyMetrics:
    """Computed accuracy metrics returned by the tracker."""

    raw_rmse: Optional[float]
    raw_mae: Optional[float]
    raw_r_squared: Optional[float]
    corrected_rmse: Optional[float]
    corrected_mae: Optional[float]
    corrected_r_squared: Optional[float]
    improvement_percentage: Optional[float]
    sample_count: int


class CorrectionMetricsTracker:
    """Tracks prediction accuracy, comparing raw ML vs EnKF-corrected.

    Records every (predicted, actual, corrected) triple and computes
    running RMSE/MAE/R² for both raw predictions and corrected states.
    Thread-safe for single-threaded asyncio context.
    """

    def __init__(self) -> None:
        self._sensors: dict[str, SensorMetrics] = {}

    def record(
        self,
        sensor_id: str,
        raw_prediction: float,
        observed_value: float,
        corrected_value: float,
    ) -> None:
        """Record a prediction-observation-correction triple."""
        if sensor_id not in self._sensors:
            self._sensors[sensor_id] = SensorMetrics()

        m = self._sensors[sensor_id]
        m.raw_predictions.append(raw_prediction)
        m.observed_values.append(observed_value)
        m.corrected_values.append(corrected_value)
        m.raw_errors_squared.append((raw_prediction - observed_value) ** 2)
        m.corrected_errors_squared.append((corrected_value - observed_value) ** 2)
        m.raw_abs_errors.append(abs(raw_prediction - observed_value))
        m.corrected_abs_errors.append(abs(corrected_value - observed_value))
        m.sample_count += 1

    def get_metrics(self) -> AccuracyMetrics:
        """Return aggregated metrics across all sensors."""
        total_samples = sum(m.sample_count for m in self._sensors.values())

        if total_samples < 2:
            return AccuracyMetrics(
                raw_rmse=None,
                raw_mae=None,
                raw_r_squared=None,
                corrected_rmse=None,
                corrected_mae=None,
                corrected_r_squared=None,
                improvement_percentage=None,
                sample_count=total_samples,
            )

        # Aggregate across all sensors
        all_raw_sq: list[float] = []
        all_corr_sq: list[float] = []
        all_raw_abs: list[float] = []
        all_corr_abs: list[float] = []
        all_observed: list[float] = []

        for m in self._sensors.values():
            all_raw_sq.extend(m.raw_errors_squared)
            all_corr_sq.extend(m.corrected_errors_squared)
            all_raw_abs.extend(m.raw_abs_errors)
            all_corr_abs.extend(m.corrected_abs_errors)
            all_observed.extend(m.observed_values)

        n = len(all_observed)
        raw_rmse = math.sqrt(sum(all_raw_sq) / n)
        corrected_rmse = math.sqrt(sum(all_corr_sq) / n)
        raw_mae = sum(all_raw_abs) / n
        corrected_mae = sum(all_corr_abs) / n

        # R² computation
        obs_mean = sum(all_observed) / n
        ss_tot = sum((o - obs_mean) ** 2 for o in all_observed)

        if ss_tot == 0:
            raw_r_squared = None
            corrected_r_squared = None
        else:
            ss_res_raw = sum(all_raw_sq)
            ss_res_corr = sum(all_corr_sq)
            raw_r_squared = 1.0 - (ss_res_raw / ss_tot)
            corrected_r_squared = 1.0 - (ss_res_corr / ss_tot)

        improvement = (
            (raw_rmse - corrected_rmse) / raw_rmse * 100.0
            if raw_rmse > 0
            else 0.0
        )

        return AccuracyMetrics(
            raw_rmse=raw_rmse,
            raw_mae=raw_mae,
            raw_r_squared=raw_r_squared,
            corrected_rmse=corrected_rmse,
            corrected_mae=corrected_mae,
            corrected_r_squared=corrected_r_squared,
            improvement_percentage=improvement,
            sample_count=n,
        )


class InnovationStatsTracker:
    """Tracks innovation sequences per sensor for whiteness testing.

    In a well-tuned EnKF, innovations should be white noise (uncorrelated).
    This tracker computes autocorrelation at lag-1 and a whiteness test.
    """

    def __init__(self, max_history: int = 200) -> None:
        self._innovations: dict[str, list[float]] = {}
        self._max_history = max_history

    def record(self, sensor_id: str, innovation_magnitude: float) -> None:
        """Record an innovation value for a sensor."""
        if sensor_id not in self._innovations:
            self._innovations[sensor_id] = []
        history = self._innovations[sensor_id]
        history.append(innovation_magnitude)
        if len(history) > self._max_history:
            self._innovations[sensor_id] = history[-self._max_history :]

    def get_stats(self, sensor_id: str) -> dict:
        """Return innovation statistics for a sensor.

        Returns dict with:
          autocorrelation_lag1, mean_innovation, std_innovation,
          whiteness_test_passed, sample_count

        Returns null fields if sample_count < 10.
        """
        history = self._innovations.get(sensor_id, [])
        n = len(history)

        if n < 10:
            return {
                "sensor_id": sensor_id,
                "autocorrelation_lag1": None,
                "mean_innovation": None,
                "std_innovation": None,
                "whiteness_test_passed": None,
                "sample_count": n,
            }

        mean_val = sum(history) / n
        std_val = (sum((x - mean_val) ** 2 for x in history) / n) ** 0.5

        # Pearson correlation between x[0:n-1] and x[1:n]
        x = history[:-1]
        y = history[1:]
        m = len(x)
        mean_x = sum(x) / m
        mean_y = sum(y) / m
        cov_xy = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(m)) / m
        std_x = (sum((xi - mean_x) ** 2 for xi in x) / m) ** 0.5
        std_y = (sum((yi - mean_y) ** 2 for yi in y) / m) ** 0.5

        if std_x < 1e-10 or std_y < 1e-10:
            autocorrelation_lag1 = 0.0
        else:
            autocorrelation_lag1 = cov_xy / (std_x * std_y)

        # Whiteness test: |autocorrelation| < 2/sqrt(N)
        threshold = 2.0 / (n**0.5)
        whiteness_passed = abs(autocorrelation_lag1) < threshold

        return {
            "sensor_id": sensor_id,
            "autocorrelation_lag1": autocorrelation_lag1,
            "mean_innovation": mean_val,
            "std_innovation": std_val,
            "whiteness_test_passed": whiteness_passed,
            "sample_count": n,
        }

    def get_all_stats(self) -> list[dict]:
        """Return innovation stats for all tracked sensors."""
        return [self.get_stats(sid) for sid in self._innovations]
