"""Run the C-MAPSS replay adapter standalone.

Streams NASA turbofan engine data through the full pipeline using
in-memory broker and TSDB, demonstrating the engine processing
real sensor degradation data.

Usage:
    python -m digital_twin_engine.adapters --dataset FD001 --engines 1,2,3 --speed 50
"""

import argparse
import asyncio
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from digital_twin_engine.adapters.cmapss_replay import CMAPSSConfig, CMAPSSReplayAdapter
from digital_twin_engine.shared.models import (
    EngineConfig,
    TelemetryEvent,
    serialize_telemetry_event,
)


async def run_standalone(config: CMAPSSConfig):
    """Run the adapter standalone, printing events to stdout."""
    adapter = CMAPSSReplayAdapter(config)
    adapter.load()

    summary = adapter.summary()
    print("=" * 60)
    print("  NASA C-MAPSS Replay Adapter")
    print("=" * 60)
    print()
    print(f"  Dataset:        {summary['dataset']} ({summary['split']})")
    print(f"  Engines:        {summary['engines']}")
    print(f"  Total cycles:   {summary['total_cycles']}")
    print(f"  Sensors/cycle:  {summary['sensors_per_cycle']}")
    print(f"  Total events:   {summary['total_events_available']}")
    print(f"  Playback speed: {summary['playback_speed']}")
    print(f"  Est. duration:  {summary['estimated_duration_seconds']:.1f}s")
    print()
    print("-" * 60)
    print()

    count = 0
    start = time.monotonic()

    async for event in adapter.stream():
        count += 1
        if count <= 10 or count % 100 == 0:
            print(
                f"  [{count:>6}] {event.sensor_id:<40} "
                f"value={event.value:>10.4f}  "
                f"type={event.measurement_type}"
            )
        if count == 10:
            print(f"  ... (streaming, showing every 100th event)")

    elapsed = time.monotonic() - start
    rate = count / elapsed if elapsed > 0 else 0

    print()
    print("-" * 60)
    print(f"  Replay complete!")
    print(f"  Events emitted: {count}")
    print(f"  Elapsed:        {elapsed:.2f}s")
    print(f"  Throughput:     {rate:.0f} events/s")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="NASA C-MAPSS Replay Adapter")
    parser.add_argument("--dataset", default="FD001", choices=["FD001", "FD002", "FD003", "FD004"])
    parser.add_argument("--split", default="train", choices=["train", "test"])
    parser.add_argument("--engines", default=None, help="Comma-separated engine IDs (default: all)")
    parser.add_argument("--speed", type=float, default=50.0, help="Playback speed multiplier")
    parser.add_argument("--max-cycles", type=int, default=None, help="Max cycles to replay")
    parser.add_argument("--sensors", default=None, help="Comma-separated sensor names")
    parser.add_argument("--data-dir", default="data/cmapss", help="Path to CMAPSS data")
    args = parser.parse_args()

    engine_ids = None
    if args.engines:
        engine_ids = [int(x.strip()) for x in args.engines.split(",")]

    sensors = None
    if args.sensors:
        sensors = [x.strip() for x in args.sensors.split(",")]

    config = CMAPSSConfig(
        data_dir=args.data_dir,
        dataset=args.dataset,
        split=args.split,
        engine_ids=engine_ids,
        speed=args.speed,
        max_cycles=args.max_cycles,
        sensors=sensors,
    )

    asyncio.run(run_standalone(config))


if __name__ == "__main__":
    main()
