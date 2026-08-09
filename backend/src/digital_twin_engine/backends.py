"""Backend factory module for dual-mode deployment support.

Provides factory functions that create the appropriate BrokerBackend and
TSDBBackend instances based on environment variables. Enables the same
pipeline code to run in both Local Mode (in-memory backends) and Docker
Mode (Kafka, InfluxDB, TimescaleDB) without modification.

Resolution order:
1. RUN_MODE=local overrides all other settings → in-memory backends
2. BROKER_TYPE / TSDB_TYPE env vars select the concrete implementation
3. Optional string parameter overrides the env var (for testability)

Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

import os

from digital_twin_engine.broker import (
    BrokerBackend,
    InMemoryBrokerBackend,
    KafkaBrokerBackend,
    RedisBrokerBackend,
)
from digital_twin_engine.tsdb import InMemoryTSDBBackend
from digital_twin_engine.tsdb.writer import TSDBBackend

# Valid broker type identifiers
VALID_BROKER_TYPES = ("memory", "kafka", "redis")

# Valid TSDB type identifiers
VALID_TSDB_TYPES = ("memory", "influxdb", "timescaledb")


def create_broker(broker_type: str | None = None) -> BrokerBackend:
    """Factory that returns the appropriate BrokerBackend.

    Resolution order:
    1. If RUN_MODE=local env var is set, always return InMemoryBrokerBackend
    2. Otherwise use broker_type parameter (or BROKER_TYPE env var):
       - "memory" → InMemoryBrokerBackend
       - "kafka"  → KafkaBrokerBackend
       - "redis"  → RedisBrokerBackend
    3. Raise ValueError for unrecognized types

    Args:
        broker_type: Override for BROKER_TYPE env var. If None, reads env.

    Returns:
        Configured BrokerBackend instance (not yet started).

    Raises:
        ValueError: If broker_type is not one of the recognized values.
    """
    # RUN_MODE=local takes highest precedence
    if os.environ.get("RUN_MODE", "").lower() == "local":
        return InMemoryBrokerBackend()

    # Resolve the effective broker type
    effective_type = broker_type if broker_type is not None else os.environ.get("BROKER_TYPE", "")
    effective_type = effective_type.lower().strip()

    if effective_type == "memory":
        return InMemoryBrokerBackend()
    elif effective_type == "kafka":
        return KafkaBrokerBackend(
            bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        )
    elif effective_type == "redis":
        return RedisBrokerBackend(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
        )
    else:
        valid_options = ", ".join(f"'{t}'" for t in VALID_BROKER_TYPES)
        raise ValueError(
            f"Unrecognized broker type: '{effective_type}'. "
            f"Valid options are: {valid_options}"
        )


def create_tsdb(tsdb_type: str | None = None) -> TSDBBackend:
    """Factory that returns the appropriate TSDBBackend.

    Resolution order:
    1. If RUN_MODE=local env var is set, always return InMemoryTSDBBackend
    2. Otherwise use tsdb_type parameter (or TSDB_TYPE env var):
       - "memory"      → InMemoryTSDBBackend
       - "influxdb"    → InfluxDBBackend
       - "timescaledb" → TimescaleDBBackend
    3. Raise ValueError for unrecognized types

    Args:
        tsdb_type: Override for TSDB_TYPE env var. If None, reads env.

    Returns:
        Configured TSDBBackend instance (not yet started).

    Raises:
        ValueError: If tsdb_type is not one of the recognized values.
    """
    # RUN_MODE=local takes highest precedence
    if os.environ.get("RUN_MODE", "").lower() == "local":
        return InMemoryTSDBBackend()

    # Resolve the effective TSDB type
    effective_type = tsdb_type if tsdb_type is not None else os.environ.get("TSDB_TYPE", "")
    effective_type = effective_type.lower().strip()

    if effective_type == "memory":
        return InMemoryTSDBBackend()
    elif effective_type == "influxdb":
        # Lazy import — influxdb-client may not be installed in all environments
        from digital_twin_engine.tsdb.influxdb_backend import InfluxDBBackend

        return InfluxDBBackend(
            url=os.environ.get("INFLUXDB_URL", "http://localhost:8086"),
            token=os.environ.get("INFLUXDB_TOKEN", ""),
            org=os.environ.get("INFLUXDB_ORG", ""),
            bucket=os.environ.get("INFLUXDB_BUCKET", "telemetry"),
        )
    elif effective_type == "timescaledb":
        # Lazy import — TimescaleDB backend module may not exist yet
        from digital_twin_engine.tsdb.timescaledb_backend import TimescaleDBBackend

        return TimescaleDBBackend(
            host=os.environ.get("TIMESCALEDB_HOST", "localhost"),
            port=int(os.environ.get("TIMESCALEDB_PORT", "5432")),
            database=os.environ.get("TIMESCALEDB_DATABASE", "telemetry"),
            user=os.environ.get("TIMESCALEDB_USER", "postgres"),
            password=os.environ.get("TIMESCALEDB_PASSWORD", ""),
        )
    else:
        valid_options = ", ".join(f"'{t}'" for t in VALID_TSDB_TYPES)
        raise ValueError(
            f"Unrecognized TSDB type: '{effective_type}'. "
            f"Valid options are: {valid_options}"
        )
