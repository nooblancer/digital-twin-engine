"""Unit tests for the LSTM + XGBoost ensemble inference module.

Tests cover:
- Feature extraction for XGBoost
- Ensemble weighting correctness
- Single-model fallback on partial failure
- Both-models-fail case (batch discarded)
- Stub model behavior
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List

import numpy as np
import pytest

from digital_twin_engine.ml_service.ensemble_inference import (
    EnsembleInference,
    LSTMModel,
    StubLSTMModel,
    StubXGBoostModel,
    XGBoostModel,
    _is_valid_output,
    create_ensemble_predict_fn,
    extract_xgboost_features,
)
from digital_twin_engine.shared.models import EngineConfig, StateVector, TelemetryEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    value: float,
    sensor_id: str = "sensor-001",
    timestamp: datetime | None = None,
) -> TelemetryEvent:
    """Create a TelemetryEvent for testing."""
    if timestamp is None:
        timestamp = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    return TelemetryEvent(
        timestamp=timestamp,
        sensor_id=sensor_id,
        measurement_type="temperature_celsius",
        value=value,
    )


def _make_events(
    values: List[float],
    sensor_id: str = "sensor-001",
) -> List[TelemetryEvent]:
    """Create a list of TelemetryEvents with incrementing timestamps."""
    from datetime import timedelta

    base_ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    events = []
    for i, v in enumerate(values):
        ts = base_ts + timedelta(seconds=i)
        events.append(_make_event(v, sensor_id=sensor_id, timestamp=ts))
    return events


class FailingLSTMModel(LSTMModel):
    """LSTM model that always raises an exception."""

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        raise RuntimeError("LSTM model failed")


class NaNLSTMModel(LSTMModel):
    """LSTM model that returns NaN output."""

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        return np.array([float("nan")])


class FailingXGBoostModel(XGBoostModel):
    """XGBoost model that always raises an exception."""

    def predict(self, features: np.ndarray) -> np.ndarray:
        raise RuntimeError("XGBoost model failed")


class InfXGBoostModel(XGBoostModel):
    """XGBoost model that returns Infinity output."""

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.array([float("inf")])


class FixedLSTMModel(LSTMModel):
    """LSTM model that returns a fixed output."""

    def __init__(self, output: List[float]) -> None:
        self._output = np.array(output, dtype=np.float64)

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        return self._output.copy()


class FixedXGBoostModel(XGBoostModel):
    """XGBoost model that returns a fixed output."""

    def __init__(self, output: List[float]) -> None:
        self._output = np.array(output, dtype=np.float64)

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self._output.copy()


# ---------------------------------------------------------------------------
# Feature extraction tests
# ---------------------------------------------------------------------------


class TestFeatureExtraction:
    """Tests for extract_xgboost_features."""

    def test_basic_features_computed(self) -> None:
        """Statistical features are correctly computed."""
        events = _make_events([1.0, 2.0, 3.0, 4.0, 5.0])
        features = extract_xgboost_features(events)

        # mean=3.0, std=√2≈1.414, min=1.0, max=5.0
        assert math.isclose(features[0], 3.0, abs_tol=1e-10)  # mean
        assert math.isclose(features[1], np.std([1, 2, 3, 4, 5]), abs_tol=1e-10)  # std
        assert math.isclose(features[2], 1.0, abs_tol=1e-10)  # min
        assert math.isclose(features[3], 5.0, abs_tol=1e-10)  # max

    def test_slope_linear_increase(self) -> None:
        """Slope should be 1.0 for a perfectly linear sequence [1,2,3,4,5]."""
        events = _make_events([1.0, 2.0, 3.0, 4.0, 5.0])
        features = extract_xgboost_features(events)

        assert math.isclose(features[4], 1.0, abs_tol=1e-10)  # slope

    def test_slope_constant_sequence(self) -> None:
        """Slope should be 0.0 for a constant sequence."""
        events = _make_events([5.0, 5.0, 5.0, 5.0])
        features = extract_xgboost_features(events)

        assert math.isclose(features[4], 0.0, abs_tol=1e-10)  # slope

    def test_lag_features(self) -> None:
        """Mean lag (consecutive differences) should be correct."""
        events = _make_events([1.0, 3.0, 5.0, 7.0])
        features = extract_xgboost_features(events)

        # diffs = [2, 2, 2], mean = 2.0
        assert math.isclose(features[5], 2.0, abs_tol=1e-10)  # lag_mean

    def test_temporal_features(self) -> None:
        """Hour and day of week are properly normalized."""
        # 2024-06-15 is a Saturday (weekday=5), hour=10
        events = _make_events([1.0, 2.0])
        features = extract_xgboost_features(events)

        expected_hour = 10.0 / 23.0
        expected_dow = 5.0 / 6.0
        assert math.isclose(features[6], expected_hour, abs_tol=1e-10)
        assert math.isclose(features[7], expected_dow, abs_tol=1e-10)

    def test_single_event(self) -> None:
        """Feature extraction works with a single event (slope=0, lag=0)."""
        events = _make_events([42.0])
        features = extract_xgboost_features(events)

        assert math.isclose(features[0], 42.0, abs_tol=1e-10)  # mean
        assert math.isclose(features[1], 0.0, abs_tol=1e-10)  # std
        assert math.isclose(features[4], 0.0, abs_tol=1e-10)  # slope
        assert math.isclose(features[5], 0.0, abs_tol=1e-10)  # lag_mean

    def test_returns_8_features(self) -> None:
        """Feature vector always has 8 elements."""
        for n in [1, 5, 20, 100]:
            events = _make_events([float(i) for i in range(n)])
            features = extract_xgboost_features(events)
            assert len(features) == 8


# ---------------------------------------------------------------------------
# Valid output check tests
# ---------------------------------------------------------------------------


class TestIsValidOutput:
    """Tests for _is_valid_output helper."""

    def test_valid_output(self) -> None:
        assert _is_valid_output(np.array([1.0, 2.0, 3.0])) is True

    def test_nan_invalid(self) -> None:
        assert _is_valid_output(np.array([1.0, float("nan")])) is False

    def test_inf_invalid(self) -> None:
        assert _is_valid_output(np.array([float("inf")])) is False

    def test_neg_inf_invalid(self) -> None:
        assert _is_valid_output(np.array([float("-inf")])) is False

    def test_empty_valid(self) -> None:
        assert _is_valid_output(np.array([])) is True


# ---------------------------------------------------------------------------
# Stub model tests
# ---------------------------------------------------------------------------


class TestStubModels:
    """Tests for stub model implementations."""

    def test_stub_lstm_returns_prediction(self) -> None:
        model = StubLSTMModel()
        seq = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        output = model.predict(seq)
        assert len(output) == 1
        assert np.all(np.isfinite(output))

    def test_stub_lstm_empty_sequence(self) -> None:
        model = StubLSTMModel()
        output = model.predict(np.array([]))
        assert len(output) == 1
        assert output[0] == 0.0

    def test_stub_xgboost_returns_prediction(self) -> None:
        model = StubXGBoostModel()
        features = np.array([3.0, 1.0, 1.0, 5.0, 1.0, 1.0, 0.5, 0.5])
        output = model.predict(features)
        assert len(output) == 1
        assert np.all(np.isfinite(output))

    def test_stub_xgboost_uses_mean_feature(self) -> None:
        model = StubXGBoostModel()
        features = np.array([42.5, 1.0, 1.0, 5.0, 1.0, 1.0, 0.5, 0.5])
        output = model.predict(features)
        assert math.isclose(output[0], 42.5, abs_tol=1e-10)


# ---------------------------------------------------------------------------
# Ensemble weighting tests
# ---------------------------------------------------------------------------


class TestEnsembleWeighting:
    """Tests for ensemble combination with weights."""

    @pytest.mark.asyncio
    async def test_ensemble_weighted_combination(self) -> None:
        """Ensemble combines LSTM and XGBoost with configured weights."""
        config = EngineConfig(lstm_weight=0.6, xgboost_weight=0.4)
        lstm = FixedLSTMModel([10.0])
        xgboost = FixedXGBoostModel([20.0])
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0, 4.0, 5.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        expected = 0.6 * 10.0 + 0.4 * 20.0  # 14.0
        assert math.isclose(result.values[0], expected, abs_tol=1e-10)

    @pytest.mark.asyncio
    async def test_equal_weights(self) -> None:
        """With equal weights, output is the average of both models."""
        config = EngineConfig(lstm_weight=0.5, xgboost_weight=0.5)
        lstm = FixedLSTMModel([100.0])
        xgboost = FixedXGBoostModel([200.0])
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert math.isclose(result.values[0], 150.0, abs_tol=1e-10)

    @pytest.mark.asyncio
    async def test_lstm_weight_1_xgboost_weight_0(self) -> None:
        """With w_lstm=1.0, w_xgboost=0.0, only LSTM output is used."""
        config = EngineConfig(lstm_weight=1.0, xgboost_weight=0.0)
        lstm = FixedLSTMModel([42.0])
        xgboost = FixedXGBoostModel([99.0])
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert math.isclose(result.values[0], 42.0, abs_tol=1e-10)

    @pytest.mark.asyncio
    async def test_result_is_state_vector(self) -> None:
        """Predict returns a properly formed StateVector."""
        config = EngineConfig()
        engine = create_ensemble_predict_fn(config=config)

        events = _make_events([1.0, 2.0, 3.0, 4.0, 5.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert isinstance(result, StateVector)
        assert result.sensor_id == "sensor-001"
        assert result.source == "prediction"
        assert result.anomaly_flag is False
        assert len(result.values) > 0

    @pytest.mark.asyncio
    async def test_ensemble_spread_computed(self) -> None:
        """When both models succeed, ensemble_spread is non-zero for differing outputs."""
        config = EngineConfig(lstm_weight=0.5, xgboost_weight=0.5)
        lstm = FixedLSTMModel([10.0])
        xgboost = FixedXGBoostModel([20.0])
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert result.ensemble_spread > 0.0


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------


class TestSingleModelFallback:
    """Tests for single-model fallback when one model fails."""

    @pytest.mark.asyncio
    async def test_lstm_fails_xgboost_used(self) -> None:
        """When LSTM raises exception, XGBoost output is used alone."""
        config = EngineConfig()
        lstm = FailingLSTMModel()
        xgboost = FixedXGBoostModel([25.0])
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert math.isclose(result.values[0], 25.0, abs_tol=1e-10)
        assert result.ensemble_spread == 0.0

    @pytest.mark.asyncio
    async def test_xgboost_fails_lstm_used(self) -> None:
        """When XGBoost raises exception, LSTM output is used alone."""
        config = EngineConfig()
        lstm = FixedLSTMModel([30.0])
        xgboost = FailingXGBoostModel()
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert math.isclose(result.values[0], 30.0, abs_tol=1e-10)

    @pytest.mark.asyncio
    async def test_lstm_nan_xgboost_used(self) -> None:
        """When LSTM returns NaN, XGBoost output is used alone."""
        config = EngineConfig()
        lstm = NaNLSTMModel()
        xgboost = FixedXGBoostModel([15.0])
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert math.isclose(result.values[0], 15.0, abs_tol=1e-10)

    @pytest.mark.asyncio
    async def test_xgboost_inf_lstm_used(self) -> None:
        """When XGBoost returns Inf, LSTM output is used alone."""
        config = EngineConfig()
        lstm = FixedLSTMModel([50.0])
        xgboost = InfXGBoostModel()
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert math.isclose(result.values[0], 50.0, abs_tol=1e-10)


# ---------------------------------------------------------------------------
# Both models fail tests
# ---------------------------------------------------------------------------


class TestBothModelsFail:
    """Tests for when both LSTM and XGBoost fail."""

    @pytest.mark.asyncio
    async def test_both_fail_returns_none(self) -> None:
        """When both models fail, predict returns None (batch discarded)."""
        config = EngineConfig()
        lstm = FailingLSTMModel()
        xgboost = FailingXGBoostModel()
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is None

    @pytest.mark.asyncio
    async def test_both_nan_returns_none(self) -> None:
        """When both models produce non-finite output, returns None."""
        config = EngineConfig()
        lstm = NaNLSTMModel()
        xgboost = InfXGBoostModel()
        engine = EnsembleInference(lstm, xgboost, config)

        events = _make_events([1.0, 2.0, 3.0])
        result = await engine.predict("sensor-001", events, config)

        assert result is None

    @pytest.mark.asyncio
    async def test_failure_count_incremented(self) -> None:
        """Inference failure count is incremented on both-models-fail."""
        config = EngineConfig()
        lstm = FailingLSTMModel()
        xgboost = FailingXGBoostModel()
        engine = EnsembleInference(lstm, xgboost, config)

        assert engine.inference_failure_count == 0

        events = _make_events([1.0, 2.0, 3.0])
        await engine.predict("sensor-001", events, config)
        assert engine.inference_failure_count == 1

        await engine.predict("sensor-001", events, config)
        assert engine.inference_failure_count == 2

    @pytest.mark.asyncio
    async def test_empty_events_returns_none(self) -> None:
        """Empty event list returns None without incrementing failure count."""
        config = EngineConfig()
        engine = create_ensemble_predict_fn(config=config)

        result = await engine.predict("sensor-001", [], config)
        assert result is None
        assert engine.inference_failure_count == 0


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------


class TestCreateEnsemblePredictFn:
    """Tests for the create_ensemble_predict_fn factory."""

    def test_creates_with_defaults(self) -> None:
        """Factory creates engine with stub models and default config."""
        engine = create_ensemble_predict_fn()
        assert isinstance(engine, EnsembleInference)

    @pytest.mark.asyncio
    async def test_default_produces_predictions(self) -> None:
        """Default engine produces valid predictions."""
        engine = create_ensemble_predict_fn()
        config = EngineConfig()
        events = _make_events([1.0, 2.0, 3.0, 4.0, 5.0])

        result = await engine.predict("sensor-001", events, config)

        assert result is not None
        assert isinstance(result, StateVector)
        assert all(math.isfinite(v) for v in result.values)

    def test_custom_models_accepted(self) -> None:
        """Factory accepts custom model instances."""
        lstm = FixedLSTMModel([1.0])
        xgboost = FixedXGBoostModel([2.0])
        config = EngineConfig(lstm_weight=0.7, xgboost_weight=0.3)

        engine = create_ensemble_predict_fn(lstm, xgboost, config)
        assert isinstance(engine, EnsembleInference)
