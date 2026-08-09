"""InfluxDB async backend for the TSDB Writer.

Implements the TSDBBackend protocol using the influxdb-client async API.
Writes telemetry events as InfluxDB points with:
- Measurement: "telemetry"
- Tags: sensor_id, measurement_type
- Fields: value
- Time: event timestamp

Validates: Requirements 4.1, 4.5, 4.6
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from influxdb_client import Point, WritePrecision
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.write_api_async import WriteApiAsync

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import TelemetryEvent
from digital_twin_engine.tsdb.writer import TSDBBackend, TSDBWriteError

logger = get_logger("tsdb_influxdb")

# Default measurement name for telemetry data in InfluxDB
INFLUXDB_MEASUREMENT = "telemetry"


class InfluxDBBackend:
    """InfluxDB async backend implementing the TSDBBackend protocol.

    Connects to an InfluxDB instance and writes TelemetryEvent data as
    time-series points. Reads support temporal and measurement-type queries.

    Args:
        url: InfluxDB server URL (e.g., "http://localhost:8086").
        token: Authentication token for the InfluxDB instance.
        org: Organization name in InfluxDB.
        bucket: Target bucket for writes and queries.
    """

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
    ) -> None:
        self._url = url
        self._token = token
        self._org = org
        self._bucket = bucket
        self._client: Optional[InfluxDBClientAsync] = None

    async def start(self) -> None:
        """Initialize the async InfluxDB client."""
        self._client = InfluxDBClientAsync(
            url=self._url,
            token=self._token,
            org=self._org,
        )
        logger.info(
            "InfluxDB backend started",
            url=self._url,
            org=self._org,
            bucket=self._bucket,
        )

    async def stop(self) -> None:
        """Close the InfluxDB client connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.info("InfluxDB backend stopped")

    def _event_to_point(self, event: TelemetryEvent) -> Point:
        """Convert a TelemetryEvent to an InfluxDB Point.

        Structure:
        - measurement: "telemetry"
        - tags: sensor_id, measurement_type
        - fields: value (float64)
        - time: event timestamp (nanosecond precision)
        """
        point = (
            Point(INFLUXDB_MEASUREMENT)
            .tag("sensor_id", event.sensor_id)
            .tag("measurement_type", event.measurement_type)
            .field("value", event.value)
            .time(event.timestamp, WritePrecision.NS)
        )
        return point

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Write a batch of TelemetryEvents to InfluxDB.

        Converts each event to an InfluxDB Point and writes the batch
        using the async write API. Preserves all original field values
        without modification.

        Raises:
            TSDBWriteError: If the write operation fails.
        """
        if self._client is None:
            raise TSDBWriteError(
                "InfluxDB client not initialized - call start() first",
                sensor_id=events[0].sensor_id if events else "",
                timestamp=str(events[0].timestamp) if events else "",
            )

        points = [self._event_to_point(event) for event in events]

        try:
            write_api: WriteApiAsync = self._client.write_api()
            await write_api.write(
                bucket=self._bucket,
                org=self._org,
                record=points,
                write_precision=WritePrecision.NS,
            )
        except Exception as e:
            sensor_id = events[0].sensor_id if events else ""
            timestamp = str(events[0].timestamp) if events else ""
            raise TSDBWriteError(
                f"InfluxDB write failed: {e}",
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
        """Query events by sensor_id within a time range from InfluxDB.

        Uses Flux query language to filter by sensor_id, time range,
        and optionally measurement_type.

        Returns:
            List of TelemetryEvents ordered chronologically by timestamp.
        """
        if self._client is None:
            raise TSDBWriteError(
                "InfluxDB client not initialized - call start() first"
            )

        # Build Flux query
        start_str = start.isoformat()
        end_str = end.isoformat()

        measurement_filter = ""
        if measurement_type is not None:
            measurement_filter = (
                f'  |> filter(fn: (r) => r["measurement_type"] == "{measurement_type}")\n'
            )

        flux_query = (
            f'from(bucket: "{self._bucket}")\n'
            f"  |> range(start: {start_str}, stop: {end_str})\n"
            f'  |> filter(fn: (r) => r["_measurement"] == "{INFLUXDB_MEASUREMENT}")\n'
            f'  |> filter(fn: (r) => r["sensor_id"] == "{sensor_id}")\n'
            f"{measurement_filter}"
            f'  |> filter(fn: (r) => r["_field"] == "value")\n'
            f"  |> sort(columns: [\"_time\"])\n"
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(flux_query, org=self._org)

            results: List[TelemetryEvent] = []
            for table in tables:
                for record in table.records:
                    event = TelemetryEvent(
                        timestamp=record.get_time().replace(tzinfo=timezone.utc),
                        sensor_id=record.values.get("sensor_id", ""),
                        measurement_type=record.values.get("measurement_type", ""),
                        value=float(record.get_value()),
                    )
                    results.append(event)

            return sorted(results, key=lambda e: e.timestamp)
        except Exception as e:
            raise TSDBWriteError(
                f"InfluxDB query failed: {e}",
                sensor_id=sensor_id,
                timestamp=start_str,
            ) from e

    async def query_by_measurement_type(
        self,
        sensor_ids: List[str],
        measurement_type: str,
        start: datetime,
        end: datetime,
    ) -> List[TelemetryEvent]:
        """Query events by measurement type across multiple sensors.

        Uses Flux query to filter by measurement_type and a set of
        sensor_ids within the specified time range.

        Returns:
            List of TelemetryEvents ordered chronologically by timestamp.
        """
        if self._client is None:
            raise TSDBWriteError(
                "InfluxDB client not initialized - call start() first"
            )

        start_str = start.isoformat()
        end_str = end.isoformat()

        # Build sensor_id filter using Flux 'contains' function
        sensor_filter_values = ", ".join(f'"{sid}"' for sid in sensor_ids)
        sensor_filter = (
            f'  |> filter(fn: (r) => contains(value: r["sensor_id"], '
            f"set: [{sensor_filter_values}]))\n"
        )

        flux_query = (
            f'from(bucket: "{self._bucket}")\n'
            f"  |> range(start: {start_str}, stop: {end_str})\n"
            f'  |> filter(fn: (r) => r["_measurement"] == "{INFLUXDB_MEASUREMENT}")\n'
            f'  |> filter(fn: (r) => r["measurement_type"] == "{measurement_type}")\n'
            f"{sensor_filter}"
            f'  |> filter(fn: (r) => r["_field"] == "value")\n'
            f"  |> sort(columns: [\"_time\"])\n"
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(flux_query, org=self._org)

            results: List[TelemetryEvent] = []
            for table in tables:
                for record in table.records:
                    event = TelemetryEvent(
                        timestamp=record.get_time().replace(tzinfo=timezone.utc),
                        sensor_id=record.values.get("sensor_id", ""),
                        measurement_type=record.values.get("measurement_type", ""),
                        value=float(record.get_value()),
                    )
                    results.append(event)

            return sorted(results, key=lambda e: e.timestamp)
        except Exception as e:
            raise TSDBWriteError(
                f"InfluxDB query failed: {e}",
                sensor_id=sensor_ids[0] if sensor_ids else "",
                timestamp=start_str,
            ) from e
