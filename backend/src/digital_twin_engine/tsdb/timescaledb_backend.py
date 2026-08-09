"""TimescaleDB async backend for the TSDB Writer.

Implements the TSDBBackend protocol using asyncpg for database connections.
Writes telemetry events as time-series rows in a TimescaleDB hypertable.

Validates: Requirements 11.1, 11.2, 11.3, 11.4
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import asyncpg

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import TelemetryEvent
from digital_twin_engine.tsdb.writer import TSDBBackend, TSDBWriteError

logger = get_logger("tsdb_timescaledb")

# ---------------------------------------------------------------------------
# SQL Statements
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telemetry (
    time            TIMESTAMPTZ NOT NULL,
    sensor_id       TEXT NOT NULL,
    measurement_type TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL
);
"""

CREATE_HYPERTABLE_SQL = """
SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_telemetry_sensor_time
    ON telemetry (sensor_id, time DESC);
"""

INSERT_SQL = """
INSERT INTO telemetry (time, sensor_id, measurement_type, value)
VALUES ($1, $2, $3, $4);
"""

QUERY_BY_SENSOR_AND_TIME_SQL = """
SELECT time, sensor_id, measurement_type, value
FROM telemetry
WHERE sensor_id = $1 AND time >= $2 AND time <= $3
ORDER BY time ASC;
"""

QUERY_BY_SENSOR_AND_TIME_WITH_TYPE_SQL = """
SELECT time, sensor_id, measurement_type, value
FROM telemetry
WHERE sensor_id = $1 AND time >= $2 AND time <= $3 AND measurement_type = $4
ORDER BY time ASC;
"""

QUERY_BY_MEASUREMENT_TYPE_SQL = """
SELECT time, sensor_id, measurement_type, value
FROM telemetry
WHERE sensor_id = ANY($1) AND measurement_type = $2 AND time >= $3 AND time <= $4
ORDER BY time ASC;
"""

# ---------------------------------------------------------------------------
# Retry Configuration (consistent with InfluxDB backend / TSDBWriter)
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_INITIAL_RETRY_DELAY_MS = 100


# ---------------------------------------------------------------------------
# TimescaleDB Backend
# ---------------------------------------------------------------------------


