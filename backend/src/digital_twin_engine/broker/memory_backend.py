"""In-memory message broker backend for Local Mode and testing.

Implements the full BrokerBackend interface using a simple dictionary
of topic → subscriber callbacks. Messages published to a topic are
delivered to all subscribers synchronously within the same event loop
iteration, making it ideal for single-process deployments and tests.
"""

from __future__ import annotations

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback


class InMemoryBrokerBackend(BrokerBackend):
    """In-memory message broker for Local Mode and testing.

    Implements the full BrokerBackend interface without external dependencies.
    Messages published to a topic are delivered to all subscribers
    synchronously within the same event loop iteration.

    Attributes:
        _subscribers: Mapping of topic names to lists of (group_id, callback)
                      tuples representing registered subscribers.
        _running: Whether the broker has been started and not yet stopped.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[str, MessageCallback]]] = {}
        self._running: bool = False

    async def start(self) -> None:
        """Initialize the in-memory broker for operation.

        Marks the broker as running. No external connections are needed.
        """
        self._running = True

    async def stop(self) -> None:
        """Shut down the in-memory broker.

        Clears all subscriber registrations and marks the broker as stopped.
        """
        self._running = False
        self._subscribers.clear()

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        """Publish a message to the specified topic.

        Invokes all registered subscriber callbacks synchronously within
        the same event loop tick (awaiting each callback in sequence).

        Args:
            topic: The target topic name.
            key: The partitioning key (typically sensor_id).
            message: The serialized message payload.
        """
        subscribers = self._subscribers.get(topic, [])
        for _group_id, callback in subscribers:
            await callback(topic, key, message)

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        """Subscribe to a topic with a consumer group and register a callback.

        The callback will be invoked for each message published to the topic.

        Args:
            topic: The topic to subscribe to.
            group_id: The consumer group identifier.
            callback: Async function called with (topic, key, message) for
                      each received message.
        """
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append((group_id, callback))

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        """Acknowledge processing of a message (no-op for in-memory broker).

        In-memory delivery is immediate and doesn't track offsets,
        so acknowledgment is not needed.

        Args:
            topic: The topic the message was consumed from.
            group_id: The consumer group that consumed the message.
            offset: Ignored — no offset tracking in memory.
        """
