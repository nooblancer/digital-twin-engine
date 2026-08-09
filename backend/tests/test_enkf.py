"""Unit tests for the EnKF iteration algorithm.

Tests the EnKFIteration class and compute_enkf_step function which implement:
- Full EnKF iteration: forecast → Kalman Gain → ensemble update
- Matrix singularity handling via pseudo-inverse
- Ensemble collapse detection and re-inflation
- Publishing corrected StateVector to broker and TSDB

Validates: Requirements 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pytest

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.topics import CORRECTIONS_STATE
from digital_twin_engine.correction.enkf import (
    EnKFIteration,
    _MIN_ENSEMBLE_SPREAD,
    _REINFLATION_NOISE_STD,
    compute_enkf_step,
)
from digital_twin_engine.correction.temporal_matcher import MatchedPair
from digital_twin_engine.shared.models import EnKFState, StateVector


# ---------------------------------------------------------------------------
# Test broker (in-memory)
# ---------------------------------------------------------------------------


class InMemoryBroker(BrokerBackend):
    """In-memory broker for testing."""

    def __init__(self) -> None:
        self.published: List[Tuple[str, str, bytes]] = []
        self._fail_publish = False

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        if self._fail_publish:
            raise RuntimeError("Simulated publish failure")
        self.published.append((topic, key, message))

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        pass

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass

    def set_fail_publish(self, fail: bool) -> None:
        self._fail_publish = fail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_matched_pair(
    sensor_id: str = "sensor-001",
    predicted_values: Optional[List[float]] = None,
    observed_value: float = 100.5,
) -> MatchedPair:
    """Create a MatchedPair for testing."""
    now = datetime.now(timezone.utc)
    return MatchedPair(
        sensor_id=sensor_id,
        prediction_timestamp=now,
        observation_timestamp=now + timedelta(seconds=0.5),
        predicted_values=predicted_values or [100.0],
        observed_value=observed_value,
        prediction_source="ensemble",
        ensemble_weights={"lstm": 0.6, "xgboost": 0.4},
    )


def make_enkf_state(
    sensor_id: str = "sensor-001",
    ensemble_size: int = 50,
    state_dim: int = 1,
    mean_value: float = 100.0,
    spread: float = 1.0,
    observation_noise: float = 0.01,
) -> EnKFState:
    """Create an EnKFState for testing with controlled parameters."""
    ensemble_members = (
        np.random.randn(ensemble_size, state_dim) * spread
        + mean_value
    )
    observation_noise_cov = np.eye(state_dim) * observation_noise
    return EnKFState(
        sensor_id=sensor_id,
        ensemble_members=ensemble_members,
        observation_noise_cov=observation_noise_cov,
        last_update_timestamp=datetime.now(timezone.utc),
        iteration_count=0,
        anomaly_threshold=3.0,
    )


# ---------------------------------------------------------------------------
# Tests: Core EnKF Computation
# ---------------------------------------------------------------------------


class TestEnKFComputation:
    """Tests for the core EnKF mathematical computation."""

    def test_compute_enkf_step_basic(self) -> None:
        """Basic EnKF step produces valid output dimensions."""
        N, d = 50, 1
        np.random.seed(42)
        X_f = np.random.randn(N, d) * 1.0 + 100.0
        y_obs = 101.0
        H = np.eye(d)
        R = np.eye(d) * 0.01

        X_a, corrected_mean, spread, innov_mag, anomaly = compute_enkf_step(
            X_f, y_obs, H, R
        )

        assert X_a.shape == (N, d)
        assert corrected_mean.shape == (d,)
        assert spread > 0
        assert innov_mag >= 0
        assert isinstance(anomaly, bool)

    def test_corrected_mean_moves_toward_observation(self) -> None:
        """Corrected mean should move closer to observation than forecast mean."""
        N, d = 100, 1
        np.random.seed(42)
        forecast_mean = 100.0
        observation = 105.0

        X_f = np.random.randn(N, d) * 2.0 + forecast_mean
        H = np.eye(d)
        R = np.eye(d) * 0.5

        _, corrected_mean, _, _, _ = compute_enkf_step(X_f, observation, H, R)

        # Corrected mean should be between forecast mean and observation
        forecast_mean_actual = np.mean(X_f, axis=0)[0]
        assert abs(corrected_mean[0] - observation) < abs(
            forecast_mean_actual - observation
        )

    def test_low_observation_noise_trusts_observation_more(self) -> None:
        """With low observation noise, corrected state should be closer to obs."""
        N, d = 100, 1
        np.random.seed(42)
        X_f = np.random.randn(N, d) * 2.0 + 100.0
        observation = 110.0
        H = np.eye(d)

        # Low noise → trust observation more
        R_low = np.eye(d) * 0.001
        _, mean_low_noise, _, _, _ = compute_enkf_step(X_f.copy(), observation, H, R_low)

        # High noise → trust observation less
        R_high = np.eye(d) * 100.0
        _, mean_high_noise, _, _, _ = compute_enkf_step(X_f.copy(), observation, H, R_high)

        # Low noise result should be closer to observation
        assert abs(mean_low_noise[0] - observation) < abs(
            mean_high_noise[0] - observation
        )

    def test_ensemble_size_preserved(self) -> None:
        """Ensemble size should not change after update."""
        N, d = 75, 1
        np.random.seed(42)
        X_f = np.random.randn(N, d) + 50.0
        H = np.eye(d)
        R = np.eye(d) * 0.1

        X_a, _, _, _, _ = compute_enkf_step(X_f, 51.0, H, R)

        assert X_a.shape[0] == N

    def test_multidimensional_state(self) -> None:
        """EnKF works with multi-dimensional state vectors."""
        N, d = 50, 3
        np.random.seed(42)
        X_f = np.random.randn(N, d) * 2.0 + np.array([10.0, 20.0, 30.0])
        y_obs = 12.0  # Observe first component only
        H = np.zeros((1, d))
        H[0, 0] = 1.0
        R = np.eye(1) * 0.1

        X_a, corrected_mean, spread, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        assert X_a.shape == (N, d)
        assert corrected_mean.shape == (d,)
        # First component should move toward observation
        assert abs(corrected_mean[0] - y_obs) < abs(np.mean(X_f[:, 0]) - y_obs)

    def test_anomaly_detection_triggered(self) -> None:
        """Anomaly flag is set when innovation exceeds threshold × std."""
        N, d = 50, 1
        np.random.seed(42)
        # Very tight ensemble (low spread)
        X_f = np.random.randn(N, d) * 0.1 + 100.0
        # Observation far from prediction → large innovation
        y_obs = 200.0
        H = np.eye(d)
        R = np.eye(d) * 0.01

        _, _, _, innov_mag, anomaly = compute_enkf_step(
            X_f, y_obs, H, R, anomaly_threshold=3.0
        )

        assert anomaly is True
        assert innov_mag > 3.0 * 0.1  # innovation > 3σ

    def test_no_anomaly_for_small_innovation(self) -> None:
        """No anomaly when innovation is within threshold."""
        N, d = 50, 1
        np.random.seed(42)
        X_f = np.random.randn(N, d) * 5.0 + 100.0
        # Observation close to mean → small innovation
        y_obs = 100.5
        H = np.eye(d)
        R = np.eye(d) * 0.1

        _, _, _, innov_mag, anomaly = compute_enkf_step(
            X_f, y_obs, H, R, anomaly_threshold=3.0
        )

        assert anomaly is False

    def test_ensemble_collapse_reinflation(self) -> None:
        """Collapsed ensemble (near-zero spread) is re-inflated."""
        N, d = 50, 1
        # All members identical → zero spread
        X_f = np.ones((N, d)) * 100.0
        y_obs = 101.0
        H = np.eye(d)
        R = np.eye(d) * 0.1

        X_a, _, spread, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        # After re-inflation and update, spread should be non-zero
        assert spread > 0
        # And ensemble should still have the right shape
        assert X_a.shape == (N, d)

    def test_singular_matrix_handled(self) -> None:
        """Singular S matrix is handled via pseudo-inverse."""
        N, d = 50, 1
        np.random.seed(42)
        X_f = np.random.randn(N, d) * 1.0 + 100.0
        y_obs = 101.0
        H = np.eye(d)
        # Zero R → S could be singular if P_f is also singular
        R = np.zeros((d, d))

        # Should not raise, uses pseudo-inverse
        X_a, corrected_mean, spread, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        assert not np.any(np.isnan(corrected_mean))
        assert not np.any(np.isinf(corrected_mean))


# ---------------------------------------------------------------------------
# Tests: EnKFIteration class (integration with broker)
# ---------------------------------------------------------------------------


class TestEnKFIteration:
    """Tests for the EnKFIteration callback class."""

    @pytest.mark.asyncio
    async def test_iteration_publishes_to_broker(self) -> None:
        """EnKF iteration publishes corrected state to corrections.state."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state()

        await enkf(pair, state)

        # Should have published to corrections.state topic
        assert len(broker.published) == 1
        topic, key, payload = broker.published[0]
        assert topic == CORRECTIONS_STATE
        assert key == "sensor-001"

        # Verify message format
        msg = json.loads(payload.decode("utf-8"))
        assert msg["sensor_id"] == "sensor-001"
        assert "correction_timestamp" in msg
        assert "corrected_state_vector" in msg
        assert isinstance(msg["corrected_state_vector"], list)
        assert "ensemble_spread" in msg
        assert "anomaly_flag" in msg
        assert msg["source"] == "correction"

    @pytest.mark.asyncio
    async def test_iteration_updates_enkf_state(self) -> None:
        """EnKF iteration updates state in-place (iteration count, members)."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state()

        original_count = state.iteration_count
        original_members = state.ensemble_members.copy()

        await enkf(pair, state)

        assert state.iteration_count == original_count + 1
        # Members should have changed
        assert not np.array_equal(state.ensemble_members, original_members)

    @pytest.mark.asyncio
    async def test_iteration_preserves_ensemble_size(self) -> None:
        """EnKF iteration does not change ensemble size (≥ 50)."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state(ensemble_size=75)

        await enkf(pair, state)

        assert state.ensemble_size == 75

    @pytest.mark.asyncio
    async def test_iteration_records_latency(self) -> None:
        """EnKF iteration records latency metrics."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state()

        await enkf(pair, state)

        assert enkf.iterations_count == 1
        assert enkf.last_latency_ms > 0
        assert enkf.average_latency_ms > 0

    @pytest.mark.asyncio
    async def test_iteration_within_latency_budget(self) -> None:
        """EnKF iteration completes within 100ms latency budget."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state(ensemble_size=50)

        start = time.perf_counter()
        await enkf(pair, state)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        # Allow generous margin for CI environments but should be well under 100ms
        assert elapsed_ms < 100.0

    @pytest.mark.asyncio
    async def test_iteration_calls_tsdb_write(self) -> None:
        """EnKF iteration writes corrected state to TSDB when handler provided."""
        broker = InMemoryBroker()
        written_states: List[StateVector] = []

        async def tsdb_write(state: StateVector) -> None:
            written_states.append(state)

        enkf = EnKFIteration(broker=broker, tsdb_write_func=tsdb_write)

        pair = make_matched_pair()
        state = make_enkf_state()

        await enkf(pair, state)

        assert len(written_states) == 1
        assert written_states[0].sensor_id == "sensor-001"
        assert written_states[0].source == "correction"

    @pytest.mark.asyncio
    async def test_iteration_handles_publish_failure(self) -> None:
        """EnKF iteration handles broker publish failure gracefully."""
        broker = InMemoryBroker()
        broker.set_fail_publish(True)
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state()

        # Should not raise
        await enkf(pair, state)

        # State should still be updated
        assert state.iteration_count == 1

    @pytest.mark.asyncio
    async def test_iteration_handles_tsdb_failure(self) -> None:
        """EnKF iteration handles TSDB write failure gracefully."""
        broker = InMemoryBroker()

        async def failing_tsdb_write(state: StateVector) -> None:
            raise RuntimeError("TSDB down")

        enkf = EnKFIteration(broker=broker, tsdb_write_func=failing_tsdb_write)

        pair = make_matched_pair()
        state = make_enkf_state()

        # Should not raise
        await enkf(pair, state)

        # Broker should still get the message
        assert len(broker.published) == 1

    @pytest.mark.asyncio
    async def test_multiple_iterations_accumulate_metrics(self) -> None:
        """Multiple iterations accumulate iteration count and latency."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        pair = make_matched_pair()
        state = make_enkf_state()

        for _ in range(5):
            await enkf(pair, state)

        assert enkf.iterations_count == 5
        assert state.iteration_count == 5
        assert enkf.average_latency_ms > 0

    @pytest.mark.asyncio
    async def test_corrected_mean_is_published_value(self) -> None:
        """Published corrected_state_vector is the ensemble mean after update."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        # Use a known observation that should pull the mean
        pair = make_matched_pair(observed_value=105.0)
        state = make_enkf_state(mean_value=100.0, spread=2.0)

        await enkf(pair, state)

        msg = json.loads(broker.published[0][2].decode("utf-8"))
        corrected_values = msg["corrected_state_vector"]

        # The published value should match the ensemble mean of updated state
        actual_mean = np.mean(state.ensemble_members, axis=0).tolist()
        for pub_val, actual_val in zip(corrected_values, actual_mean):
            assert abs(pub_val - actual_val) < 1e-10


