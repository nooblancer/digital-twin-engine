"""Property-based tests for WebSocket payload field completeness (v1.2 fields).

# Feature: digital-twin-v1.2, Property 1: WebSocket payload contains all fields with correct values

Tests that when the BrokerSubscriber transforms a correction message payload,
the output contains ALL existing fields (backward compatibility) AND all new
v1.2 fields (kalman_gain, innovation_magnitude, confidence_band_95, raw_prediction)
with values matching the source payload.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
"""

from __future__ import annotations

import json
from typing import Optional

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from digital_twin_engine.api.broker_subscriber import BrokerSubscriber
from digital_twin_engine.broker.topics import CORRECTIONS_STATE


# ---------------------------------------------------------------------------
# Required fields in the WebSocket correction payload
# ---------------------------------------------------------------------------

# Existing (backward-compatible) fields — Requirement 1.5
EXISTING_REQUIRED_FIELDS = {
    "sensor_id",
    "timestamp",
    "values",
    "ensemble_spread",
    "anomaly_flag",
}

# New v1.2 fields — Requirements 1.1, 1.2, 1.3, 1.4
NEW_V12_FIELDS = {
    "kalman_gain",
    "innovation_magnitude",
    "confidence_band_95",
    "raw_prediction",
}

ALL_REQUIRED_FIELDS = EXISTING_REQUIRED_FIELDS | NEW_V12_FIELDS


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

sensor_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=50,
)

timestamp_strategy = st.from_regex(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z",
    fullmatch=True,
)

