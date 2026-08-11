"""Property-based tests for Accuracy API response schema completeness.

Uses the Hypothesis library to verify that when the CorrectionMetricsTracker has
sufficient samples (>= 2), the GET /metrics/accuracy endpoint returns all response
fields as non-null numeric values with the correct schema shape.

**Validates: Requirements 3.1, 3.2, 3.5**
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import hypothesis.strategies as st
from hypothesis import given, settings, HealthCheck, assume
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.correction.correction_metrics_tracker import (
    CorrectionMetricsTracker,
)


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def tracker_with_sufficient_samples(draw, min_samples=2, max_samples=50):
    """Generate a CorrectionMetricsTracker pre-loaded with random data.

    Generates random (raw_prediction, observed_value, corrected_value) triples
    with sample_count >= 2, ensuring observed values are not all identical
    (so R² is computable and non-null).

    Values are bounded to avoid overflow in squared-error computations.
    """
    n = draw(st.integers(min_value=min_samples, max_value=max_samples))

    tracker = CorrectionMetricsTracker()
    sensor_ids = draw(
        st.lists(
            st.sampled_from(["sensor-001", "sensor-002", "sensor-003"]),
            min_size=n,
            max_size=n,
        )
    )

    observed_values = []
    for i in range(n):
        raw = draw(
            st.floats(
                min_value=-500.0,
                max_value=500.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        observed = draw(
            st.floats(
                min_value=-500.0,
                max_value=500.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        corrected = draw(
            st.floats(
                min_value=-500.0,
                max_value=500.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        tracker.record(sensor_ids[i], raw, observed, corrected)
        observed_values.append(observed)

    # Ensure observed values are not all identical so ss_tot > 0 and R² is non-null
    assume(len(set(observed_values)) > 1)

    return tracker, n


# ===========================================================================
# Property 10: Accuracy API response schema completeness
# **Validates: Requirements 3.1, 3.2, 3.5**
# ===========================================================================


class TestAccuracyAPIResponseSchemaCompleteness:
    """Property 10: Accuracy API response schema completeness.

    WHEN the CorrectionMetricsTracker has sample_count >= 2 and observed values
    are not all identical, the GET /metrics/accuracy endpoint SHALL return a JSON
    response where all metric fields (raw_rmse, raw_mae, raw_r_squared,
    corrected_rmse, corrected_mae, corrected_r_squared, improvement_percentage,
    sample_count) are present and non-null numeric values.

    **Validates: Requirements 3.1, 3.2, 3.5**
    """

    @given(tracker_data=tracker_with_sufficient_samples(min_samples=2, max_samples=50))
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_all_fields_present_and_numeric_when_sufficient_samples(
        self, tracker_data
    ):
        """All response fields are non-null numerics when sample_count >= 2."""
        tracker, expected_count = tracker_data

        # Patch the accuracy_tracker used by the API endpoint
        with patch(
            "digital_twin_engine.api.correction_metrics_api.accuracy_tracker",
            tracker,
        ):
            from digital_twin_engine.api.correction_metrics_api import router
            from fastapi import FastAPI

            app = FastAPI()
            app.include_router(router)

            async def do_request():
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    resp = await client.get("/metrics/accuracy")
                    return resp

            resp = asyncio.run(do_request())

        assert resp.status_code == 200, (
            f"Expected HTTP 200, got {resp.status_code}: {resp.text}"
        )

        body = resp.json()

        # Requirement 3.1: Response SHALL contain all expected fields
        expected_fields = [
            "raw_rmse",
            "raw_mae",
            "raw_r_squared",
            "corrected_rmse",
            "corrected_mae",
            "corrected_r_squared",
            "improvement_percentage",
            "sample_count",
        ]
        for field_name in expected_fields:
            assert field_name in body, (
                f"Missing field '{field_name}' in response. Got keys: {list(body.keys())}"
            )

        # Requirement 3.2: All metric fields SHALL be numeric (non-null)
        numeric_fields = [
            "raw_rmse",
            "raw_mae",
            "raw_r_squared",
            "corrected_rmse",
            "corrected_mae",
            "corrected_r_squared",
            "improvement_percentage",
        ]
        for field_name in numeric_fields:
            value = body[field_name]
            assert value is not None, (
                f"Field '{field_name}' is null but expected non-null numeric "
                f"when sample_count={body.get('sample_count')}"
            )
            assert isinstance(value, (int, float)), (
                f"Field '{field_name}' has type {type(value).__name__}, "
                f"expected numeric. Value: {value}"
            )

        # Requirement 3.5: sample_count SHALL be a positive integer
        assert body["sample_count"] == expected_count, (
            f"sample_count mismatch: got {body['sample_count']}, expected {expected_count}"
        )
        assert isinstance(body["sample_count"], int), (
            f"sample_count should be int, got {type(body['sample_count']).__name__}"
        )
        assert body["sample_count"] >= 2, (
            f"sample_count should be >= 2, got {body['sample_count']}"
        )

        # Additional schema validation: RMSE values must be non-negative
        assert body["raw_rmse"] >= 0, f"raw_rmse should be >= 0, got {body['raw_rmse']}"
        assert body["corrected_rmse"] >= 0, (
            f"corrected_rmse should be >= 0, got {body['corrected_rmse']}"
        )

        # MAE values must be non-negative
        assert body["raw_mae"] >= 0, f"raw_mae should be >= 0, got {body['raw_mae']}"
        assert body["corrected_mae"] >= 0, (
            f"corrected_mae should be >= 0, got {body['corrected_mae']}"
        )
