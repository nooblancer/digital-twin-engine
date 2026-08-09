"""Entrypoint for the TSDB Writer service.

Launches the async consumer that reads from the telemetry.raw broker topic
and writes to the time-series database.
"""

import asyncio
import os

from digital_twin_engine.shared.logging import get_logger

logger = get_logger("tsdb_writer_main")


async def run() -> None:
    """Start the TSDB writer consumer."""
    broker_type = os.environ.get("BROKER_TYPE", "kafka")
    broker_url = os.environ.get("BROKER_URL", "kafka:29092")
    tsdb_type = os.environ.get("TSDB_TYPE", "influxdb")

    batch_size = int(os.environ.get("WRITE_BATCH_SIZE", "100"))
    batch_window_seconds = float(os.environ.get("BATCH_WINDOW_SECONDS", "1.0"))
    max_retries = int(os.environ.get("WRITE_RETRY_COUNT", "3"))

    # Initialize broker backend
    if broker_type == "kafka":
        from digital_twin_engine.broker.kafka_backend import KafkaBrokerBackend

        broker = KafkaBrokerBackend(bootstrap_servers=broker_url)
    else:
        from digital_twin_engine.broker.redis_backend import RedisBrokerBackend

        broker = RedisBrokerBackend(redis_url=broker_url)

    # Initialize TSDB backend
    if tsdb_type == "influxdb":
        from digital_twin_engine.tsdb.influxdb_backend import InfluxDBBackend

        influx_url = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
        influx_token = os.environ.get("INFLUXDB_TOKEN", "dev-token-digital-twin")
        influx_org = os.environ.get("INFLUXDB_ORG", "digital-twin")
        influx_bucket = os.environ.get("INFLUXDB_BUCKET", "telemetry")

        tsdb_backend = InfluxDBBackend(
            url=influx_url,
            token=influx_token,
            org=influx_org,
            bucket=influx_bucket,
        )
    else:
        # TimescaleDB - placeholder for asyncpg-based backend
        raise NotImplementedError("TimescaleDB backend not yet wired for Docker service")

    # Initialize consumer
    from digital_twin_engine.tsdb.consumer import TSDBConsumer

    consumer = TSDBConsumer(
        broker=broker,
        tsdb_backend=tsdb_backend,
        batch_size=batch_size,
        batch_window_seconds=batch_window_seconds,
        max_retries=max_retries,
    )

    await broker.start()
    await consumer.start()

    logger.info(
        "TSDB writer service started",
        broker_type=broker_type,
        broker_url=broker_url,
        tsdb_type=tsdb_type,
        batch_size=batch_size,
    )

    # Run until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await consumer.stop()
        await broker.stop()
        logger.info("TSDB writer service stopped")


def main() -> None:
    """Entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
