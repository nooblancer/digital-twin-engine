"""Entrypoint for the ML Service.

Launches the batch accumulator consumer that reads from the telemetry.raw
broker topic, accumulates per-sensor batches, and generates predictions
using the LSTM+XGBoost ensemble.
"""

import asyncio
import os
import time

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import EngineConfig

logger = get_logger("ml_service_main")


async def run() -> None:
    """Start the ML Service consumer."""
    broker_type = os.environ.get("BROKER_TYPE", "kafka")
    broker_url = os.environ.get("BROKER_URL", "kafka:29092")

    config = EngineConfig(
        min_batch_size=int(os.environ.get("MIN_BATCH_SIZE", "10")),
        max_batch_size=int(os.environ.get("MAX_BATCH_SIZE", "500")),
        max_batch_wait_seconds=float(os.environ.get("MAX_BATCH_WAIT_SECONDS", "5.0")),
        prediction_horizon_seconds=float(os.environ.get("PREDICTION_HORIZON_SECONDS", "60.0")),
        lstm_weight=float(os.environ.get("LSTM_WEIGHT", "0.6")),
        xgboost_weight=float(os.environ.get("XGBOOST_WEIGHT", "0.4")),
    )

    # Start Prometheus metrics server
    from digital_twin_engine.ml_service.metrics import (
        inference_latency_seconds,
        messages_processed_total,
        start_metrics_server,
    )

    start_metrics_server()
    logger.info("Prometheus metrics server started", port=int(os.environ.get("ML_METRICS_PORT", "9090")))

    # Initialize broker backend
    if broker_type == "kafka":
        from digital_twin_engine.broker.kafka_backend import KafkaBrokerBackend

        broker = KafkaBrokerBackend(bootstrap_servers=broker_url)
    else:
        from digital_twin_engine.broker.redis_backend import RedisBrokerBackend

        broker = RedisBrokerBackend(redis_url=broker_url)

    # Load ML models (falls back to stubs if files are missing or corrupted)
    from digital_twin_engine.ml_service.ensemble_inference import EnsembleInference
    from digital_twin_engine.ml_service.model_loader import ModelLoader

    loader = ModelLoader()
    lstm_model, xgboost_model = loader.load_all()
    inference = EnsembleInference(
        lstm_model=lstm_model,
        xgboost_model=xgboost_model,
        config=config,
    )

    # Prediction function for the batch accumulator with metrics instrumentation
    async def predict_fn(sensor_id, events, cfg):
        messages_processed_total.inc()
        start = time.perf_counter()
        result = await inference.predict(sensor_id, events, cfg)
        elapsed = time.perf_counter() - start
        inference_latency_seconds.observe(elapsed)
        return result

    # Initialize batch accumulator
    from digital_twin_engine.ml_service.batch_accumulator import BatchAccumulator

    accumulator = BatchAccumulator(
        broker=broker,
        config=config,
        predict_fn=predict_fn,
        consumer_group="ml-service-group",
    )

    await broker.start()
    await accumulator.start()

    logger.info(
        "ML service started",
        broker_type=broker_type,
        broker_url=broker_url,
        min_batch_size=config.min_batch_size,
        max_batch_wait_seconds=config.max_batch_wait_seconds,
        lstm_weight=config.lstm_weight,
        xgboost_weight=config.xgboost_weight,
    )

    # Run until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await accumulator.stop()
        await broker.stop()
        logger.info("ML service stopped")


def main() -> None:
    """Entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
