"""Local Mode entry point for the Digital Twin Telemetry Engine.

Starts the full pipeline in a single asyncio process using in-memory
broker and TSDB backends. No external services (Docker, Kafka, Redis,
InfluxDB) or admin permissions required.

Usage:
    python run_local.py

Components wired:
    - InMemoryBrokerBackend (message transport)
    - InMemoryTSDBBackend (time-series storage)
    - API Gateway (FastAPI on port 8000 with WebSocket support)
    - Broker Subscriber (updates state cache + broadcasts to WebSocket clients)
    - ML Service (BatchAccumulator + Ensemble Inference with stub models)
    - Correction Engine (TemporalMatcher + EnKF)
    - TSDB Consumer (batch writes raw telemetry to TSDB)
    - C-MAPSS Replay Adapter (feeds sensor data into the broker)

Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

# Set RUN_MODE before any other imports so factory functions use in-memory backends
os.environ["RUN_MODE"] = "local"
# Suppress verbose per-event logging; only show warnings and errors
os.environ.setdefault("LOG_LEVEL", "WARNING")

import uvicorn

import structlog

from digital_twin_engine.adapters.cmapss_replay import CMAPSSConfig, CMAPSSReplayAdapter
from digital_twin_engine.adapters.__main__ import fault_injector
from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.broker_subscriber import BrokerSubscriber
from digital_twin_engine.api.engines import configure_engine_services
from digital_twin_engine.api.fault_injection_api import configure_fault_injector
from digital_twin_engine.api.health import register_health_check
from digital_twin_engine.api.simulation_api import configure_simulation_services
from digital_twin_engine.broker import InMemoryBrokerBackend
from digital_twin_engine.broker.topics import TELEMETRY_RAW
from digital_twin_engine.correction.enkf import EnKFIteration
from digital_twin_engine.correction.temporal_matcher import TemporalMatcher
from digital_twin_engine.ml_service.batch_accumulator import BatchAccumulator
from digital_twin_engine.ml_service.ensemble_inference import create_ensemble_predict_fn
from digital_twin_engine.prognostics.component_health import ComponentHealthMapper
from digital_twin_engine.prognostics.degradation_tracker import DegradationCurveTracker
from digital_twin_engine.prognostics.health_index import HealthIndexAggregator
from digital_twin_engine.prognostics.rul_predictor import RULPredictor
from digital_twin_engine.shared.models import ComponentStatus, EngineConfig, StateVector, TelemetryEvent
from digital_twin_engine.shared.models import serialize_telemetry_event
from digital_twin_engine.simulation.fault_injector import FaultInjector
from digital_twin_engine.simulation.failure_prob_cache import FailureProbabilityCache
from digital_twin_engine.simulation.monte_carlo_projector import MonteCarloProjector
from digital_twin_engine.simulation.what_if_simulator import WhatIfSimulator
from digital_twin_engine.tsdb import InMemoryTSDBBackend, TSDBConsumer


# Suppress verbose per-event logs in Local Mode (only ERROR+ will print)
import logging
logging.basicConfig(level=logging.ERROR)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR),
)


def print_banner() -> None:
    """Print the startup banner showing active components and access URLs."""
    banner = """\
═══════════════════════════════════════════════════════════
  DIGITAL TWIN ENGINE — Local Mode
═══════════════════════════════════════════════════════════
  Components:
    ✓ Ingestion Server (in-process)
    ✓ ML Service (LSTM+XGBoost ensemble)
    ✓ Correction Engine (EnKF)
    ✓ TSDB Writer (in-memory)
    ✓ API Gateway (FastAPI)
    ✓ C-MAPSS Adapter (auto-start)
    ✓ WebSocket Broadcast
    ✓ RUL Predictor
    ✓ Health Index Aggregator
    ✓ Degradation Curve Tracker
    ✓ Component Health Mapper
    ✓ Fault Injector
    ✓ Monte Carlo Projector
    ✓ What-If Simulator
    ✓ Failure Probability Cache

  Access:
    API:       http://localhost:8000
    WebSocket: ws://localhost:8000/ws/telemetry
    Health:    http://localhost:8000/health
