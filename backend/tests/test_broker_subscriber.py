"""Unit tests for the Broker Subscriber service.

Tests the BrokerSubscriber class:
- Subscribes to all required broker topics on start
- Updates StateCache on corrections.state messages
- Updates predictions cache on predictions.state messages
- Broadcasts messages to WebSocket clients
- Implements exponential backoff retry on broker failure
- Starts in degraded mode if broker unavailable
- Reconnects with backoff on connection loss during operation

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 13.1
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.api.broker_subscriber import (
    TOPIC_TYPE_MAP,
    BrokerSubscriber,
    _CONSUMER_GROUP,
    _MAX_RETRY_ATTEMPTS,
)
from digital_twin_engine.api.state_cache import StateCache
from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.topics import (
    ALERTS_ANOMALY,
    CORRECTIONS_STATE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def broker() -> AsyncMock:
    """Create a mock BrokerBackend."""
    mock = AsyncMock()
    mock.subscribe = AsyncMock()
    return mock


@pytest.fixture
def state_cache() -> StateCache:
    """Create a real StateCache instance."""
    return StateCache()


@pytest.fixture
def ws_manager() -> AsyncMock:
    """Create a mock WebSocketBroadcastManager."""
    mock = AsyncMock(spec=WebSocketBroadcastManager)
    mock.broadcast = AsyncMock()
    return mock


@pytest.fixture
def subscriber() -> BrokerSubscriber:
    """Create a fresh BrokerSubscriber instance."""
    return BrokerSubscriber()


# ---------------------------------------------------------------------------
# Start / Subscribe tests
# ---------------------------------------------------------------------------


class TestStart:
    """Tests for BrokerSubscriber.start()."""

    async def test_start_subscribes_to_all_topics(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Start should subscribe to corrections.state, predictions.state,
        alerts.anomaly, and telemetry.raw topics."""
        await subscriber.start(broker, state_cache, ws_manager)

        subscribed_topics = [
            call.kwargs["topic"] for call in broker.subscribe.call_args_list
        ]
        assert CORRECTIONS_STATE in subscribed_topics
        assert PREDICTIONS_STATE in subscribed_topics
        assert ALERTS_ANOMALY in subscribed_topics
        assert TELEMETRY_RAW in subscribed_topics

    async def test_start_uses_correct_consumer_group(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Start should use the 'api-gateway' consumer group for all subscriptions."""
        await subscriber.start(broker, state_cache, ws_manager)

        for call in broker.subscribe.call_args_list:
            assert call.kwargs["group_id"] == _CONSUMER_GROUP

    async def test_start_sets_running_true(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Start should set the running flag to True."""
        await subscriber.start(broker, state_cache, ws_manager)
        assert subscriber.running is True

    async def test_start_not_degraded_on_success(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Start should not be in degraded mode when broker is available."""
        await subscriber.start(broker, state_cache, ws_manager)
        assert subscriber.degraded is False

    async def test_start_accepts_broker_via_dependency_injection(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """BrokerSubscriber should not create its own broker connection."""
        await subscriber.start(broker, state_cache, ws_manager)
        # Verify the subscriber uses the injected broker, not creating its own
        broker.subscribe.assert_called()


# ---------------------------------------------------------------------------
# Retry and degraded mode tests
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    """Tests for exponential backoff retry on broker failure."""

    async def test_retries_on_subscribe_failure(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Should retry subscription on failure with exponential backoff."""
        # Fail twice, then succeed
        broker.subscribe.side_effect = [
            ConnectionError("Broker unavailable"),
            ConnectionError("Broker unavailable"),
            None, None, None, None,  # 4 successful subscriptions
        ]

        with patch("digital_twin_engine.api.broker_subscriber.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await subscriber.start(broker, state_cache, ws_manager)

        # Should have slept twice for two failures
        assert mock_sleep.await_count == 2
        assert subscriber.degraded is False

    async def test_enters_degraded_mode_after_max_retries(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Should enter degraded mode after exhausting all retry attempts."""
        broker.subscribe.side_effect = ConnectionError("Broker unavailable")

        with patch("digital_twin_engine.api.broker_subscriber.asyncio.sleep", new_callable=AsyncMock):
            await subscriber.start(broker, state_cache, ws_manager)

        assert subscriber.degraded is True
        assert subscriber.running is True  # Still running, just degraded

    async def test_exponential_backoff_timings(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Should use exponential backoff: 1s, 2s, 4s, 8s between retries."""
        broker.subscribe.side_effect = ConnectionError("Broker unavailable")

        with patch("digital_twin_engine.api.broker_subscriber.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await subscriber.start(broker, state_cache, ws_manager)

        # 5 attempts, 4 sleeps between them
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0, 4.0, 8.0]

    async def test_max_retry_attempts_is_five(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Should attempt subscription exactly 5 times before giving up."""
        call_count = 0

        async def counting_subscribe(**kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Broker unavailable")

        broker.subscribe.side_effect = counting_subscribe

        with patch("digital_twin_engine.api.broker_subscriber.asyncio.sleep", new_callable=AsyncMock):
            await subscriber.start(broker, state_cache, ws_manager)

        # 5 attempts × 4 topics per attempt = up to 20 calls,
        # but first call per attempt will fail so at most 5 calls
        assert call_count == _MAX_RETRY_ATTEMPTS


# ---------------------------------------------------------------------------
# Message handling tests
# ---------------------------------------------------------------------------


class TestMessageHandling:
    """Tests for message callback handling."""

    async def test_corrections_state_updates_cache(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """corrections.state messages should update the StateCache."""
        await subscriber.start(broker, state_cache, ws_manager)

        # Get the callback from the subscribe call for corrections.state
        callback = self._get_callback_for_topic(broker, CORRECTIONS_STATE)

        message = json.dumps({
            "sensor_id": "sensor-1",
            "correction_timestamp": "2024-01-01T00:00:00Z",
            "corrected_state_vector": [1.0, 2.0, 3.0],
            "ensemble_spread": 0.05,
            "anomaly_flag": False,
        }).encode()

        await callback(CORRECTIONS_STATE, "sensor-1", message)

        cached = state_cache.get_current("sensor-1")
        assert cached is not None
        assert cached.sensor_id == "sensor-1"
        assert cached.state_vector == [1.0, 2.0, 3.0]

    async def test_predictions_state_updates_predictions_cache(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """predictions.state messages should update the predictions cache."""
        await subscriber.start(broker, state_cache, ws_manager)

        callback = self._get_callback_for_topic(broker, PREDICTIONS_STATE)

        message = json.dumps({
            "sensor_id": "sensor-2",
            "predictions": [
                {"timestamp": "2024-01-01T00:01:00Z", "state_vector": [4.0, 5.0]},
                {"timestamp": "2024-01-01T00:02:00Z", "state_vector": [6.0, 7.0]},
            ],
        }).encode()

        await callback(PREDICTIONS_STATE, "sensor-2", message)

        assert "sensor-2" in subscriber.predictions_cache
        assert len(subscriber.predictions_cache["sensor-2"]) == 2

    async def test_corrections_broadcast_to_websocket(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """corrections.state messages should be broadcast as type 'correction' with transformed payload."""
        await subscriber.start(broker, state_cache, ws_manager)

        callback = self._get_callback_for_topic(broker, CORRECTIONS_STATE)

        payload = {
            "sensor_id": "sensor-1",
            "correction_timestamp": "2024-01-01T00:00:00Z",
            "corrected_state_vector": [1.0, 2.0],
            "ensemble_spread": 0.05,
            "anomaly_flag": False,
        }
        message = json.dumps(payload).encode()

        await callback(CORRECTIONS_STATE, "sensor-1", message)

        # The broker subscriber transforms payloads to the frontend WebSocket contract
        expected_broadcast = {
            "sensor_id": "sensor-1",
            "timestamp": "2024-01-01T00:00:00Z",
            "values": [1.0, 2.0],
            "ensemble_spread": 0.05,
            "anomaly_flag": False,
            # v1.2 fields — None when not present in the source message
            "kalman_gain": None,
            "innovation_magnitude": None,
            "confidence_band_95": None,
            "raw_prediction": None,
        }
        ws_manager.broadcast.assert_awaited_once_with("correction", expected_broadcast)

    async def test_predictions_broadcast_to_websocket(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """predictions.state messages should be broadcast as type 'prediction' with transformed payload."""
        await subscriber.start(broker, state_cache, ws_manager)

        callback = self._get_callback_for_topic(broker, PREDICTIONS_STATE)

        payload = {
            "sensor_id": "sensor-2",
            "prediction_timestamp": "2024-01-01T00:01:00Z",
            "values": [1.0, 2.0],
            "prediction_horizon_seconds": 60,
            "source": "ensemble",
        }
        message = json.dumps(payload).encode()

        await callback(PREDICTIONS_STATE, "sensor-2", message)

        # The broker subscriber transforms payloads to the frontend WebSocket contract
        expected_broadcast = {
            "sensor_id": "sensor-2",
            "prediction_timestamp": "2024-01-01T00:01:00Z",
            "state_vector": [1.0, 2.0],
            "model_used": "ensemble",
            "prediction_horizon_seconds": 60,
        }
        ws_manager.broadcast.assert_awaited_once_with("prediction", expected_broadcast)

    async def test_anomaly_broadcast_to_websocket(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """alerts.anomaly messages should be broadcast as type 'anomaly' with transformed payload."""
        await subscriber.start(broker, state_cache, ws_manager)

        callback = self._get_callback_for_topic(broker, ALERTS_ANOMALY)

        payload = {
            "sensor_id": "sensor-3",
            "correction_timestamp": "2024-01-01T00:00:00Z",
            "observed_value": 5.0,
            "predicted_value": 2.0,
            "innovation_magnitude": 3.0,
            "threshold": 2.5,
        }
        message = json.dumps(payload).encode()

        await callback(ALERTS_ANOMALY, "sensor-3", message)

        # The broker subscriber transforms anomaly payloads to frontend contract
        expected_broadcast = {
            "sensor_id": "sensor-3",
            "timestamp": "2024-01-01T00:00:00Z",
            "severity": "informational",
            "description": "Innovation magnitude 3.000 exceeds threshold 2.5 (observed=5.0000, predicted=2.0000)",
        }
        ws_manager.broadcast.assert_awaited_once_with("anomaly", expected_broadcast)

    async def test_telemetry_broadcast_to_websocket(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """telemetry.raw messages should be broadcast as type 'telemetry'."""
        await subscriber.start(broker, state_cache, ws_manager)

        callback = self._get_callback_for_topic(broker, TELEMETRY_RAW)

        payload = {"sensor_id": "sensor-4", "raw_values": [10.0, 20.0]}
        message = json.dumps(payload).encode()

        await callback(TELEMETRY_RAW, "sensor-4", message)

        ws_manager.broadcast.assert_awaited_once_with("telemetry", payload)

    async def test_invalid_json_does_not_crash(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Invalid JSON messages should be logged and skipped, not crash."""
        await subscriber.start(broker, state_cache, ws_manager)

        callback = self._get_callback_for_topic(broker, CORRECTIONS_STATE)

        # Send invalid JSON
        await callback(CORRECTIONS_STATE, "sensor-1", b"not valid json")

        # Should not have broadcast anything
        ws_manager.broadcast.assert_not_awaited()

    async def test_message_not_processed_after_stop(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Messages should not be processed after stop() is called."""
        await subscriber.start(broker, state_cache, ws_manager)
        await subscriber.stop()

        callback = self._get_callback_for_topic(broker, CORRECTIONS_STATE)

        payload = {
            "sensor_id": "sensor-1",
            "correction_timestamp": "2024-01-01T00:00:00Z",
            "corrected_state_vector": [1.0],
            "ensemble_spread": 0.0,
            "anomaly_flag": False,
        }
        message = json.dumps(payload).encode()

        await callback(CORRECTIONS_STATE, "sensor-1", message)

        # Should not have updated cache or broadcast
        assert state_cache.get_current("sensor-1") is None
        ws_manager.broadcast.assert_not_awaited()

    @staticmethod
    def _get_callback_for_topic(broker: AsyncMock, target_topic: str):
        """Extract the registered callback for a specific topic."""
        for call in broker.subscribe.call_args_list:
            if call.kwargs["topic"] == target_topic:
                return call.kwargs["callback"]
        raise ValueError(f"No subscription found for topic: {target_topic}")


# ---------------------------------------------------------------------------
# Stop tests
# ---------------------------------------------------------------------------


class TestStop:
    """Tests for BrokerSubscriber.stop()."""

    async def test_stop_sets_running_false(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Stop should set the running flag to False."""
        await subscriber.start(broker, state_cache, ws_manager)
        await subscriber.stop()
        assert subscriber.running is False

    async def test_stop_cancels_reconnect_task(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """Stop should cancel any pending reconnect task."""
        await subscriber.start(broker, state_cache, ws_manager)

        # Simulate connection loss to start reconnect task
        subscriber._degraded = True
        subscriber._reconnect_task = asyncio.create_task(asyncio.sleep(100))

        await subscriber.stop()

        assert subscriber._reconnect_task is None or subscriber._reconnect_task.done()


# ---------------------------------------------------------------------------
# Reconnection tests
# ---------------------------------------------------------------------------


class TestReconnection:
    """Tests for broker reconnection on connection loss."""

    async def test_handle_connection_lost_enters_degraded_mode(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """handle_connection_lost should enter degraded mode."""
        await subscriber.start(broker, state_cache, ws_manager)
        subscriber.handle_connection_lost()
        assert subscriber.degraded is True

    async def test_handle_connection_lost_spawns_reconnect_task(
        self, subscriber: BrokerSubscriber, broker: AsyncMock,
        state_cache: StateCache, ws_manager: AsyncMock,
    ):
        """handle_connection_lost should start a reconnection task."""
        await subscriber.start(broker, state_cache, ws_manager)
        subscriber.handle_connection_lost()
        assert subscriber._reconnect_task is not None
        # Clean up
        await subscriber.stop()

    async def test_handle_connection_lost_noop_when_not_running(
        self, subscriber: BrokerSubscriber,
    ):
        """handle_connection_lost should be a no-op when not running."""
        subscriber.handle_connection_lost()
        assert subscriber._reconnect_task is None
        assert subscriber.degraded is False


# ---------------------------------------------------------------------------
# Topic type mapping tests
# ---------------------------------------------------------------------------


class TestTopicTypeMapping:
    """Tests for the topic-to-type mapping."""

    def test_corrections_maps_to_correction(self):
        """corrections.state should map to type 'correction'."""
        assert TOPIC_TYPE_MAP[CORRECTIONS_STATE] == "correction"

    def test_predictions_maps_to_prediction(self):
        """predictions.state should map to type 'prediction'."""
        assert TOPIC_TYPE_MAP[PREDICTIONS_STATE] == "prediction"

    def test_alerts_maps_to_anomaly(self):
        """alerts.anomaly should map to type 'anomaly'."""
        assert TOPIC_TYPE_MAP[ALERTS_ANOMALY] == "anomaly"

    def test_telemetry_maps_to_telemetry(self):
        """telemetry.raw should map to type 'telemetry'."""
        assert TOPIC_TYPE_MAP[TELEMETRY_RAW] == "telemetry"
