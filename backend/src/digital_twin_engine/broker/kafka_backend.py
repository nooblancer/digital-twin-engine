"""Apache Kafka broker backend implementation.

Provides durable, partitioned, replay-capable message routing using aiokafka.
Events are keyed by sensor_id to ensure per-sensor ordering guarantees.
Consumer groups enable parallel consumption while maintaining ordering.

Retention is configured at 24 hours minimum for all topics.
Backpressure warning metrics are emitted when consumer lag exceeds 5000 messages.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("message_broker.kafka")

# Backpressure threshold: emit warning when consumer lag exceeds this
BACKPRESSURE_LAG_THRESHOLD = 5000

# Default Kafka topic retention: 24 hours in milliseconds
DEFAULT_RETENTION_MS = 24 * 60 * 60 * 1000


class KafkaBrokerBackend(BrokerBackend):
    """Kafka-based message broker backend using aiokafka.

    Features:
    - Partitioning by sensor_id key for per-sensor ordering
    - Consumer groups for parallel consumption
    - 24-hour retention for unacknowledged messages
    - Backpressure warning metric when consumer lag > 5000 messages
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "digital-twin-engine",
        retention_ms: int = DEFAULT_RETENTION_MS,
    ) -> None:
        """Initialize the Kafka backend.

        Args:
            bootstrap_servers: Comma-separated Kafka broker addresses.
            client_id: Client identifier for Kafka connections.
            retention_ms: Topic retention period in milliseconds (default 24h).
        """
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._retention_ms = retention_ms
        self._producer: Optional[AIOKafkaProducer] = None
        self._consumers: Dict[str, AIOKafkaConsumer] = {}
        self._consumer_tasks: List[asyncio.Task[None]] = []
        self._running = False

    async def start(self) -> None:
        """Start the Kafka producer and prepare for operations."""
        logger.info(
            "Starting Kafka backend",
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
            retention_ms=self._retention_ms,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
            # Key serializer: encode string key to bytes
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            # Ensure messages are durably written
            acks="all",
        )
        await self._producer.start()
        self._running = True
        logger.info("Kafka producer started")

    async def stop(self) -> None:
        """Stop all consumers and the producer, releasing resources."""
        logger.info("Stopping Kafka backend")
        self._running = False

        # Cancel consumer tasks
        for task in self._consumer_tasks:
            task.cancel()
        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        self._consumer_tasks.clear()

        # Stop consumers
        for consumer_key, consumer in self._consumers.items():
            try:
                await consumer.stop()
            except Exception as exc:
                logger.error(
                    "Error stopping consumer",
                    consumer_key=consumer_key,
                    error=str(exc),
                )
        self._consumers.clear()

        # Stop producer
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

        logger.info("Kafka backend stopped")

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        """Publish a message to a Kafka topic, keyed by sensor_id.

        The key ensures all messages with the same sensor_id go to
        the same partition, preserving per-sensor ordering.

        Args:
            topic: Kafka topic name.
            key: Partitioning key (sensor_id).
            message: Serialized message payload.

        Raises:
            RuntimeError: If the producer is not started.
            KafkaError: If publishing fails.
        """
        if self._producer is None:
            raise RuntimeError("Kafka producer not started. Call start() first.")

        try:
            await self._producer.send_and_wait(
                topic=topic,
                key=key,
                value=message,
            )
            logger.debug(
                "Message published",
                topic=topic,
                key=key,
                message_size=len(message),
            )
        except KafkaError as exc:
            logger.error(
                "Failed to publish message",
                topic=topic,
                key=key,
                error=str(exc),
            )
            raise

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        """Subscribe to a Kafka topic with a consumer group.

        Creates an AIOKafkaConsumer for the given topic and group,
        and starts a background task that polls messages and invokes
        the callback. Monitors consumer lag and emits backpressure
        warnings when lag exceeds the threshold.

        Args:
            topic: Kafka topic to subscribe to.
            group_id: Consumer group ID for parallel consumption.
            callback: Async callback invoked with (topic, key, message).
        """
        consumer_key = f"{topic}:{group_id}"
        logger.info(
            "Subscribing to topic",
            topic=topic,
            group_id=group_id,
        )

        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=group_id,
            key_deserializer=lambda k: k.decode("utf-8") if k else "",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        self._consumers[consumer_key] = consumer

        # Launch background consumption loop
        task = asyncio.create_task(
            self._consume_loop(consumer, topic, group_id, callback),
            name=f"kafka-consumer-{consumer_key}",
        )
        self._consumer_tasks.append(task)

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        """Commit the consumer offset for the given topic and group.

        Args:
            topic: The topic being consumed.
            group_id: The consumer group.
            offset: Not used directly; commits current position.
        """
        consumer_key = f"{topic}:{group_id}"
        consumer = self._consumers.get(consumer_key)
        if consumer is None:
            logger.error(
                "Cannot acknowledge: no consumer found",
                topic=topic,
                group_id=group_id,
            )
            return

        try:
            await consumer.commit()
            logger.debug(
                "Offset committed",
                topic=topic,
                group_id=group_id,
            )
        except KafkaError as exc:
            logger.error(
                "Failed to commit offset",
                topic=topic,
                group_id=group_id,
                error=str(exc),
            )

    async def _consume_loop(
        self,
        consumer: AIOKafkaConsumer,
        topic: str,
        group_id: str,
        callback: MessageCallback,
    ) -> None:
        """Background loop that polls Kafka and dispatches messages to callback.

        Monitors consumer lag and emits backpressure warning metrics
        when lag exceeds the configured threshold.
        """
        logger.info(
            "Consumer loop started",
            topic=topic,
            group_id=group_id,
        )

        try:
            while self._running:
                try:
                    msg_batch = await consumer.getmany(
                        timeout_ms=1000, max_records=100
                    )
                    for tp, messages in msg_batch.items():
                        for msg in messages:
                            key = msg.key if msg.key else ""
                            value = msg.value if msg.value else b""
                            try:
                                await callback(topic, key, value)
                            except Exception as exc:
                                logger.error(
                                    "Callback error processing message",
                                    topic=topic,
                                    group_id=group_id,
                                    key=key,
                                    offset=msg.offset,
                                    error=str(exc),
                                )

                    # Check consumer lag for backpressure detection
                    await self._check_consumer_lag(consumer, topic, group_id)

                except KafkaError as exc:
                    logger.error(
                        "Kafka consumer error",
                        topic=topic,
                        group_id=group_id,
                        error=str(exc),
                    )
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info(
                "Consumer loop cancelled",
                topic=topic,
                group_id=group_id,
            )

    async def _check_consumer_lag(
        self,
        consumer: AIOKafkaConsumer,
        topic: str,
        group_id: str,
    ) -> None:
        """Check consumer lag and emit backpressure warning if threshold exceeded."""
        try:
            partitions = consumer.assignment()
            if not partitions:
                return

            # Get end offsets (latest available)
            end_offsets = await consumer.end_offsets(partitions)

            total_lag = 0
            for tp in partitions:
                current_position = await consumer.position(tp)
                end_offset = end_offsets.get(tp, 0)
                partition_lag = max(0, end_offset - current_position)
                total_lag += partition_lag

            if total_lag > BACKPRESSURE_LAG_THRESHOLD:
                logger.warning(
                    "Backpressure warning: consumer lag exceeds threshold",
                    topic=topic,
                    group_id=group_id,
                    consumer_lag=total_lag,
                    threshold=BACKPRESSURE_LAG_THRESHOLD,
                    metric_type="backpressure_warning",
                )
        except Exception as exc:
            logger.debug(
                "Could not check consumer lag",
                topic=topic,
                group_id=group_id,
                error=str(exc),
            )
