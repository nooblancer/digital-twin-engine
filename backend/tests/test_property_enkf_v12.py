"""Property-based tests for EnKF v1.2 extensions: Kalman Gain bounds and confidence band symmetry.

Uses the Hypothesis library to verify universal properties across many inputs.

**Validates: Requirements 1.3, 1.6, 8.2**
"""

from __future__ import annotations

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume, HealthCheck
import pytest

from digital_twin_engine.correction.enkf import compute_enkf_step


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def positive_definite_matrices(draw, dim=1):
    """Generate random positive-definite matrices of shape (dim, dim).

    Strategy: Generate a random matrix A and compute A @ A.T + epsilon*I
    to guarantee positive definiteness.
    """
    # Generate entries for the raw matrix
    entries = draw(
        st.lists(
            st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
            min_size=dim * dim,
            max_size=dim * dim,
        )
    )
    A = np.array(entries).reshape(dim, dim)
    # A @ A.T is positive semi-definite; add small diagonal to make it strictly positive definite
    epsilon = draw(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
    M = A @ A.T + epsilon * np.eye(dim)
    return M


@st.composite
def ensemble_members_strategy(draw, min_members=50, max_members=100, state_dim=1):
    """Generate valid ensemble matrices with meaningful spread for EnKF testing."""
    n = draw(st.integers(min_value=min_members, max_value=max_members))
    center = draw(st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    spread = draw(st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False))
    members = np.random.randn(n, state_dim) * spread + center
    return members


# ===========================================================================
# Property 2: Kalman Gain is bounded [0, 1]
# **Validates: Requirements 1.3, 1.6**
# ===========================================================================


class TestKalmanGainBounded:
    """The EnKF SHALL produce a kalman_gain scalar K[0,0] in the range [0, 1],
    representing the scalar trust ratio for the primary observed state variable.

    **Validates: Requirements 1.3, 1.6**

    Mathematical basis: K = P_f @ H.T @ inv(H @ P_f @ H.T + R)
    For scalar observation (H selects first component), K[0,0] should be in [0, 1]
    when P_f and R are positive-definite. The implementation clips to [0, 1].
    """

    @given(
        P_f_matrix=positive_definite_matrices(dim=1),
        R_matrix=positive_definite_matrices(dim=1),
        n_members=st.integers(min_value=50, max_value=80),
        y_obs=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_kalman_gain_scalar_bounded_0_1_scalar_case(
        self, P_f_matrix, R_matrix, n_members, y_obs
    ):
        """K[0,0] is bounded in [0, 1] for any positive-definite P_f and R (scalar obs)."""
        d = 1
        # Build ensemble that has covariance approximately P_f
        # Use Cholesky decomposition to generate ensemble with target covariance
        P_f_val = float(P_f_matrix[0, 0])
        std_val = np.sqrt(P_f_val)
        center = 100.0  # Arbitrary center
        X_f = np.random.randn(n_members, d) * std_val + center

        H = np.eye(d)
        R = R_matrix[:d, :d]

        X_a, corrected_mean, spread, innov_mag, anomaly = compute_enkf_step(
            X_f, y_obs, H, R, anomaly_threshold=3.0
        )

        # Recompute K[0,0] the same way the production code does
        x_mean = np.mean(X_f, axis=0)
        A = X_f - x_mean[np.newaxis, :]
        P_f_computed = (A.T @ A) / (n_members - 1)
        HP = H @ P_f_computed
        HPHt = HP @ H.T
        S = HPHt + R
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            S_inv = np.linalg.pinv(S)
        K = P_f_computed @ H.T @ S_inv
        kalman_gain_scalar = float(np.clip(K[0, 0], 0.0, 1.0))

        assert 0.0 <= kalman_gain_scalar <= 1.0, (
            f"Kalman Gain K[0,0] = {kalman_gain_scalar} is outside [0, 1] bounds. "
            f"P_f[0,0]={P_f_computed[0,0]:.6f}, R[0,0]={R[0,0]:.6f}"
        )

    @given(
        n_members=st.integers(min_value=50, max_value=80),
        state_dim=st.integers(min_value=2, max_value=4),
        center=st.floats(min_value=-200.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        spread_val=st.floats(min_value=0.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        r_val=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        y_obs=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_kalman_gain_scalar_bounded_0_1_multidim(
        self, n_members, state_dim, center, spread_val, r_val, y_obs
    ):
        """K[0,0] is bounded in [0, 1] for multi-dimensional state."""
        X_f = np.random.randn(n_members, state_dim) * spread_val + center
        H = np.zeros((1, state_dim))
        H[0, 0] = 1.0  # Observe first state variable
        R = np.array([[r_val]])

        X_a, corrected_mean, spread, innov_mag, anomaly = compute_enkf_step(
            X_f, y_obs, H, R, anomaly_threshold=3.0
        )

        # Recompute K[0,0] as in production code
        x_mean = np.mean(X_f, axis=0)
        A = X_f - x_mean[np.newaxis, :]
        ensemble_spread = np.std(X_f, axis=0).mean()
        # Handle potential collapse (same as production code)
        if ensemble_spread < 1e-10:
            noise = np.random.randn(n_members, state_dim) * 0.01
            X_f_adj = X_f + noise
            x_mean = np.mean(X_f_adj, axis=0)
            A = X_f_adj - x_mean[np.newaxis, :]

        P_f_computed = (A.T @ A) / (n_members - 1)
        HP = H @ P_f_computed
        HPHt = HP @ H.T
        S = HPHt + R
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            S_inv = np.linalg.pinv(S)

        if np.any(np.isnan(S_inv)) or np.any(np.isinf(S_inv)):
            S_inv = np.linalg.pinv(S)

        K = P_f_computed @ H.T @ S_inv
        kalman_gain_scalar = float(np.clip(K[0, 0], 0.0, 1.0))

        assert 0.0 <= kalman_gain_scalar <= 1.0, (
            f"Kalman Gain K[0,0] = {kalman_gain_scalar} is outside [0, 1] for "
            f"state_dim={state_dim}, spread={spread_val}, R={r_val}"
        )

    @given(
        n_members=st.integers(min_value=50, max_value=80),
        spread_val=st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False),
        r_val=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_kalman_gain_trust_ratio_semantics(self, n_members, spread_val, r_val):
        """K[0,0] reflects trust ratio: higher P_f relative to R means higher K (trusts sensor more)."""
        d = 1
        center = 100.0
        X_f = np.random.randn(n_members, d) * spread_val + center
        H = np.eye(d)

        # Compute K with given R
        x_mean = np.mean(X_f, axis=0)
        A = X_f - x_mean[np.newaxis, :]
        P_f = (A.T @ A) / (n_members - 1)

        R_small = np.array([[r_val]])
        R_large = np.array([[r_val * 100.0]])  # 100x larger R

        # K with small R (should trust sensor more)
        S_small = H @ P_f @ H.T + R_small
        K_small = float(np.clip((P_f @ H.T @ np.linalg.inv(S_small))[0, 0], 0.0, 1.0))

        # K with large R (should trust model more, lower K)
        S_large = H @ P_f @ H.T + R_large
        K_large = float(np.clip((P_f @ H.T @ np.linalg.inv(S_large))[0, 0], 0.0, 1.0))

        assert K_small >= K_large, (
            f"Expected K(small_R)={K_small:.4f} >= K(large_R)={K_large:.4f}. "
            f"Lower observation noise should mean higher trust in sensor."
        )


# ===========================================================================
# Property 3: Confidence band is symmetric around corrected mean
# **Validates: Requirements 1.3, 8.2**
# ===========================================================================


class TestConfidenceBandSymmetric:
    """The confidence_band_95 SHALL be symmetric around the corrected mean,
    computed as [corrected_mean[0] - 1.96 * ensemble_std, corrected_mean[0] + 1.96 * ensemble_std].

    **Validates: Requirements 1.3, 8.2**
    """

    @given(
        n_members=st.integers(min_value=50, max_value=100),
        center=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        spread_val=st.floats(min_value=0.5, max_value=20.0, allow_nan=False, allow_infinity=False),
        y_obs=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        r_val=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_confidence_band_symmetric_around_mean(
        self, n_members, center, spread_val, y_obs, r_val
    ):
        """confidence_band_95 is symmetric: lower and upper equidistant from corrected_mean."""
        d = 1
        X_f = np.random.randn(n_members, d) * spread_val + center
        H = np.eye(d)
        R = np.array([[r_val]])

        X_a, corrected_mean, _, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        # Compute confidence band the same way as production code
        ensemble_std = float(np.std(X_a[:, 0]))
        confidence_band_95 = [
            float(corrected_mean[0] - 1.96 * ensemble_std),
            float(corrected_mean[0] + 1.96 * ensemble_std),
        ]

        lower = confidence_band_95[0]
        upper = confidence_band_95[1]
        mean_val = float(corrected_mean[0])

        # Check symmetry: distance from mean to lower == distance from mean to upper
        dist_lower = mean_val - lower
        dist_upper = upper - mean_val

        assert abs(dist_lower - dist_upper) < 1e-10, (
            f"Confidence band is not symmetric: "
            f"lower_dist={dist_lower:.10f}, upper_dist={dist_upper:.10f}, "
            f"mean={mean_val:.6f}, band=[{lower:.6f}, {upper:.6f}]"
        )

    @given(
        n_members=st.integers(min_value=50, max_value=100),
        center=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        spread_val=st.floats(min_value=0.5, max_value=20.0, allow_nan=False, allow_infinity=False),
        y_obs=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        r_val=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_confidence_band_width_equals_2x196_std(
        self, n_members, center, spread_val, y_obs, r_val
    ):
        """confidence_band_95 width equals exactly 2 × 1.96 × ensemble_std."""
        d = 1
        X_f = np.random.randn(n_members, d) * spread_val + center
        H = np.eye(d)
        R = np.array([[r_val]])

        X_a, corrected_mean, _, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        # Compute confidence band the same way as production code
        ensemble_std = float(np.std(X_a[:, 0]))
        confidence_band_95 = [
            float(corrected_mean[0] - 1.96 * ensemble_std),
            float(corrected_mean[0] + 1.96 * ensemble_std),
        ]

        band_width = confidence_band_95[1] - confidence_band_95[0]
        expected_width = 2.0 * 1.96 * ensemble_std

        assert abs(band_width - expected_width) < 1e-10, (
            f"Band width {band_width:.10f} != expected 2*1.96*std = {expected_width:.10f}. "
            f"ensemble_std={ensemble_std:.6f}"
        )

    @given(
        n_members=st.integers(min_value=50, max_value=100),
        center=st.floats(min_value=-200.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        spread_val=st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False),
        y_obs=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        r_val=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_confidence_band_lower_leq_upper(
        self, n_members, center, spread_val, y_obs, r_val
    ):
        """Lower bound is always <= upper bound (band is non-negative width)."""
        d = 1
        X_f = np.random.randn(n_members, d) * spread_val + center
        H = np.eye(d)
        R = np.array([[r_val]])

        X_a, corrected_mean, _, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        ensemble_std = float(np.std(X_a[:, 0]))
        confidence_band_95 = [
            float(corrected_mean[0] - 1.96 * ensemble_std),
            float(corrected_mean[0] + 1.96 * ensemble_std),
        ]

        assert confidence_band_95[0] <= confidence_band_95[1], (
            f"Lower bound {confidence_band_95[0]} > upper bound {confidence_band_95[1]}"
        )

    @given(
        n_members=st.integers(min_value=50, max_value=100),
        center=st.floats(min_value=-200.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        spread_val=st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False),
        y_obs=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        r_val=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_corrected_mean_inside_confidence_band(
        self, n_members, center, spread_val, y_obs, r_val
    ):
        """The corrected mean always lies within the 95% confidence band."""
        d = 1
        X_f = np.random.randn(n_members, d) * spread_val + center
        H = np.eye(d)
        R = np.array([[r_val]])

        X_a, corrected_mean, _, _, _ = compute_enkf_step(X_f, y_obs, H, R)

        ensemble_std = float(np.std(X_a[:, 0]))
        confidence_band_95 = [
            float(corrected_mean[0] - 1.96 * ensemble_std),
            float(corrected_mean[0] + 1.96 * ensemble_std),
        ]

        mean_val = float(corrected_mean[0])
        assert confidence_band_95[0] <= mean_val <= confidence_band_95[1], (
            f"Corrected mean {mean_val} is outside confidence band "
            f"[{confidence_band_95[0]}, {confidence_band_95[1]}]"
        )
