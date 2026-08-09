"""Run the C-MAPSS replay adapter standalone or in Docker mode.

Streams NASA turbofan engine data through the full pipeline using
in-memory broker and TSDB (standalone mode), or connects to the
Ingestion Server WebSocket endpoint (Docker mode) for distributed
pipeline processing.

Standalone mode (default):
    python -m digital_twin_engine.adapters --dataset FD001 --engines 1,2,3 --speed 50

Docker mode (auto-detected via INGESTION_URL env var):
    INGESTION_URL=http://ingestion-server:8080 python -m digital_twin_engine.adapters

Validates: Requirements 6.1, 6.2, 6.3, 6.4
"""

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# Only replace stdout when running as a script (not when imported by tests)
if __name__ == "__main__" or os.environ.get("_ADAPTER_STDOUT_WRAP"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from digital_twin_engine.adapters.cmapss_replay import CMAPSSConfig, CMAPSSReplayAdapter
from digital_twin_engine.shared.models import (
    EngineConfig,
    TelemetryEvent,
    serialize_telemetry_event,
)

logger = logging.getLogger("digital_twin_engine.adapters")


# ---------------------------------------------------------------------------
# Docker Mode: Connection retry logic
# ---------------------------------------------------------------------------

# Exponential backoff parameters
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0
_BACKOFF_MULTIPLIER = 2.0


async def _wait_for_health(base_url: str) -> None:
    """Wait for the Ingestion Server health check to pass.

    Polls GET {base_url}/docs (the FastAPI auto-generated endpoint used
    by the Docker healthcheck) with exponential backoff until successful.

    Args:
        base_url: Base URL of the Ingestion Server (e.g. http://ingestion-server:8080).
    """
    health_url = f"{base_url}/docs"
    backoff = _INITIAL_BACKOFF_S

    logger.info(f"Waiting for Ingestion Server at {health_url} ...")

    while True:
        try:
            loop = asyncio.get_event_loop()
            # Run blocking urllib call in executor to avoid blocking the event loop
            req = urllib.request.Request(health_url, method="GET")
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=5),
            )
            logger.info("Ingestion Server is healthy — proceeding to connect.")
            return
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            logger.warning(
                f"Ingestion Server not ready ({exc}). "
                f"Retrying in {backoff:.1f}s..."
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)


async def _stream_to_websocket(ws_url: str, config: CMAPSSConfig) -> None:
    """Connect to the Ingestion Server WebSocket and stream C-MAPSS data.

    Streams telemetry events as JSON over the WebSocket connection.
    Raises on connection loss so the caller can retry.

    Args:
        ws_url: WebSocket URL (e.g. ws://ingestion-server:8080/ws/telemetry).
        config: C-MAPSS replay adapter configuration.
    """
    import websockets

    adapter = CMAPSSReplayAdapter(config)
    adapter.load()

    summary = adapter.summary()
    logger.info(
        f"Streaming C-MAPSS data: dataset={summary['dataset']}, "
        f"engines={summary['engines']}, speed={summary['playback_speed']}"
    )

    async with websockets.connect(ws_url) as ws:
        count = 0
        start = time.monotonic()

        async for event in adapter.stream():
            payload = serialize_telemetry_event(event)
            await ws.send(payload)
            count += 1

            if count % 1000 == 0:
                elapsed = time.monotonic() - start
                rate = count / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Streamed {count} events ({rate:.0f} events/s)"
                )

        elapsed = time.monotonic() - start
        rate = count / elapsed if elapsed > 0 else 0
        logger.info(
            f"Replay complete: {count} events in {elapsed:.1f}s "
            f"({rate:.0f} events/s). Restarting..."
        )


async def run_docker_mode(base_url: str, config: CMAPSSConfig) -> None:
    """Run the adapter in Docker mode with connection retry logic.

    1. Wait for the Ingestion Server health check to pass.
    2. Connect to the WebSocket endpoint and stream data.
    3. On connection failure or disconnect, retry with exponential backoff.
    4. Retries are unlimited — the adapter runs until the container is stopped.

    Args:
        base_url: Base URL of the Ingestion Server (e.g. http://ingestion-server:8080).
        config: C-MAPSS replay adapter configuration.
    """
    import websockets

    # Derive WebSocket URL from HTTP base URL
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/telemetry"

    # Step 1: Wait for health check
    await _wait_for_health(base_url)

    # Step 2: Connect and stream with retry on failure
    backoff = _INITIAL_BACKOFF_S

    while True:
        try:
            await _stream_to_websocket(ws_url, config)
            # Replay finished (dataset exhausted) — reset backoff and restart
            backoff = _INITIAL_BACKOFF_S
        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.WebSocketException,
            OSError,
            ConnectionError,
        ) as exc:
            logger.warning(
                f"Connection lost ({type(exc).__name__}: {exc}). "
                f"Retrying in {backoff:.1f}s..."
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)

            # Re-check health before reconnecting (server may be restarting)
            await _wait_for_health(base_url)
            # Reset backoff after successful health check
            backoff = _INITIAL_BACKOFF_S


# ---------------------------------------------------------------------------
# Standalone Mode: Print events to stdout
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    # Configure logging for Docker mode
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

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
        loop=True,  # In Docker mode, loop continuously
    )

    # Detect Docker mode via INGESTION_URL environment variable
    ingestion_url = os.environ.get("INGESTION_URL")

    if ingestion_url:
        # Docker mode: connect to Ingestion Server WebSocket
        logger.info(
            f"Starting in Docker mode — target: {ingestion_url}"
        )
        # In Docker mode, default to looping and moderate speed
        config = CMAPSSConfig(
            data_dir=args.data_dir,
            dataset=args.dataset,
            split=args.split,
            engine_ids=engine_ids,
            speed=args.speed,
            max_cycles=args.max_cycles,
            sensors=sensors,
            loop=True,
        )
        asyncio.run(run_docker_mode(ingestion_url, config))
    else:
        # Standalone mode: print events to stdout
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
