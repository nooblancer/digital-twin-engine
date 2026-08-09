"""TSDB writer - Time-series database persistence service.

Provides the TSDBWriter for consuming TelemetryEvents from the message broker
and persisting them to a time-series database (InfluxDB or TimescaleDB).

Key features:
- Async consumer reading from `telemetry.raw` topic
- Batch writes for efficiency (configurable batch size or time window)
- Retry with exponential backoff on write failure (100ms initial, 3 retries)
- Permanent failure logging with sensor_id, timestamp, and failure reason
- Temporal range queries by sensor_id and measurement_type
"""

from digital_twin_engine.tsdb.consumer import TSDBConsumer, TSDB_CONSUMER_GROUP
from digital_twin_engine.tsdb.writer import TSDBWriter, TSDBWriteError, WriteFailureLog

__all__ = [
    "TSDB_CONSUMER_GROUP",
    "TSDBConsumer",
    "TSDBWriteError",
    "TSDBWriter",
    "WriteFailureLog",
]
