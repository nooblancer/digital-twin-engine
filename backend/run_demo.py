"""Demo: Run the full Digital Twin Telemetry Engine pipeline locally.

Wires all components together using in-memory broker and TSDB,
generates synthetic telemetry from the simulator, and shows the
data flowing through the pipeline in real time.
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import numpy as np

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.broker.topics import (
    ALERTS_ANOMALY,
    CORRECTIONS_STATE,
    METRICS_PIPELINE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)
from digital_twin_engine.correction.enkf import EnKFIteration
from digital_twin_engine.correction.temporal_matcher import TemporalMatcher
from digital_twin_engine.ml_service.batch_accumulator import BatchAccumulator
from digital_twin_engine.ml_service.ensemble_inference import create_ensemble_predict_fn
from digital_twin_engine.shared.models import (
    EngineConfig,
    StateVector,
    TelemetryEvent,
    serialize_telemetry_event,
)
from digital_twin_engine.tsdb.writer import InMemoryTSDBBackend, TSDBWriter
from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.state_cache import StateCache


# ===========================================================================
# In-Memory Broker (same as integration tests)
# ===========================================================================

class DemoBroker(BrokerBackend):
    """In-memory broker with real-time logging of message flow."""

    def __init__(self) -> None:
        self._subscriptions: Dict[str, List[Tuple[str, MessageCallback]]] = {}
        self._counts: Dict[str, int] = {}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        self._counts[topic] = self._counts.get(topic, 0) + 1
        callbacks = self._subscriptions.get(topic, [])
        for group_id, callback in callbacks:
            await callback(topic, key, message)

    async def subscribe(self, topic: str, group_id: str, callback: MessageCallback) -> None:
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        self._subscriptions[topic].append((group_id, callback))

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass

    def set_fail_publish(self, fail: bool) -> None:
        pass

    def get_counts(self) -> Dict[str, int]:
        return dict(self._counts)


# ===========================================================================
# Pipeline Demo
# ===========================================================================

async def run_demo():
    print("=" * 70)
    print("  DIGITAL TWIN TELEMETRY ENGINE - Live Pipeline Demo")
    print("=" * 70)
    print()

    # --- Configuration ---
    config = EngineConfig(
        min_batch_size=10,
        max_batch_size=500,
        max_batch_wait_seconds=2.0,
        prediction_horizon_seconds=60.0,
        lstm_weight=0.6,
        xgboost_weight=0.4,
        ensemble_size=50,
        temporal_tolerance_seconds=2.0,
        anomaly_threshold_sigma=3.0,
    )

    # --- Initialize all components ---
    broker = DemoBroker()
    await broker.start()
    tsdb = InMemoryTSDBBackend()
    state_cache = StateCache()

    # Track pipeline events for display
    predictions_made = []
    corrections_made = []
    anomalies_detected = []

    # TSDB write callback
    async def tsdb_write_corrected(sv: StateVector) -> None:
        event = TelemetryEvent(
            timestamp=sv.timestamp,
            sensor_id=sv.sensor_id,
            measurement_type="corrected_state",
            value=sv.values[0] if sv.values else 0.0,
        )
        await tsdb.write_events([event])

    # TSDB consumer for raw telemetry
    async def tsdb_raw_consumer(topic, key, message):
        data = json.loads(message.decode("utf-8"))
        event = TelemetryEvent(
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
            sensor_id=data["sensor_id"],
            measurement_type=data["measurement_type"],
            value=data["value"],
        )
        await tsdb.write_events([event])

    # Prediction tracker
    async def prediction_tracker(topic, key, message):
        data = json.loads(message.decode("utf-8"))
        predictions_made.append(data)

    # Correction tracker
    async def correction_tracker(topic, key, message):
        data = json.loads(message.decode("utf-8"))
        corrections_made.append(data)
        state_cache.update_from_message(key, message)

    # Anomaly tracker
    async def anomaly_tracker(topic, key, message):
        data = json.loads(message.decode("utf-8"))
        anomalies_detected.append(data)

    # --- Wire up services ---
    # EnKF iteration
    enkf = EnKFIteration(broker=broker, tsdb_write_func=tsdb_write_corrected)

    # Temporal matcher (Correction Engine)
    matcher = TemporalMatcher(
        broker=broker, config=config, on_match=enkf, consumer_group="correction"
    )

    # ML Service
    ensemble = create_ensemble_predict_fn(config=config)
    accumulator = BatchAccumulator(
        broker=broker, config=config, predict_fn=ensemble.predict, consumer_group="ml"
    )

    # Subscribe consumers
    await broker.subscribe(TELEMETRY_RAW, "tsdb_writer", tsdb_raw_consumer)
    await broker.subscribe(PREDICTIONS_STATE, "tracker", prediction_tracker)
    await broker.subscribe(CORRECTIONS_STATE, "tracker", correction_tracker)
    await broker.subscribe(ALERTS_ANOMALY, "tracker", anomaly_tracker)

    # Start services
    await matcher.start()
    await accumulator.start()

    print("[OK] Pipeline components initialized:")
    print("    • Ingestion (in-process)")
    print("    • Message Broker (in-memory)")
    print("    • TSDB Writer (in-memory)")
    print("    • ML Service (LSTM+XGBoost ensemble)")
    print("    • Correction Engine (EnKF, 50 ensemble members)")
    print("    • API Gateway (FastAPI)")
    print()

    # --- Simulate sensor data ---
    sensors = {
        "turbine-001-temp": {"base": 340.0, "drift": 0.5, "noise": 2.0},
        "pump-003-pressure": {"base": 101.3, "drift": -0.1, "noise": 0.5},
        "valve-007-flow": {"base": 45.0, "drift": 0.0, "noise": 1.5},
    }

    for sid in sensors:
        state_cache.register_sensor(sid)

    print("-" * 70)
    print("  PHASE 1: Streaming telemetry from 3 sensors (30 events each)")
    print("-" * 70)
    print()

    now = datetime.now(timezone.utc)
    rng = np.random.default_rng(42)

    for sensor_id, params in sensors.items():
        print(f"  📡 Sensor: {sensor_id}")
        for i in range(30):
            ts = now + timedelta(milliseconds=i * 100)
            value = params["base"] + params["drift"] * (i * 0.1) + rng.normal(0, params["noise"])
            event = TelemetryEvent(
                timestamp=ts,
                sensor_id=sensor_id,
                measurement_type="temperature" if "temp" in sensor_id else "pressure" if "pressure" in sensor_id else "flow_rate",
                value=round(value, 4),
            )
            serialized = serialize_telemetry_event(event)
            await broker.publish(TELEMETRY_RAW, sensor_id, serialized.encode("utf-8"))

        await asyncio.sleep(0.05)  # Let async tasks process
        print(f"     → 30 events published")

    await asyncio.sleep(0.3)  # Let the pipeline fully process
    print()

    # --- Show results ---
    print("-" * 70)
    print("  PIPELINE RESULTS")
    print("-" * 70)
    print()

    counts = broker.get_counts()
    print(f"  📊 Message Broker Traffic:")
    print(f"     • telemetry.raw:      {counts.get(TELEMETRY_RAW, 0)} messages")
    print(f"     • predictions.state:  {counts.get(PREDICTIONS_STATE, 0)} messages")
    print(f"     • corrections.state:  {counts.get(CORRECTIONS_STATE, 0)} messages")
    print(f"     • alerts.anomaly:     {counts.get(ALERTS_ANOMALY, 0)} messages")
    print(f"     • metrics.pipeline:   {counts.get(METRICS_PIPELINE, 0)} messages")
    print()

    print(f"  🤖 ML Service:")
    print(f"     • Predictions generated: {len(predictions_made)}")
    if predictions_made:
        last = predictions_made[-1]
        print(f"     • Latest prediction for: {last.get('sensor_id', 'N/A')}")
        print(f"     • Model used: {last.get('model_used', 'N/A')}")
    print()

    print(f"  🔧 Correction Engine (EnKF):")
    print(f"     • Corrections applied: {len(corrections_made)}")
    print(f"     • Anomalies detected: {len(anomalies_detected)}")
    if corrections_made:
        last = corrections_made[-1]
        print(f"     • Latest correction for: {last.get('sensor_id', 'N/A')}")
        print(f"     • Ensemble spread: {last.get('ensemble_spread', 'N/A')}")
        print(f"     • Anomaly flag: {last.get('anomaly_flag', 'N/A')}")
    print()

    print(f"  💾 Time-Series Database:")
    for sid in sensors:
        records = await tsdb.query_by_sensor_and_time(
            sensor_id=sid,
            start=now - timedelta(seconds=1),
            end=now + timedelta(seconds=10),
        )
        print(f"     • {sid}: {len(records)} records stored")
    print()

    # --- Query API Gateway ---
    print("-" * 70)
    print("  API GATEWAY QUERIES")
    print("-" * 70)
    print()

    from httpx import ASGITransport, AsyncClient

    gateway = APIGateway(tsdb_backend=tsdb, state_cache=state_cache)
    transport = ASGITransport(app=gateway.app)

    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        # Health check
        resp = await client.get("/health")
        print(f"  GET /health → {resp.status_code}")
        if resp.status_code == 200:
            health = resp.json()
            print(f"     Overall: {health.get('overall_status', 'N/A')}")
        print()

        # Current state for each sensor
        for sid in sensors:
            resp = await client.get(f"/sensors/{sid}/state/current")
            print(f"  GET /sensors/{sid}/state/current → {resp.status_code}")
            if resp.status_code == 200:
                body = resp.json()
                sv = body.get("state_vector", [])
                spread = body.get("ensemble_spread", "N/A")
                anomaly = body.get("anomaly_flag", False)
                print(f"     State vector: {sv}")
                print(f"     Ensemble spread: {spread}")
                print(f"     Anomaly: {anomaly}")
            else:
                print(f"     (no corrected state yet)")
            print()

        # History query for first sensor
        first_sensor = list(sensors.keys())[0]
        resp = await client.get(
            f"/sensors/{first_sensor}/state/history",
            params={
                "start": (now - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "end": (now + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "limit": 5,
                "offset": 0,
            },
        )
        print(f"  GET /sensors/{first_sensor}/state/history?limit=5 → {resp.status_code}")
        if resp.status_code == 200:
            body = resp.json()
            pagination = body.get("pagination", {})
            print(f"     Total records: {pagination.get('total_count', 0)}")
            print(f"     Page: offset={pagination.get('offset')}, limit={pagination.get('limit')}")
            results = body.get("results", [])
            for r in results[:3]:
                print(f"     • ts={r['timestamp'][:19]}  state={r['state_vector']}")
            if len(results) > 3:
                print(f"     ... ({len(results) - 3} more)")
        print()

    # --- Cleanup ---
    await accumulator.stop()
    await matcher.stop()
    await broker.stop()

    print("=" * 70)
    print("  DONE - Pipeline demo complete! All services running correctly.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_demo())
