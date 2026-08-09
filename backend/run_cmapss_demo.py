"""Demo: Run NASA C-MAPSS turbofan data through the full Digital Twin pipeline.

Shows real engine degradation data flowing through:
  Sensor Data -> Broker -> TSDB + ML Prediction -> EnKF Correction -> API

Watch as the engine degrades over time and the system detects anomalies.

Usage:
    python run_cmapss_demo.py
    python run_cmapss_demo.py --engines 1,5,10 --speed 100
"""

import argparse
import asyncio
import io
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import numpy as np

from digital_twin_engine.adapters.cmapss_replay import CMAPSSConfig, CMAPSSReplayAdapter
from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
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
from digital_twin_engine.shared.models import (
    EngineConfig,
    StateVector,
    TelemetryEvent,
    serialize_telemetry_event,
)
from digital_twin_engine.tsdb.writer import InMemoryTSDBBackend


# ===========================================================================
# In-Memory Broker
# ===========================================================================

class DemoBroker(BrokerBackend):
    def __init__(self):
        self._subs: Dict[str, List[Tuple[str, MessageCallback]]] = {}
        self._counts: Dict[str, int] = {}

    async def start(self): pass
    async def stop(self): pass

    async def publish(self, topic, key, message):
        self._counts[topic] = self._counts.get(topic, 0) + 1
        for gid, cb in self._subs.get(topic, []):
            await cb(topic, key, message)

    async def subscribe(self, topic, group_id, callback):
        self._subs.setdefault(topic, []).append((group_id, callback))

    async def acknowledge(self, topic, group_id, offset): pass
    def set_fail_publish(self, fail): pass


# ===========================================================================
# Main Demo
# ===========================================================================

