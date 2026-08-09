"""Entrypoint for the Correction Engine service.

Launches the temporal matcher and EnKF iteration consumer that reads from
both the predictions.state and telemetry.raw topics, matches predictions
to observations, and runs the Ensemble Kalman Filter.
"""

import asyncio
import os

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import EngineConfig

logger = get_logger("correction_engine_main")


async def run() -> None:
    """Start the Correction Engine service."""
    broker_type = os.environ.get("BROKER_TYPE", "kafka")
    broker_url = os.environ.get("BROKER_URL", "kafka:29092")

    config = EngineConfig(
        ensemble_size=int(os.environ.get("ENSEMBLE_SIZE", "50")),
        temporal_tolerance_seconds=float(os.environ.get("TEMPORAL_TOLERANCE_SECONDS", "1.0")),
        anomaly_threshold_sigma=float(os.environ.get("ANOMALY_THRESHOLD_SIGMA", "3.0")),
    )

    # Initialize broker backend
    if broker_type == "kafka":
        from digital_twin_engine.broker.kafka_backend import KafkaBrokerBackend

        broker = KafkaBrokerBackend(bootstrap_servers=broker_url)
    else:
        from digital_twin_engine.broker.redis_backend import RedisBrokerBackend

        broker = RedisBrokerBackend(redis_url=broker_url)

    # Initialize EnKF iteration handler
    from digital_twin_engine.correction.enkf import EnKFIteration

    enkf_iteration = EnKFIteration(broker=broker)

    # Initialize temporal matcher
    from digital_twin_engine.correction.temporal_matcher import TemporalMatcher

    matcher = TemporalMatcher(
        broker=broker,
        config=config,
        on_match=enkf_iteration,
        consumer_group="correction-engine-group",
    )

    await broker.start()
    await matcher.start()

    logger.info(
        "Correction Engine started",
        broker_type=broker_type,
        broker_url=broker_url,
        ensemble_size=config.ensemble_size,
        temporal_tolerance_seconds=config.temporal_tolerance_seconds,
        anomaly_threshold_sigma=config.anomaly_threshold_sigma,
    )

    # Run until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await matcher.stop()
        await broker.stop()
        logger.info("Correction Engine stopped")


def main() -> None:
    """Entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
