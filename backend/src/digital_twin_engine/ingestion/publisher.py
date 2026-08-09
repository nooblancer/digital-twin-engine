"""Message broker publisher with buffering and backpressure for telemetry events.

Publishes validated TelemetryEvents to the `telemetry.raw` topic via Kafka
(aiokafka) or Redis Pub/Sub (redis/aioredis). Implements:
- Async publish within 50ms of receipt for valid events (Requirement 1.4)
- In-memory buffer (max 10,000 events) when broker is unreachable (Requirement 1.8)
- Exponential backoff retry: 100ms initial, 5s cap (Requirement 1.8)
- Backpressure signal on buffer overflow — no silent drop (Requirement 3.1)
- Partitioning by sensor_id for ordering guarantees (Requirement 3.3)

Validates: Requirements 1.4, 1.8, 3.1
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from enum import Enum
from typing import Any, Deque, Optional

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import TelemetryEvent, serialize_telemetry_event


logger = get_logger("publisher")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPIC = "telemetry.raw"
MAX_BUFFER_SIZE = 10_000
INITIAL_BACKOFF_MS = 100
MAX_BACKOFF_MS = 5_000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BackpressureError(Exception):
    """Raised when the in-memory buffer is full and cannot accept new events.

    Callers should propagate this as a backpressure signal to upstream producers
    rather than silently dropping events.
    """

    def __init__(self, buffer_size: int = MAX_BUFFER_SIZE) -> None:
        self.buffer_size = buffer_size
        super().__init__(
            f"Publisher buffer full ({buffer_size} events). "
            "Cannot accept new events until broker connectivity is restored."
        )


class PublisherNotStartedError(Exception):
    """Raised when publish is called before the publisher has been started."""

    pass


# ---------------------------------------------------------------------------
# Broker type enum
# ---------------------------------------------------------------------------


class BrokerType(str, Enum):
    """Supported message broker backends."""

    KAFKA = "kafka"
    REDIS = "redis"


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class TelemetryPublisher:
    """Async message broker publisher with buffering and exponential backoff.

    Usage:
        publisher = TelemetryPublisher(broker_type=BrokerType.KAFKA, broker_url="localhost:9092")
        await publisher.start()
        try:
            await publisher.publish(event)
        except BackpressureError:
            # buffer full, reject upstream
            ...
        await publisher.stop()
    """

    def __init__(
        self,
        broker_type: BrokerType = BrokerType.KAFKA,
        broker_url: str = "localhost:9092",
        max_buffer_size: int = MAX_BUFFER_SIZE,
        topic: str = TOPIC,
    ) -> None:
        self._broker_type = broker_type
        self._broker_url = broker_url
        self._max_buffer_size = max_buffer_size
        self._topic = topic

        # Internal state
        self._buffer: Deque[tuple[str, bytes]] = deque()  # (key, serialized_value)
        self._started = False
        self._connected = False
        self._producer: Any = None  # AIOKafkaProducer or Redis client
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Backoff state
        self._current_backoff_ms: float = INITIAL_BACKOFF_MS
        self._retry_count: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def buffer_size(self) -> int:
        """Current number of events in the buffer."""
        return len(self._buffer)

    @property
    def max_buffer_size(self) -> int:
        """Maximum buffer capacity."""
        return self._max_buffer_size

    @property
    def is_connected(self) -> bool:
        """Whether the publisher currently has a live broker connection."""
        return self._connected

    @property
    def is_started(self) -> bool:
        """Whether the publisher lifecycle has been started."""
        return self._started

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the publisher and connect to the broker.

        Initializes the underlying Kafka producer or Redis client and starts
        the background buffer flush task.
        """
        if self._started:
            return

        self._started = True
        await self._connect()
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(
            "Publisher started",
            broker_type=self._broker_type.value,
            broker_url=self._broker_url,
            topic=self._topic,
        )

    async def stop(self) -> None:
        """Stop the publisher and release all resources.

        Attempts to flush remaining buffered events before shutting down.
        """
        if not self._started:
            return

        self._started = False

        # Cancel the flush loop
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Attempt final flush
        await self._flush_buffer()

        # Close the producer/client
        await self._disconnect()

        logger.info(
            "Publisher stopped",
            remaining_buffer_size=len(self._buffer),
        )

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, event: TelemetryEvent) -> float:
        """Publish a validated telemetry event to the broker.

        Args:
            event: A validated TelemetryEvent to publish.

        Returns:
            The publish latency in milliseconds.

        Raises:
            BackpressureError: If the buffer is full and cannot accept new events.
            PublisherNotStartedError: If the publisher has not been started.
        """
        if not self._started:
            raise PublisherNotStartedError("Publisher must be started before publishing.")

        start_time = time.perf_counter()

        # Serialize the event
        key = event.sensor_id.encode("utf-8")
        value = serialize_telemetry_event(event).encode("utf-8")

        # Try direct publish if connected
        if self._connected:
            try:
                await self._send(key, value)
                latency_ms = (time.perf_counter() - start_time) * 1000
                return latency_ms
            except Exception as exc:
                # Broker became unreachable during send
                logger.warning(
                    "Broker send failed, buffering event",
                    error=str(exc),
                    buffer_size=len(self._buffer),
                )
                self._connected = False
                self._current_backoff_ms = INITIAL_BACKOFF_MS
                self._retry_count = 0

        # Buffer the event (broker is unreachable)
        if len(self._buffer) >= self._max_buffer_size:
            raise BackpressureError(self._max_buffer_size)

        self._buffer.append((key.decode("utf-8"), value))
        latency_ms = (time.perf_counter() - start_time) * 1000
        return latency_ms

    # ------------------------------------------------------------------
    # Internal: Connection management
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Establish connection to the message broker."""
        try:
            if self._broker_type == BrokerType.KAFKA:
                await self._connect_kafka()
            else:
                await self._connect_redis()
            self._connected = True
            self._current_backoff_ms = INITIAL_BACKOFF_MS
            self._retry_count = 0
            logger.info("Connected to broker", broker_type=self._broker_type.value)
        except Exception as exc:
            self._connected = False
            logger.warning(
                "Failed to connect to broker",
                broker_type=self._broker_type.value,
                error=str(exc),
            )

    async def _connect_kafka(self) -> None:
        """Connect to Kafka using aiokafka."""
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._broker_url,
            acks="all",
            request_timeout_ms=5000,
            retry_backoff_ms=100,
        )
        await self._producer.start()

    async def _connect_redis(self) -> None:
        """Connect to Redis using redis (aioredis-compatible)."""
        import redis.asyncio as aioredis

        self._producer = aioredis.from_url(
            self._broker_url,
            decode_responses=False,
        )
        # Test connection
        await self._producer.ping()

    async def _disconnect(self) -> None:
        """Disconnect from the message broker."""
        try:
            if self._producer is not None:
                if self._broker_type == BrokerType.KAFKA:
                    await self._producer.stop()
                else:
                    await self._producer.aclose()
                self._producer = None
        except Exception as exc:
            logger.warning("Error during disconnect", error=str(exc))
        self._connected = False

    # ------------------------------------------------------------------
    # Internal: Send
    # ------------------------------------------------------------------

    async def _send(self, key: bytes, value: bytes) -> None:
        """Send a single message to the broker.

        Raises on failure so the caller can handle buffering.
        """
        if self._broker_type == BrokerType.KAFKA:
            await self._producer.send_and_wait(
                self._topic,
                value=value,
                key=key,
            )
        else:
            # Redis Pub/Sub: publish to the topic (channel)
            await self._producer.publish(self._topic, value)

    # ------------------------------------------------------------------
    # Internal: Buffer flush loop with exponential backoff
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Background task that flushes buffered events with exponential backoff.

        Continuously attempts to reconnect and drain the buffer when the broker
        was previously unreachable. Uses exponential backoff:
          delay = min(INITIAL_BACKOFF_MS * 2^retry, MAX_BACKOFF_MS)
        """
        while self._started:
            try:
                if not self._connected:
                    # Wait with exponential backoff before retry
                    delay_s = self._current_backoff_ms / 1000.0
                    await asyncio.sleep(delay_s)

                    # Attempt reconnection
                    await self._connect()

                    if not self._connected:
                        # Increase backoff for next attempt
                        self._retry_count += 1
                        self._current_backoff_ms = min(
                            INITIAL_BACKOFF_MS * (2 ** self._retry_count),
                            MAX_BACKOFF_MS,
                        )
                        continue

                # Flush buffered events
                await self._flush_buffer()

                # Sleep briefly before next check
                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Unexpected error in flush loop",
                    error=str(exc),
                )
                await asyncio.sleep(0.1)

    async def _flush_buffer(self) -> None:
        """Attempt to send all buffered events to the broker."""
        if not self._connected or not self._buffer:
            return

        flushed = 0
        while self._buffer and self._connected:
            key_str, value = self._buffer[0]
            try:
                await self._send(key_str.encode("utf-8"), value)
                self._buffer.popleft()
                flushed += 1
            except Exception as exc:
                # Broker became unreachable during flush
                logger.warning(
                    "Broker failed during buffer flush",
                    error=str(exc),
                    flushed_count=flushed,
                    remaining_buffer_size=len(self._buffer),
                )
                self._connected = False
                self._current_backoff_ms = INITIAL_BACKOFF_MS
                self._retry_count = 0
                break

        if flushed > 0:
            logger.info(
                "Flushed buffered events",
                flushed_count=flushed,
                remaining_buffer_size=len(self._buffer),
            )
