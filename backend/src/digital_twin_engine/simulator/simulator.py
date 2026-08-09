"""Async telemetry simulator with WebSocket client.

Generates synthetic TelemetryEvents according to configured patterns and
streams them to the Ingestion Server over WebSocket connections.

Features:
- Concurrent simulation of 100+ sensors with independent configurations
- Target emission rate maintenance with ≤5% deviation over 10-second windows
- Connection lifecycle management (connect, reconnect, graceful shutdown)
- Summary reporting on completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import websockets
from websockets.exceptions import (
    ConnectionClosed,
    InvalidURI,
    WebSocketException,
)

from digital_twin_engine.simulator.config import SensorSimConfig, SimulatorConfig
from digital_twin_engine.simulator.patterns import (
    PatternConfig,
    RandomWalkConfig,
    generate_value,
)

logger = logging.getLogger(__name__)


@dataclass
class SimulationSummary:
    """Summary statistics reported on simulation completion."""

    total_events_emitted: int
    elapsed_seconds: float
    actual_average_rate: float  # events/s
    events_per_sensor: Dict[str, int]
    connection_errors: int
    started_at: str
    stopped_at: str


@dataclass
class _SensorState:
    """Internal per-sensor mutable state during simulation."""

    config: SensorSimConfig
    previous_value: float
    events_emitted: int = 0
    rng: random.Random = field(default_factory=random.Random)


class TelemetrySimulator:
    """Async simulator that generates and streams synthetic telemetry events.

    Usage:
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=[...],
            emission_rate=100.0,
            duration_seconds=60.0,
        )
        simulator = TelemetrySimulator(config)
        summary = await simulator.run()
    """

    def __init__(self, config: SimulatorConfig, seed: int | None = None) -> None:
        """Initialize the simulator.

        Args:
            config: Simulator configuration.
            seed: Optional random seed for reproducibility.
        """
        self._config = config
        self._seed = seed
        self._running = False
        self._stop_event = asyncio.Event()
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._sensor_states: Dict[str, _SensorState] = {}
        self._total_events = 0
        self._connection_errors = 0
        self._start_time: float = 0.0
        self._rate_tracker = _RateTracker()

    @property
    def config(self) -> SimulatorConfig:
        """Return the simulator configuration."""
        return self._config

    @property
    def is_running(self) -> bool:
        """Whether the simulator is currently running."""
        return self._running

    async def run(self) -> SimulationSummary:
        """Run the simulation for the configured duration.

        Returns:
            SimulationSummary with statistics about the run.

        Raises:
            ConnectionError: If unable to establish WebSocket connection after retries.
        """
        self._running = True
        self._stop_event.clear()
        self._total_events = 0
        self._connection_errors = 0
        self._rate_tracker = _RateTracker()
        started_at = datetime.now(timezone.utc)

        # Initialize sensor states
        self._init_sensor_states()

        try:
            # Connect to server
            await self._connect_with_retry()

            # Run concurrent sensor tasks
            self._start_time = time.monotonic()
            await self._run_sensors()

        finally:
            self._running = False
            await self._close_connection()

        stopped_at = datetime.now(timezone.utc)
        elapsed = time.monotonic() - self._start_time

        return SimulationSummary(
            total_events_emitted=self._total_events,
            elapsed_seconds=elapsed,
            actual_average_rate=self._total_events / elapsed if elapsed > 0 else 0.0,
            events_per_sensor={
                sid: state.events_emitted
                for sid, state in self._sensor_states.items()
            },
            connection_errors=self._connection_errors,
            started_at=started_at.isoformat(),
            stopped_at=stopped_at.isoformat(),
        )

    def stop(self) -> None:
        """Signal the simulator to stop."""
        self._stop_event.set()

    def _init_sensor_states(self) -> None:
        """Initialize per-sensor state with RNG seeds."""
        self._sensor_states.clear()
        base_seed = self._seed if self._seed is not None else random.randint(0, 2**32)
        for i, sensor_cfg in enumerate(self._config.sensors):
            rng = random.Random(base_seed + i)
            # For random walk, initial value is the base from config
            initial_value = (
                sensor_cfg.pattern_config.base
                if hasattr(sensor_cfg.pattern_config, "base")
                else 0.0
            )
            self._sensor_states[sensor_cfg.sensor_id] = _SensorState(
                config=sensor_cfg,
                previous_value=initial_value,
                rng=rng,
            )

    async def _connect_with_retry(self) -> None:
        """Connect to the WebSocket server with retry logic.

        Raises:
            ConnectionError: If all retry attempts fail.
        """
        last_error: Optional[Exception] = None
        for attempt in range(self._config.max_connect_retries + 1):
            try:
                self._websocket = await asyncio.wait_for(
                    websockets.connect(self._config.server_url),
                    timeout=self._config.connect_timeout_seconds,
                )
                logger.info(
                    "Connected to server",
                    extra={"url": self._config.server_url, "attempt": attempt + 1},
                )
                return
            except (
                asyncio.TimeoutError,
                OSError,
                WebSocketException,
                InvalidURI,
            ) as exc:
                last_error = exc
                self._connection_errors += 1
                logger.warning(
                    "Connection attempt failed",
                    extra={
                        "url": self._config.server_url,
                        "attempt": attempt + 1,
                        "error": str(exc),
                    },
                )
                if attempt < self._config.max_connect_retries:
                    await asyncio.sleep(self._config.retry_delay_seconds)

        raise ConnectionError(
            f"Failed to connect to {self._config.server_url} after "
            f"{self._config.max_connect_retries + 1} attempts: {last_error}"
        )

    async def _reconnect(self) -> bool:
        """Attempt to reconnect after connection loss.

        Returns:
            True if reconnection succeeded, False otherwise.
        """
        logger.info("Attempting reconnection...")
        for attempt in range(self._config.max_connect_retries):
            try:
                await asyncio.sleep(self._config.retry_delay_seconds)
                self._websocket = await asyncio.wait_for(
                    websockets.connect(self._config.server_url),
                    timeout=self._config.connect_timeout_seconds,
                )
                logger.info(
                    "Reconnected to server",
                    extra={"url": self._config.server_url, "attempt": attempt + 1},
                )
                return True
            except (
                asyncio.TimeoutError,
                OSError,
                WebSocketException,
            ) as exc:
                self._connection_errors += 1
                logger.warning(
                    "Reconnection attempt failed",
                    extra={"attempt": attempt + 1, "error": str(exc)},
                )

        logger.error(
            "All reconnection attempts failed",
            extra={"url": self._config.server_url},
        )
        return False

    async def _close_connection(self) -> None:
        """Close the WebSocket connection gracefully."""
        if self._websocket is not None:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

    async def _run_sensors(self) -> None:
        """Run all sensor simulation tasks concurrently."""
        tasks = []
        for sensor_cfg in self._config.sensors:
            rate = self._config.get_sensor_rate(sensor_cfg)
            if rate > 0:
                task = asyncio.create_task(
                    self._sensor_loop(sensor_cfg.sensor_id, rate)
                )
                tasks.append(task)

        # Also create a duration watchdog
        duration_task = asyncio.create_task(self._duration_watchdog())
        tasks.append(duration_task)

        # Wait for stop signal or all tasks to complete
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Check for exceptions
        for task in done:
            if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
                exc = task.exception()
                if isinstance(exc, ConnectionError):
                    raise exc

    async def _duration_watchdog(self) -> None:
        """Wait for the configured duration or stop signal."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self._config.duration_seconds,
            )
        except asyncio.TimeoutError:
            # Duration elapsed, signal stop
            self._stop_event.set()

    async def _sensor_loop(self, sensor_id: str, rate: float) -> None:
        """Generate and send events for a single sensor at the target rate.

        Uses a token-bucket-like approach to maintain the target rate with
        ≤5% deviation over any 10-second window.
        """
        state = self._sensor_states[sensor_id]
        interval = 1.0 / rate  # Time between events in seconds

        next_emit_time = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            elapsed_since_start = now - self._start_time

            # Check if we've exceeded duration
            if elapsed_since_start >= self._config.duration_seconds:
                self._stop_event.set()
                break

            # Wait until next emission time
            sleep_time = next_emit_time - now
            if sleep_time > 0:
                try:
                    # Use wait_for with stop_event to allow early termination
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=sleep_time,
                    )
                    # If we get here, stop was signaled
                    break
                except asyncio.TimeoutError:
                    pass  # Time to emit

            # Generate event
            event_json = self._generate_event(sensor_id, elapsed_since_start)

            # Send event
            sent = await self._send_event(event_json)
            if sent:
                state.events_emitted += 1
                self._total_events += 1
                self._rate_tracker.record_event(time.monotonic())

            # Schedule next emission
            next_emit_time += interval

            # If we've fallen behind, catch up but don't burst excessively
            now = time.monotonic()
            if next_emit_time < now - interval * 10:
                # Too far behind, reset to avoid burst
                next_emit_time = now

    def _generate_event(self, sensor_id: str, elapsed_seconds: float) -> str:
        """Generate a single telemetry event JSON string.

        Args:
            sensor_id: The sensor identifier.
            elapsed_seconds: Time elapsed since simulation start.

        Returns:
            JSON string conforming to TelemetryEvent schema.
        """
        state = self._sensor_states[sensor_id]

        # Generate value based on pattern
        value = generate_value(
            config=state.config.pattern_config,
            elapsed_seconds=elapsed_seconds,
            previous_value=state.previous_value,
            rng=state.rng,
        )
        state.previous_value = value

        # Build event payload
        event = {
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "sensor_id": sensor_id,
            "measurement_type": state.config.measurement_type,
            "value": value,
        }

        return json.dumps(event)

    async def _send_event(self, event_json: str) -> bool:
        """Send an event over WebSocket, handling connection loss.

        Returns:
            True if the event was sent successfully.
        """
        if self._websocket is None:
            return False

        try:
            await self._websocket.send(event_json)
            return True
        except ConnectionClosed:
            logger.warning("Connection lost during send")
            self._connection_errors += 1
            # Attempt reconnection
            if await self._reconnect():
                # Retry the send
                try:
                    await self._websocket.send(event_json)
                    return True
                except Exception:
                    return False
            else:
                # All reconnection attempts failed, terminate
                self._stop_event.set()
                raise ConnectionError(
                    "Lost connection during transmission and reconnection failed"
                )
        except Exception as exc:
            logger.error(f"Send error: {exc}")
            return False


class _RateTracker:
    """Tracks emission rate over sliding 10-second windows.

    Used internally to monitor that the simulator maintains
    the target rate with ≤5% deviation.
    """

    def __init__(self, window_seconds: float = 10.0) -> None:
        self._window_seconds = window_seconds
        self._timestamps: List[float] = []

    def record_event(self, timestamp: float) -> None:
        """Record an event emission timestamp."""
        self._timestamps.append(timestamp)
        # Prune old timestamps beyond the window
        cutoff = timestamp - self._window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.pop(0)

    def current_rate(self) -> float:
        """Calculate the current emission rate over the last window."""
        if len(self._timestamps) < 2:
            return 0.0
        window_start = self._timestamps[0]
        window_end = self._timestamps[-1]
        duration = window_end - window_start
        if duration <= 0:
            return 0.0
        return len(self._timestamps) / duration

    def events_in_window(self) -> int:
        """Return the number of events in the current window."""
        return len(self._timestamps)
