"""Entrypoint for the TSDB Writer service.

Launches the async consumer that reads from the telemetry.raw broker topic
and writes to the time-series database.

Uses the backend factory functions (create_broker, create_tsdb) for backend
selection based on environment variables, supporting InfluxDB, TimescaleDB,
and in-memory backends without code changes.

Validates: Requirements 11.1, 13.4
"""

import asyncio
import os

from digital_twin_engine.backends import create_broker, create_tsdb
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("tsdb_writer_main")


async def run() -> None:
    """Start the TSDB writer consumer."""
    batch_size = int(os.environ.get("WRITE_BATCH_SIZE", "100"))
    batch_window_seconds = float(os.environ.get("BATCH_WINDOW_SECONDS", "1.0"))
    max_retries = int(os.environ.get("WRITE_RETRY_COUNT", "3"))

    # Use factory functions for backend selection based on env vars
    broker = create_broker()
    tsdb_backend = create_tsdb()

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
    await tsdb_backend.start()
    await consumer.start()

    broker_type = os.environ.get("BROKER_TYPE", "memory")
    tsdb_type = os.environ.get("TSDB_TYPE", "memory")

    logger.info(
        "TSDB writer service started",
        broker_type=broker_type,
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
        await tsdb_backend.stop()
        await broker.stop()
        logger.info("TSDB writer service stopped")


def main() -> None:
    """Entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
