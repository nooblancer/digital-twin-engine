"""LSTM + XGBoost ensemble inference module for the ML Service.

Implements:
- Model loading (stubs that can be swapped for real TensorFlow/PyTorch LSTM and
  Scikit-Learn XGBoost models)
- Feature extraction for XGBoost: mean, std, min, max, slope, lag features,
  temporal features (hour_of_day, day_of_week)
- Ensemble combination: result = w_lstm * lstm_output + w_xgboost * xgboost_output
- Single-model fallback when one model fails (NaN/Inf/exception)
- Both-models-fail case: discard batch, emit inference failure metric

Requirements: 5.2, 5.3, 5.4, 5.5, 5.8, 5.9
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import EngineConfig, StateVector, TelemetryEvent

logger = get_logger("ml_service")


# ---------------------------------------------------------------------------
# Feature extraction for XGBoost
# ---------------------------------------------------------------------------


def extract_xgboost_features(events: List[TelemetryEvent]) -> np.ndarray:
    """Extract tabular features from a batch of telemetry events for XGBoost.

    Features extracted:
    - Statistical: mean, std, min, max
    - Slope: linear regression slope of values over time
    - Lag features: mean of consecutive differences (lag-1)
    - Temporal: hour_of_day (0-23 normalized to 0-1),
                day_of_week (0-6 normalized to 0-1)

    Args:
        events: List of TelemetryEvent objects (at least 1 event).

    Returns:
        1-D numpy array of extracted features.
    """
    values = np.array([e.value for e in events], dtype=np.float64)

    # Statistical features
    mean_val = float(np.mean(values))
    std_val = float(np.std(values, ddof=0))
    min_val = float(np.min(values))
    max_val = float(np.max(values))

    # Slope: linear regression slope over the batch index
    n = len(values)
    if n > 1:
        x = np.arange(n, dtype=np.float64)
        x_mean = np.mean(x)
        v_mean = np.mean(values)
        numerator = float(np.sum((x - x_mean) * (values - v_mean)))
        denominator = float(np.sum((x - x_mean) ** 2))
        slope = numerator / denominator if denominator != 0.0 else 0.0
    else:
        slope = 0.0

    # Lag features: mean of consecutive differences
    if n > 1:
        diffs = np.diff(values)
        lag_mean = float(np.mean(diffs))
    else:
        lag_mean = 0.0

    # Temporal features from the last event timestamp
    last_ts = events[-1].timestamp
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    hour_of_day = last_ts.hour / 23.0  # normalize to [0, 1]
    day_of_week = last_ts.weekday() / 6.0  # normalize to [0, 1]

    return np.array(
        [mean_val, std_val, min_val, max_val, slope, lag_mean, hour_of_day, day_of_week],
        dtype=np.float64,
    )


# ---------------------------------------------------------------------------
# Abstract model interfaces
# ---------------------------------------------------------------------------


class LSTMModel(ABC):
    """Abstract interface for an LSTM model used in the ensemble.

    Implementations must accept a sequence of values and return a predicted
    state vector as a numpy array.
    """

    @abstractmethod
    def predict(self, sequence: np.ndarray) -> np.ndarray:
        """Run LSTM inference on a sequence of telemetry values.

        Args:
            sequence: 1-D array of float64 values from the telemetry batch.

        Returns:
            1-D numpy array representing the predicted state vector.
        """


class XGBoostModel(ABC):
    """Abstract interface for an XGBoost model used in the ensemble.

    Implementations must accept extracted features and return a predicted
    state vector as a numpy array.
    """

    @abstractmethod
    def predict(self, features: np.ndarray) -> np.ndarray:
        """Run XGBoost inference on extracted tabular features.

        Args:
            features: 1-D array of extracted features from the telemetry batch.

        Returns:
            1-D numpy array representing the predicted state vector.
        """


# ---------------------------------------------------------------------------
# Stub / default model implementations
# ---------------------------------------------------------------------------


class StubLSTMModel(LSTMModel):
    """Stub LSTM model for development and testing.

    Produces a simple prediction based on the last value and trend in the
    input sequence. Can be replaced with a real TensorFlow/PyTorch model.
    """

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        """Generate a stub prediction from the input sequence.

        Uses the last value plus half the mean difference as prediction.
        """
        if len(sequence) == 0:
            return np.array([0.0], dtype=np.float64)

        last_val = sequence[-1]
        if len(sequence) > 1:
            mean_diff = float(np.mean(np.diff(sequence)))
            predicted = last_val + mean_diff * 0.5
        else:
            predicted = last_val

        return np.array([predicted], dtype=np.float64)


class StubXGBoostModel(XGBoostModel):
    """Stub XGBoost model for development and testing.

    Produces a simple prediction based on the mean feature. Can be replaced
    with a real Scikit-Learn XGBoost model.
    """

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Generate a stub prediction from extracted features.

        Uses the mean value feature (index 0) as the base prediction.
        """
        if len(features) == 0:
            return np.array([0.0], dtype=np.float64)

        # Use mean value (feature index 0) as base prediction
        mean_val = features[0]
        return np.array([mean_val], dtype=np.float64)


