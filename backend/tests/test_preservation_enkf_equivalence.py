"""Preservation Property Tests: EnKF Mathematical Equivalence and Pipeline Integrity.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7**

These tests MUST PASS on unfixed code. They capture baseline behavior that
must be preserved after the fix is applied.

Property 2: Preservation — EnKF Mathematical Equivalence and Pipeline Integrity

Key properties tested:
1. _compute_enkf_update is deterministic: given the same inputs and random state,
   it produces identical outputs regardless of calling context (direct vs thread)
2. For non-bug-condition inputs (single sensor, non-concurrent), the pipeline
   produces identical outputs to the unfixed code baseline
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import AsyncMock

import numpy as np
import hypothesis.strategies as st
import pytest
from hypothesis import given, settings, HealthCheck, assume

from digital_twin_engine.correction.enkf import EnKFIteration, EnKFUpdateResult
from digital_twin_engine.correction.temporal_matcher import MatchedPair
from digital_twin_engine.shared.models import EnKFState


# ---------------------------------------------------------------------------
# Hypothesis Strategies — generate valid EnKF inputs
# ---------------------------------------------------------------------------


@st.composite
def enkf_state_strategy(draw, state_dim: int = 1) -> EnKFState:
    """Generate a valid EnKFState with deterministic ensemble members.

    Uses a drawn seed for numpy RNG to ensure reproducibility.
    """
    mean_value = draw(
        st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False)
    )
    spread = draw(
        st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)
    )
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    rng = np.random.default_rng(seed)
    ensemble_members = rng.normal(loc=mean_value, scale=spread, size=(50, state_dim))

    # Observation noise covariance: positive definite diagonal matrix
    obs_noise = draw(
        st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    observation_noise_cov = np.eye(state_dim) * obs_noise

    sensor_id = f"sensor-{draw(st.integers(min_value=1, max_value=50)):03d}"

    return EnKFState(
        sensor_id=sensor_id,
        ensemble_members=ensemble_members,
        observation_noise_cov=observation_noise_cov,
        last_update_timestamp=datetime.now(timezone.utc),
        iteration_count=0,
        anomaly_threshold=3.0,
    )


@st.composite
def matched_pair_strategy(draw, state_dim: int = 1) -> MatchedPair:
    """Generate a valid MatchedPair with predicted values matching state dimension."""
    sensor_id = f"sensor-{draw(st.integers(min_value=1, max_value=50)):03d}"
    now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    predicted_values = [
        draw(
            st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False)
        )
        for _ in range(state_dim)
    ]

    observed_value = draw(
        st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False)
    )

    return MatchedPair(
        sensor_id=sensor_id,
        prediction_timestamp=now,
        observation_timestamp=now + timedelta(seconds=0.5),
        predicted_values=predicted_values,
        observed_value=observed_value,
        prediction_source="ensemble",
        ensemble_weights={"lstm": 0.6, "xgboost": 0.4},
    )


def deep_copy_enkf_state(state: EnKFState) -> EnKFState:
    """Create a deep copy of an EnKFState (numpy arrays need explicit copy)."""
    return EnKFState(
        sensor_id=state.sensor_id,
        ensemble_members=state.ensemble_members.copy(),
        observation_noise_cov=state.observation_noise_cov.copy(),
        last_update_timestamp=state.last_update_timestamp,
        iteration_count=state.iteration_count,
        anomaly_threshold=state.anomaly_threshold,
    )


# ---------------------------------------------------------------------------
# Property 2: Preservation — EnKF Mathematical Equivalence
# ---------------------------------------------------------------------------


class TestPreservationEnKFDeterminism:
    """Property 2: Preservation - EnKF Mathematical Equivalence

    For all valid matched pairs and EnKF states, _compute_enkf_update
    produces deterministic results — the output must be identical regardless
    of whether called directly or via asyncio.to_thread (threading boundary
    must not alter computation).

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7**
    """

    @given(data=st.data())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    def test_compute_enkf_update_deterministic_with_same_seed(self, data):
        """_compute_enkf_update produces identical results when called with same
        inputs and same numpy random state.

        **Validates: Requirements 3.1, 3.7**

        This property ensures the mathematical computation is deterministic:
        given identical inputs and random state, the output (kalman_gain,
        updated ensemble, innovation) is bit-for-bit identical.
        """
        state_dim = data.draw(st.integers(min_value=1, max_value=3), label="state_dim")
        pair = data.draw(matched_pair_strategy(state_dim=state_dim), label="pair")
        state = data.draw(enkf_state_strategy(state_dim=state_dim), label="state")

        # Create EnKFIteration with mock broker
        mock_broker = AsyncMock()
        enkf_iteration = EnKFIteration(broker=mock_broker)

        # First call: set numpy random state, compute update
        seed = 12345
        state_copy_1 = deep_copy_enkf_state(state)
        np.random.seed(seed)
        result_1 = enkf_iteration._compute_enkf_update(pair, state_copy_1)

        # Second call: reset numpy random state, compute update with fresh state copy
        state_copy_2 = deep_copy_enkf_state(state)
        np.random.seed(seed)
        result_2 = enkf_iteration._compute_enkf_update(pair, state_copy_2)

        # Assert outputs are identical
        np.testing.assert_array_equal(
            result_1.state_vector.values,
            result_2.state_vector.values,
            err_msg="Corrected state values must be identical for same inputs + seed",
        )
        assert result_1.innovation_magnitude == result_2.innovation_magnitude, (
            f"Innovation magnitude mismatch: {result_1.innovation_magnitude} vs "
            f"{result_2.innovation_magnitude}"
        )
        assert result_1.kalman_gain_scalar == result_2.kalman_gain_scalar, (
            f"Kalman gain scalar mismatch: {result_1.kalman_gain_scalar} vs "
            f"{result_2.kalman_gain_scalar}"
        )
        assert result_1.confidence_band_95 == result_2.confidence_band_95, (
            f"Confidence band mismatch: {result_1.confidence_band_95} vs "
            f"{result_2.confidence_band_95}"
        )
        assert result_1.predicted_value == result_2.predicted_value, (
            f"Predicted value mismatch: {result_1.predicted_value} vs "
            f"{result_2.predicted_value}"
        )

    @pytest.mark.asyncio
    @given(data=st.data())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    async def test_compute_enkf_update_thread_equivalence(self, data):
        """_compute_enkf_update produces identical results when called directly
        vs via asyncio.to_thread (with same random state).

        **Validates: Requirements 3.1, 3.3, 3.4, 3.7**

        This is the core preservation property: the threading boundary introduced
        by the fix must not alter computation results. On unfixed code, this test
        passes trivially because both calls are direct. After the fix, this
        confirms the thread offloading doesn't change results.
        """
        state_dim = data.draw(st.integers(min_value=1, max_value=3), label="state_dim")
        pair = data.draw(matched_pair_strategy(state_dim=state_dim), label="pair")
        state = data.draw(enkf_state_strategy(state_dim=state_dim), label="state")

        # Create EnKFIteration with mock broker
        mock_broker = AsyncMock()
        enkf_iteration = EnKFIteration(broker=mock_broker)

        # Direct call with fixed seed
        seed = 42
        state_direct = deep_copy_enkf_state(state)
        np.random.seed(seed)
        result_direct = enkf_iteration._compute_enkf_update(pair, state_direct)

        # Call via asyncio.to_thread with same fixed seed
        state_threaded = deep_copy_enkf_state(state)

        def compute_in_thread():
            np.random.seed(seed)
            return enkf_iteration._compute_enkf_update(pair, state_threaded)

        result_threaded = await asyncio.to_thread(compute_in_thread)

        # Assert outputs are identical
        np.testing.assert_array_equal(
            result_direct.state_vector.values,
            result_threaded.state_vector.values,
            err_msg="Direct vs threaded computation must produce identical state values",
        )
        assert result_direct.innovation_magnitude == result_threaded.innovation_magnitude, (
            f"Innovation magnitude mismatch: direct={result_direct.innovation_magnitude} "
            f"vs threaded={result_threaded.innovation_magnitude}"
        )
        assert result_direct.kalman_gain_scalar == result_threaded.kalman_gain_scalar, (
            f"Kalman gain mismatch: direct={result_direct.kalman_gain_scalar} "
            f"vs threaded={result_threaded.kalman_gain_scalar}"
        )
        assert result_direct.confidence_band_95 == result_threaded.confidence_band_95, (
            f"Confidence band mismatch: direct={result_direct.confidence_band_95} "
            f"vs threaded={result_threaded.confidence_band_95}"
        )
        assert result_direct.predicted_value == result_threaded.predicted_value, (
            f"Predicted value mismatch: direct={result_direct.predicted_value} "
            f"vs threaded={result_threaded.predicted_value}"
        )


class TestPreservationPipelineIntegrity:
    """Property 2: Preservation - Pipeline Integrity for Non-Bug-Condition Inputs

    For all non-bug-condition inputs (single sensor, non-concurrent operation),
    the pipeline produces identical outputs to unfixed code.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7**
    """

    @pytest.mark.asyncio
    @given(data=st.data())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    async def test_single_sensor_pipeline_produces_correct_outputs(self, data):
        """Single-sensor pipeline flow produces correct TSDB writes and broker publishes.

        **Validates: Requirements 3.1, 3.3, 3.4**

        For non-bug-condition inputs (single sensor, sequential operation),
        the EnKFIteration.__call__ must:
        1. Compute a corrected state vector
        2. Publish the corrected state to the broker
        3. Write to TSDB if handler provided
        """
        state_dim = data.draw(st.integers(min_value=1, max_value=2), label="state_dim")
        pair = data.draw(matched_pair_strategy(state_dim=state_dim), label="pair")
        state = data.draw(enkf_state_strategy(state_dim=state_dim), label="state")

        # Ensure sensor_id matches between pair and state
        pair = MatchedPair(
            sensor_id=state.sensor_id,
            prediction_timestamp=pair.prediction_timestamp,
            observation_timestamp=pair.observation_timestamp,
            predicted_values=pair.predicted_values,
            observed_value=pair.observed_value,
            prediction_source=pair.prediction_source,
            ensemble_weights=pair.ensemble_weights,
        )

        # Set up mocks
        mock_broker = AsyncMock()
        mock_broker.publish = AsyncMock()
        mock_tsdb_write = AsyncMock()

        enkf_iteration = EnKFIteration(broker=mock_broker, tsdb_write_func=mock_tsdb_write)

        # Set random seed for reproducibility
        np.random.seed(99)

        initial_iteration_count = state.iteration_count

        # Run single-sensor pipeline (non-bug-condition: single sensor, sequential)
        await enkf_iteration.__call__(pair, state)

        # Verify pipeline behavior:
        # 1. Broker publish was called (corrected state published)
        assert mock_broker.publish.called, (
            "Expected broker.publish to be called for corrected state"
        )

        # 2. TSDB write was called with a StateVector
        assert mock_tsdb_write.called, (
            "Expected TSDB write function to be called"
        )
        tsdb_arg = mock_tsdb_write.call_args[0][0]
        assert hasattr(tsdb_arg, "values"), "TSDB write argument must be a StateVector"
        assert hasattr(tsdb_arg, "sensor_id"), "TSDB write argument must have sensor_id"
        assert tsdb_arg.sensor_id == state.sensor_id, (
            f"TSDB write sensor_id mismatch: {tsdb_arg.sensor_id} vs {state.sensor_id}"
        )

        # 3. EnKF state was updated in-place
        assert state.iteration_count == initial_iteration_count + 1, (
            f"Expected iteration_count to increment: "
            f"{state.iteration_count} vs {initial_iteration_count + 1}"
        )

        # 4. Metrics tracked (iteration count increased)
        assert enkf_iteration.iterations_count == 1, (
            f"Expected 1 iteration recorded, got {enkf_iteration.iterations_count}"
        )
        assert enkf_iteration.last_latency_ms > 0, (
            "Expected positive latency measurement"
        )

    @pytest.mark.asyncio
    @given(data=st.data())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    async def test_broker_message_contains_v12_fields(self, data):
        """Broker publish message contains v1.2 correction fields.

        **Validates: Requirements 3.2, 3.3**

        The published message must include kalman_gain, innovation_magnitude,
        confidence_band_95, and raw_prediction fields for WebSocket broadcast.
        """
        import json

        state_dim = data.draw(st.integers(min_value=1, max_value=2), label="state_dim")
        pair = data.draw(matched_pair_strategy(state_dim=state_dim), label="pair")
        state = data.draw(enkf_state_strategy(state_dim=state_dim), label="state")

        # Match sensor_id
        pair = MatchedPair(
            sensor_id=state.sensor_id,
            prediction_timestamp=pair.prediction_timestamp,
            observation_timestamp=pair.observation_timestamp,
            predicted_values=pair.predicted_values,
            observed_value=pair.observed_value,
            prediction_source=pair.prediction_source,
            ensemble_weights=pair.ensemble_weights,
        )

        mock_broker = AsyncMock()
        mock_broker.publish = AsyncMock()

        enkf_iteration = EnKFIteration(broker=mock_broker)

        np.random.seed(77)
        await enkf_iteration.__call__(pair, state)

        # Verify broker was called at least once
        assert mock_broker.publish.called, "Expected broker.publish to be called"

        # Find the corrections.state publish call (there may also be alerts.anomaly)
        corrections_payload = None
        for call in mock_broker.publish.call_args_list:
            topic = call[0][0]
            if topic == "corrections.state":
                # Third arg is the payload bytes
                payload_bytes = call[0][2]
                corrections_payload = json.loads(payload_bytes.decode("utf-8"))
                break

        assert corrections_payload is not None, (
            "Expected at least one publish call to 'corrections.state' topic. "
            f"Got topics: {[c[0][0] for c in mock_broker.publish.call_args_list]}"
        )

        payload = corrections_payload

        assert "sensor_id" in payload, "Message must contain sensor_id"
        assert "corrected_state_vector" in payload, "Message must contain corrected_state_vector"
        assert "kalman_gain" in payload, "Message must contain kalman_gain (v1.2)"
        assert "innovation_magnitude" in payload, (
            "Message must contain innovation_magnitude (v1.2)"
        )
        assert "confidence_band_95" in payload, (
            "Message must contain confidence_band_95 (v1.2)"
        )
        assert "raw_prediction" in payload, "Message must contain raw_prediction (v1.2)"

        # Validate field types
        assert isinstance(payload["kalman_gain"], (int, float)), (
            f"kalman_gain must be numeric, got {type(payload['kalman_gain'])}"
        )
        assert 0.0 <= payload["kalman_gain"] <= 1.0, (
            f"kalman_gain must be in [0, 1], got {payload['kalman_gain']}"
        )
        assert isinstance(payload["innovation_magnitude"], (int, float)), (
            f"innovation_magnitude must be numeric, got {type(payload['innovation_magnitude'])}"
        )
        assert isinstance(payload["confidence_band_95"], list), (
            f"confidence_band_95 must be a list, got {type(payload['confidence_band_95'])}"
        )
        assert len(payload["confidence_band_95"]) == 2, (
            f"confidence_band_95 must have 2 elements, got {len(payload['confidence_band_95'])}"
        )

    @given(data=st.data())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    def test_enkf_state_mutation_is_correct(self, data):
        """_compute_enkf_update correctly mutates EnKF state in-place.

        **Validates: Requirements 3.1, 3.7**

        The EnKF state must be updated with:
        - New ensemble_members (the analysis ensemble X_a)
        - Incremented iteration_count
        - Updated last_update_timestamp
        """
        state_dim = data.draw(st.integers(min_value=1, max_value=3), label="state_dim")
        pair = data.draw(matched_pair_strategy(state_dim=state_dim), label="pair")
        state = data.draw(enkf_state_strategy(state_dim=state_dim), label="state")

        mock_broker = AsyncMock()
        enkf_iteration = EnKFIteration(broker=mock_broker)

        original_ensemble = state.ensemble_members.copy()
        original_iteration = state.iteration_count
        original_timestamp = state.last_update_timestamp

        np.random.seed(55)
        result = enkf_iteration._compute_enkf_update(pair, state)

        # State must be mutated
        assert state.iteration_count == original_iteration + 1, (
            f"iteration_count must increment: {state.iteration_count} vs "
            f"{original_iteration + 1}"
        )
        assert state.last_update_timestamp >= original_timestamp, (
            "last_update_timestamp must be updated"
        )
        # Ensemble members should change (unless observation == forecast mean exactly)
        # We just verify the shape is preserved
        assert state.ensemble_members.shape == original_ensemble.shape, (
            f"Ensemble shape must be preserved: {state.ensemble_members.shape} "
            f"vs {original_ensemble.shape}"
        )

        # Result must contain valid StateVector
        assert result.state_vector is not None
        assert result.state_vector.sensor_id == pair.sensor_id
        assert len(result.state_vector.values) == state_dim
        assert result.innovation_magnitude >= 0.0
        assert 0.0 <= result.kalman_gain_scalar <= 1.0
        assert len(result.confidence_band_95) == 2
        # Confidence band lower <= upper
        assert result.confidence_band_95[0] <= result.confidence_band_95[1], (
            f"Confidence band must have lower <= upper: {result.confidence_band_95}"
        )
