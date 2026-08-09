"""Redis Pub/Sub broker backend implementation.

Provides a lightweight message broker alternative for local development
and testing. Uses Redis Pub/Sub channels named after topics.

Limitations compared to Kafka backend:
- No partitioning (messages are broadcast to all subscribers)
- No consumer groups (all subscribers receive all messages)
- No message persistence or replay capability
- No offset tracking or acknowledgment semantics
- No ordering guarantees beyond Redis single-channel FIFO

This backend is intended for development and lightweight deployments only.
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Optional

import redis.asyncio as aioredis

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("message_broker.redis")


class RedisBrokerBackend(BrokerBackend):
    """Redis Pub/Sub broker backend for lightweight development use.

    Messages are published to Redis channels named after topics.
    Each message is wrapped with a key field to preserve sensor_id
    information for subscribers.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
    ) -> None:
        """Initialize the Redis backend.

        Args:
            redis_url: Redis connection URL.
        """
        self._redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None
        self._pubsub_instances: List[aioredis.client.PubSub] = []
        self._subscriber_tasks: List[asyncio.Task[None]] = []
        self._running = False

    async def start(self) -> None:
        """Connect to Redis and prepare for operations."""
        logger.info("Starting Redis Pub/Sub backend", redis_url=self._redis_url)
        self._client = aioredis.from_url(
            self._redis_url, decode_responses=False
        )
        # Verify connection
        await self._client.ping()
        self._running = True
        logger.info("Redis Pub/Sub backend started")

    async def stop(self) -> None:
        """Disconnect from Redis and clean up resources."""
        logger.info("Stopping Redis Pub/Sub backend")
        self._running = False

        # Cancel subscriber tasks
        for task in self._subscriber_tasks:
            task.cancel()
        if self._subscriber_tasks:
            await asyncio.gather(*self._subscriber_tasks, return_exceptions=True)
        self._subscriber_tasks.clear()

        # Close pubsub instances
        for pubsub in self._pubsub_instances:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception as exc:
                logger.error("Error closing pubsub", error=str(exc))
        self._pubsub_instances.clear()

        # Close Redis client
        if self._client is not None:
            await self._client.close()
            self._client = None

        logger.info("Redis Pub/Sub backend stopped")

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        """Publish a message to a Redis Pub/Sub channel.

        The message is wrapped in an envelope containing the key (sensor_id)
        for downstream consumers to use.

        Args:
            topic: The channel name (topic).
            key: The message key (sensor_id), included in envelope.
            message: The serialized message payload.

        Raises:
            RuntimeError: If the client is not connected.
        """
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call start() first.")

        # Wrap message with key in a simple envelope
        envelope = json.dumps({
            "key": key,
            "payload": message.decode("utf-8", errors="replace"),
        }).encode("utf-8")

        try:
            await self._client.publish(topic, envelope)
            logger.debug(
                "Message published",
                topic=topic,
                key=key,
                message_size=len(message),
            )
        except aioredis.RedisError as exc:
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
        """Subscribe to a Redis Pub/Sub channel.

        Note: Redis Pub/Sub does not support consumer groups. The group_id
        parameter is accepted for interface compatibility but does not
        affect message delivery. All subscribers receive all messages.

        Args:
            topic: The channel name to subscribe to.
            group_id: Consumer group ID (ignored in Redis - for interface compat).
            callback: Async callback invoked with (topic, key, message).
        """
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call start() first.")

        logger.info(
            "Subscribing to channel",
            topic=topic,
            group_id=group_id,
            note="Redis Pub/Sub does not support consumer groups",
        )

        pubsub = self._client.pubsub()
        await pubsub.subscribe(topic)
        self._pubsub_instances.append(pubsub)

        # Launch background listener
        task = asyncio.create_task(
            self._listen_loop(pubsub, topic, group_id, callback),
            name=f"redis-subscriber-{topic}:{group_id}",
        )
        self._subscriber_tasks.append(task)

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        """No-op for Redis Pub/Sub.

        Redis Pub/Sub is fire-and-forget; there is no offset tracking
        or acknowledgment mechanism. This method exists for interface
        compatibility.

        Args:
            topic: The topic (unused).
            group_id: The consumer group (unused).
            offset: The offset (unused).
        """
        logger.debug(
            "Acknowledge called (no-op for Redis Pub/Sub)",
            topic=topic,
            group_id=group_id,
        )

    async def _listen_loop(
        self,
        pubsub: aioredis.client.PubSub,
        topic: str,
        group_id: str,
        callback: MessageCallback,
    ) -> None:
        """Background loop that listens for Redis Pub/Sub messages.

        Deserializes the envelope to extract the key and payload,
        then invokes the registered callback.
        """
        logger.info(
            "Redis listener started",
            topic=topic,
            group_id=group_id,
        )

        try:
            while self._running:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message is None:
                        continue

                    if message["type"] != "message":
                        continue

                    raw_data = message["data"]
                    if isinstance(raw_data, str):
                        raw_data = raw_data.encode("utf-8")

                    # Unwrap envelope
                    try:
                        envelope = json.loads(raw_data)
                        key = envelope.get("key", "")
                        payload_str = envelope.get("payload", "")
                        payload = payload_str.encode("utf-8") if isinstance(
                            payload_str, str
                        ) else payload_str
                    except (json.JSONDecodeError, AttributeError):
                        # If not a valid envelope, treat raw data as payload
                        key = ""
                        payload = raw_data

                    try:
                        await callback(topic, key, payload)
                    except Exception as exc:
                        logger.error(
                            "Callback error processing message",
                            topic=topic,
                            group_id=group_id,
                            key=key,
                            error=str(exc),
                        )
                except aioredis.RedisError as exc:
                    logger.error(
                        "Redis subscriber error",
                        topic=topic,
                        group_id=group_id,
                        error=str(exc),
                    )
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info(
                "Redis listener cancelled",
                topic=topic,
                group_id=group_id,
            )
