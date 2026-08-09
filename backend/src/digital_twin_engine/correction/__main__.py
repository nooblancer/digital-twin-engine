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

    # Start Prometheus metrics server
    from digital_twin_engine.correction.metrics import (
        correction_iterations_total,
        messages_processed_total,
        start_metrics_server,
    )

    start_metrics_server()
    logger.info("Prometheus metrics server started", port=int(os.environ.get("CORRECTION_METRICS_PORT", "9091")))

    # Initialize broker backend
    if broker_type == "kafka":
        from digital_twin_engine.broker.kafka_backend import KafkaBrokerBackend

        broker = KafkaBrokerBackend(bootstrap_servers=broker_url)
    else:
        from digital_twin_engine.broker.redis_backend import RedisBrokerBackend

        broker = RedisBrokerBackend(redis_url=broker_url)

    # Initialize EnKF iteration handler
    from digital_twin_engine.correction.enkf import EnKFIteration

    enkf_iteration_handler = EnKFIteration(broker=broker)

    # Wrap the EnKF iteration handler to instrument with Prometheus metrics
    async def instrumented_on_match(matched_pair, enkf_state):
        await enkf_iteration_handler(matched_pair, enkf_state)
        correction_iterations_total.inc()

    # Initialize temporal matcher with instrumented callback
    from digital_twin_engine.correction.temporal_matcher import TemporalMatcher

    # Wrap broker subscribe to increment messages_processed_total
    original_subscribe = broker.subscribe

    async def instrumented_subscribe(topic, group_id, callback):
        async def wrapped_callback(t, k, m):
            messages_processed_total.inc()
            await callback(t, k, m)

        await original_subscribe(topic, group_id, wrapped_callback)

    broker.subscribe = instrumented_subscribe  # type: ignore[assignment]

    matcher = TemporalMatcher(
        broker=broker,
        config=config,
        on_match=instrumented_on_match,
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
