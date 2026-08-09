"""TSDB Writer - Async consumer and batch writer for time-series persistence.

Consumes TelemetryEvents from the message broker and writes them to a
time-series database. Implements retry with exponential backoff on write
failures and logs permanent write failures.

Validates: Requirements 4.1, 4.2, 4.3, 4.5, 4.6
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import TelemetryEvent

logger = get_logger("tsdb_writer")


# ---------------------------------------------------------------------------
# Types and Errors
# ---------------------------------------------------------------------------


class TSDBWriteError(Exception):
    """Raised when a write to the TSDB fails."""

    def __init__(self, message: str, sensor_id: str = "", timestamp: str = "") -> None:
        self.sensor_id = sensor_id
        self.timestamp_str = timestamp
        super().__init__(message)


@dataclass(frozen=True)
class WriteFailureLog:
    """Record of a permanent write failure after retry exhaustion."""

    sensor_id: str
    timestamp: datetime
    failure_reason: str
    retry_count: int


# ---------------------------------------------------------------------------
# TSDB Backend Protocol
# ---------------------------------------------------------------------------


class TSDBBackend(Protocol):
    """Protocol defining the interface for TSDB storage backends."""

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Write a batch of events to the TSDB.

        Raises TSDBWriteError on failure.
        """
        ...

    async def query_by_sensor_and_time(
        self,
        sensor_id: str,
        start: datetime,
        end: datetime,
        measurement_type: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """Query events by sensor_id within a time range.

        Args:
            sensor_id: The sensor identifier to query.
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).
            measurement_type: Optional filter by measurement type.

        Returns:
            List of TelemetryEvents matching criteria, ordered chronologically.
        """
        ...

    async def query_by_measurement_type(
        self,
        sensor_ids: List[str],
        measurement_type: str,
        start: datetime,
        end: datetime,
    ) -> List[TelemetryEvent]:
        """Query events by measurement type across multiple sensors.

        Args:
            sensor_ids: List of sensor identifiers (up to 100).
            measurement_type: The measurement type to filter by.
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).

        Returns:
            List of TelemetryEvents matching criteria, ordered chronologically.
        """
        ...


# ---------------------------------------------------------------------------
# In-Memory TSDB Backend (for testing and development)
# ---------------------------------------------------------------------------


class InMemoryTSDBBackend:
    """In-memory TSDB implementation for testing and development.

    Stores events in a list and supports temporal/sensor queries.
    Thread-safe for asyncio (single-threaded event loop).
    """

    def __init__(self, fail_writes: bool = False) -> None:
        self._events: List[TelemetryEvent] = []
        self._fail_writes = fail_writes
        self._write_call_count = 0

    @property
    def events(self) -> List[TelemetryEvent]:
        """Access all stored events."""
        return list(self._events)

    @property
    def write_call_count(self) -> int:
        """Number of write_events calls made."""
        return self._write_call_count

    def set_fail_writes(self, fail: bool) -> None:
        """Toggle write failure simulation."""
        self._fail_writes = fail

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Write events to in-memory storage.

        Raises TSDBWriteError if fail_writes is True.
        """
        self._write_call_count += 1
        if self._fail_writes:
            raise TSDBWriteError(
                "Simulated TSDB write failure",
                sensor_id=events[0].sensor_id if events else "",
                timestamp=str(events[0].timestamp) if events else "",
            )
        self._events.extend(events)

    async def query_by_sensor_and_time(
        self,
        sensor_id: str,
        start: datetime,
        end: datetime,
        measurement_type: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """Query events by sensor and time range."""
        results = [
            e for e in self._events
            if e.sensor_id == sensor_id
            and start <= e.timestamp <= end
            and (measurement_type is None or e.measurement_type == measurement_type)
        ]
        return sorted(results, key=lambda e: e.timestamp)

    async def query_by_measurement_type(
        self,
        sensor_ids: List[str],
        measurement_type: str,
        start: datetime,
        end: datetime,
    ) -> List[TelemetryEvent]:
        """Query events by measurement type across multiple sensors."""
        results = [
            e for e in self._events
            if e.sensor_id in sensor_ids
            and e.measurement_type == measurement_type
            and start <= e.timestamp <= end
        ]
        return sorted(results, key=lambda e: e.timestamp)


# ---------------------------------------------------------------------------
# TSDB Writer
# ---------------------------------------------------------------------------


class TSDBWriter:
    """Async consumer that batches and writes TelemetryEvents to the TSDB.

    Features:
    - Configurable batch size (default 100 events) or time window (1 second)
    - Retry with exponential backoff (100ms initial, 3 retries) on write failure
    - Logs permanent write failures with sensor_id, timestamp, and failure reason

    Validates: Requirements 4.1, 4.5, 4.6
    """

    def __init__(
        self,
        backend: TSDBBackend,
        batch_size: int = 100,
        batch_window_seconds: float = 1.0,
        max_retries: int = 3,
        initial_retry_delay_ms: int = 100,
    ) -> None:
        self._backend = backend
        self._batch_size = batch_size
        self._batch_window_seconds = batch_window_seconds
        self._max_retries = max_retries
        self._initial_retry_delay_ms = initial_retry_delay_ms

        self._buffer: List[TelemetryEvent] = []
        self._failure_log: List[WriteFailureLog] = []
        self._retry_attempts_log: List[int] = []  # Track retry counts per failed write

    @property
    def failure_log(self) -> List[WriteFailureLog]:
        """Access the log of permanent write failures."""
        return list(self._failure_log)

    @property
    def retry_attempts_log(self) -> List[int]:
        """Access the log of retry attempt counts for failed writes."""
        return list(self._retry_attempts_log)

    @property
    def buffer_size(self) -> int:
        """Current number of events in the write buffer."""
        return len(self._buffer)

    async def write_event(self, event: TelemetryEvent) -> None:
        """Buffer an event and flush if batch size is reached.

        The event is added to the internal buffer. If the buffer reaches
        batch_size, it is flushed to the TSDB.
        """
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            await self.flush()

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Write multiple events, flushing batches as needed."""
        for event in events:
            await self.write_event(event)

    async def flush(self) -> None:
        """Flush the current buffer to the TSDB with retry logic."""
        if not self._buffer:
            return

        batch = list(self._buffer)
        self._buffer.clear()

        await self._write_with_retry(batch)

    async def _write_with_retry(self, events: List[TelemetryEvent]) -> None:
        """Attempt to write events with exponential backoff retry.

        Retries up to max_retries times (exactly 3 by default).
        After exhausting retries, logs the failure as permanent.

        The retry strategy:
        - Attempt 0: initial write (not counted as a retry)
        - Attempt 1: retry after 100ms
        - Attempt 2: retry after 200ms
        - Attempt 3: retry after 400ms
        - After attempt 3 fails: log permanent failure
        """
        last_error: Optional[Exception] = None
        retry_count = 0

        # Initial attempt
        try:
            await self._backend.write_events(events)
            return  # Success on first try
        except (TSDBWriteError, Exception) as e:
            last_error = e

        # Retry loop: up to max_retries attempts
        for attempt in range(self._max_retries):
            retry_count = attempt + 1
            delay_ms = self._initial_retry_delay_ms * (2 ** attempt)
            await asyncio.sleep(delay_ms / 1000.0)

            try:
                await self._backend.write_events(events)
                self._retry_attempts_log.append(retry_count)
                return  # Success after retry
            except (TSDBWriteError, Exception) as e:
                last_error = e

        # All retries exhausted - log permanent failure
        self._retry_attempts_log.append(retry_count)
        for event in events:
            failure = WriteFailureLog(
                sensor_id=event.sensor_id,
                timestamp=event.timestamp,
                failure_reason=str(last_error),
                retry_count=self._max_retries,
            )
            self._failure_log.append(failure)
            logger.error(
                "Permanent write failure after retry exhaustion",
                sensor_id=event.sensor_id,
                timestamp=str(event.timestamp),
                failure_reason=str(last_error),
                retry_count=self._max_retries,
            )

    async def query_by_sensor_and_time(
        self,
        sensor_id: str,
        start: datetime,
        end: datetime,
        measurement_type: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """Query events from the TSDB by sensor and time range.

        Returns events ordered chronologically by timestamp.
        """
        return await self._backend.query_by_sensor_and_time(
            sensor_id, start, end, measurement_type
        )

    async def query_by_measurement_type(
        self,
        sensor_ids: List[str],
        measurement_type: str,
        start: datetime,
        end: datetime,
    ) -> List[TelemetryEvent]:
        """Query events from the TSDB by measurement type across sensors.

        Returns events ordered chronologically by timestamp.
        """
        return await self._backend.query_by_measurement_type(
            sensor_ids, measurement_type, start, end
        )
