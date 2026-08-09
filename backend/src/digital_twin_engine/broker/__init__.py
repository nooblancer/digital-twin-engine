"""Message broker integration - Kafka/Redis/In-Memory pub-sub routing layer.

Provides an abstract broker interface with three backends:
- KafkaBrokerBackend: Production-grade, durable, partitioned messaging
- RedisBrokerBackend: Lightweight Pub/Sub for local development
- InMemoryBrokerBackend: Zero-dependency in-process broker for Local Mode and testing

Usage:
    from digital_twin_engine.broker import (
        BrokerBackend,
        InMemoryBrokerBackend,
        KafkaBrokerBackend,
        RedisBrokerBackend,
        TELEMETRY_RAW,
    )

    # Production
    broker = KafkaBrokerBackend(bootstrap_servers="kafka:9092")

    # Development (Redis)
    broker = RedisBrokerBackend(redis_url="redis://localhost:6379")

    # Local Mode (in-memory)
    broker = InMemoryBrokerBackend()

    await broker.start()
    await broker.publish(TELEMETRY_RAW, sensor_id, payload)
    await broker.stop()
"""

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.kafka_backend import (
    BACKPRESSURE_LAG_THRESHOLD,
    DEFAULT_RETENTION_MS,
    KafkaBrokerBackend,
)
from digital_twin_engine.broker.memory_backend import InMemoryBrokerBackend
from digital_twin_engine.broker.redis_backend import RedisBrokerBackend
from digital_twin_engine.broker.topics import (
    ALERTS_ANOMALY,
    ALL_TOPICS,
    CORRECTIONS_STATE,
    METRICS_PIPELINE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)

__all__ = [
    "ALERTS_ANOMALY",
    "ALL_TOPICS",
    "BACKPRESSURE_LAG_THRESHOLD",
    "BrokerBackend",
    "CORRECTIONS_STATE",
    "DEFAULT_RETENTION_MS",
    "InMemoryBrokerBackend",
    "KafkaBrokerBackend",
    "METRICS_PIPELINE",
    "MessageCallback",
    "PREDICTIONS_STATE",
    "RedisBrokerBackend",
    "TELEMETRY_RAW",
]
