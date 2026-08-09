"""Unit tests for the broker abstraction layer.

Tests the broker interface contract, topic definitions, Kafka backend
configuration, and Redis backend behavior.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.broker import (
    ALERTS_ANOMALY,
    ALL_TOPICS,
    BACKPRESSURE_LAG_THRESHOLD,
    CORRECTIONS_STATE,
    DEFAULT_RETENTION_MS,
    METRICS_PIPELINE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
    BrokerBackend,
    KafkaBrokerBackend,
    MessageCallback,
    RedisBrokerBackend,
)
from digital_twin_engine.broker.base import MessageCallback


# ---------------------------------------------------------------------------
# Topic Definitions
# ---------------------------------------------------------------------------


class TestTopicDefinitions:
    """Verify all required topics are defined correctly."""

    def test_telemetry_raw_topic(self):
        assert TELEMETRY_RAW == "telemetry.raw"

    def test_predictions_state_topic(self):
        assert PREDICTIONS_STATE == "predictions.state"

    def test_corrections_state_topic(self):
        assert CORRECTIONS_STATE == "corrections.state"

    def test_alerts_anomaly_topic(self):
        assert ALERTS_ANOMALY == "alerts.anomaly"

    def test_metrics_pipeline_topic(self):
        assert METRICS_PIPELINE == "metrics.pipeline"

    def test_all_topics_contains_all_defined_topics(self):
        assert TELEMETRY_RAW in ALL_TOPICS
        assert PREDICTIONS_STATE in ALL_TOPICS
        assert CORRECTIONS_STATE in ALL_TOPICS
        assert ALERTS_ANOMALY in ALL_TOPICS
        assert METRICS_PIPELINE in ALL_TOPICS
        assert len(ALL_TOPICS) == 5


# ---------------------------------------------------------------------------
# BrokerBackend Interface
# ---------------------------------------------------------------------------


class TestBrokerInterface:
    """Verify the BrokerBackend abstract interface."""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            BrokerBackend()

    def test_abstract_methods_are_defined(self):
        abstract_methods = BrokerBackend.__abstractmethods__
        assert "publish" in abstract_methods
        assert "subscribe" in abstract_methods
        assert "acknowledge" in abstract_methods
        assert "start" in abstract_methods
        assert "stop" in abstract_methods

    def test_kafka_backend_is_subclass(self):
        assert issubclass(KafkaBrokerBackend, BrokerBackend)

    def test_redis_backend_is_subclass(self):
        assert issubclass(RedisBrokerBackend, BrokerBackend)


# ---------------------------------------------------------------------------
# Kafka Backend Configuration
# ---------------------------------------------------------------------------


class TestKafkaBackendConfig:
    """Verify Kafka backend configuration and constants."""

    def test_default_bootstrap_servers(self):
        backend = KafkaBrokerBackend()
        assert backend._bootstrap_servers == "localhost:9092"

    def test_custom_bootstrap_servers(self):
        backend = KafkaBrokerBackend(bootstrap_servers="kafka-1:9092,kafka-2:9092")
        assert backend._bootstrap_servers == "kafka-1:9092,kafka-2:9092"

    def test_default_client_id(self):
        backend = KafkaBrokerBackend()
        assert backend._client_id == "digital-twin-engine"

    def test_custom_client_id(self):
        backend = KafkaBrokerBackend(client_id="my-service")
        assert backend._client_id == "my-service"

    def test_default_retention_is_24_hours(self):
        backend = KafkaBrokerBackend()
        assert backend._retention_ms == DEFAULT_RETENTION_MS
        assert DEFAULT_RETENTION_MS == 24 * 60 * 60 * 1000

    def test_custom_retention(self):
        custom_ms = 48 * 60 * 60 * 1000
        backend = KafkaBrokerBackend(retention_ms=custom_ms)
        assert backend._retention_ms == custom_ms

    def test_backpressure_threshold_is_5000(self):
        assert BACKPRESSURE_LAG_THRESHOLD == 5000

    def test_not_running_initially(self):
        backend = KafkaBrokerBackend()
        assert backend._running is False
        assert backend._producer is None

    @pytest.mark.asyncio
    async def test_publish_raises_when_not_started(self):
        backend = KafkaBrokerBackend()
        with pytest.raises(RuntimeError, match="not started"):
            await backend.publish("topic", "key", b"msg")


# ---------------------------------------------------------------------------
# Redis Backend Configuration
# ---------------------------------------------------------------------------


class TestRedisBackendConfig:
    """Verify Redis backend configuration."""

    def test_default_redis_url(self):
        backend = RedisBrokerBackend()
        assert backend._redis_url == "redis://localhost:6379"

    def test_custom_redis_url(self):
        backend = RedisBrokerBackend(redis_url="redis://redis-host:6380")
        assert backend._redis_url == "redis://redis-host:6380"

    def test_not_running_initially(self):
        backend = RedisBrokerBackend()
        assert backend._running is False
        assert backend._client is None

    @pytest.mark.asyncio
    async def test_publish_raises_when_not_started(self):
        backend = RedisBrokerBackend()
        with pytest.raises(RuntimeError, match="not connected"):
            await backend.publish("topic", "key", b"msg")

    @pytest.mark.asyncio
    async def test_subscribe_raises_when_not_started(self):
        backend = RedisBrokerBackend()

        async def dummy_callback(topic, key, msg):
            pass

        with pytest.raises(RuntimeError, match="not connected"):
            await backend.subscribe("topic", "group", dummy_callback)


# ---------------------------------------------------------------------------
# Redis Backend Publish Envelope Format
# ---------------------------------------------------------------------------


class TestRedisEnvelopeFormat:
    """Verify the Redis message envelope structure."""

    @pytest.mark.asyncio
    async def test_publish_creates_correct_envelope(self):
        """Ensure the published message wraps key and payload in JSON envelope."""
        backend = RedisBrokerBackend()

        # Mock Redis client
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock()
        backend._client = mock_client
        backend._running = True

        topic = TELEMETRY_RAW
        key = "sensor-001"
        message = b'{"value": 42.0}'

        await backend.publish(topic, key, message)

        # Verify publish was called
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert call_args[0][0] == topic

        # Verify envelope format
        envelope_bytes = call_args[0][1]
        envelope = json.loads(envelope_bytes)
        assert envelope["key"] == "sensor-001"
        assert envelope["payload"] == '{"value": 42.0}'

    @pytest.mark.asyncio
    async def test_acknowledge_is_noop(self):
        """Redis acknowledge should not raise or have side effects."""
        backend = RedisBrokerBackend()
        backend._client = AsyncMock()
        backend._running = True

        # Should not raise
        await backend.acknowledge(TELEMETRY_RAW, "group-1", None)


# ---------------------------------------------------------------------------
# Kafka Backend Publish Key Partitioning
# ---------------------------------------------------------------------------


class TestKafkaKeyPartitioning:
    """Verify that Kafka publish uses sensor_id as the partition key."""

    @pytest.mark.asyncio
    async def test_publish_uses_key_for_partitioning(self):
        """Ensure messages are sent with the key for partition assignment."""
        backend = KafkaBrokerBackend()

        # Mock producer
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        backend._producer = mock_producer
        backend._running = True

        topic = TELEMETRY_RAW
        key = "turbine-001-temp"
        message = b'{"timestamp": "2024-01-15T10:30:00Z", "value": 42.0}'

        await backend.publish(topic, key, message)

        mock_producer.send_and_wait.assert_called_once_with(
            topic=topic,
            key=key,
            value=message,
        )

    @pytest.mark.asyncio
    async def test_publish_different_keys_preserved(self):
        """Multiple publishes with different keys use their respective keys."""
        backend = KafkaBrokerBackend()

        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        backend._producer = mock_producer
        backend._running = True

        await backend.publish(TELEMETRY_RAW, "sensor-a", b"msg-1")
        await backend.publish(TELEMETRY_RAW, "sensor-b", b"msg-2")

        calls = mock_producer.send_and_wait.call_args_list
        assert calls[0].kwargs["key"] == "sensor-a"
        assert calls[1].kwargs["key"] == "sensor-b"
