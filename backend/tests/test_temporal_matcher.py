"""Unit tests for the Correction Engine temporal matching and EnKF state management.

Tests the TemporalMatcher class which implements:
- Temporal matching of predictions to observations by sensor_id
- Per-sensor EnKFState maintenance with minimum 50 ensemble members
- Timeout-based discard of unmatched items after 2× temporal tolerance

Validates: Requirements 6.1, 6.2, 6.8
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.topics import (
    METRICS_PIPELINE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)
from digital_twin_engine.correction.temporal_matcher import (
    MatchedPair,
    PendingObservation,
    PendingPrediction,
    TemporalMatcher,
)
from digital_twin_engine.shared.models import (
    EnKFState,
    EngineConfig,
    TelemetryEvent,
    serialize_telemetry_event,
)


# ---------------------------------------------------------------------------
# Test broker backend (in-memory for testing)
# ---------------------------------------------------------------------------


class InMemoryBroker(BrokerBackend):
    """In-memory broker for testing. Stores subscriptions and published messages."""

    def __init__(self) -> None:
        self.subscriptions: Dict[str, List[Tuple[str, MessageCallback]]] = {}
        self.published: List[Tuple[str, str, bytes]] = []
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        self.published.append((topic, key, message))

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        if topic not in self.subscriptions:
            self.subscriptions[topic] = []
        self.subscriptions[topic].append((group_id, callback))

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass

    async def deliver(self, topic: str, key: str, message: bytes) -> None:
        """Simulate message delivery to subscribed callbacks."""
        if topic in self.subscriptions:
            for group_id, callback in self.subscriptions[topic]:
                await callback(topic, key, message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_prediction_message(
    sensor_id: str,
    timestamp: datetime,
    values: Optional[List[float]] = None,
) -> bytes:
    """Create a prediction message payload."""
    payload = {
        "sensor_id": sensor_id,
        "prediction_timestamp": timestamp.isoformat(),
        "prediction_horizon_seconds": 60.0,
        "values": values or [100.0],
        "ensemble_spread": 0.5,
        "anomaly_flag": False,
        "source": "ensemble",
        "ensemble_weights": {"lstm": 0.6, "xgboost": 0.4},
    }
    return json.dumps(payload).encode("utf-8")


def make_observation_message(
    sensor_id: str,
    timestamp: datetime,
    value: float = 100.5,
    measurement_type: str = "temperature",
) -> bytes:
    """Create a telemetry observation message payload."""
    event = TelemetryEvent(
        timestamp=timestamp,
        sensor_id=sensor_id,
        measurement_type=measurement_type,
        value=value,
    )
    return serialize_telemetry_event(event).encode("utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> EngineConfig:
    """Default engine config for testing."""
    return EngineConfig(
        temporal_tolerance_seconds=1.0,
        ensemble_size=50,
        anomaly_threshold_sigma=3.0,
    )


@pytest.fixture
def broker() -> InMemoryBroker:
    """In-memory broker instance."""
    return InMemoryBroker()


@pytest.fixture
def match_results() -> List[Tuple[MatchedPair, EnKFState]]:
    """Collector for match callback results."""
    return []


@pytest.fixture
def matcher(
    broker: InMemoryBroker,
    config: EngineConfig,
    match_results: List[Tuple[MatchedPair, EnKFState]],
) -> TemporalMatcher:
    """TemporalMatcher instance with match callback that collects results."""

    async def on_match(pair: MatchedPair, state: EnKFState) -> None:
        match_results.append((pair, state))

    return TemporalMatcher(
        broker=broker,
        config=config,
        on_match=on_match,
    )


# ---------------------------------------------------------------------------
# Tests: Temporal Matching
# ---------------------------------------------------------------------------


class TestTemporalMatching:
    """Tests for temporal matching logic (Requirement 6.1)."""

    @pytest.mark.asyncio
    async def test_prediction_then_observation_within_tolerance(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """Match occurs when observation arrives within tolerance after prediction."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-001"

        # Prediction arrives first
        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        # Observation arrives within 0.5s tolerance
        obs_ts = now + timedelta(seconds=0.5)
        obs_msg = make_observation_message(sensor_id, obs_ts, value=101.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        assert len(match_results) == 1
        pair, state = match_results[0]
        assert pair.sensor_id == sensor_id
        assert pair.observed_value == 101.0
        assert pair.predicted_values == [100.0]

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_observation_then_prediction_within_tolerance(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """Match occurs when prediction arrives within tolerance after observation."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-002"

        # Observation arrives first
        obs_msg = make_observation_message(sensor_id, now, value=50.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        # Prediction arrives within tolerance
        pred_ts = now + timedelta(seconds=0.8)
        pred_msg = make_prediction_message(sensor_id, pred_ts, values=[49.5])
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        assert len(match_results) == 1
        pair, _ = match_results[0]
        assert pair.sensor_id == sensor_id
        assert pair.observed_value == 50.0
        assert pair.predicted_values == [49.5]

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_no_match_when_outside_tolerance(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """No match when timestamp difference exceeds tolerance."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-003"

        # Prediction at time T
        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        # Observation at T + 1.5s (exceeds 1.0s tolerance)
        obs_ts = now + timedelta(seconds=1.5)
        obs_msg = make_observation_message(sensor_id, obs_ts, value=100.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        assert len(match_results) == 0
        assert len(matcher.pending_predictions["sensor-003"]) == 1
        assert len(matcher.pending_observations["sensor-003"]) == 1

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_no_match_across_different_sensors(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """No match when sensor_ids differ even if timestamps match."""
        await matcher.start()

        now = datetime.now(timezone.utc)

        # Prediction for sensor A
        pred_msg = make_prediction_message("sensor-A", now)
        await broker.deliver(PREDICTIONS_STATE, "sensor-A", pred_msg)

        # Observation for sensor B at the same time
        obs_msg = make_observation_message("sensor-B", now, value=100.0)
        await broker.deliver(TELEMETRY_RAW, "sensor-B", obs_msg)

        assert len(match_results) == 0
        assert len(matcher.pending_predictions["sensor-A"]) == 1
        assert len(matcher.pending_observations["sensor-B"]) == 1

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_exact_tolerance_boundary_matches(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """Match occurs at exactly the tolerance boundary (≤ not <)."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-boundary"

        # Prediction at time T
        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        # Observation at exactly T + 1.0s (within tolerance of 1.0s)
        obs_ts = now + timedelta(seconds=1.0)
        obs_msg = make_observation_message(sensor_id, obs_ts, value=200.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        assert len(match_results) == 1

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_closest_match_selected_when_multiple_pending(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """When multiple observations are within tolerance, the closest is matched."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-multi"

        # Two observations at different times
        obs1_ts = now + timedelta(seconds=0.3)
        obs2_ts = now + timedelta(seconds=0.8)
        obs_msg1 = make_observation_message(sensor_id, obs1_ts, value=10.0)
        obs_msg2 = make_observation_message(sensor_id, obs2_ts, value=20.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg1)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg2)

        # Prediction at time T (closest to obs1 at T+0.3)
        pred_msg = make_prediction_message(sensor_id, now, values=[9.5])
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        assert len(match_results) == 1
        pair, _ = match_results[0]
        assert pair.observed_value == 10.0  # Closest observation selected

        await matcher.stop()


# ---------------------------------------------------------------------------
# Tests: EnKF State Management
# ---------------------------------------------------------------------------


class TestEnKFStateManagement:
    """Tests for per-sensor EnKF state management (Requirement 6.2)."""

    def test_get_or_create_initializes_state(
        self, matcher: TemporalMatcher
    ) -> None:
        """A new EnKF state is created with correct ensemble size."""
        state = matcher.get_or_create_enkf_state("new-sensor")

        assert state.sensor_id == "new-sensor"
        assert state.ensemble_size >= 50
        assert state.ensemble_members.shape[0] >= 50
        assert state.iteration_count == 0
        assert state.anomaly_threshold == 3.0

    def test_get_or_create_returns_existing_state(
        self, matcher: TemporalMatcher
    ) -> None:
        """Subsequent calls return the same state object."""
        state1 = matcher.get_or_create_enkf_state("sensor-x")
        state2 = matcher.get_or_create_enkf_state("sensor-x")

        assert state1 is state2

    def test_ensemble_size_matches_config(self, broker: InMemoryBroker) -> None:
        """Ensemble size is configurable and defaults to minimum 50."""
        config = EngineConfig(ensemble_size=100)
        matcher = TemporalMatcher(broker=broker, config=config)

        state = matcher.get_or_create_enkf_state("sensor-large")
        assert state.ensemble_size == 100

    @pytest.mark.asyncio
    async def test_enkf_state_created_on_match(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """EnKF state is auto-created when a match occurs for a new sensor."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "new-sensor-match"

        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        obs_msg = make_observation_message(sensor_id, now, value=42.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        assert sensor_id in matcher.enkf_states
        state = matcher.enkf_states[sensor_id]
        assert state.ensemble_size >= 50

        await matcher.stop()

    def test_different_sensors_have_independent_states(
        self, matcher: TemporalMatcher
    ) -> None:
        """Each sensor has its own independent EnKF state."""
        state_a = matcher.get_or_create_enkf_state("sensor-a")
        state_b = matcher.get_or_create_enkf_state("sensor-b")

        assert state_a is not state_b
        assert state_a.sensor_id == "sensor-a"
        assert state_b.sensor_id == "sensor-b"


# ---------------------------------------------------------------------------
# Tests: Timeout and Discard
# ---------------------------------------------------------------------------


class TestTimeoutDiscard:
    """Tests for unmatched item timeout and discard (Requirement 6.8)."""

    @pytest.mark.asyncio
    async def test_prediction_discarded_after_timeout(
        self, broker: InMemoryBroker
    ) -> None:
        """Unmatched predictions are discarded after 2× tolerance."""
        # Use very short tolerance for test speed
        config = EngineConfig(temporal_tolerance_seconds=0.1, ensemble_size=50)
        matcher = TemporalMatcher(broker=broker, config=config)
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-timeout"

        # Add a prediction that will never be matched
        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        assert len(matcher.pending_predictions.get(sensor_id, [])) == 1

        # Wait for 2× tolerance + cleanup interval margin
        await asyncio.sleep(0.8)

        # Prediction should be discarded
        assert len(matcher.pending_predictions.get(sensor_id, [])) == 0
        assert matcher.prediction_timeouts >= 1

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_observation_discarded_after_timeout(
        self, broker: InMemoryBroker
    ) -> None:
        """Unmatched observations are discarded after 2× tolerance."""
        config = EngineConfig(temporal_tolerance_seconds=0.1, ensemble_size=50)
        matcher = TemporalMatcher(broker=broker, config=config)
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-obs-timeout"

        # Add an observation that will never be matched
        obs_msg = make_observation_message(sensor_id, now, value=55.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        assert len(matcher.pending_observations.get(sensor_id, [])) == 1

        # Wait for 2× tolerance + cleanup margin
        await asyncio.sleep(0.8)

        # Observation should be discarded
        assert len(matcher.pending_observations.get(sensor_id, [])) == 0
        assert matcher.observation_timeouts >= 1

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_timeout_emits_metric(self, broker: InMemoryBroker) -> None:
        """Timeout discards emit a metric to the metrics topic."""
        config = EngineConfig(temporal_tolerance_seconds=0.1, ensemble_size=50)
        matcher = TemporalMatcher(broker=broker, config=config)
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-metric"

        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        # Wait for timeout
        await asyncio.sleep(0.8)

        # Check that a metric was published to METRICS_PIPELINE
        metric_messages = [
            (t, k, m) for t, k, m in broker.published if t == METRICS_PIPELINE
        ]
        assert len(metric_messages) >= 1

        # Verify metric content
        metric_data = json.loads(metric_messages[0][2].decode("utf-8"))
        assert metric_data["metric_type"] == "matching_timeout"
        assert metric_data["sensor_id"] == sensor_id
        assert metric_data["discarded_item_type"] == "prediction"

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_matched_items_not_discarded(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
        match_results: List[Tuple[MatchedPair, EnKFState]],
    ) -> None:
        """Items that are matched are removed from pending and not subject to timeout."""
        await matcher.start()

        now = datetime.now(timezone.utc)
        sensor_id = "sensor-no-timeout"

        # Create a match immediately
        pred_msg = make_prediction_message(sensor_id, now)
        await broker.deliver(PREDICTIONS_STATE, sensor_id, pred_msg)

        obs_msg = make_observation_message(sensor_id, now, value=100.0)
        await broker.deliver(TELEMETRY_RAW, sensor_id, obs_msg)

        # Verify match occurred and pending lists are empty
        assert len(match_results) == 1
        assert len(matcher.pending_predictions.get(sensor_id, [])) == 0
        assert len(matcher.pending_observations.get(sensor_id, [])) == 0

        await matcher.stop()


# ---------------------------------------------------------------------------
# Tests: Message Parsing Edge Cases
# ---------------------------------------------------------------------------


class TestMessageParsing:
    """Tests for message parsing robustness."""

    @pytest.mark.asyncio
    async def test_malformed_prediction_json_ignored(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
    ) -> None:
        """Invalid JSON in prediction message is logged and ignored."""
        await matcher.start()

        await broker.deliver(
            PREDICTIONS_STATE, "sensor-x", b"not valid json"
        )

        assert matcher.matches_count == 0
        assert len(matcher.pending_predictions) == 0

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_malformed_observation_json_ignored(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
    ) -> None:
        """Invalid JSON in observation message is logged and ignored."""
        await matcher.start()

        await broker.deliver(TELEMETRY_RAW, "sensor-x", b"not valid json")

        assert matcher.matches_count == 0
        assert len(matcher.pending_observations) == 0

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_prediction_missing_sensor_id_ignored(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
    ) -> None:
        """Prediction messages without sensor_id are ignored."""
        await matcher.start()

        msg = json.dumps({"prediction_timestamp": "2024-01-01T00:00:00Z"}).encode()
        await broker.deliver(PREDICTIONS_STATE, "", msg)

        assert len(matcher.pending_predictions) == 0

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_prediction_invalid_timestamp_ignored(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
    ) -> None:
        """Prediction messages with invalid timestamps are ignored."""
        await matcher.start()

        msg = json.dumps({
            "sensor_id": "sensor-bad-ts",
            "prediction_timestamp": "not-a-date",
        }).encode()
        await broker.deliver(PREDICTIONS_STATE, "sensor-bad-ts", msg)

        assert len(matcher.pending_predictions) == 0

        await matcher.stop()


# ---------------------------------------------------------------------------
# Tests: Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for matcher start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_subscribes_to_both_topics(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
    ) -> None:
        """Starting the matcher subscribes to predictions.state and telemetry.raw."""
        await matcher.start()

        assert PREDICTIONS_STATE in broker.subscriptions
        assert TELEMETRY_RAW in broker.subscriptions

        await matcher.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_cleanup_task(
        self,
        matcher: TemporalMatcher,
        broker: InMemoryBroker,
    ) -> None:
        """Stopping the matcher cancels the cleanup task."""
        await matcher.start()
        assert matcher.running is True

        await matcher.stop()
        assert matcher.running is False