state_vector_strategy = st.lists(
    st.floats(min_value=-2000.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=5,
)

ensemble_spread_strategy = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

anomaly_flag_strategy = st.booleans()

# v1.2 field strategies
kalman_gain_strategy = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

innovation_magnitude_strategy = st.floats(
    min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
)

confidence_band_strategy = st.tuples(
    st.floats(min_value=-2000.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-2000.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
).map(lambda t: [min(t[0], t[1]), max(t[0], t[1])])

raw_prediction_strategy = st.floats(
    min_value=-2000.0, max_value=2000.0, allow_nan=False, allow_infinity=False
)


@st.composite
def correction_payload_with_v12_fields(draw):
    """Generate a full correction broker payload including v1.2 fields."""
    sensor_id = draw(sensor_id_strategy)
    correction_timestamp = draw(timestamp_strategy)
    corrected_state_vector = draw(state_vector_strategy)
    ensemble_spread = draw(ensemble_spread_strategy)
    anomaly_flag = draw(anomaly_flag_strategy)
    kalman_gain = draw(kalman_gain_strategy)
    innovation_magnitude = draw(innovation_magnitude_strategy)
    confidence_band_95 = draw(confidence_band_strategy)
    raw_prediction = draw(raw_prediction_strategy)

    return {
        "sensor_id": sensor_id,
        "correction_timestamp": correction_timestamp,
        "corrected_state_vector": corrected_state_vector,
        "ensemble_spread": ensemble_spread,
        "anomaly_flag": anomaly_flag,
        "kalman_gain": kalman_gain,
        "innovation_magnitude": innovation_magnitude,
        "confidence_band_95": confidence_band_95,
        "raw_prediction": raw_prediction,
    }


@st.composite
def correction_payload_without_v12_fields(draw):
    """Generate a correction broker payload WITHOUT v1.2 fields (legacy message)."""
    sensor_id = draw(sensor_id_strategy)
    correction_timestamp = draw(timestamp_strategy)
    corrected_state_vector = draw(state_vector_strategy)
    ensemble_spread = draw(ensemble_spread_strategy)
    anomaly_flag = draw(anomaly_flag_strategy)

    return {
        "sensor_id": sensor_id,
        "correction_timestamp": correction_timestamp,
        "corrected_state_vector": corrected_state_vector,
        "ensemble_spread": ensemble_spread,
        "anomaly_flag": anomaly_flag,
    }


# ===========================================================================
# Property 1: WebSocket payload contains all fields with correct values
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
# ===========================================================================


class TestWebSocketPayloadFieldCompleteness:
    """The BrokerSubscriber._transform_payload() for CORRECTIONS_STATE SHALL
    produce a WebSocket payload containing all existing fields AND new v1.2
    fields (kalman_gain, innovation_magnitude, confidence_band_95, raw_prediction)
    with values matching the source broker message.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """

    @given(payload=correction_payload_with_v12_fields())
    @settings(max_examples=200)
    def test_all_fields_present_in_transformed_payload(self, payload: dict) -> None:
        """Transformed payload contains ALL required existing + v1.2 fields."""
        subscriber = BrokerSubscriber()
        result = subscriber._transform_payload(CORRECTIONS_STATE, payload)

        missing_fields = ALL_REQUIRED_FIELDS - set(result.keys())
        assert not missing_fields, (
            f"Transformed payload missing fields: {missing_fields}. "
            f"Got keys: {set(result.keys())}"
        )

    @given(payload=correction_payload_with_v12_fields())
    @settings(max_examples=200)
    def test_existing_fields_have_correct_values(self, payload: dict) -> None:
        """Existing fields maintain backward-compatible values from source payload."""
        subscriber = BrokerSubscriber()
        result = subscriber._transform_payload(CORRECTIONS_STATE, payload)

        # sensor_id passes through directly
        assert result["sensor_id"] == payload["sensor_id"], (
            f"sensor_id mismatch: {result['sensor_id']} != {payload['sensor_id']}"
        )
        # correction_timestamp maps to timestamp
        assert result["timestamp"] == payload["correction_timestamp"], (
            f"timestamp mismatch: {result['timestamp']} != {payload['correction_timestamp']}"
        )
        # corrected_state_vector maps to values
        assert result["values"] == payload["corrected_state_vector"], (
            f"values mismatch: {result['values']} != {payload['corrected_state_vector']}"
        )
        # ensemble_spread passes through
        assert result["ensemble_spread"] == payload["ensemble_spread"], (
            f"ensemble_spread mismatch: {result['ensemble_spread']} != {payload['ensemble_spread']}"
        )
        # anomaly_flag passes through
        assert result["anomaly_flag"] == payload["anomaly_flag"], (
            f"anomaly_flag mismatch: {result['anomaly_flag']} != {payload['anomaly_flag']}"
        )

    @given(payload=correction_payload_with_v12_fields())
    @settings(max_examples=200)
    def test_v12_fields_have_correct_values(self, payload: dict) -> None:
        """New v1.2 fields pass through with correct values from source payload."""
        subscriber = BrokerSubscriber()
        result = subscriber._transform_payload(CORRECTIONS_STATE, payload)

        # kalman_gain — Requirement 1.1
        assert result["kalman_gain"] == payload["kalman_gain"], (
            f"kalman_gain mismatch: {result['kalman_gain']} != {payload['kalman_gain']}"
        )
        # innovation_magnitude — Requirement 1.2
        assert result["innovation_magnitude"] == payload["innovation_magnitude"], (
            f"innovation_magnitude mismatch: "
            f"{result['innovation_magnitude']} != {payload['innovation_magnitude']}"
        )
        # confidence_band_95 — Requirement 1.3
        assert result["confidence_band_95"] == payload["confidence_band_95"], (
            f"confidence_band_95 mismatch: "
            f"{result['confidence_band_95']} != {payload['confidence_band_95']}"
        )
        # raw_prediction — Requirement 1.4
        assert result["raw_prediction"] == payload["raw_prediction"], (
            f"raw_prediction mismatch: {result['raw_prediction']} != {payload['raw_prediction']}"
        )

    @given(payload=correction_payload_without_v12_fields())
    @settings(max_examples=200)
    def test_legacy_payloads_produce_null_v12_fields(self, payload: dict) -> None:
        """Legacy payloads (without v1.2 fields) produce None for new fields.

        This ensures backward compatibility — older messages gracefully
        pass None/null for the new fields.
        """
        subscriber = BrokerSubscriber()
        result = subscriber._transform_payload(CORRECTIONS_STATE, payload)

        # All fields must still be present in the output
        missing_fields = ALL_REQUIRED_FIELDS - set(result.keys())
        assert not missing_fields, (
            f"Legacy payload transformed output missing fields: {missing_fields}"
        )

        # v1.2 fields must be None for legacy messages
        assert result["kalman_gain"] is None, (
            f"Expected None for kalman_gain on legacy payload, got {result['kalman_gain']}"
        )
        assert result["innovation_magnitude"] is None, (
            f"Expected None for innovation_magnitude on legacy payload, "
            f"got {result['innovation_magnitude']}"
        )
        assert result["confidence_band_95"] is None, (
            f"Expected None for confidence_band_95 on legacy payload, "
            f"got {result['confidence_band_95']}"
        )
        assert result["raw_prediction"] is None, (
            f"Expected None for raw_prediction on legacy payload, "
            f"got {result['raw_prediction']}"
        )

    @given(payload=correction_payload_with_v12_fields())
    @settings(max_examples=100)
    def test_transformed_payload_is_json_serializable(self, payload: dict) -> None:
        """Transformed payload can be serialized to valid JSON for WebSocket broadcast."""
        subscriber = BrokerSubscriber()
        result = subscriber._transform_payload(CORRECTIONS_STATE, payload)

        # Must be JSON serializable (WebSocket broadcast requires this)
        message = json.dumps({"type": "correction", "payload": result})
        parsed = json.loads(message)

        assert parsed["type"] == "correction"
        assert set(parsed["payload"].keys()) >= ALL_REQUIRED_FIELDS

    @given(payload=correction_payload_with_v12_fields())
    @settings(max_examples=100)
    def test_no_extra_mutation_of_source_values(self, payload: dict) -> None:
        """Transform does not alter or mutate the field values beyond renaming."""
        subscriber = BrokerSubscriber()
        # Make a copy to detect mutations
        original_payload = payload.copy()
        original_payload["corrected_state_vector"] = list(payload["corrected_state_vector"])
        original_payload["confidence_band_95"] = list(payload["confidence_band_95"])

        result = subscriber._transform_payload(CORRECTIONS_STATE, payload)

        # Source payload should not be mutated
        assert payload["sensor_id"] == original_payload["sensor_id"]
        assert payload["corrected_state_vector"] == original_payload["corrected_state_vector"]
        assert payload["confidence_band_95"] == original_payload["confidence_band_95"]
        assert payload["kalman_gain"] == original_payload["kalman_gain"]
