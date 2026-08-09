"""Temporal matching and EnKF state management for the Correction Engine.

This module implements:
- An async consumer reading from `predictions.state` and `telemetry.raw` topics
- Temporal matching: match predictions to observations by sensor_id when
  timestamp difference ≤ configured tolerance (default 1s)
- Per-sensor EnKFState maintenance with minimum 50 ensemble members
- Discard unmatched items after 2× temporal tolerance timeout; emit matching
  timeout metric

Requirements: 6.1, 6.2, 6.8
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import numpy as np

from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import (
    METRICS_PIPELINE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)
from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import (
    EnKFState,
    EngineConfig,
    Prediction,
    TelemetryEvent,
    deserialize_telemetry_event,
)


logger = get_logger("correction_engine")


# ---------------------------------------------------------------------------
# Matched pair type
# ---------------------------------------------------------------------------


@dataclass
class MatchedPair:
    """A temporally-matched prediction and observation for EnKF iteration."""

    sensor_id: str
    prediction_timestamp: datetime
    observation_timestamp: datetime
    predicted_values: List[float]
    observed_value: float
    prediction_source: str  # model_used field
    ensemble_weights: Dict[str, float]


# ---------------------------------------------------------------------------
# Pending items with arrival timestamps for timeout tracking
# ---------------------------------------------------------------------------


@dataclass
class PendingPrediction:
    """A prediction waiting for a matching observation."""

    sensor_id: str
    timestamp: datetime
    values: List[float]
    model_used: str
    ensemble_weights: Dict[str, float]
    arrival_time: float  # monotonic clock for timeout tracking


@dataclass
class PendingObservation:
    """An observation waiting for a matching prediction."""

    sensor_id: str
    timestamp: datetime
    value: float
    measurement_type: str
    arrival_time: float  # monotonic clock for timeout tracking


# Type for the EnKF iteration callback
EnKFIterationFunc = Callable[
    [MatchedPair, EnKFState],
    Awaitable[None],
]


# ---------------------------------------------------------------------------
# TemporalMatcher
# ---------------------------------------------------------------------------


class TemporalMatcher:
    """Matches predictions to observations by sensor_id and temporal proximity.

    Consumes from both `predictions.state` and `telemetry.raw` topics.
    When a prediction and observation for the same sensor have timestamps
    within the configured tolerance, they are matched and trigger an EnKF
    iteration (via the provided callback).

    Unmatched items are discarded after 2× the temporal tolerance and a
    timeout metric is emitted.

    Args:
        broker: The message broker backend for consuming/publishing.
        config: Engine configuration with temporal tolerance and ensemble size.
        on_match: Async callback invoked when a match is found. Receives the
                  matched pair and the sensor's EnKFState.
        consumer_group: Consumer group ID for broker subscriptions.
    """

    def __init__(
        self,
        broker: BrokerBackend,
        config: EngineConfig,
        on_match: Optional[EnKFIterationFunc] = None,
        consumer_group: str = "correction_engine",
    ) -> None:
        self._broker = broker
        self._config = config
        self._on_match = on_match
        self._consumer_group = consumer_group

        # Per-sensor pending items keyed by sensor_id
        self._pending_predictions: Dict[str, List[PendingPrediction]] = defaultdict(list)
        self._pending_observations: Dict[str, List[PendingObservation]] = defaultdict(list)

        # Per-sensor EnKF state
        self._enkf_states: Dict[str, EnKFState] = {}

        # Runtime state
        self._running = False
        self._cleanup_task: Optional[asyncio.Task[None]] = None

        # Metrics counters
        self._matches_count: int = 0
        self._prediction_timeouts: int = 0
        self._observation_timeouts: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def pending_predictions(self) -> Dict[str, List[PendingPrediction]]:
        """Access to pending predictions (for testing/inspection)."""
        return self._pending_predictions

    @property
    def pending_observations(self) -> Dict[str, List[PendingObservation]]:
        """Access to pending observations (for testing/inspection)."""
        return self._pending_observations

    @property
    def enkf_states(self) -> Dict[str, EnKFState]:
        """Access to per-sensor EnKF states (for testing/inspection)."""
        return self._enkf_states

    @property
    def matches_count(self) -> int:
        """Total number of successful matches."""
        return self._matches_count

    @property
    def prediction_timeouts(self) -> int:
        """Total number of predictions discarded due to timeout."""
        return self._prediction_timeouts

    @property
    def observation_timeouts(self) -> int:
        """Total number of observations discarded due to timeout."""
        return self._observation_timeouts

    @property
    def running(self) -> bool:
        """Whether the matcher is currently running."""
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start consuming from both topics and begin timeout cleanup.

        Subscribes to `predictions.state` and `telemetry.raw` topics and
        starts the periodic cleanup task for expired items.
        """
        self._running = True

        await self._broker.subscribe(
            PREDICTIONS_STATE,
            self._consumer_group,
            self._on_prediction_message,
        )
        await self._broker.subscribe(
            TELEMETRY_RAW,
            self._consumer_group,
            self._on_observation_message,
        )

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(
            "Temporal matcher started",
            temporal_tolerance_s=self._config.temporal_tolerance_seconds,
            ensemble_size=self._config.ensemble_size,
        )

    async def stop(self) -> None:
        """Stop the matcher and cancel the cleanup task."""
        self._running = False

        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        logger.info(
            "Temporal matcher stopped",
            total_matches=self._matches_count,
            prediction_timeouts=self._prediction_timeouts,
            observation_timeouts=self._observation_timeouts,
        )

    # ------------------------------------------------------------------
    # EnKF State Management
    # ------------------------------------------------------------------

    def get_or_create_enkf_state(self, sensor_id: str) -> EnKFState:
        """Get or initialize the EnKF state for a sensor.

        Creates a new state with the configured ensemble size if one doesn't
        exist for the given sensor_id. The ensemble members are initialized
        with small random perturbations around zero.

        Args:
            sensor_id: The sensor identifier.

        Returns:
            The EnKFState for the sensor.
        """
        if sensor_id not in self._enkf_states:
            ensemble_size = self._config.ensemble_size
            # Initialize ensemble with small random perturbations
            # State dimension defaults to 1 (scalar observation)
            state_dim = 1
            ensemble_members = np.random.randn(ensemble_size, state_dim) * 0.1
            observation_noise_cov = np.eye(state_dim) * 0.01

            self._enkf_states[sensor_id] = EnKFState(
                sensor_id=sensor_id,
                ensemble_members=ensemble_members,
                observation_noise_cov=observation_noise_cov,
                last_update_timestamp=datetime.now(timezone.utc),
                iteration_count=0,
                anomaly_threshold=self._config.anomaly_threshold_sigma,
            )

            logger.info(
                "Initialized EnKF state",
                sensor_id=sensor_id,
                ensemble_size=ensemble_size,
                state_dim=state_dim,
            )

        return self._enkf_states[sensor_id]

    # ------------------------------------------------------------------
    # Message Handlers
    # ------------------------------------------------------------------

    async def _on_prediction_message(
        self, topic: str, key: str, message: bytes
    ) -> None:
        """Handle incoming prediction messages from predictions.state topic.

        Parses the prediction, attempts to find a matching observation,
        and if no match is found, stores it as pending.
        """
        try:
            data = json.loads(message.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Failed to parse prediction message", error=str(exc))
            return

        sensor_id = data.get("sensor_id", "")
        if not sensor_id:
            logger.warning("Prediction message missing sensor_id")
            return

        timestamp_str = data.get("prediction_timestamp", "")
        try:
            prediction_ts = datetime.fromisoformat(
                timestamp_str.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError) as exc:
            logger.warning(
                "Invalid prediction timestamp",
                sensor_id=sensor_id,
                error=str(exc),
            )
            return

        prediction = PendingPrediction(
            sensor_id=sensor_id,
            timestamp=prediction_ts,
            values=data.get("values", []),
            model_used=data.get("source", "ensemble"),
            ensemble_weights=data.get("ensemble_weights", {}),
            arrival_time=time.monotonic(),
        )

        # Try to find a matching observation
        matched_obs = self._find_matching_observation(sensor_id, prediction_ts)

        if matched_obs is not None:
            await self._handle_match(prediction, matched_obs)
        else:
            self._pending_predictions[sensor_id].append(prediction)

    async def _on_observation_message(
        self, topic: str, key: str, message: bytes
    ) -> None:
        """Handle incoming observation messages from telemetry.raw topic.

        Parses the telemetry event, attempts to find a matching prediction,
        and if no match is found, stores it as pending.
        """
        try:
            event = deserialize_telemetry_event(message.decode("utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse observation message", error=str(exc))
            return

        sensor_id = event.sensor_id
        observation = PendingObservation(
            sensor_id=sensor_id,
            timestamp=event.timestamp,
            value=event.value,
            measurement_type=event.measurement_type,
            arrival_time=time.monotonic(),
        )

        # Try to find a matching prediction
        matched_pred = self._find_matching_prediction(sensor_id, event.timestamp)

        if matched_pred is not None:
            await self._handle_match(matched_pred, observation)
        else:
            self._pending_observations[sensor_id].append(observation)

    # ------------------------------------------------------------------
    # Temporal Matching Logic
    # ------------------------------------------------------------------

    def _find_matching_observation(
        self, sensor_id: str, prediction_ts: datetime
    ) -> Optional[PendingObservation]:
        """Find and remove the best matching observation for a prediction.

        Searches pending observations for the same sensor_id where the
        absolute timestamp difference is within the configured tolerance.
        Returns the closest match if multiple qualify.

        Returns:
            The matching PendingObservation, or None if no match found.
        """
        tolerance = self._config.temporal_tolerance_seconds
        observations = self._pending_observations.get(sensor_id, [])

        if not observations:
            return None

        best_match: Optional[PendingObservation] = None
        best_diff: float = float("inf")
        best_idx: int = -1

        for i, obs in enumerate(observations):
            diff = abs((prediction_ts - obs.timestamp).total_seconds())
            if diff <= tolerance and diff < best_diff:
                best_match = obs
                best_diff = diff
                best_idx = i

        if best_match is not None:
            observations.pop(best_idx)
            # Clean up empty list
            if not observations:
                del self._pending_observations[sensor_id]

        return best_match

    def _find_matching_prediction(
        self, sensor_id: str, observation_ts: datetime
    ) -> Optional[PendingPrediction]:
        """Find and remove the best matching prediction for an observation.

        Searches pending predictions for the same sensor_id where the
        absolute timestamp difference is within the configured tolerance.
        Returns the closest match if multiple qualify.

        Returns:
            The matching PendingPrediction, or None if no match found.
        """
        tolerance = self._config.temporal_tolerance_seconds
        predictions = self._pending_predictions.get(sensor_id, [])

        if not predictions:
            return None

        best_match: Optional[PendingPrediction] = None
        best_diff: float = float("inf")
        best_idx: int = -1

        for i, pred in enumerate(predictions):
            diff = abs((observation_ts - pred.timestamp).total_seconds())
            if diff <= tolerance and diff < best_diff:
                best_match = pred
                best_diff = diff
                best_idx = i

        if best_match is not None:
            predictions.pop(best_idx)
            # Clean up empty list
            if not predictions:
                del self._pending_predictions[sensor_id]

        return best_match

    # ------------------------------------------------------------------
    # Match Handling
    # ------------------------------------------------------------------

    async def _handle_match(
        self,
        prediction: PendingPrediction,
        observation: PendingObservation,
    ) -> None:
        """Process a matched prediction-observation pair.

        Creates a MatchedPair, retrieves/creates the sensor's EnKF state,
        and invokes the EnKF iteration callback.
        """
        self._matches_count += 1

        matched_pair = MatchedPair(
            sensor_id=prediction.sensor_id,
            prediction_timestamp=prediction.timestamp,
            observation_timestamp=observation.timestamp,
            predicted_values=prediction.values,
            observed_value=observation.value,
            prediction_source=prediction.model_used,
            ensemble_weights=prediction.ensemble_weights,
        )

        enkf_state = self.get_or_create_enkf_state(prediction.sensor_id)

        logger.info(
            "Temporal match found",
            sensor_id=prediction.sensor_id,
            prediction_ts=prediction.timestamp.isoformat(),
            observation_ts=observation.timestamp.isoformat(),
            time_diff_s=abs(
                (prediction.timestamp - observation.timestamp).total_seconds()
            ),
        )

        if self._on_match is not None:
            await self._on_match(matched_pair, enkf_state)

    # ------------------------------------------------------------------
    # Timeout Cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Periodically discard unmatched items that have exceeded 2× tolerance.

        Runs every 0.5 seconds to check for expired predictions and
        observations, emitting timeout metrics for each discarded item.
        """
        try:
            while self._running:
                await asyncio.sleep(0.5)
                await self._cleanup_expired_items()
        except asyncio.CancelledError:
            pass

    async def _cleanup_expired_items(self) -> None:
        """Remove and emit metrics for items that exceeded the timeout.

        Items are discarded if they have been pending for longer than
        2 × temporal_tolerance_seconds (measured from their arrival time).
        """
        timeout = 2.0 * self._config.temporal_tolerance_seconds
        now = time.monotonic()

        # Clean up expired predictions
        expired_prediction_sensors: List[str] = []
        for sensor_id, predictions in list(self._pending_predictions.items()):
            expired_indices = []
            for i, pred in enumerate(predictions):
                if (now - pred.arrival_time) >= timeout:
                    expired_indices.append(i)

            # Remove in reverse order to maintain indices
            for i in reversed(expired_indices):
                discarded = predictions.pop(i)
                self._prediction_timeouts += 1
                await self._emit_timeout_metric(
                    sensor_id=sensor_id,
                    item_type="prediction",
                    timestamp=discarded.timestamp,
                )

            if not predictions:
                expired_prediction_sensors.append(sensor_id)

        for sensor_id in expired_prediction_sensors:
            if sensor_id in self._pending_predictions:
                del self._pending_predictions[sensor_id]

        # Clean up expired observations
        expired_observation_sensors: List[str] = []
        for sensor_id, observations in list(self._pending_observations.items()):
            expired_indices = []
            for i, obs in enumerate(observations):
                if (now - obs.arrival_time) >= timeout:
                    expired_indices.append(i)

            # Remove in reverse order to maintain indices
            for i in reversed(expired_indices):
                discarded = observations.pop(i)
                self._observation_timeouts += 1
                await self._emit_timeout_metric(
                    sensor_id=sensor_id,
                    item_type="observation",
                    timestamp=discarded.timestamp,
                )

            if not observations:
                expired_observation_sensors.append(sensor_id)

        for sensor_id in expired_observation_sensors:
            if sensor_id in self._pending_observations:
                del self._pending_observations[sensor_id]

    async def _emit_timeout_metric(
        self,
        sensor_id: str,
        item_type: str,
        timestamp: datetime,
    ) -> None:
        """Emit a matching timeout metric to the metrics topic.

        Args:
            sensor_id: The sensor that had the unmatched item.
            item_type: Either "prediction" or "observation".
            timestamp: The timestamp of the discarded item.
        """
        metric = {
            "metric_type": "matching_timeout",
            "sensor_id": sensor_id,
            "discarded_item_type": item_type,
            "item_timestamp": timestamp.isoformat(),
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            "tolerance_seconds": self._config.temporal_tolerance_seconds,
        }

        logger.warning(
            "Temporal match timeout - discarding unmatched item",
            sensor_id=sensor_id,
            item_type=item_type,
            item_timestamp=timestamp.isoformat(),
        )

        try:
            message = json.dumps(metric).encode("utf-8")
            await self._broker.publish(METRICS_PIPELINE, sensor_id, message)
        except Exception as exc:
            logger.error(
                "Failed to emit timeout metric",
                sensor_id=sensor_id,
                error=str(exc),
            )
