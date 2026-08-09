"""Property-based tests for the ML Service ensemble inference and batch accumulation.

Uses the Hypothesis library to verify universal properties across many inputs.
"""

# Feature: digital-twin-telemetry-engine, Property 10: Ensemble Weighting Correctness
# Feature: digital-twin-telemetry-engine, Property 11: Batch Accumulation Prediction Trigger
# Feature: digital-twin-telemetry-engine, Property 12: Single Model Fallback on Partial Failure

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import AsyncMock

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume
import pytest

from digital_twin_engine.ml_service.batch_accumulator import (
    BatchAccumulator,
    SensorBuffer,
)
from digital_twin_engine.ml_service.ensemble_inference import (
    EnsembleInference,
    LSTMModel,
    XGBoostModel,
    create_ensemble_predict_fn,
)
from digital_twin_engine.shared.models import (
    EngineConfig,
    StateVector,
    TelemetryEvent,
)


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def ensemble_weights(draw):
    """Generate valid ensemble weights (w_lstm, w_xgboost) that are non-negative and sum to 1.0."""
    w_lstm = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    w_xgboost = 1.0 - w_lstm
    # Ensure w_xgboost is non-negative (handle floating-point edge)
    assume(w_xgboost >= 0.0)
    assume(math.isclose(w_lstm + w_xgboost, 1.0, abs_tol=1e-9))
    return w_lstm, w_xgboost


@st.composite
def output_vectors(draw, min_dim=1, max_dim=10):
    """Generate finite numpy output vectors of random dimension."""
    dim = draw(st.integers(min_value=min_dim, max_value=max_dim))
    values = draw(
        st.lists(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=dim,
            max_size=dim,
        )
    )
    return np.array(values, dtype=np.float64)


@st.composite
def equal_dim_output_vectors(draw, min_dim=1, max_dim=10):
    """Generate two output vectors of the same dimension."""
    dim = draw(st.integers(min_value=min_dim, max_value=max_dim))
    lstm_values = draw(
        st.lists(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=dim,
            max_size=dim,
        )
    )
    xgboost_values = draw(
        st.lists(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=dim,
            max_size=dim,
        )
    )
    return (
        np.array(lstm_values, dtype=np.float64),
        np.array(xgboost_values, dtype=np.float64),
    )


