"""TSDB Consumer - Async broker consumer with batch writing.

Reads TelemetryEvents from the `telemetry.raw` broker topic and writes them
to the TSDB via the TSDBWriter. Implements dual-trigger batching:
- Batch size trigger: flush when buffer reaches configured batch size (default 100)
- Time window trigger: flush when 1 second elapses since the first buffered event

Whichever condition is met first triggers the flush.

Validates: Requirements 4.1, 4.5, 4.6
"""

from __future__ import annotations

import asyncio
from typing import Optional

from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import TELEMETRY_RAW
from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import (
    TelemetryEvent,
    deserialize_telemetry_event,
)
from digital_twin_engine.tsdb.writer import TSDBWriter, TSDBBackend

logger = get_logger("tsdb_consumer")

# Default consumer group ID for the TSDB writer service
TSDB_CONSUMER_GROUP = "tsdb-writer-group"


class TSDBConsumer:
    """Async consumer that reads from the broker and batch-writes to the TSDB.

    Implements dual-trigger batching:
    - Flush when batch_size events are buffered
    - Flush when batch_window_seconds elapse since the first event in the buffer

    Whichever condition fires first triggers the write.

    The consumer preserves all original field values without modification
    during the read-from-broker → write-to-TSDB pipeline.

    Args:
        broker: The message broker backend to consume from.
        tsdb_backend: The TSDB storage backend for persistence.
        batch_size: Maximum events per batch before flush (default 100).
        batch_window_seconds: Maximum time in seconds before flush (default 1.0).
        max_retries: Maximum retry attempts on write failure (default 3).
        initial_retry_delay_ms: Initial backoff delay in ms (default 100).
        consumer_group: Consumer group ID for broker subscription.
    """

    def __init__(
        self,
        broker: BrokerBackend,
        tsdb_backend: TSDBBackend,
        batch_size: int = 100,
        batch_window_seconds: float = 1.0,
        max_retries: int = 3,
        initial_retry_delay_ms: int = 100,
        consumer_group: str = TSDB_CONSUMER_GROUP,
    ) -> None:
        self._broker = broker
        self._consumer_group = consumer_group
        self._batch_window_seconds = batch_window_seconds

        # The writer handles batch buffering, retry, and failure logging
        self._writer = TSDBWriter(
            backend=tsdb_backend,
            batch_size=batch_size,
            batch_window_seconds=batch_window_seconds,
            max_retries=max_retries,
            initial_retry_delay_ms=initial_retry_delay_ms,
        )

        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._first_event_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def writer(self) -> TSDBWriter:
        """Access the underlying TSDBWriter for queries and inspection."""
        return self._writer

    @property
    def is_running(self) -> bool:
        """Whether the consumer is currently running."""
        return self._running

    async def start(self) -> None:
        """Start consuming from the telemetry.raw topic.

        Subscribes to the broker and begins processing messages.
        The time-window flush loop runs concurrently.
        """
        if self._running:
            return

        self._running = True
        logger.info(
            "TSDB consumer starting",
            topic=TELEMETRY_RAW,
            consumer_group=self._consumer_group,
            batch_size=self._writer._batch_size,
            batch_window_seconds=self._batch_window_seconds,
        )

        # Subscribe to the broker topic
        await self._broker.subscribe(
            topic=TELEMETRY_RAW,
            group_id=self._consumer_group,
            callback=self._on_message,
        )

        # Start the periodic flush task for time-window batching
        self._flush_task = asyncio.create_task(self._time_window_flush_loop())

    async def stop(self) -> None:
        """Stop the consumer and flush any remaining buffered events.

        Cancels the time-window flush loop and performs a final flush.
        """
        if not self._running:
            return

        self._running = False

        # Cancel the flush loop
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Final flush of any remaining events
        async with self._lock:
            await self._writer.flush()
            self._first_event_time = None

        logger.info("TSDB consumer stopped")

    async def _on_message(self, topic: str, key: str, message: bytes) -> None:
        """Callback invoked by the broker for each received message.

        Deserializes the message into a TelemetryEvent and buffers it.
        If the batch size threshold is reached, triggers an immediate flush.

        Args:
            topic: The topic the message was received from.
            key: The message key (sensor_id).
            message: The serialized event payload (JSON bytes).
        """
        try:
            event = deserialize_telemetry_event(message.decode("utf-8"))
        except Exception as e:
            logger.error(
                "Failed to deserialize message from broker",
                topic=topic,
                key=key,
                error=str(e),
            )
            return

        async with self._lock:
            # Track when the first event in the current batch arrived
            if self._writer.buffer_size == 0:
                self._first_event_time = asyncio.get_event_loop().time()

            # Add event to the writer's buffer; this may trigger a flush
            # if batch_size is reached
            await self._writer.write_event(event)

            # If the writer flushed (buffer is now empty), reset the timer
            if self._writer.buffer_size == 0:
                self._first_event_time = None

    async def _time_window_flush_loop(self) -> None:
        """Periodically check if the time window has elapsed and flush.

        Runs every 100ms to check whether batch_window_seconds have passed
        since the first event was buffered. If so, flushes the batch.
        """
        check_interval = 0.1  # Check every 100ms

        while self._running:
            try:
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break

            async with self._lock:
                if (
                    self._first_event_time is not None
                    and self._writer.buffer_size > 0
                ):
                    elapsed = (
                        asyncio.get_event_loop().time() - self._first_event_time
                    )
                    if elapsed >= self._batch_window_seconds:
                        await self._writer.flush()
                        self._first_event_time = None
