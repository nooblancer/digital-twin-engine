"""Property-based tests for State Cache update from corrections.

Uses the Hypothesis library to verify that:
- For any valid correction message containing a sensor_id and corrected state
  vector, after processing the message from the corrections.state topic, the
  state cache returns that corrected state when queried for the corresponding
  sensor_id, and the returned state has the same sensor_id, state_vector values,
  timestamp, and ensemble_spread as the original message (Property 3).

Validates: Requirements 2.2
"""

# Feature: backend-infrastructure, Property 3: State Cache Update from Corrections

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import hypothesis.strategies as st
from hypothesis import given, settings

from digital_twin_engine.api.state_cache import StateCache


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for sensor IDs: non-empty printable strings without null bytes
sensor_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
)

# Strategy for timestamps: datetimes within a reasonable range, always UTC
timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
)

# Strategy for state vectors: lists of finite floats
state_vectors = st.lists(
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    min_size=1,
    max_size=20,
)

# Strategy for ensemble spreads: positive finite floats
ensemble_spreads = st.floats(
    min_value=0.0,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
)

# Strategy for anomaly flags
anomaly_flags = st.booleans()


# ---------------------------------------------------------------------------
# Property 3: State Cache Update from Corrections
# ---------------------------------------------------------------------------


class TestProperty3StateCacheUpdateFromCorrections:
    """Property 3: State Cache Update from Corrections.

    For any valid correction message containing a sensor_id and corrected state
    vector, after processing the message from the corrections.state topic, the
    state cache SHALL return that corrected state when queried for the
    corresponding sensor_id, and the returned state SHALL have the same
    sensor_id, state_vector values, timestamp, and ensemble_spread as the
    original message.

    **Validates: Requirements 2.2**
    """

    @given(
        sensor_id=sensor_ids,
        timestamp=timestamps,
        state_vector=state_vectors,
        ensemble_spread=ensemble_spreads,
        anomaly_flag=anomaly_flags,
    )
    @settings(max_examples=100, deadline=None)
    def test_correction_message_updates_state_cache(
        self,
        sensor_id: str,
        timestamp: datetime,
        state_vector: list[float],
        ensemble_spread: float,
        anomaly_flag: bool,
    ):
        """Processing a correction message via update_from_message should make
        the state queryable via get_current with all fields matching."""
        # Arrange: create a fresh cache and build the correction message
        cache = StateCache()

        correction_message = {
            "sensor_id": sensor_id,
            "correction_timestamp": timestamp.isoformat(),
            "corrected_state_vector": state_vector,
            "ensemble_spread": ensemble_spread,
            "anomaly_flag": anomaly_flag,
        }
        payload = json.dumps(correction_message).encode("utf-8")

        # Act: process the correction message
        cache.update_from_message(sensor_id, payload)

        # Assert: query the cache and verify the returned state matches
        result = cache.get_current(sensor_id)

        assert result is not None, (
            f"State cache returned None for sensor_id={sensor_id!r} "
            f"after processing a valid correction message"
        )
        assert result.sensor_id == sensor_id, (
            f"Expected sensor_id={sensor_id!r}, got {result.sensor_id!r}"
        )
        assert result.state_vector == state_vector, (
            f"Expected state_vector={state_vector}, got {result.state_vector}"
        )
        assert result.ensemble_spread == ensemble_spread, (
            f"Expected ensemble_spread={ensemble_spread}, "
            f"got {result.ensemble_spread}"
        )
        assert result.anomaly_flag == anomaly_flag, (
            f"Expected anomaly_flag={anomaly_flag}, got {result.anomaly_flag}"
        )
        # Verify timestamp matches (compare as UTC)
        expected_ts = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
        assert result.timestamp == expected_ts, (
            f"Expected timestamp={expected_ts.isoformat()}, "
            f"got {result.timestamp.isoformat()}"
        )

    @given(
        sensor_id=sensor_ids,
        timestamp=timestamps,
        state_vector=state_vectors,
        ensemble_spread=ensemble_spreads,
        anomaly_flag=anomaly_flags,
    )
    @settings(max_examples=100, deadline=None)
    def test_correction_message_does_not_affect_other_sensors(
        self,
        sensor_id: str,
        timestamp: datetime,
        state_vector: list[float],
        ensemble_spread: float,
        anomaly_flag: bool,
    ):
        """Processing a correction for one sensor should not create state
        entries for other sensors."""
        cache = StateCache()

        correction_message = {
            "sensor_id": sensor_id,
            "correction_timestamp": timestamp.isoformat(),
            "corrected_state_vector": state_vector,
            "ensemble_spread": ensemble_spread,
            "anomaly_flag": anomaly_flag,
        }
        payload = json.dumps(correction_message).encode("utf-8")

        cache.update_from_message(sensor_id, payload)

        # A different sensor should still return None
        other_sensor = sensor_id + "_other"
        assert cache.get_current(other_sensor) is None, (
            f"Expected None for unrelated sensor {other_sensor!r}, "
            f"but got a cached state"
        )

    @given(
        sensor_id=sensor_ids,
        ts1=timestamps,
        ts2=timestamps,
        sv1=state_vectors,
        sv2=state_vectors,
        es1=ensemble_spreads,
        es2=ensemble_spreads,
        af1=anomaly_flags,
        af2=anomaly_flags,
    )
    @settings(max_examples=100, deadline=None)
    def test_newer_correction_overwrites_older(
        self,
        sensor_id: str,
        ts1: datetime,
        ts2: datetime,
        sv1: list[float],
        sv2: list[float],
        es1: float,
        es2: float,
        af1: bool,
        af2: bool,
    ):
        """When two corrections arrive for the same sensor, the cache should
        reflect the one with the more recent timestamp."""
        cache = StateCache()

        # Ensure ts1 <= ts2 for deterministic ordering
        if ts1 > ts2:
            ts1, ts2 = ts2, ts1
            sv1, sv2 = sv2, sv1
            es1, es2 = es2, es1
            af1, af2 = af2, af1

        # Process older correction first
        msg1 = {
            "sensor_id": sensor_id,
            "correction_timestamp": ts1.isoformat(),
            "corrected_state_vector": sv1,
            "ensemble_spread": es1,
            "anomaly_flag": af1,
        }
        cache.update_from_message(sensor_id, json.dumps(msg1).encode("utf-8"))

        # Process newer correction
        msg2 = {
            "sensor_id": sensor_id,
            "correction_timestamp": ts2.isoformat(),
            "corrected_state_vector": sv2,
            "ensemble_spread": es2,
            "anomaly_flag": af2,
        }
        cache.update_from_message(sensor_id, json.dumps(msg2).encode("utf-8"))

        # The cache should reflect the newer (ts2) correction
        result = cache.get_current(sensor_id)
        assert result is not None
        assert result.state_vector == sv2, (
            f"Cache should have newer state_vector={sv2}, got {result.state_vector}"
        )
        assert result.ensemble_spread == es2
        assert result.anomaly_flag == af2