class TimescaleDBBackend:
    """TimescaleDB async backend implementing the TSDBBackend protocol.

    Connects to a TimescaleDB (PostgreSQL) instance and writes TelemetryEvent
    data as time-series rows. Uses asyncpg for async database access.

    Retry behavior on connection failure is consistent with the InfluxDB backend:
    - Initial retry delay: 100ms
    - Max retries: 3
    - Exponential backoff (100ms, 200ms, 400ms)

    Args:
        host: Database host address.
        port: Database port (default 5432).
        database: Database name.
        user: Database user.
        password: Database password.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "telemetry",
        user: str = "postgres",
        password: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self) -> None:
        """Initialize the asyncpg connection pool and create hypertables.

        Creates the telemetry table, hypertable, and indexes if they do not
        already exist. Retries connection with exponential backoff on failure.

        Raises:
            TSDBWriteError: If connection cannot be established after retries.
        """
        await self._connect_with_retry()

        # Create schema
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(CREATE_TABLE_SQL)
            await conn.execute(CREATE_HYPERTABLE_SQL)
            await conn.execute(CREATE_INDEX_SQL)

        logger.info(
            "TimescaleDB backend started",
            host=self._host,
            port=self._port,
            database=self._database,
        )

    async def stop(self) -> None:
        """Close the database connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("TimescaleDB backend stopped")

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Write a batch of TelemetryEvents to TimescaleDB.

        Uses asyncpg's executemany for efficient batch inserts.

        Raises:
            TSDBWriteError: If the write operation fails.
        """
        if self._pool is None:
            raise TSDBWriteError(
                "TimescaleDB pool not initialized - call start() first",
                sensor_id=events[0].sensor_id if events else "",
                timestamp=str(events[0].timestamp) if events else "",
            )

        rows = [
            (
                e.timestamp.astimezone(timezone.utc),
                e.sensor_id,
                e.measurement_type,
                e.value,
            )
            for e in events
        ]

        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(INSERT_SQL, rows)
        except Exception as e:
            sensor_id = events[0].sensor_id if events else ""
            timestamp = str(events[0].timestamp) if events else ""
            raise TSDBWriteError(
                f"TimescaleDB write failed: {e}",
                sensor_id=sensor_id,
                timestamp=timestamp,
            ) from e

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
        if self._pool is None:
            raise TSDBWriteError(
                "TimescaleDB pool not initialized - call start() first",
            )

        try:
            async with self._pool.acquire() as conn:
                if measurement_type is not None:
                    rows = await conn.fetch(
                        QUERY_BY_SENSOR_AND_TIME_WITH_TYPE_SQL,
                        sensor_id,
                        start,
                        end,
                        measurement_type,
                    )
                else:
                    rows = await conn.fetch(
                        QUERY_BY_SENSOR_AND_TIME_SQL,
                        sensor_id,
                        start,
                        end,
                    )
        except Exception as e:
            raise TSDBWriteError(
                f"TimescaleDB query failed: {e}",
                sensor_id=sensor_id,
                timestamp=str(start),
            ) from e

        return [self._row_to_event(row) for row in rows]

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
        if self._pool is None:
            raise TSDBWriteError(
                "TimescaleDB pool not initialized - call start() first",
            )

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    QUERY_BY_MEASUREMENT_TYPE_SQL,
                    sensor_ids,
                    measurement_type,
                    start,
                    end,
                )
        except Exception as e:
            raise TSDBWriteError(
                f"TimescaleDB query failed: {e}",
                sensor_id=sensor_ids[0] if sensor_ids else "",
                timestamp=str(start),
            ) from e

        return [self._row_to_event(row) for row in rows]

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _connect_with_retry(self) -> None:
        """Create asyncpg connection pool with exponential backoff retry.

        Retry strategy (consistent with InfluxDB backend / TSDBWriter):
        - Attempt 0: initial connection attempt
        - Attempt 1: retry after 100ms
        - Attempt 2: retry after 200ms
        - Attempt 3: retry after 400ms
        - After attempt 3 fails: raise TSDBWriteError
        """
        last_error: Optional[Exception] = None

        # Initial attempt
        try:
            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                min_size=2,
                max_size=10,
            )
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "TimescaleDB connection failed, will retry",
                host=self._host,
                error=str(e),
            )

        # Retry loop
        for attempt in range(_MAX_RETRIES):
            delay_ms = _INITIAL_RETRY_DELAY_MS * (2**attempt)
            await asyncio.sleep(delay_ms / 1000.0)

            try:
                self._pool = await asyncpg.create_pool(
                    host=self._host,
                    port=self._port,
                    database=self._database,
                    user=self._user,
                    password=self._password,
                    min_size=2,
                    max_size=10,
                )
                logger.info(
                    "TimescaleDB connection established after retry",
                    attempt=attempt + 1,
                )
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    "TimescaleDB connection retry failed",
                    attempt=attempt + 1,
                    max_retries=_MAX_RETRIES,
                    error=str(e),
                )

        # All retries exhausted
        raise TSDBWriteError(
            f"TimescaleDB connection failed after {_MAX_RETRIES} retries: {last_error}",
        )

    @staticmethod
    def _row_to_event(row: asyncpg.Record) -> TelemetryEvent:
        """Convert a database row to a TelemetryEvent."""
        ts = row["time"]
        # Ensure timezone-aware UTC
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return TelemetryEvent(
            timestamp=ts,
            sensor_id=row["sensor_id"],
            measurement_type=row["measurement_type"],
            value=float(row["value"]),
        )