═══════════════════════════════════════════════════════════"""
    print(banner)


async def run_local() -> None:
    """Start the full pipeline in a single asyncio process.

    Wires all pipeline components using in-memory backends and runs them
    concurrently. The API Gateway is served on port 8000 with uvicorn.
    Handles graceful shutdown on SIGINT/SIGTERM.
    """
    print_banner()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        """Handle SIGINT/SIGTERM by setting the shutdown event."""
        shutdown_event.set()

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM
            pass

    # --- Create in-memory backends ---
    broker = InMemoryBrokerBackend()
    tsdb = InMemoryTSDBBackend()

    await broker.start()
    await tsdb.start()

    # --- Configuration ---
    config = EngineConfig(
        min_batch_size=10,
        max_batch_size=100,
        max_batch_wait_seconds=2.0,
        temporal_tolerance_seconds=5.0,
        anomaly_threshold_sigma=2.5,
        ensemble_size=50,
    )

    # --- Create API Gateway ---
    gateway = APIGateway(tsdb_backend=tsdb)

    # --- Register health checks for Local Mode ---
    # In Local Mode all components are in-process; report HEALTHY when running.
    # Registered immediately after gateway creation so _health_checks dict is
    # populated before any TCP connection can trigger a /health request.
    async def _healthy() -> ComponentStatus:
        return ComponentStatus.HEALTHY

    register_health_check("ingestion_server", _healthy)
    register_health_check("message_broker", _healthy)
    register_health_check("tsdb", _healthy)
    register_health_check("tsdb_writer", _healthy)
    register_health_check("ml_service", _healthy)
    register_health_check("correction_engine", _healthy)

    # --- Create Broker Subscriber (feeds state cache + WebSocket broadcasts) ---
    subscriber = BrokerSubscriber()
    await subscriber.start(broker, gateway.state_cache, gateway.ws_manager, gateway.predictions_cache)

    # --- TSDB Consumer (batch-writes raw telemetry to TSDB) ---
    tsdb_consumer = TSDBConsumer(broker=broker, tsdb_backend=tsdb)
    await tsdb_consumer.start()

    # --- ML Service (ensemble prediction) ---
    ensemble = create_ensemble_predict_fn(config=config)
    accumulator = BatchAccumulator(
        broker=broker,
        config=config,
        predict_fn=ensemble.predict,
        consumer_group="ml-local",
    )
    await accumulator.start()

    # --- Correction Engine (temporal matching + EnKF) ---
    async def tsdb_write_corrected(sv: StateVector) -> None:
        """Write corrected state vector to TSDB."""
        event = TelemetryEvent(
            timestamp=sv.timestamp,
            sensor_id=sv.sensor_id,
            measurement_type="corrected_state",
            value=sv.values[0] if sv.values else 0.0,
        )
        await tsdb.write_events([event])

    enkf = EnKFIteration(broker=broker, tsdb_write_func=tsdb_write_corrected)
    matcher = TemporalMatcher(
        broker=broker,
        config=config,
        on_match=enkf,
        consumer_group="correction-local",
    )
    await matcher.start()

    # --- Digital Twin Prognostics Services ---
    rul_predictor = RULPredictor(broker=broker, ws_manager=gateway.ws_manager)
    await rul_predictor.start()

    degradation_tracker = DegradationCurveTracker(ws_manager=gateway.ws_manager)

    health_index_aggregator = HealthIndexAggregator(
        broker=broker, ws_manager=gateway.ws_manager,
        degradation_tracker=degradation_tracker,
    )
    await health_index_aggregator.start()

    component_health_mapper = ComponentHealthMapper(
        broker=broker, ws_manager=gateway.ws_manager
    )
    await component_health_mapper.start()

    # --- Wire services into API snapshot endpoint ---
    configure_engine_services(
        rul_predictor=rul_predictor,
        health_index_aggregator=health_index_aggregator,
        component_health_mapper=component_health_mapper,
        degradation_tracker=degradation_tracker,
    )

    # --- Wire FaultInjector singleton into the fault injection API ---
    configure_fault_injector(fault_injector)

    # --- Wire Simulation Services (MonteCarloProjector, WhatIfSimulator, FailureProbabilityCache) ---
    monte_carlo_projector = MonteCarloProjector(
        health_index_aggregator=health_index_aggregator,
        degradation_tracker=degradation_tracker,
    )
    what_if_simulator = WhatIfSimulator(projector=monte_carlo_projector)
    failure_prob_cache = FailureProbabilityCache(
        projector=monte_carlo_projector,
        health_index_aggregator=health_index_aggregator,
        degradation_tracker=degradation_tracker,
    )
    configure_simulation_services(
        what_if_simulator=what_if_simulator,
        failure_prob_cache=failure_prob_cache,
    )

    # Start the FailureProbabilityCache background task
    await failure_prob_cache.start()

    # --- C-MAPSS Replay Adapter ---
    async def run_adapter() -> None:
        """Run the C-MAPSS replay adapter, publishing events to the broker.

        If the dataset is not available, logs a warning and exits gracefully.
        """
        data_dir = os.environ.get("CMAPSS_DATA_DIR", "data/cmapss")
        cmapss_config = CMAPSSConfig(
            data_dir=data_dir,
            dataset="FD001",
            split="train",
            engine_ids=[1, 2, 3],
            speed=1.0,
            max_cycles=None,
            loop=True,
        )

        adapter = CMAPSSReplayAdapter(cmapss_config, fault_injector=fault_injector)
        try:
            adapter.load()
        except FileNotFoundError:
            print(
                "[WARN] C-MAPSS dataset not found. "
                "The pipeline is running but no telemetry data will be streamed.\n"
                "       Download with: python download_cmapss.py"
            )
            # Keep alive until shutdown - adapter is optional
            await shutdown_event.wait()
            return

        print(f"[INFO] C-MAPSS adapter loaded: {adapter.summary()}")

        async for event in adapter.stream():
            if shutdown_event.is_set():
                break
            serialized = serialize_telemetry_event(event)
            await broker.publish(
                TELEMETRY_RAW, event.sensor_id, serialized.encode("utf-8")
            )

    # --- Uvicorn Server ---
    uvicorn_config = uvicorn.Config(
        gateway.app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        ws_ping_interval=None,  # Disable WebSocket keepalive pings to prevent timeout crashes
        ws_ping_timeout=None,
    )
    server = uvicorn.Server(uvicorn_config)

    # Override uvicorn's default signal handling - we handle it ourselves
    server.install_signal_handlers = lambda: None

    # --- Run all components concurrently ---
    async def run_server() -> None:
        """Run uvicorn until shutdown is signaled."""
        await server.serve()

    async def wait_for_shutdown() -> None:
        """Wait for shutdown signal, then stop all components."""
        await shutdown_event.wait()
        print("\n[INFO] Shutdown signal received, stopping components...")
        server.should_exit = True

    # Start all concurrent tasks
    tasks = [
        asyncio.create_task(run_server(), name="uvicorn"),
        asyncio.create_task(run_adapter(), name="cmapss-adapter"),
        asyncio.create_task(wait_for_shutdown(), name="shutdown-watcher"),
    ]

    try:
        # Wait until shutdown is signaled or the server stops
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # If only the adapter finished, keep running until shutdown
        remaining_critical = [t for t in pending if t.get_name() in ("uvicorn", "shutdown-watcher")]
        if remaining_critical and all(t.get_name() == "cmapss-adapter" for t in done):
            # Adapter finished (dataset exhausted) - keep server running
            done2, pending2 = await asyncio.wait(remaining_critical, return_when=asyncio.FIRST_COMPLETED)
            pending = pending2

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        # Graceful cleanup
        await failure_prob_cache.stop()
        await rul_predictor.stop()
        await health_index_aggregator.stop()
        await component_health_mapper.stop()
        await accumulator.stop()
        await matcher.stop()
        await tsdb_consumer.stop()
        await subscriber.stop()
        await broker.stop()
        await tsdb.stop()
        print("[INFO] All components stopped. Goodbye!")


if __name__ == "__main__":
    asyncio.run(run_local())
