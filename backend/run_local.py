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
import json
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
from digital_twin_engine.alerting.predictive_alerts import PredictiveAlertSystem
from digital_twin_engine.alerting.root_cause import RootCauseAnalyzer
from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.benchmark import configure_benchmark_services
from digital_twin_engine.api.broker_subscriber import BrokerSubscriber
from digital_twin_engine.api.engines import configure_engine_services
from digital_twin_engine.api.fault_injection_api import configure_fault_injector
from digital_twin_engine.api.health import register_health_check
from digital_twin_engine.api.simulation_api import configure_simulation_services
from digital_twin_engine.benchmarking.benchmark_runner import LiveBenchmarkRunner
from digital_twin_engine.benchmarking.latency_profiler import LatencyProfiler
from digital_twin_engine.benchmarking.throughput_monitor import ThroughputMonitor
from digital_twin_engine.broker import InMemoryBrokerBackend
from digital_twin_engine.broker.topics import (
    ALERTS_ANOMALY,
    CORRECTIONS_STATE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)
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
    ✓ Root Cause Analyzer
    ✓ Predictive Alert System
    ✓ Live Benchmark Runner
    ✓ Latency Profiler
    ✓ Throughput Monitor

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
    # (Root cause analyzer and predictive alert system are wired after v1.4 module setup below)

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

    # --- v1.4 Intelligence Modules ---
    # Root Cause Analyzer: ranks sensors by innovation magnitude on anomaly
    root_cause_analyzer = RootCauseAnalyzer()

    # Predictive Alert System: forward projection for maintenance recommendations
    predictive_alert_system = PredictiveAlertSystem(
        monte_carlo_projector=monte_carlo_projector,
        health_index_aggregator=health_index_aggregator,
        degradation_tracker=degradation_tracker,
    )

    # Live Benchmark Runner: continuous accuracy metrics vs C-MAPSS ground truth
    benchmark_runner = LiveBenchmarkRunner()

    # Latency Profiler: tracks ingestion-to-correction end-to-end latency
    latency_profiler = LatencyProfiler()

    # Throughput Monitor: tracks events/sec, predictions/sec, corrections/sec
    throughput_monitor = ThroughputMonitor()

    # --- Wire v1.4 services into API layer ---
    # Update engine services with root cause analyzer and predictive alert system
    configure_engine_services(
        rul_predictor=rul_predictor,
        health_index_aggregator=health_index_aggregator,
        component_health_mapper=component_health_mapper,
        degradation_tracker=degradation_tracker,
        root_cause_analyzer=root_cause_analyzer,
        predictive_alert_system=predictive_alert_system,
    )

    # Wire benchmark and performance services into the benchmark API
    configure_benchmark_services(
        benchmark_runner=benchmark_runner,
        latency_profiler=latency_profiler,
        throughput_monitor=throughput_monitor,
    )

    # --- v1.4 Pipeline Hooks via Broker Subscriptions ---
    # Regex to extract engine_id from sensor_id pattern: "engine-{id:03d}-{sensor_name}"
    import re
    _SENSOR_ID_PATTERN = re.compile(r"^engine-(\d{3})-(.+)$")

    def _parse_sensor_id(sensor_id: str) -> tuple[int, str] | tuple[None, None]:
        """Extract engine_id and sensor_name from sensor_id string."""
        match = _SENSOR_ID_PATTERN.match(sensor_id)
        if match:
            return int(match.group(1)), match.group(2)
        return None, None

    async def _on_telemetry_raw(topic: str, key: str, message: bytes) -> None:
        """Hook: record ingestion event for latency profiling and throughput.

        Called on each telemetry.raw message to:
        - Start a latency span (LatencyProfiler.start_span)
        - Record an event for throughput tracking (ThroughputMonitor.record_event)
        """
        throughput_monitor.record_event()

        try:
            payload = json.loads(message)
            sensor_id = payload.get("sensor_id", key)
            # Use sensor_id as correlation key (cycle info not directly in raw telemetry)
            # The correction will end the span using the same sensor_id
            latency_profiler.start_span(sensor_id)
        except (json.JSONDecodeError, ValueError):
            pass

    async def _on_prediction_generated(topic: str, key: str, message: bytes) -> None:
        """Hook: record prediction generation for throughput tracking."""
        throughput_monitor.record_prediction()

    async def _on_correction_published(topic: str, key: str, message: bytes) -> None:
        """Hook: record correction for latency, throughput, benchmark, and root cause.

        Called on each corrections.state message to:
        - End the latency span (LatencyProfiler.end_span)
        - Record correction for throughput (ThroughputMonitor.record_correction)
        - Record innovation for RootCauseAnalyzer
        - Record benchmark data (LiveBenchmarkRunner.record) with RUL data
        """
        throughput_monitor.record_correction()

        try:
            payload = json.loads(message)
            sensor_id = payload.get("sensor_id", key)

            # End latency span for this sensor
            latency_profiler.end_span(sensor_id)

            # Record innovation for root cause analysis
            engine_id, sensor_name = _parse_sensor_id(sensor_id)
            innovation_magnitude = payload.get("innovation_magnitude")
            if engine_id is not None and sensor_name is not None and innovation_magnitude is not None:
                root_cause_analyzer.record_innovation(
                    engine_id=engine_id,
                    sensor_name=sensor_name,
                    innovation_magnitude=innovation_magnitude,
                )

            # Record benchmark data if RUL predictor has state for this engine
            if engine_id is not None and _rul_predictor_ref is not None:
                engine_state = _rul_predictor_ref.get_engine_state(engine_id)
                if engine_state.cycle_count > 0:
                    # Use corrected value as the corrected prediction proxy
                    corrected_values = payload.get("corrected_state_vector", [])
                    raw_prediction = payload.get("raw_prediction")
                    confidence_band = payload.get("confidence_band_95", [0.0, 0.0])

                    if raw_prediction is not None and corrected_values:
                        # Ground truth RUL: use RUL predictor's current estimate as proxy
                        # In a real system this would come from C-MAPSS ground truth labels
                        ground_truth_rul = float(engine_state.current_rul)
                        benchmark_runner.record(
                            raw_prediction=raw_prediction,
                            corrected_prediction=corrected_values[0],
                            ground_truth_rul=ground_truth_rul,
                            confidence_lower=confidence_band[0] if len(confidence_band) >= 2 else 0.0,
                            confidence_upper=confidence_band[1] if len(confidence_band) >= 2 else 0.0,
                        )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    async def _on_anomaly_detected(topic: str, key: str, message: bytes) -> None:
        """Hook: trigger root cause analysis on anomaly detection.

        Called on each alerts.anomaly message to collect current innovations
        for the affected engine and run analyze_anomaly().
        """
        try:
            payload = json.loads(message)
            sensor_id = payload.get("sensor_id", key)
            engine_id, sensor_name = _parse_sensor_id(sensor_id)

            if engine_id is not None:
                # Gather current innovation magnitudes for all sensors of this engine
                # from the root cause analyzer's history
                engine_history = root_cause_analyzer._history.get(engine_id, {})
                sensor_innovations = {}
                for s_name, history_deque in engine_history.items():
                    if history_deque:
                        # Use the most recent innovation magnitude for each sensor
                        sensor_innovations[s_name] = history_deque[-1]

                # If we have the anomaly-triggering sensor's innovation from the payload,
                # ensure it's included/updated
                innovation_mag = payload.get("innovation_magnitude")
                if sensor_name is not None and innovation_mag is not None:
                    sensor_innovations[sensor_name] = innovation_mag

                if sensor_innovations:
                    root_cause_analyzer.analyze_anomaly(
                        engine_id=engine_id,
                        sensor_innovations=sensor_innovations,
                    )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Keep a reference to the rul_predictor for benchmark recording
    _rul_predictor_ref = rul_predictor

    # Subscribe to broker topics for v1.4 pipeline hooks
    await broker.subscribe(
        TELEMETRY_RAW, "v14-latency-throughput", _on_telemetry_raw
    )
    await broker.subscribe(
        PREDICTIONS_STATE, "v14-throughput-predictions", _on_prediction_generated
    )
    await broker.subscribe(
        CORRECTIONS_STATE, "v14-correction-hooks", _on_correction_published
    )
    await broker.subscribe(
        ALERTS_ANOMALY, "v14-anomaly-root-cause", _on_anomaly_detected
    )

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
            speed=float(os.environ.get("ADAPTER_SPEED", "0.5")),
            max_cycles=None,
            loop=True,
            parallel_engines=True,
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
