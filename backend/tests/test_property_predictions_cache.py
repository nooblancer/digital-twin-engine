"""Property-based tests for Predictions Cache update.

Uses the Hypothesis library to verify that:
- For any valid prediction message containing a sensor_id and prediction data,
  after processing the message from the predictions.state topic, the predictions
  cache SHALL contain the prediction data for the corresponding sensor_id
  (Property 4).

Validates: Requirements 2.3
"""

# Feature: backend-infrastructure, Property 4: Predictions Cache Update

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import hypothesis.strategies as st
from hypothesis import given, settings

from digital_twin_engine.api.broker_subscriber import BrokerSubscriber
from digital_twin_engine.api.state_cache import StateCache
from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.topics import PREDICTIONS_STATE


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

# Strategy for ISO-like timestamp strings
timestamp_strings = st.from_regex(
    r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z",
    fullmatch=True,
)

# Strategy for state vectors in predictions: lists of finite floats
prediction_state_vectors = st.lists(
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    min_size=1,
    max_size=20,
)

# Strategy for a single prediction entry
prediction_entries = st.fixed_dictionaries(
    {"timestamp": timestamp_strings, "state_vector": prediction_state_vectors}
)

# Strategy for prediction lists: 1 to 20 prediction entries
prediction_lists = st.lists(prediction_entries, min_size=1, max_size=20)


# ---------------------------------------------------------------------------
# Helper: create a started BrokerSubscriber and extract the predictions callback
# ---------------------------------------------------------------------------


async def _create_subscriber_and_get_callback():
    """Create a BrokerSubscriber, start it with a mock broker, and return
    the subscriber along with the registered callback for predictions.state."""
    subscriber = BrokerSubscriber()
    broker = AsyncMock()
    broker.subscribe = AsyncMock()
    state_cache = StateCache()
    ws_manager = AsyncMock(spec=WebSocketBroadcastManager)
    ws_manager.broadcast = AsyncMock()

    await subscriber.start(broker, state_cache, ws_manager)

    # Extract the callback registered for predictions.state
    callback = None
    for call in broker.subscribe.call_args_list:
        if call.kwargs["topic"] == PREDICTIONS_STATE:
            callback = call.kwargs["callback"]
            break

    assert callback is not None, "No subscription found for predictions.state"
    return subscriber, callback


# ---------------------------------------------------------------------------
# Property 4: Predictions Cache Update
# ---------------------------------------------------------------------------


class TestProperty4PredictionsCacheUpdate:
    """Property 4: Predictions Cache Update.

    For any valid prediction message containing a sensor_id and prediction data,
    after processing the message from the predictions.state topic, the
    predictions cache SHALL contain the prediction data for the corresponding
    sensor_id.

    **Validates: Requirements 2.3**
    """

    @given(sensor_id=sensor_ids, predictions=prediction_lists)
    @settings(max_examples=150, deadline=None)
    async def test_prediction_message_updates_cache(
        self,
        sensor_id: str,
        predictions: list[dict],
    ):
        """Processing a prediction message should store the predictions list
        in the predictions cache keyed by sensor_id."""
        # Arrange
        subscriber, callback = await _create_subscriber_and_get_callback()

        message_payload = {
            "sensor_id": sensor_id,
            "predictions": predictions,
        }
        message_bytes = json.dumps(message_payload).encode("utf-8")

        # Act: invoke the callback as the broker would
        await callback(PREDICTIONS_STATE, sensor_id, message_bytes)

        # Assert: predictions cache contains the correct data
        assert sensor_id in subscriber.predictions_cache, (
            f"Expected sensor_id={sensor_id!r} in predictions_cache, "
            f"but it was not found"
        )
        cached_predictions = subscriber.predictions_cache[sensor_id]
        assert cached_predictions == predictions, (
            f"Expected predictions={predictions}, got {cached_predictions}"
        )

    @given(sensor_id=sensor_ids, predictions=prediction_lists)
    @settings(max_examples=100, deadline=None)
    async def test_prediction_cache_preserves_all_entries(
        self,
        sensor_id: str,
        predictions: list[dict],
    ):
        """The cached predictions list should have the same number of entries
        as the original prediction data."""
        subscriber, callback = await _create_subscriber_and_get_callback()

        message_payload = {
            "sensor_id": sensor_id,
            "predictions": predictions,
        }
        message_bytes = json.dumps(message_payload).encode("utf-8")

        await callback(PREDICTIONS_STATE, sensor_id, message_bytes)

        cached = subscriber.predictions_cache[sensor_id]
        assert len(cached) == len(predictions), (
            f"Expected {len(predictions)} prediction entries, got {len(cached)}"
        )

    @given(sensor_id=sensor_ids, predictions=prediction_lists)
    @settings(max_examples=100, deadline=None)
    async def test_prediction_cache_does_not_affect_other_sensors(
        self,
        sensor_id: str,
        predictions: list[dict],
    ):
        """Processing a prediction for one sensor should not create entries
        for other sensors."""
        subscriber, callback = await _create_subscriber_and_get_callback()

        message_payload = {
            "sensor_id": sensor_id,
            "predictions": predictions,
        }
        message_bytes = json.dumps(message_payload).encode("utf-8")

        await callback(PREDICTIONS_STATE, sensor_id, message_bytes)

        # A different sensor should not be in the cache
        other_sensor = sensor_id + "_other"
        assert other_sensor not in subscriber.predictions_cache, (
            f"Expected sensor {other_sensor!r} to not be in predictions_cache"
        )

    @given(
        sensor_id=sensor_ids,
        predictions1=prediction_lists,
        predictions2=prediction_lists,
    )
    @settings(max_examples=100, deadline=None)
    async def test_newer_prediction_overwrites_older(
        self,
        sensor_id: str,
        predictions1: list[dict],
        predictions2: list[dict],
    ):
        """When two prediction messages arrive for the same sensor, the cache
        should reflect the most recent one."""
        subscriber, callback = await _create_subscriber_and_get_callback()

        # Send first prediction
        msg1 = {"sensor_id": sensor_id, "predictions": predictions1}
        await callback(PREDICTIONS_STATE, sensor_id, json.dumps(msg1).encode("utf-8"))

        # Send second prediction
        msg2 = {"sensor_id": sensor_id, "predictions": predictions2}
        await callback(PREDICTIONS_STATE, sensor_id, json.dumps(msg2).encode("utf-8"))

        # Cache should reflect the second (most recent) prediction
        assert subscriber.predictions_cache[sensor_id] == predictions2, (
            f"Cache should have newer predictions={predictions2}, "
            f"got {subscriber.predictions_cache[sensor_id]}"
        )