async def run_demo(args):
    print("=" * 70)
    print("  NASA C-MAPSS TURBOFAN ENGINE - Digital Twin Pipeline Demo")
    print("=" * 70)
    print()

    # --- Load dataset ---
    engine_ids = None
    if args.engines:
        engine_ids = [int(x.strip()) for x in args.engines.split(",")]

    # Focus on key degradation sensors for the ML pipeline
    key_sensors = [
        "hpc_outlet_temp_total",
        "lpt_outlet_temp_total",
        "physical_fan_speed_rpm",
        "physical_core_speed_rpm",
        "hpc_outlet_pressure_total",
        "bypass_ratio",
        "corrected_fan_speed_rpm",
        "bleed_enthalpy",
    ]

    cmapss_config = CMAPSSConfig(
        data_dir=args.data_dir,
        dataset=args.dataset,
        split="train",
        engine_ids=engine_ids,
        speed=args.speed,
        sensors=key_sensors,
        max_cycles=args.max_cycles,
    )

    adapter = CMAPSSReplayAdapter(cmapss_config)
    adapter.load()
    summary = adapter.summary()

    print(f"  Dataset:       {summary['dataset']} (train - full run-to-failure)")
    print(f"  Engines:       {summary['engines']}")
    print(f"  Cycles:        {summary['total_cycles']}")
    print(f"  Sensors:       {summary['sensors_per_cycle']} key degradation channels")
    print(f"  Speed:         {summary['playback_speed']}")
    print(f"  Est. duration: {summary['estimated_duration_seconds']:.1f}s")
    print()

    # --- Setup pipeline ---
    broker = DemoBroker()
    await broker.start()
    tsdb = InMemoryTSDBBackend()

    config = EngineConfig(
        min_batch_size=10,
        max_batch_size=100,
        max_batch_wait_seconds=2.0,
        temporal_tolerance_seconds=5.0,
        anomaly_threshold_sigma=2.5,
        ensemble_size=50,
    )

    predictions_count = 0
    corrections_count = 0
    anomalies: List[Dict] = []

    async def on_prediction(topic, key, message):
        nonlocal predictions_count
        predictions_count += 1

    async def on_correction(topic, key, message):
        nonlocal corrections_count
        corrections_count += 1

    async def on_anomaly(topic, key, message):
        data = json.loads(message.decode("utf-8"))
        anomalies.append(data)

    # TSDB consumer
    async def tsdb_consumer(topic, key, message):
        data = json.loads(message.decode("utf-8"))
        event = TelemetryEvent(
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
            sensor_id=data["sensor_id"],
            measurement_type=data["measurement_type"],
            value=data["value"],
        )
        await tsdb.write_events([event])

    # Wire up
    async def tsdb_write_sv(sv: StateVector):
        event = TelemetryEvent(
            timestamp=sv.timestamp, sensor_id=sv.sensor_id,
            measurement_type="corrected_state",
            value=sv.values[0] if sv.values else 0.0,
        )
        await tsdb.write_events([event])

    enkf = EnKFIteration(broker=broker, tsdb_write_func=tsdb_write_sv)
    matcher = TemporalMatcher(broker=broker, config=config, on_match=enkf, consumer_group="corr")
    ensemble = create_ensemble_predict_fn(config=config)
    accumulator = BatchAccumulator(broker=broker, config=config, predict_fn=ensemble.predict, consumer_group="ml")

    await broker.subscribe(TELEMETRY_RAW, "tsdb", tsdb_consumer)
    await broker.subscribe(PREDICTIONS_STATE, "track", on_prediction)
    await broker.subscribe(CORRECTIONS_STATE, "track", on_correction)
    await broker.subscribe(ALERTS_ANOMALY, "track", on_anomaly)
    await matcher.start()
    await accumulator.start()

    print("  Pipeline: Ingestion -> Broker -> TSDB + ML -> EnKF -> API")
    print()
    print("-" * 70)
    print("  STREAMING ENGINE DATA...")
    print("-" * 70)
    print()

    # --- Stream data through pipeline ---
    events_published = 0
    cycle_count = 0
    last_report_cycle = 0
    start_time = time.monotonic()

    async for event in adapter.stream():
        serialized = serialize_telemetry_event(event)
        await broker.publish(TELEMETRY_RAW, event.sensor_id, serialized.encode("utf-8"))
        events_published += 1

        # Track cycles (each cycle = sensors_per_cycle events for first engine)
        current_cycle = events_published // summary['sensors_per_cycle']

        # Progress report every 20 cycles
        if current_cycle > last_report_cycle and current_cycle % 20 == 0:
            elapsed = time.monotonic() - start_time
            rate = events_published / elapsed if elapsed > 0 else 0
            print(
                f"  Cycle {current_cycle:>4} | "
                f"Events: {events_published:>6} | "
                f"Predictions: {predictions_count:>3} | "
                f"Corrections: {corrections_count:>3} | "
                f"Anomalies: {len(anomalies):>2} | "
                f"Rate: {rate:.0f} evt/s"
            )
            last_report_cycle = current_cycle

    # Let pipeline finish processing
    await asyncio.sleep(0.5)

    elapsed = time.monotonic() - start_time

    # --- Final results ---
    print()
    print("-" * 70)
    print("  RESULTS")
    print("-" * 70)
    print()
    print(f"  Total events streamed:  {events_published}")
    print(f"  Elapsed time:           {elapsed:.2f}s")
    print(f"  Throughput:             {events_published/elapsed:.0f} events/s")
    print()
    print(f"  ML Predictions made:    {predictions_count}")
    print(f"  EnKF Corrections:       {corrections_count}")
    print(f"  Anomalies detected:     {len(anomalies)}")
    print()

    if anomalies:
        print("  ANOMALY LOG (degradation events detected):")
        print("  " + "-" * 66)
        for i, a in enumerate(anomalies[:10]):
            sid = a.get("sensor_id", "?")
            innov = a.get("innovation_magnitude", 0)
            obs = a.get("observed_value", 0)
            pred = a.get("predicted_value", 0)
            print(
                f"  [{i+1:>2}] {sid:<45} "
                f"innov={innov:.3f}  obs={obs:.2f}  pred={pred:.2f}"
            )
        if len(anomalies) > 10:
            print(f"  ... and {len(anomalies) - 10} more")
        print()

    broker_counts = broker._counts
    print(f"  Broker message totals:")
    print(f"    telemetry.raw:     {broker_counts.get(TELEMETRY_RAW, 0)}")
    print(f"    predictions.state: {broker_counts.get(PREDICTIONS_STATE, 0)}")
    print(f"    corrections.state: {broker_counts.get(CORRECTIONS_STATE, 0)}")
    print(f"    alerts.anomaly:    {broker_counts.get(ALERTS_ANOMALY, 0)}")
    print()

    # Cleanup
    await accumulator.stop()
    await matcher.stop()
    await broker.stop()

    print("=" * 70)
    print("  Demo complete! Real NASA turbofan data processed successfully.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="C-MAPSS Digital Twin Pipeline Demo")
    parser.add_argument("--dataset", default="FD001", choices=["FD001", "FD002", "FD003", "FD004"])
    parser.add_argument("--engines", default="1,2,3", help="Comma-separated engine IDs")
    parser.add_argument("--speed", type=float, default=100.0, help="Playback speed")
    parser.add_argument("--max-cycles", type=int, default=50, help="Max cycles per engine")
    parser.add_argument("--data-dir", default="data/cmapss", help="Path to CMAPSS data")
    args = parser.parse_args()
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