@st.composite
def valid_telemetry_events(draw, min_count=1, max_count=50):
    """Generate a list of valid TelemetryEvents for a single sensor."""
    count = draw(st.integers(min_value=min_count, max_value=max_count))
    sensor_id = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
        min_size=1,
        max_size=30,
    ).filter(lambda s: s.strip() != ""))
    base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    base_value = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))

    events = []
    for i in range(count):
        value = base_value + draw(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
        ts = base_ts + timedelta(seconds=i)
        events.append(TelemetryEvent(
            timestamp=ts,
            sensor_id=sensor_id,
            measurement_type="temperature",
            value=value,
        ))
    return sensor_id, events


# ---------------------------------------------------------------------------
# Helper model implementations for property testing
# ---------------------------------------------------------------------------


class VectorLSTMModel(LSTMModel):
    """LSTM model that returns a predetermined output vector."""

    def __init__(self, output: np.ndarray) -> None:
        self._output = output.copy()

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        return self._output.copy()


class VectorXGBoostModel(XGBoostModel):
    """XGBoost model that returns a predetermined output vector."""

    def __init__(self, output: np.ndarray) -> None:
        self._output = output.copy()

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self._output.copy()


class FailingLSTMModel(LSTMModel):
    """LSTM model that always raises an exception."""

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        raise RuntimeError("LSTM inference failed")


class FailingXGBoostModel(XGBoostModel):
    """XGBoost model that always raises an exception."""

    def predict(self, features: np.ndarray) -> np.ndarray:
        raise RuntimeError("XGBoost inference failed")


class NaNLSTMModel(LSTMModel):
    """LSTM model that returns NaN in output."""

    def __init__(self, dim: int = 1) -> None:
        self._dim = dim

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        output = np.zeros(self._dim)
        output[0] = float("nan")
        return output


class InfXGBoostModel(XGBoostModel):
    """XGBoost model that returns Infinity in output."""

    def __init__(self, dim: int = 1) -> None:
        self._dim = dim

    def predict(self, features: np.ndarray) -> np.ndarray:
        output = np.zeros(self._dim)
        output[0] = float("inf")
        return output


# ---------------------------------------------------------------------------
# Property 10: Ensemble Weighting Correctness
# ---------------------------------------------------------------------------


class TestProperty10EnsembleWeightingCorrectness:
    """Property 10: Ensemble Weighting Correctness.

    For any LSTM output vector and XGBoost output vector of equal dimension,
    and any ensemble weights (w_lstm, w_xgboost) where both weights are
    non-negative and sum to 1.0, the combined State_Vector SHALL equal
    w_lstm * lstm_output + w_xgboost * xgboost_output element-wise
    (within floating-point tolerance).

    **Validates: Requirements 5.4**
    """

    @given(
        vectors=equal_dim_output_vectors(min_dim=1, max_dim=10),
        weights=ensemble_weights(),
    )
    @settings(max_examples=100)
    def test_ensemble_combination_equals_weighted_sum(
        self,
        vectors: tuple,
        weights: tuple,
    ):
        """Combined output equals w_lstm * lstm + w_xgboost * xgboost element-wise."""
        lstm_output, xgboost_output = vectors
        w_lstm, w_xgboost = weights

        # Build config with the generated weights
        config = EngineConfig(lstm_weight=w_lstm, xgboost_weight=w_xgboost)

        # Create models that return the generated outputs
        lstm_model = VectorLSTMModel(lstm_output)
        xgboost_model = VectorXGBoostModel(xgboost_output)

        engine = EnsembleInference(lstm_model, xgboost_model, config)

        # Create a valid batch of events
        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        # Run inference
        result = asyncio.run(engine.predict("test-sensor", events, config))

        assert result is not None
        assert isinstance(result, StateVector)

        # Compute expected element-wise weighted sum
        expected = w_lstm * lstm_output + w_xgboost * xgboost_output

        # Verify element-wise equality within floating-point tolerance
        assert len(result.values) == len(expected)
        for i, (actual, exp) in enumerate(zip(result.values, expected)):
            assert math.isclose(actual, exp, rel_tol=1e-9, abs_tol=1e-12), (
                f"Element {i}: expected {exp}, got {actual} "
                f"(w_lstm={w_lstm}, w_xgboost={w_xgboost})"
            )

    @given(
        vectors=equal_dim_output_vectors(min_dim=1, max_dim=10),
    )
    @settings(max_examples=100)
    def test_extreme_weights_select_single_model(self, vectors: tuple):
        """With w_lstm=1.0, result equals LSTM output; with w_lstm=0.0, result equals XGBoost output."""
        lstm_output, xgboost_output = vectors

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        # Test w_lstm=1.0 (only LSTM)
        config_lstm_only = EngineConfig(lstm_weight=1.0, xgboost_weight=0.0)
        engine_lstm = EnsembleInference(
            VectorLSTMModel(lstm_output),
            VectorXGBoostModel(xgboost_output),
            config_lstm_only,
        )
        result_lstm = asyncio.run(engine_lstm.predict("test-sensor", events, config_lstm_only))
        assert result_lstm is not None
        for i, (actual, exp) in enumerate(zip(result_lstm.values, lstm_output)):
            assert math.isclose(actual, exp, rel_tol=1e-9, abs_tol=1e-12)

        # Test w_lstm=0.0 (only XGBoost)
        config_xgb_only = EngineConfig(lstm_weight=0.0, xgboost_weight=1.0)
        engine_xgb = EnsembleInference(
            VectorLSTMModel(lstm_output),
            VectorXGBoostModel(xgboost_output),
            config_xgb_only,
        )
        result_xgb = asyncio.run(engine_xgb.predict("test-sensor", events, config_xgb_only))
        assert result_xgb is not None
        for i, (actual, exp) in enumerate(zip(result_xgb.values, xgboost_output)):
            assert math.isclose(actual, exp, rel_tol=1e-9, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# Property 11: Batch Accumulation Prediction Trigger
# ---------------------------------------------------------------------------


class TestProperty11BatchAccumulationPredictionTrigger:
    """Property 11: Batch Accumulation Prediction Trigger.

    For any stream of Telemetry_Events for a sensor_id, the ML_Service SHALL
    generate a prediction when either (a) the accumulated batch reaches the
    configured minimum batch size, or (b) the configured maximum wait time
    elapses since the first event in the current buffer — whichever occurs first.
    No prediction SHALL be generated for incomplete batches before the timeout.

    **Validates: Requirements 5.1, 5.7**
    """

    @given(
        batch_size=st.integers(min_value=10, max_value=50),
        event_count=st.integers(min_value=10, max_value=100),
    )
    @settings(max_examples=100)
    def test_prediction_triggered_at_min_batch_size(
        self,
        batch_size: int,
        event_count: int,
    ):
        """Prediction is triggered when buffer reaches configured min batch size."""
        # Ensure we send at least min_batch_size events
        assume(event_count >= batch_size)

        predictions: List[StateVector] = []

        async def mock_predict_fn(
            sensor_id: str, events: List[TelemetryEvent], config: EngineConfig
        ) -> Optional[StateVector]:
            sv = StateVector(
                sensor_id=sensor_id,
                timestamp=datetime.now(timezone.utc),
                values=[1.0],
                ensemble_spread=0.1,
                anomaly_flag=False,
                source="prediction",
            )
            predictions.append(sv)
            return sv

        config = EngineConfig(
            min_batch_size=batch_size,
            max_batch_size=500,
            max_batch_wait_seconds=60.0,  # Long timeout so it won't trigger
        )

        # Create a mock broker
        broker = AsyncMock()
        broker.subscribe = AsyncMock()
        broker.publish = AsyncMock()

        accumulator = BatchAccumulator(
            broker=broker,
            config=config,
            predict_fn=mock_predict_fn,
        )

        # Simulate adding events directly to the buffer and triggering
        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

        async def run_test():
            sensor_id = "test-sensor"
            for i in range(event_count):
                event = TelemetryEvent(
                    timestamp=base_ts + timedelta(seconds=i),
                    sensor_id=sensor_id,
                    measurement_type="temperature",
                    value=float(i),
                )
                buffer = accumulator._get_or_create_buffer(sensor_id)
                buffer.add(event)

                # Check trigger condition (mimics _on_message logic)
                if buffer.size >= config.min_batch_size:
                    await accumulator._trigger_prediction(sensor_id)

        asyncio.run(run_test())

        # Should have triggered at least once
        expected_predictions = event_count // batch_size
        assert len(predictions) >= expected_predictions
        assert len(predictions) > 0

    @given(
        batch_size=st.integers(min_value=10, max_value=50),
        events_sent=st.integers(min_value=1, max_value=9),
    )
    @settings(max_examples=100)
    def test_no_prediction_before_min_batch_or_timeout(
        self,
        batch_size: int,
        events_sent: int,
    ):
        """No prediction is generated for incomplete batches before timeout."""
        # Ensure we send fewer events than min batch size
        assume(events_sent < batch_size)

        predictions: List[StateVector] = []

        async def mock_predict_fn(
            sensor_id: str, events: List[TelemetryEvent], config: EngineConfig
        ) -> Optional[StateVector]:
            sv = StateVector(
                sensor_id=sensor_id,
                timestamp=datetime.now(timezone.utc),
                values=[1.0],
                ensemble_spread=0.1,
                anomaly_flag=False,
                source="prediction",
            )
            predictions.append(sv)
            return sv

        config = EngineConfig(
            min_batch_size=batch_size,
            max_batch_size=500,
            max_batch_wait_seconds=60.0,  # Very long timeout
        )

        broker = AsyncMock()
        broker.subscribe = AsyncMock()
        broker.publish = AsyncMock()

        accumulator = BatchAccumulator(
            broker=broker,
            config=config,
            predict_fn=mock_predict_fn,
        )

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

        async def run_test():
            sensor_id = "test-sensor"
            for i in range(events_sent):
                event = TelemetryEvent(
                    timestamp=base_ts + timedelta(seconds=i),
                    sensor_id=sensor_id,
                    measurement_type="temperature",
                    value=float(i),
                )
                buffer = accumulator._get_or_create_buffer(sensor_id)
                buffer.add(event)

                # Only trigger if batch size met (should never be met)
                if buffer.size >= config.min_batch_size:
                    await accumulator._trigger_prediction(sensor_id)

        asyncio.run(run_test())

        # No prediction should have been triggered
        assert len(predictions) == 0

        # Buffer should still contain the events
        buffer = accumulator.buffers.get("test-sensor")
        assert buffer is not None
        assert buffer.size == events_sent

    @given(
        batch_size=st.integers(min_value=10, max_value=50),
        events_sent=st.integers(min_value=1, max_value=9),
        max_wait=st.floats(min_value=1.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_timeout_triggers_prediction_for_incomplete_batch(
        self,
        batch_size: int,
        events_sent: int,
        max_wait: float,
    ):
        """Prediction is triggered by timeout for incomplete batches."""
        assume(events_sent < batch_size)

        predictions: List[StateVector] = []

        async def mock_predict_fn(
            sensor_id: str, events: List[TelemetryEvent], config: EngineConfig
        ) -> Optional[StateVector]:
            sv = StateVector(
                sensor_id=sensor_id,
                timestamp=datetime.now(timezone.utc),
                values=[1.0],
                ensemble_spread=0.1,
                anomaly_flag=False,
                source="prediction",
            )
            predictions.append(sv)
            return sv

        config = EngineConfig(
            min_batch_size=batch_size,
            max_batch_size=500,
            max_batch_wait_seconds=max_wait,
        )

        broker = AsyncMock()
        broker.subscribe = AsyncMock()
        broker.publish = AsyncMock()

        accumulator = BatchAccumulator(
            broker=broker,
            config=config,
            predict_fn=mock_predict_fn,
        )

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

        async def run_test():
            sensor_id = "test-sensor"
            # Add events (fewer than min batch size)
            buffer = accumulator._get_or_create_buffer(sensor_id)
            for i in range(events_sent):
                event = TelemetryEvent(
                    timestamp=base_ts + timedelta(seconds=i),
                    sensor_id=sensor_id,
                    measurement_type="temperature",
                    value=float(i),
                )
                buffer.add(event)

            # Manually set the first_event_time to simulate time passage
            # (avoids needing real sleep which would make PBT slow)
            buffer.first_event_time = time.monotonic() - (max_wait + 0.1)

            # Check timeouts (simulating what _timeout_checker does)
            await accumulator._check_timeouts()

        asyncio.run(run_test())

        # Prediction should have been triggered by timeout
        assert len(predictions) == 1


# ---------------------------------------------------------------------------
# Property 12: Single Model Fallback on Partial Failure
# ---------------------------------------------------------------------------


class TestProperty12SingleModelFallbackOnPartialFailure:
    """Property 12: Single Model Fallback on Partial Failure.

    For any inference batch where exactly one of the LSTM or XGBoost models
    fails (returns non-finite output or raises an exception), the ML_Service
    SHALL produce a prediction using only the successful model's output,
    discarding the failed model's contribution.

    **Validates: Requirements 5.8**
    """

    @given(output_vec=output_vectors(min_dim=1, max_dim=5))
    @settings(max_examples=100)
    def test_lstm_failure_uses_xgboost_only(self, output_vec: np.ndarray):
        """When LSTM fails (exception), prediction equals XGBoost output exactly."""
        config = EngineConfig()
        lstm_model = FailingLSTMModel()
        xgboost_model = VectorXGBoostModel(output_vec)

        engine = EnsembleInference(lstm_model, xgboost_model, config)

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        result = asyncio.run(engine.predict("test-sensor", events, config))

        assert result is not None
        assert isinstance(result, StateVector)
        # Result should equal the XGBoost output exactly (no ensemble weighting applied)
        assert len(result.values) == len(output_vec)
        for actual, expected in zip(result.values, output_vec):
            assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12), (
                f"Expected {expected}, got {actual}"
            )

    @given(output_vec=output_vectors(min_dim=1, max_dim=5))
    @settings(max_examples=100)
    def test_xgboost_failure_uses_lstm_only(self, output_vec: np.ndarray):
        """When XGBoost fails (exception), prediction equals LSTM output exactly."""
        config = EngineConfig()
        lstm_model = VectorLSTMModel(output_vec)
        xgboost_model = FailingXGBoostModel()

        engine = EnsembleInference(lstm_model, xgboost_model, config)

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        result = asyncio.run(engine.predict("test-sensor", events, config))

        assert result is not None
        assert isinstance(result, StateVector)
        # Result should equal the LSTM output exactly
        assert len(result.values) == len(output_vec)
        for actual, expected in zip(result.values, output_vec):
            assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12), (
                f"Expected {expected}, got {actual}"
            )

    @given(output_vec=output_vectors(min_dim=1, max_dim=5))
    @settings(max_examples=100)
    def test_lstm_nan_uses_xgboost_only(self, output_vec: np.ndarray):
        """When LSTM returns NaN (non-finite), prediction uses XGBoost only."""
        config = EngineConfig()
        lstm_model = NaNLSTMModel(dim=len(output_vec))
        xgboost_model = VectorXGBoostModel(output_vec)

        engine = EnsembleInference(lstm_model, xgboost_model, config)

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        result = asyncio.run(engine.predict("test-sensor", events, config))

        assert result is not None
        assert isinstance(result, StateVector)
        assert len(result.values) == len(output_vec)
        for actual, expected in zip(result.values, output_vec):
            assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)

    @given(output_vec=output_vectors(min_dim=1, max_dim=5))
    @settings(max_examples=100)
    def test_xgboost_inf_uses_lstm_only(self, output_vec: np.ndarray):
        """When XGBoost returns Infinity (non-finite), prediction uses LSTM only."""
        config = EngineConfig()
        lstm_model = VectorLSTMModel(output_vec)
        xgboost_model = InfXGBoostModel(dim=len(output_vec))

        engine = EnsembleInference(lstm_model, xgboost_model, config)

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        result = asyncio.run(engine.predict("test-sensor", events, config))

        assert result is not None
        assert isinstance(result, StateVector)
        assert len(result.values) == len(output_vec)
        for actual, expected in zip(result.values, output_vec):
            assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)

    @given(
        output_vec=output_vectors(min_dim=1, max_dim=5),
        weights=ensemble_weights(),
    )
    @settings(max_examples=100)
    def test_fallback_ignores_ensemble_weights(
        self,
        output_vec: np.ndarray,
        weights: tuple,
    ):
        """On fallback, the successful model's raw output is used regardless of weights."""
        w_lstm, w_xgboost = weights

        config = EngineConfig(lstm_weight=w_lstm, xgboost_weight=w_xgboost)

        # Test: LSTM fails, XGBoost succeeds
        engine = EnsembleInference(
            FailingLSTMModel(),
            VectorXGBoostModel(output_vec),
            config,
        )

        base_ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            TelemetryEvent(
                timestamp=base_ts + timedelta(seconds=i),
                sensor_id="test-sensor",
                measurement_type="temperature",
                value=float(i + 1),
            )
            for i in range(5)
        ]

        result = asyncio.run(engine.predict("test-sensor", events, config))

        assert result is not None
        # The output should be the raw XGBoost output, NOT weighted
        for actual, expected in zip(result.values, output_vec):
            assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12), (
                f"Fallback should use raw model output, not weighted. "
                f"Expected {expected}, got {actual}"
            )