# ---------------------------------------------------------------------------
# Tests: Anomaly Detection (Task 7.3)
# Validates: Requirement 6.7
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    """Tests for anomaly detection in the EnKF correction engine.

    Validates Requirement 6.7:
    - Flag corrected StateVector when innovation magnitude > threshold × ensemble std
    - Emit anomaly event to alerts.anomaly topic with required fields
    - Configurable anomaly threshold (default 3.0σ, range 1.0-10.0)
    """

    @pytest.mark.asyncio
    async def test_anomaly_flag_set_when_innovation_exceeds_threshold(self) -> None:
        """StateVector anomaly_flag is True when innovation > threshold × ensemble std."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        # Tight ensemble (small spread) with observation far away → large innovation
        np.random.seed(42)
        pair = make_matched_pair(observed_value=200.0)
        state = make_enkf_state(mean_value=100.0, spread=0.1, observation_noise=0.01)
        state.anomaly_threshold = 3.0

        await enkf(pair, state)

        # Check the published corrected state has anomaly_flag=True
        corrections_msg = None
        for topic, key, payload in broker.published:
            if topic == CORRECTIONS_STATE:
                corrections_msg = json.loads(payload.decode("utf-8"))
                break

        assert corrections_msg is not None
        assert corrections_msg["anomaly_flag"] is True

    @pytest.mark.asyncio
    async def test_anomaly_flag_not_set_for_normal_observation(self) -> None:
        """StateVector anomaly_flag is False when innovation is within threshold."""
        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        # Wide ensemble with observation close to mean → small innovation
        np.random.seed(42)
        pair = make_matched_pair(observed_value=100.2)
        state = make_enkf_state(mean_value=100.0, spread=5.0, observation_noise=0.1)
        state.anomaly_threshold = 3.0

        await enkf(pair, state)

        # Check the published corrected state has anomaly_flag=False
        corrections_msg = None
        for topic, key, payload in broker.published:
            if topic == CORRECTIONS_STATE:
                corrections_msg = json.loads(payload.decode("utf-8"))
                break

        assert corrections_msg is not None
        assert corrections_msg["anomaly_flag"] is False

    @pytest.mark.asyncio
    async def test_anomaly_event_emitted_to_alerts_topic(self) -> None:
        """Anomaly detection emits event to alerts.anomaly topic with required fields."""
        from digital_twin_engine.broker.topics import ALERTS_ANOMALY

        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        # Trigger anomaly: observation far from tight ensemble
        np.random.seed(42)
        pair = make_matched_pair(
            sensor_id="turbine-007",
            observed_value=500.0,
            predicted_values=[100.0],
        )
        state = make_enkf_state(
            sensor_id="turbine-007",
            mean_value=100.0,
            spread=0.5,
            observation_noise=0.01,
        )
        state.anomaly_threshold = 3.0

        await enkf(pair, state)

        # Find the anomaly event in published messages
        anomaly_msg = None
        for topic, key, payload in broker.published:
            if topic == ALERTS_ANOMALY:
                anomaly_msg = json.loads(payload.decode("utf-8"))
                break

        assert anomaly_msg is not None, "No anomaly event published to alerts.anomaly"

        # Validate required fields per requirement 6.7
        assert anomaly_msg["sensor_id"] == "turbine-007"
        assert "correction_timestamp" in anomaly_msg
        assert anomaly_msg["observed_value"] == 500.0
        assert "predicted_value" in anomaly_msg
        assert isinstance(anomaly_msg["predicted_value"], float)
        assert "innovation_magnitude" in anomaly_msg
        assert anomaly_msg["innovation_magnitude"] > 0
        assert anomaly_msg["threshold"] == 3.0

    @pytest.mark.asyncio
    async def test_no_anomaly_event_when_within_threshold(self) -> None:
        """No anomaly event emitted when innovation is within threshold."""
        from digital_twin_engine.broker.topics import ALERTS_ANOMALY

        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        # Normal observation close to prediction
        np.random.seed(42)
        pair = make_matched_pair(observed_value=100.1)
        state = make_enkf_state(mean_value=100.0, spread=5.0, observation_noise=0.1)
        state.anomaly_threshold = 3.0

        await enkf(pair, state)

        # No message should be published to alerts.anomaly
        anomaly_messages = [
            (t, k, p) for t, k, p in broker.published if t == ALERTS_ANOMALY
        ]
        assert len(anomaly_messages) == 0

    @pytest.mark.asyncio
    async def test_configurable_anomaly_threshold(self) -> None:
        """Anomaly threshold is configurable and affects detection sensitivity."""
        from digital_twin_engine.broker.topics import ALERTS_ANOMALY

        broker_strict = InMemoryBroker()
        broker_lenient = InMemoryBroker()

        # Set up identical scenario with different thresholds
        np.random.seed(42)
        pair = make_matched_pair(observed_value=115.0)
        state_strict = make_enkf_state(mean_value=100.0, spread=2.0, observation_noise=0.01)
        state_strict.anomaly_threshold = 1.5  # Strict threshold → anomaly

        np.random.seed(42)
        state_lenient = make_enkf_state(mean_value=100.0, spread=2.0, observation_noise=0.01)
        state_lenient.anomaly_threshold = 10.0  # Lenient threshold → no anomaly

        enkf_strict = EnKFIteration(broker=broker_strict)
        enkf_lenient = EnKFIteration(broker=broker_lenient)

        await enkf_strict(pair, state_strict)
        await enkf_lenient(pair, state_lenient)

        # Strict threshold should trigger anomaly
        strict_anomalies = [
            t for t, _, _ in broker_strict.published if t == ALERTS_ANOMALY
        ]
        assert len(strict_anomalies) == 1

        # Lenient threshold should NOT trigger anomaly
        lenient_anomalies = [
            t for t, _, _ in broker_lenient.published if t == ALERTS_ANOMALY
        ]
        assert len(lenient_anomalies) == 0

    @pytest.mark.asyncio
    async def test_anomaly_threshold_from_engine_config(self) -> None:
        """EngineConfig.anomaly_threshold_sigma validates range 1.0-10.0."""
        from digital_twin_engine.shared.models import EngineConfig

        # Default is 3.0
        config = EngineConfig()
        assert config.anomaly_threshold_sigma == 3.0

        # Valid range bounds
        config_min = EngineConfig(anomaly_threshold_sigma=1.0)
        assert config_min.anomaly_threshold_sigma == 1.0

        config_max = EngineConfig(anomaly_threshold_sigma=10.0)
        assert config_max.anomaly_threshold_sigma == 10.0

        # Below range → validation error
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EngineConfig(anomaly_threshold_sigma=0.5)

        # Above range → validation error
        with pytest.raises(ValidationError):
            EngineConfig(anomaly_threshold_sigma=11.0)

    @pytest.mark.asyncio
    async def test_anomaly_event_key_is_sensor_id(self) -> None:
        """Anomaly event is published with sensor_id as the message key."""
        from digital_twin_engine.broker.topics import ALERTS_ANOMALY

        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        np.random.seed(42)
        pair = make_matched_pair(sensor_id="pump-42", observed_value=999.0)
        state = make_enkf_state(
            sensor_id="pump-42", mean_value=100.0, spread=0.1, observation_noise=0.01
        )
        state.anomaly_threshold = 3.0

        await enkf(pair, state)

        # Verify key for anomaly event is sensor_id
        for topic, key, payload in broker.published:
            if topic == ALERTS_ANOMALY:
                assert key == "pump-42"
                break
        else:
            pytest.fail("No anomaly event found")

    @pytest.mark.asyncio
    async def test_anomaly_innovation_magnitude_correct(self) -> None:
        """Innovation magnitude in anomaly event equals |y_obs - H * x_predicted|."""
        from digital_twin_engine.broker.topics import ALERTS_ANOMALY

        broker = InMemoryBroker()
        enkf = EnKFIteration(broker=broker)

        # Use known values: ensemble mean at ~100, observation at 200
        np.random.seed(42)
        pair = make_matched_pair(
            predicted_values=[100.0],
            observed_value=200.0,
        )
        state = make_enkf_state(mean_value=100.0, spread=0.1, observation_noise=0.01)
        state.anomaly_threshold = 3.0

        await enkf(pair, state)

        # Find anomaly event
        for topic, key, payload in broker.published:
            if topic == ALERTS_ANOMALY:
                msg = json.loads(payload.decode("utf-8"))
                # Innovation should be approximately |200 - 100| = 100
                # (exact value depends on ensemble randomness, but should be ~100)
                assert msg["innovation_magnitude"] > 50.0  # definitely large
                assert msg["innovation_magnitude"] < 150.0  # reasonable bounds
                break
        else:
            pytest.fail("No anomaly event found")
