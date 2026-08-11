"""Ensemble Kalman Filter (EnKF) iteration for the Correction Engine.

Implements the full EnKF algorithm:
1. Forecast: Use ML model prediction to set ensemble forecast
2. Compute ensemble mean and perturbation matrix
3. Compute innovation: y_obs - H * x_predicted (for each member)
4. Compute Kalman Gain: K = P_f * H^T * (H * P_f * H^T + R)^{-1}
5. Update each ensemble member: x_a[i] = x_f[i] + K * (y_obs + ε[i] - H * x_f[i])
6. Output corrected state: mean(x_a)

Handles:
- Matrix singularity via Moore-Penrose pseudo-inverse
- Ensemble collapse (spread → 0) via re-inflation with small perturbation
- Publishing corrected StateVector to corrections.state topic and TSDB
- 100ms latency budget compliance

Requirements: 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from numpy.linalg import LinAlgError

from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import ALERTS_ANOMALY, CORRECTIONS_STATE
from digital_twin_engine.correction.correction_metrics_tracker import (
    CorrectionMetricsTracker,
    InnovationStatsTracker,
)
from digital_twin_engine.correction.temporal_matcher import MatchedPair
from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import EnKFState, StateVector

logger = get_logger("correction_engine")

# Minimum ensemble spread before re-inflation is triggered
_MIN_ENSEMBLE_SPREAD = 1e-10

# Re-inflation noise standard deviation
_REINFLATION_NOISE_STD = 0.01

# Module-level singleton trackers for correction metrics observability (v1.2)
# These are accessed by the REST API endpoints in correction_metrics_api.py
accuracy_tracker = CorrectionMetricsTracker()
innovation_tracker = InnovationStatsTracker()


@dataclass
class EnKFUpdateResult:
    """Result of an EnKF update computation, including metadata for anomaly emission."""

    state_vector: StateVector
    innovation_magnitude: float
    predicted_value: float  # First element of predicted state (observation space)
    kalman_gain_scalar: float = 0.0  # K[0,0] clipped to [0, 1] (v1.2)
    confidence_band_95: list = None  # [lower, upper] 95% CI (v1.2)

    def __post_init__(self):
        if self.confidence_band_95 is None:
            self.confidence_band_95 = [0.0, 0.0]


class EnKFIteration:
    """Performs a single Ensemble Kalman Filter iteration.

    This class encapsulates the EnKF algorithm and can be used as the
    on_match callback for the TemporalMatcher. It publishes corrected
    state vectors to the message broker and optionally writes to TSDB.

    Args:
        broker: Message broker backend for publishing corrected states.
        tsdb_write_func: Optional async callable to write corrected state to TSDB.
            Signature: async (StateVector) -> None
    """

    def __init__(
        self,
        broker: BrokerBackend,
        tsdb_write_func: Optional[object] = None,
    ) -> None:
        self._broker = broker
        self._tsdb_write_func = tsdb_write_func

        # Metrics
        self._iterations_count: int = 0
        self._total_latency_ms: float = 0.0
        self._last_latency_ms: float = 0.0

    @property
    def iterations_count(self) -> int:
        """Total number of EnKF iterations completed."""
        return self._iterations_count

    @property
    def last_latency_ms(self) -> float:
        """Latency of the most recent iteration in milliseconds."""
        return self._last_latency_ms

    @property
    def average_latency_ms(self) -> float:
        """Average iteration latency in milliseconds."""
        if self._iterations_count == 0:
            return 0.0
        return self._total_latency_ms / self._iterations_count

    async def __call__(self, matched_pair: MatchedPair, enkf_state: EnKFState) -> None:
        """Execute one full EnKF iteration.

        This method serves as the on_match callback for the TemporalMatcher.

        Args:
            matched_pair: The temporally-matched prediction and observation.
            enkf_state: The per-sensor EnKF state to update in-place.
        """
        start_time = time.perf_counter()

        update_result = self._compute_enkf_update(matched_pair, enkf_state)
        result = update_result.state_vector

        # Publish corrected state
        await self._publish_corrected_state(
            result,
            matched_pair,
            enkf_state,
            update_result=update_result,
            kalman_gain_scalar=update_result.kalman_gain_scalar,
            confidence_band_95=update_result.confidence_band_95,
        )

        # Record correction metrics for accuracy tracking (v1.2)
        # Uses: matched_pair.observed_value, update_result.predicted_value, corrected_mean[0]
        accuracy_tracker.record(
            sensor_id=matched_pair.sensor_id,
            raw_prediction=update_result.predicted_value,
            observed_value=matched_pair.observed_value,
            corrected_value=result.values[0],
        )

        # Record innovation magnitude for whiteness testing (v1.2)
        innovation_tracker.record(
            sensor_id=matched_pair.sensor_id,
            innovation_magnitude=update_result.innovation_magnitude,
        )

        # Emit anomaly event if flagged
        if result.anomaly_flag:
            await self._emit_anomaly_event(
                matched_pair=matched_pair,
                state=result,
                innovation_magnitude=update_result.innovation_magnitude,
                predicted_value=update_result.predicted_value,
                threshold=enkf_state.anomaly_threshold,
            )

        # Write to TSDB if handler provided
        if self._tsdb_write_func is not None:
            try:
                await self._tsdb_write_func(result)
            except Exception as exc:
                logger.error(
                    "Failed to write corrected state to TSDB",
                    sensor_id=matched_pair.sensor_id,
                    error=str(exc),
                )

        # Record latency
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self._last_latency_ms = elapsed_ms
        self._total_latency_ms += elapsed_ms
        self._iterations_count += 1

        logger.info(
            "EnKF iteration completed",
            sensor_id=matched_pair.sensor_id,
            iteration_count=enkf_state.iteration_count,
            latency_ms=round(elapsed_ms, 2),
            ensemble_spread=round(result.ensemble_spread, 6),
            anomaly_flag=result.anomaly_flag,
        )

    def _compute_enkf_update(
        self, matched_pair: MatchedPair, enkf_state: EnKFState
    ) -> EnKFUpdateResult:
        """Core EnKF computation.

        Steps:
        1. Forecast: Set ensemble forecast from current ensemble + prediction shift
        2. Compute ensemble mean and perturbation matrix
        3. Check for ensemble collapse and re-inflate if needed
        4. Compute forecast covariance P_f from perturbation matrix
        5. Compute Kalman Gain K = P_f * H^T * (H * P_f * H^T + R)^{-1}
        6. Update each ensemble member with perturbed observations
        7. Update EnKF state in-place

        Returns:
            EnKFUpdateResult containing the corrected StateVector and metadata.
        """
        N = enkf_state.ensemble_size  # Number of ensemble members
        d = enkf_state.state_dim  # State dimension

        # --- Step 1: Forecast ---
        # Use the ML prediction to shift the ensemble towards the predicted value.
        # The ensemble members represent the forecast ensemble X_f.
        X_f = enkf_state.ensemble_members.copy()  # Shape: (N, d)

        # If predicted_values are available, shift ensemble mean towards prediction
        if matched_pair.predicted_values:
            predicted = np.array(matched_pair.predicted_values[:d], dtype=np.float64)
            if len(predicted) < d:
                # Pad with zeros if prediction dimension is smaller
                predicted = np.pad(predicted, (0, d - len(predicted)))

            # Shift ensemble so that mean aligns with prediction
            current_mean = np.mean(X_f, axis=0)
            shift = predicted - current_mean
            X_f = X_f + shift[np.newaxis, :]

        # --- Step 2: Compute ensemble mean and perturbation matrix ---
        x_mean = np.mean(X_f, axis=0)  # Shape: (d,)
        # Perturbation matrix A: each column is (x_f[i] - x_mean)
        A = X_f - x_mean[np.newaxis, :]  # Shape: (N, d)

        # --- Step 3: Check for ensemble collapse ---
        ensemble_spread = np.std(X_f, axis=0).mean()
        if ensemble_spread < _MIN_ENSEMBLE_SPREAD:
            logger.warning(
                "Ensemble collapse detected, re-inflating",
                sensor_id=matched_pair.sensor_id,
                spread=float(ensemble_spread),
            )
            # Re-inflate with small random perturbation
            noise = np.random.randn(N, d) * _REINFLATION_NOISE_STD
            X_f = X_f + noise
            x_mean = np.mean(X_f, axis=0)
            A = X_f - x_mean[np.newaxis, :]
            ensemble_spread = np.std(X_f, axis=0).mean()

        # --- Step 4: Compute forecast covariance ---
        # P_f = (1 / (N-1)) * A^T * A  → Shape: (d, d)
        P_f = (A.T @ A) / (N - 1)  # Shape: (d, d)

        # --- Step 5: Observation operator H ---
        # For direct observation of state variables, H is identity
        # (observation maps directly to state space)
        # If observation dimension < state dimension, H selects first component
        obs_dim = 1  # Single scalar observation
        H = np.zeros((obs_dim, d), dtype=np.float64)
        H[0, 0] = 1.0  # Observe the first state variable

        # Observation noise covariance R
        R = enkf_state.observation_noise_cov  # Shape: (obs_dim, obs_dim) or (d, d)
        # Ensure R matches observation dimension
        if R.shape[0] > obs_dim:
            R = R[:obs_dim, :obs_dim]

        # --- Step 6: Compute Kalman Gain ---
        # K = P_f * H^T * (H * P_f * H^T + R)^{-1}
        # Shape analysis:
        #   P_f: (d, d), H: (obs_dim, d), H^T: (d, obs_dim)
        #   H * P_f * H^T: (obs_dim, obs_dim)
        #   P_f * H^T: (d, obs_dim)
        #   K: (d, obs_dim)

        HP = H @ P_f  # (obs_dim, d)
        HPHt = HP @ H.T  # (obs_dim, obs_dim)
        S = HPHt + R  # Innovation covariance: (obs_dim, obs_dim)

        # Compute inverse of S; use pseudo-inverse for singularity
        try:
            S_inv = np.linalg.inv(S)
        except LinAlgError:
            logger.warning(
                "Matrix singularity in Kalman Gain, using pseudo-inverse",
                sensor_id=matched_pair.sensor_id,
            )
            S_inv = np.linalg.pinv(S)

        # Also check for near-singular S (condition number too high)
        if np.any(np.isnan(S_inv)) or np.any(np.isinf(S_inv)):
            logger.warning(
                "Near-singular matrix detected, using pseudo-inverse",
                sensor_id=matched_pair.sensor_id,
            )
            S_inv = np.linalg.pinv(S)

        K = P_f @ H.T @ S_inv  # Kalman Gain: (d, obs_dim)

        # Extract scalar Kalman Gain for primary state variable (v1.2)
        # K[0,0] is the trust ratio: 1.0 = fully trusting sensor, 0.0 = fully trusting model
        # Clip to [0, 1] because degenerate numerical cases (near-singular S) could exceed bounds
        kalman_gain_scalar = float(np.clip(K[0, 0], 0.0, 1.0))

        # --- Step 7: Update each ensemble member ---
        # y_obs: scalar observation
        y_obs = np.array([[matched_pair.observed_value]], dtype=np.float64)  # (obs_dim, 1)

        # Innovation: y_obs - H * x_mean (for anomaly detection)
        innovation = y_obs.flatten() - (H @ x_mean)  # (obs_dim,)
        innovation_magnitude = float(np.linalg.norm(innovation))

        # Anomaly detection: check if innovation exceeds threshold × ensemble std
        ensemble_std_obs = np.std(H @ X_f.T, axis=1)  # Std in observation space
        ensemble_std_scalar = float(ensemble_std_obs[0]) if ensemble_std_obs[0] > 0 else ensemble_spread
        anomaly_flag = innovation_magnitude > (enkf_state.anomaly_threshold * ensemble_std_scalar)

        # Perturbed observations for each ensemble member
        # ε[i] ~ N(0, R) for each member
        obs_perturbations = np.random.multivariate_normal(
            np.zeros(obs_dim), R, size=N
        )  # Shape: (N, obs_dim)

        # Update: x_a[i] = x_f[i] + K * (y_obs + ε[i] - H * x_f[i])
        X_a = np.zeros_like(X_f)  # Shape: (N, d)
        for i in range(N):
            # Perturbed observation for member i
            y_perturbed = y_obs.flatten() + obs_perturbations[i]  # (obs_dim,)
            # Predicted observation for member i
            Hx_i = H @ X_f[i]  # (obs_dim,)
            # Innovation for member i
            innov_i = y_perturbed - Hx_i  # (obs_dim,)
            # Update
            X_a[i] = X_f[i] + (K @ innov_i)  # (d,)

        # --- Step 8: Compute corrected state (ensemble mean) ---
        corrected_mean = np.mean(X_a, axis=0)  # Shape: (d,)
        corrected_spread = float(np.std(X_a, axis=0).mean())

        # Compute 95% confidence band for primary state variable (v1.2)
        ensemble_std = float(np.std(X_a[:, 0]))  # std of first state dimension across ensemble
        confidence_band_95 = [
            float(corrected_mean[0] - 1.96 * ensemble_std),
            float(corrected_mean[0] + 1.96 * ensemble_std),
        ]

        # --- Step 9: Update EnKF state in-place ---
        enkf_state.ensemble_members = X_a
        enkf_state.last_update_timestamp = datetime.now(timezone.utc)
        enkf_state.iteration_count += 1

        # Build corrected StateVector
        corrected_state = StateVector(
            sensor_id=matched_pair.sensor_id,
            timestamp=datetime.now(timezone.utc),
            values=corrected_mean.tolist(),
            ensemble_spread=corrected_spread,
            anomaly_flag=anomaly_flag,
            source="correction",
        )

        # Compute the predicted value in observation space for anomaly reporting
        predicted_value_obs_arr = H @ x_mean
        predicted_value_obs = float(predicted_value_obs_arr.flatten()[0])

        return EnKFUpdateResult(
            state_vector=corrected_state,
            innovation_magnitude=innovation_magnitude,
            predicted_value=predicted_value_obs,
            kalman_gain_scalar=kalman_gain_scalar,
            confidence_band_95=confidence_band_95,
        )

    async def _publish_corrected_state(
        self,
        state: StateVector,
        matched_pair: MatchedPair,
        enkf_state: EnKFState,
        update_result: EnKFUpdateResult,
        kalman_gain_scalar: float,
        confidence_band_95: list[float],
    ) -> None:
        """Publish corrected state to the corrections.state broker topic.

        Message format matches the design spec:
        {
            "sensor_id": "...",
            "correction_timestamp": "...",
            "corrected_state_vector": [...],
            "ensemble_spread": 0.45,
            "anomaly_flag": false,
            "iteration_count": 42,
            "source": "correction",
            "kalman_gain": 0.42,
            "innovation_magnitude": 1.23,
            "confidence_band_95": [510.1, 514.5],
            "raw_prediction": 515.7
        }
        """
        message = {
            # Existing fields (backward compatible)
            "sensor_id": state.sensor_id,
            "correction_timestamp": state.timestamp.isoformat(),
            "corrected_state_vector": state.values,
            "ensemble_spread": state.ensemble_spread,
            "anomaly_flag": state.anomaly_flag,
            "iteration_count": enkf_state.iteration_count,
            "source": "correction",
            # NEW fields for v1.2
            "kalman_gain": kalman_gain_scalar,
            "innovation_magnitude": update_result.innovation_magnitude,
            "confidence_band_95": confidence_band_95,
            "raw_prediction": update_result.predicted_value,
        }

        payload = json.dumps(message).encode("utf-8")

        try:
            await self._broker.publish(
                CORRECTIONS_STATE, state.sensor_id, payload
            )
        except Exception as exc:
            logger.error(
                "Failed to publish corrected state",
                sensor_id=state.sensor_id,
                error=str(exc),
            )

    async def _emit_anomaly_event(
        self,
        matched_pair: MatchedPair,
        state: StateVector,
        innovation_magnitude: float,
        predicted_value: float,
        threshold: float,
    ) -> None:
        """Emit an anomaly detection event to the alerts.anomaly topic.

        Called when the corrected StateVector has anomaly_flag=True, indicating
        the innovation magnitude exceeded threshold × ensemble standard deviation.

        Args:
            matched_pair: The matched prediction-observation pair.
            state: The corrected StateVector (with anomaly_flag=True).
            innovation_magnitude: The magnitude of the innovation vector.
            predicted_value: The predicted value in observation space.
            threshold: The configured anomaly threshold (multiples of sigma).
        """
        anomaly_event = {
            "sensor_id": matched_pair.sensor_id,
            "correction_timestamp": state.timestamp.isoformat(),
            "observed_value": matched_pair.observed_value,
            "predicted_value": predicted_value,
            "innovation_magnitude": innovation_magnitude,
            "threshold": threshold,
        }

        payload = json.dumps(anomaly_event).encode("utf-8")

        try:
            await self._broker.publish(
                ALERTS_ANOMALY, matched_pair.sensor_id, payload
            )
            logger.warning(
                "Anomaly detected and emitted",
                sensor_id=matched_pair.sensor_id,
                innovation_magnitude=round(innovation_magnitude, 4),
                threshold=threshold,
                observed_value=matched_pair.observed_value,
                predicted_value=round(predicted_value, 4),
            )
        except Exception as exc:
            logger.error(
                "Failed to emit anomaly event",
                sensor_id=matched_pair.sensor_id,
                error=str(exc),
            )


def compute_enkf_step(
    X_f: np.ndarray,
    y_obs: float,
    H: np.ndarray,
    R: np.ndarray,
    anomaly_threshold: float = 3.0,
) -> tuple[np.ndarray, np.ndarray, float, float, bool]:
    """Pure-function EnKF computation step (for testing and reuse).

    Performs the mathematical core of the EnKF without side effects.

    Args:
        X_f: Forecast ensemble matrix, shape (N, d).
        y_obs: Scalar observation value.
        H: Observation operator matrix, shape (obs_dim, d).
        R: Observation noise covariance, shape (obs_dim, obs_dim).
        anomaly_threshold: Anomaly detection threshold in std deviations.

    Returns:
        Tuple of:
        - X_a: Updated ensemble matrix, shape (N, d)
        - corrected_mean: Ensemble mean after update, shape (d,)
        - ensemble_spread: Standard deviation of updated ensemble
        - innovation_magnitude: Magnitude of innovation vector
        - anomaly_flag: Whether innovation exceeds threshold
    """
    N, d = X_f.shape
    obs_dim = H.shape[0]

    # Ensemble mean and perturbation
    x_mean = np.mean(X_f, axis=0)
    A = X_f - x_mean[np.newaxis, :]

    # Check for collapse
    spread = np.std(X_f, axis=0).mean()
    if spread < _MIN_ENSEMBLE_SPREAD:
        noise = np.random.randn(N, d) * _REINFLATION_NOISE_STD
        X_f = X_f + noise
        x_mean = np.mean(X_f, axis=0)
        A = X_f - x_mean[np.newaxis, :]

    # Forecast covariance
    P_f = (A.T @ A) / (N - 1)

    # Kalman Gain
    HP = H @ P_f
    HPHt = HP @ H.T
    S = HPHt + R

    try:
        S_inv = np.linalg.inv(S)
    except LinAlgError:
        S_inv = np.linalg.pinv(S)

    if np.any(np.isnan(S_inv)) or np.any(np.isinf(S_inv)):
        S_inv = np.linalg.pinv(S)

    K = P_f @ H.T @ S_inv

    # Innovation
    y_vec = np.array([y_obs], dtype=np.float64)
    innovation = y_vec - (H @ x_mean)
    innovation_magnitude = float(np.linalg.norm(innovation))

    # Anomaly detection
    ensemble_std_obs = np.std(H @ X_f.T, axis=1)
    ensemble_std_scalar = float(ensemble_std_obs[0]) if ensemble_std_obs[0] > 0 else spread
    anomaly_flag = innovation_magnitude > (anomaly_threshold * ensemble_std_scalar)

    # Perturbed observations
    obs_perturbations = np.random.multivariate_normal(
        np.zeros(obs_dim), R, size=N
    )

    # Update ensemble
    X_a = np.zeros_like(X_f)
    for i in range(N):
        y_perturbed = y_vec + obs_perturbations[i]
        Hx_i = H @ X_f[i]
        innov_i = y_perturbed - Hx_i
        X_a[i] = X_f[i] + (K @ innov_i)

    corrected_mean = np.mean(X_a, axis=0)
    corrected_spread = float(np.std(X_a, axis=0).mean())

    return X_a, corrected_mean, corrected_spread, innovation_magnitude, anomaly_flag
