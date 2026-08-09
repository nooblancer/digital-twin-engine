"""Abstract base class defining the Message Broker interface.

All broker backends (Kafka, Redis) must implement this interface to provide
a consistent API for publishing, subscribing, and acknowledging messages
across the pipeline.
"""

from __future__ import annotations

import abc
from typing import Awaitable, Callable

# Type alias for subscription callbacks.
# Callback receives: topic, key (sensor_id), message payload (bytes)
MessageCallback = Callable[[str, str, bytes], Awaitable[None]]


class BrokerBackend(abc.ABC):
    """Abstract broker interface for the Digital Twin Telemetry Engine.

    Implementations must provide async publish/subscribe/acknowledge methods
    and lifecycle management via start/stop.
    """

    @abc.abstractmethod
    async def start(self) -> None:
        """Initialize connections and prepare the broker for operation.

        Must be called before any publish/subscribe operations.
        """

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down broker connections and release resources."""

    @abc.abstractmethod
    async def publish(self, topic: str, key: str, message: bytes) -> None:
        """Publish a message to the specified topic.

        Args:
            topic: The target topic/channel name.
            key: The partitioning key (typically sensor_id) for ordering.
            message: The serialized message payload.
        """

    @abc.abstractmethod
    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        """Subscribe to a topic with a consumer group and register a callback.

        The callback is invoked for each message received on the topic.
        Messages for the same key are delivered in publish order within
        a consumer group.

        Args:
            topic: The topic/channel to subscribe to.
            group_id: The consumer group identifier for parallel consumption.
            callback: Async function called with (topic, key, message) for
                      each received message.
        """

    @abc.abstractmethod
    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        """Acknowledge processing of a message at the given offset.

        Commits the consumer position so the message will not be redelivered.

        Args:
            topic: The topic the message was consumed from.
            group_id: The consumer group that consumed the message.
            offset: Backend-specific offset/position indicator.
        """
