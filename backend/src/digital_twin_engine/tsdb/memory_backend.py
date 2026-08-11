"""In-Memory TSDB Backend with lifecycle management.

Provides a standalone in-memory implementation of the TSDBBackend protocol
with proper start/stop lifecycle methods, suitable for testing and development.

Validates: Requirements 12.3, 13.2, 13.4
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import TelemetryEvent
from digital_twin_engine.tsdb.writer import TSDBWriteError

logger = get_logger("tsdb_memory_backend")


class InMemoryTSDBBackend:
    """In-memory TSDB implementation with lifecycle management.

    Stores events in a list and supports temporal/sensor queries.
    Thread-safe for asyncio (single-threaded event loop).

    Lifecycle:
        backend = InMemoryTSDBBackend()
        await backend.start()
        # ... use backend ...
        await backend.stop()
    """

    def __init__(self, fail_writes: bool = False, max_events: int = 50000) -> None:
        self._events: List[TelemetryEvent] = []
        self._fail_writes = fail_writes
        self._max_events = max_events
        self._write_call_count = 0
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the in-memory backend for operation.

        Must be called before any read/write operations.
        """
        self._running = True
        logger.info("InMemoryTSDBBackend started")

    async def stop(self) -> None:
        """Gracefully shut down the backend and release resources."""
        self._running = False
        logger.info("InMemoryTSDBBackend stopped")

    @property
    def running(self) -> bool:
        """Whether the backend is currently running."""
        return self._running

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def events(self) -> List[TelemetryEvent]:
        """Access all stored events."""
        return list(self._events)

    @property
    def write_call_count(self) -> int:
        """Number of write_events calls made."""
        return self._write_call_count

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_fail_writes(self, fail: bool) -> None:
        """Toggle write failure simulation."""
        self._fail_writes = fail

    # ------------------------------------------------------------------
    # TSDBBackend Protocol Implementation
    # ------------------------------------------------------------------

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Write events to in-memory storage.

        Raises TSDBWriteError if fail_writes is True.
        Evicts oldest events when max_events limit is reached.
        """
        self._write_call_count += 1
        if self._fail_writes:
            raise TSDBWriteError(
                "Simulated TSDB write failure",
                sensor_id=events[0].sensor_id if events else "",
                timestamp=str(events[0].timestamp) if events else "",
            )
        self._events.extend(events)
        # Evict oldest events if over limit
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    async def query_by_sensor_and_time(
        self,
        sensor_id: str,
        start: datetime,
        end: datetime,
        measurement_type: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """Query events by sensor and time range.

        Args:
            sensor_id: The sensor identifier to query.
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).
            measurement_type: Optional filter by measurement type.

        Returns:
            List of TelemetryEvents matching criteria, ordered chronologically.
        """
        results = [
            e
            for e in self._events
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
        """Query events by measurement type across multiple sensors.

        Args:
            sensor_ids: List of sensor identifiers (up to 100).
            measurement_type: The measurement type to filter by.
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).

        Returns:
            List of TelemetryEvents matching criteria, ordered chronologically.
        """
        results = [
            e
            for e in self._events
            if e.sensor_id in sensor_ids
            and e.measurement_type == measurement_type
            and start <= e.timestamp <= end
        ]
        return sorted(results, key=lambda e: e.timestamp)