# ---------------------------------------------------------------------------
# Ensemble inference engine
# ---------------------------------------------------------------------------


def _is_valid_output(output: np.ndarray) -> bool:
    """Check that model output contains only finite values (no NaN/Inf)."""
    return bool(np.all(np.isfinite(output)))


class EnsembleInference:
    """LSTM + XGBoost ensemble inference engine.

    Combines outputs from both models using configurable weights.
    Handles single-model fallback and both-models-fail cases.

    Args:
        lstm_model: LSTM model instance implementing predict().
        xgboost_model: XGBoost model instance implementing predict().
        config: Engine configuration with ensemble weights.
    """

    def __init__(
        self,
        lstm_model: LSTMModel,
        xgboost_model: XGBoostModel,
        config: EngineConfig,
    ) -> None:
        self._lstm_model = lstm_model
        self._xgboost_model = xgboost_model
        self._config = config
        self._inference_failure_count = 0

    @property
    def inference_failure_count(self) -> int:
        """Number of inference failures (both models failed) since startup."""
        return self._inference_failure_count

    def _run_lstm(self, events: List[TelemetryEvent]) -> Optional[np.ndarray]:
        """Run LSTM model on the event sequence, returning None on failure."""
        try:
            sequence = np.array([e.value for e in events], dtype=np.float64)
            output = self._lstm_model.predict(sequence)
            if not _is_valid_output(output):
                logger.error(
                    "LSTM model produced non-finite output",
                    sensor_id=events[0].sensor_id if events else "unknown",
                    batch_size=len(events),
                )
                return None
            return output
        except Exception as exc:
            logger.error(
                "LSTM model inference failed",
                sensor_id=events[0].sensor_id if events else "unknown",
                batch_size=len(events),
                error=str(exc),
            )
            return None

    def _run_xgboost(self, events: List[TelemetryEvent]) -> Optional[np.ndarray]:
        """Run XGBoost model on extracted features, returning None on failure."""
        try:
            features = extract_xgboost_features(events)
            output = self._xgboost_model.predict(features)
            if not _is_valid_output(output):
                logger.error(
                    "XGBoost model produced non-finite output",
                    sensor_id=events[0].sensor_id if events else "unknown",
                    batch_size=len(events),
                )
                return None
            return output
        except Exception as exc:
            logger.error(
                "XGBoost model inference failed",
                sensor_id=events[0].sensor_id if events else "unknown",
                batch_size=len(events),
                error=str(exc),
            )
            return None

    def _combine_outputs(
        self,
        lstm_output: Optional[np.ndarray],
        xgboost_output: Optional[np.ndarray],
    ) -> Optional[tuple[np.ndarray, str]]:
        """Combine model outputs using ensemble weights or fallback logic.

        Returns:
            Tuple of (combined_output, model_used_label) or None if both failed.
        """
        w_lstm = self._config.lstm_weight
        w_xgboost = self._config.xgboost_weight

        if lstm_output is not None and xgboost_output is not None:
            # Both models succeeded — ensemble combination
            # Ensure same output dimension by truncating/padding to minimum
            min_len = min(len(lstm_output), len(xgboost_output))
            lstm_trimmed = lstm_output[:min_len]
            xgboost_trimmed = xgboost_output[:min_len]
            combined = w_lstm * lstm_trimmed + w_xgboost * xgboost_trimmed
            return combined, "ensemble"

        if lstm_output is not None and xgboost_output is None:
            # Single-model fallback: XGBoost failed, use LSTM only
            logger.info(
                "Falling back to LSTM-only prediction (XGBoost failed)",
            )
            return lstm_output, "lstm_only"

        if lstm_output is None and xgboost_output is not None:
            # Single-model fallback: LSTM failed, use XGBoost only
            logger.info(
                "Falling back to XGBoost-only prediction (LSTM failed)",
            )
            return xgboost_output, "xgboost_only"

        # Both models failed
        return None

    async def predict(
        self,
        sensor_id: str,
        events: List[TelemetryEvent],
        config: EngineConfig,
    ) -> Optional[StateVector]:
        """Generate a predicted StateVector from a batch of telemetry events.

        This is the predict_fn conforming to the PredictionFunc signature:
        (sensor_id, events, config) -> Optional[StateVector]

        Runs both LSTM and XGBoost models, combines their outputs, and handles
        single-model fallback and both-models-fail cases.

        Args:
            sensor_id: The sensor identifier for this batch.
            events: List of TelemetryEvent objects in the batch.
            config: Engine configuration (used for ensemble weights).

        Returns:
            A StateVector with the ensemble prediction, or None if both
            models failed (batch discarded).
        """
        if not events:
            return None

        start_time = time.monotonic()

        # Run both models
        lstm_output = self._run_lstm(events)
        xgboost_output = self._run_xgboost(events)

        # Combine outputs
        result = self._combine_outputs(lstm_output, xgboost_output)

        if result is None:
            # Both models failed — discard batch, emit failure metric
            self._inference_failure_count += 1
            logger.error(
                "Both models failed; discarding batch",
                sensor_id=sensor_id,
                batch_size=len(events),
                total_failures=self._inference_failure_count,
            )
            return None

        combined_output, model_used = result
        elapsed_ms = (time.monotonic() - start_time) * 1000.0

        # Compute ensemble spread (std dev of the two model outputs if both available)
        if lstm_output is not None and xgboost_output is not None:
            min_len = min(len(lstm_output), len(xgboost_output))
            stacked = np.vstack([lstm_output[:min_len], xgboost_output[:min_len]])
            ensemble_spread = float(np.mean(np.std(stacked, axis=0)))
        else:
            ensemble_spread = 0.0

        # Build StateVector
        state_vector = StateVector(
            sensor_id=sensor_id,
            timestamp=datetime.now(timezone.utc),
            values=[float(v) for v in combined_output],
            ensemble_spread=ensemble_spread,
            anomaly_flag=False,
            source="prediction",
        )

        logger.info(
            "Ensemble prediction generated",
            sensor_id=sensor_id,
            model_used=model_used,
            batch_size=len(events),
            latency_ms=round(elapsed_ms, 2),
            output_dim=len(combined_output),
        )

        return state_vector


# ---------------------------------------------------------------------------
# Factory function for creating the ensemble predict_fn
# ---------------------------------------------------------------------------


def create_ensemble_predict_fn(
    lstm_model: Optional[LSTMModel] = None,
    xgboost_model: Optional[XGBoostModel] = None,
    config: Optional[EngineConfig] = None,
) -> EnsembleInference:
    """Create an EnsembleInference instance with the given or default models.

    If no models are provided, stub models are used (suitable for development
    and testing). In production, pass real model instances loaded from disk.

    Args:
        lstm_model: An LSTM model instance. Defaults to StubLSTMModel.
        xgboost_model: An XGBoost model instance. Defaults to StubXGBoostModel.
        config: Engine configuration. Defaults to EngineConfig().

    Returns:
        An EnsembleInference instance whose `predict` method conforms to the
        PredictionFunc signature used by BatchAccumulator.
    """
    if lstm_model is None:
        lstm_model = StubLSTMModel()
    if xgboost_model is None:
        xgboost_model = StubXGBoostModel()
    if config is None:
        config = EngineConfig()

    return EnsembleInference(
        lstm_model=lstm_model,
        xgboost_model=xgboost_model,
        config=config,
    )
