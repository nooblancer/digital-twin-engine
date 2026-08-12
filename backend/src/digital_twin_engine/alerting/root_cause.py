"""Root Cause Analyzer for anomaly diagnostics.

Ranks contributing sensors by their innovation magnitude when an anomaly is
detected, producing a prioritized diagnostic breakdown. Uses a rolling history
of innovation magnitudes per sensor to compute sigma deviations (how many
standard deviations above normal each sensor's innovation is).

Reference: .kiro/backend-research-and-replan.md (Phase 4: Intelligent Alerting
& Root Cause Analysis) and correction/enkf.py (_compute_enkf_update).

Requirements: 1.1, 1.5
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np


@dataclass
class SensorContribution:
    """A single sensor's contribution to an anomaly."""

    sensor_name: str
    innovation_magnitude: float
    sigma_deviation: float


@dataclass
class AnomalyAnalysis:
    """Complete root cause analysis result."""

    engine_id: int
    anomaly_active: bool
    timestamp: Optional[str] = None
    contributions: List[SensorContribution] = field(default_factory=list)


class RootCauseAnalyzer:
    """Ranks sensors by innovation magnitude when anomaly detected.

    Maintains a rolling history of innovation magnitudes per sensor
    to compute sigma deviations (how many std devs above normal).

    Algorithm (from research doc Phase 4):
        1. Record every innovation magnitude into a per-sensor rolling deque.
        2. On anomaly, for each sensor compute:
           sigma_deviation = innovation_magnitude / std(history)
           If std(history) == 0, sigma_deviation = 0.0
        3. Sort sensors by sigma_deviation descending.
        4. Store as latest analysis for the engine.
    """

    HISTORY_SIZE = 200  # Rolling window for std computation

    def __init__(self) -> None:
        # engine_id -> sensor_name -> deque of innovation magnitudes
        self._history: Dict[int, Dict[str, deque]] = {}
        # engine_id -> latest AnomalyAnalysis
        self._latest_analysis: Dict[int, AnomalyAnalysis] = {}

    def record_innovation(
        self, engine_id: int, sensor_name: str, innovation_magnitude: float
    ) -> None:
        """Record an innovation magnitude observation for running stats.

        Called on every EnKF update to maintain the rolling history used
        for sigma deviation computation.

        Args:
            engine_id: The engine this sensor belongs to.
            sensor_name: Name of the sensor (e.g. 'hpc_outlet_temp_total').
            innovation_magnitude: |y_obs - H·x_predicted| from the EnKF update.
        """
        if engine_id not in self._history:
            self._history[engine_id] = {}

        engine_sensors = self._history[engine_id]
        if sensor_name not in engine_sensors:
            engine_sensors[sensor_name] = deque(maxlen=self.HISTORY_SIZE)

        engine_sensors[sensor_name].append(innovation_magnitude)

    def analyze_anomaly(
        self, engine_id: int, sensor_innovations: Dict[str, float]
    ) -> AnomalyAnalysis:
        """Compute ranked root cause analysis for an anomaly event.

        Args:
            engine_id: The engine that triggered the anomaly.
            sensor_innovations: Map of sensor_name -> current innovation_magnitude.

        Returns:
            AnomalyAnalysis with sensors ranked by sigma_deviation descending.

        Algorithm:
            1. For each sensor, compute sigma_deviation = innovation / std(history)
               - If std(history) == 0 (constant history or insufficient data),
                 sigma_deviation = 0.0
            2. Sort sensors by sigma_deviation descending
            3. Store as latest analysis for this engine
        """
        contributions: List[SensorContribution] = []

        engine_sensors = self._history.get(engine_id, {})

        for sensor_name, innovation_mag in sensor_innovations.items():
            history = engine_sensors.get(sensor_name)

            if history is not None and len(history) > 0:
                std = float(np.std(list(history)))
                if std < 1e-12:
                    sigma_deviation = 0.0
                else:
                    sigma_deviation = innovation_mag / std
            else:
                # No history available — cannot compute meaningful sigma
                sigma_deviation = 0.0

            contributions.append(
                SensorContribution(
                    sensor_name=sensor_name,
                    innovation_magnitude=innovation_mag,
                    sigma_deviation=sigma_deviation,
                )
            )

        # Sort by sigma_deviation descending (highest deviation first)
        contributions.sort(key=lambda c: c.sigma_deviation, reverse=True)

        analysis = AnomalyAnalysis(
            engine_id=engine_id,
            anomaly_active=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contributions=contributions,
        )

        self._latest_analysis[engine_id] = analysis
        return analysis

    def get_latest_analysis(self, engine_id: int) -> AnomalyAnalysis:
        """Return the most recent anomaly analysis for an engine.

        Returns analysis with anomaly_active=False if no anomaly recorded.
        """
        if engine_id in self._latest_analysis:
            return self._latest_analysis[engine_id]

        return AnomalyAnalysis(
            engine_id=engine_id,
            anomaly_active=False,
        )
