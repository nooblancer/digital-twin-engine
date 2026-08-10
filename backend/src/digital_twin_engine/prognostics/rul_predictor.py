"""RUL (Remaining Useful Life) Predictor for the Digital Twin Engine.

Subscribes to corrected state vectors from the EnKF correction engine,
accumulates per-engine sensor readings into cycles, and computes RUL
estimates using a piecewise-linear degradation model.

The predictor establishes a baseline from the first 10 cycles of operation
for each engine unit, then computes normalized deviation from baseline
to estimate remaining useful life.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Dict, List, Optional

from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import CORRECTIONS_STATE
from digital_twin_engine.prognostics.models import (
    EngineRULState,
    RUL_MAX,
    RUL_MIN,
    SensorBaseline,
)
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("rul_predictor")

# Number of cycles used to establish sensor baselines
BASELINE_CYCLES = 10

# Minimum number of valid sensor readings to consider a cycle complete
MIN_VALID_SENSORS = 14

# Total expected sensors per engine (C-MAPSS has 21 sensors)
EXPECTED_SENSORS = 21

# RUL threshold for urgent attention events
URGENT_RUL_THRESHOLD = 30

# Regex pattern to extract engine ID and sensor name from sensor_id
_SENSOR_ID_PATTERN = re.compile(r"^engine-(\d{3})-(.+)$")

# Maximum deviation multiplier for RUL linear decrease
# When deviation reaches this many std devs from baseline, RUL = 0
_MAX_DEVIATION_MULTIPLIER = 5.0


class RULPredictor:
    """Computes Remaining Useful Life estimates for engine units.

    Subscribes to corrections.state broker topic, accumulates sensor
    readings per engine per cycle, and computes RUL using a piecewise-linear
    degradation model based on normalized deviation from baseline.

    The model works as follows:
    - Baseline: Mean + std of each sensor over first 10 cycles
    - Deviation: Normalized distance of current sensor values from baseline
    - Piecewise-linear model:
        - RUL = 125 when all sensors are within 1 std dev of baseline
        - Linear decrease toward 0 as max deviation grows beyond 1 std dev
    - Output capped to [0, 125] inclusive
    - Emits urgent_attention event when RUL < 30
    - Incomplete cycle (< 14 valid sensors): retain previous RUL
    - First incomplete cycle: assign RUL = 125
    """

    def __init__(
        self, broker: BrokerBackend, ws_manager: WebSocketBroadcastManager
    ) -> None:
        self._broker = broker
        self._ws_manager = ws_manager

        # Per-engine state tracking
        # engine_id -> list of cycle readings (each cycle is {sensor_name: value})
        self._cycle_history: Dict[int, List[Dict[str, float]]] = defaultdict(list)

        # engine_id -> current accumulating cycle readings {sensor_name: value}
        self._current_cycle: Dict[int, Dict[str, float]] = defaultdict(dict)

        # engine_id -> set of sensor names seen in the current cycle
        self._current_cycle_sensors: Dict[int, set] = defaultdict(set)

        # engine_id -> computed baselines {sensor_name: SensorBaseline}
        self._baselines: Dict[int, Dict[str, SensorBaseline]] = {}

        # engine_id -> current RUL state
        self._engine_states: Dict[int, EngineRULState] = {}

    async def start(self) -> None:
        """Subscribe to corrections.state and begin processing."""
        await self._broker.subscribe(
            CORRECTIONS_STATE, "rul_predictor", self.on_correction
        )
        logger.info("RUL Predictor started, subscribed to corrections.state")

    async def stop(self) -> None:
        """Clean shutdown."""
        logger.info("RUL Predictor stopped")

    async def on_correction(self, topic: str, key: str, message: bytes) -> None:
        """Callback for each corrected state vector. Accumulates per-engine.

        Each message represents a single sensor reading for an engine.
        When a sensor is seen for the second time (indicating a new cycle),
        the previous cycle is finalized and RUL is computed.

        Args:
            topic: The broker topic (corrections.state).
            key: The sensor_id key (format: engine-{id:03d}-{sensor_name}).
            message: JSON-encoded correction payload.
        """
        # Parse the sensor_id from the key
        match = _SENSOR_ID_PATTERN.match(key)
        if not match:
            logger.warning("Unrecognized sensor_id format", sensor_id=key)
            return

        engine_id = int(match.group(1))
        sensor_name = match.group(2)

        # Parse the message payload
        try:
            payload = json.loads(message)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "Failed to decode correction message",
                sensor_id=key,
                error=str(exc),
            )
            return

        # Extract the sensor value from the corrected state vector
        corrected_values = payload.get("corrected_state_vector", [])
        if not corrected_values:
            logger.warning("Empty corrected_state_vector", sensor_id=key)
            return

        # Use the first value in the state vector as the sensor reading
        value = corrected_values[0]
        if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
            logger.warning(
                "Invalid sensor value",
                sensor_id=key,
                value=value,
            )
            return

        # Check if this sensor was already seen in the current cycle
        # (indicates a new cycle has started)
        if sensor_name in self._current_cycle_sensors[engine_id]:
            # Finalize the current cycle
            await self._finalize_cycle(engine_id)

        # Accumulate this sensor reading
        self._current_cycle[engine_id][sensor_name] = float(value)
        self._current_cycle_sensors[engine_id].add(sensor_name)

    async def _finalize_cycle(self, engine_id: int) -> None:
        """Finalize the current cycle for an engine and compute RUL.

        Moves current cycle readings to history, computes baselines if
        enough cycles are available, and computes the RUL estimate.
        """
        cycle_readings = self._current_cycle[engine_id].copy()
        valid_sensor_count = len(cycle_readings)

        # Reset current cycle accumulator
        self._current_cycle[engine_id] = {}
        self._current_cycle_sensors[engine_id] = set()

        # Determine cycle number
        cycle_number = len(self._cycle_history[engine_id])

        # Check for incomplete cycle (< 14 valid sensors)
        is_incomplete = valid_sensor_count < MIN_VALID_SENSORS

        if is_incomplete:
            if engine_id not in self._engine_states:
                # First incomplete cycle: assign RUL = 125 (Requirement 1.6)
                self._engine_states[engine_id] = EngineRULState(
                    engine_id=engine_id,
                    current_rul=RUL_MAX,
                    cycle_count=cycle_number + 1,
                    baseline_established=False,
                    last_update_cycle=cycle_number,
                    is_incomplete=True,
                )
                logger.info(
                    "First incomplete cycle, assigning RUL=125",
                    engine_id=engine_id,
                    valid_sensors=valid_sensor_count,
                )
            else:
                # Retain previous RUL and flag as incomplete (Requirement 1.5)
                state = self._engine_states[engine_id]
                self._engine_states[engine_id] = EngineRULState(
                    engine_id=state.engine_id,
                    current_rul=state.current_rul,
                    cycle_count=cycle_number + 1,
                    baseline_established=state.baseline_established,
                    last_update_cycle=cycle_number,
                    is_incomplete=True,
                )
                logger.debug(
                    "Incomplete cycle, retaining previous RUL",
                    engine_id=engine_id,
                    rul=state.current_rul,
                    valid_sensors=valid_sensor_count,
                )

            # Store the cycle readings in history even if incomplete
            self._cycle_history[engine_id].append(cycle_readings)
            await self._broadcast_rul_update(engine_id, cycle_number)
            return

        # Store complete cycle in history
        self._cycle_history[engine_id].append(cycle_readings)

        # Compute/update baselines if we have enough cycles
        if len(self._cycle_history[engine_id]) >= BASELINE_CYCLES:
            if engine_id not in self._baselines:
                self._compute_baselines(engine_id)

        # Compute RUL
        rul = self.compute_rul(engine_id)

        # Update engine state
        baseline_established = engine_id in self._baselines
        self._engine_states[engine_id] = EngineRULState(
            engine_id=engine_id,
            current_rul=rul,
            cycle_count=cycle_number + 1,
            baseline_established=baseline_established,
            last_update_cycle=cycle_number,
            is_incomplete=False,
        )

        # Emit urgent_attention event if RUL < 30 (Requirement 1.3)
        if rul < URGENT_RUL_THRESHOLD:
            await self._emit_urgent_attention(engine_id, rul, cycle_number)

        # Broadcast RUL update via WebSocket
        await self._broadcast_rul_update(engine_id, cycle_number)

    def _compute_baselines(self, engine_id: int) -> None:
        """Compute baseline statistics from first 10 cycles.

        For each sensor that appears in the first 10 cycles, computes
        mean and standard deviation to establish the nominal operating range.
        """
        history = self._cycle_history[engine_id]
        baseline_cycles = history[:BASELINE_CYCLES]

        # Collect all values per sensor across baseline cycles
        sensor_values: Dict[str, List[float]] = defaultdict(list)
        for cycle in baseline_cycles:
            for sensor_name, value in cycle.items():
                sensor_values[sensor_name].append(value)

        # Compute mean and std for each sensor
        baselines: Dict[str, SensorBaseline] = {}
        for sensor_name, values in sensor_values.items():
            n = len(values)
            if n == 0:
                continue
            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n
            std = math.sqrt(variance)

            baselines[sensor_name] = SensorBaseline(
                sensor_name=sensor_name,
                mean=mean,
                std=std,
                sample_count=n,
            )

        self._baselines[engine_id] = baselines
        logger.info(
            "Baseline computed",
            engine_id=engine_id,
            sensor_count=len(baselines),
        )

    def compute_rul(self, engine_id: int) -> int:
        """Compute RUL for engine using piecewise-linear degradation model.

        Returns integer cycles remaining [0, 125].

        The model:
        - If no baseline established yet, return RUL_MAX (125)
        - Compute normalized deviation for each sensor:
          deviation = |current - mean| / std
        - Take the maximum deviation across all sensors
        - Piecewise-linear:
          - If max_deviation <= 1.0: RUL = 125 (within 1 std dev)
          - If max_deviation > 1.0: RUL decreases linearly from 125 to 0
            as deviation goes from 1.0 to MAX_DEVIATION_MULTIPLIER
        - Cap output to [0, 125]
        """
        if engine_id not in self._baselines:
            return RUL_MAX

        baselines = self._baselines[engine_id]
        history = self._cycle_history[engine_id]

        if not history:
            return RUL_MAX

        # Use the latest complete cycle
        latest_cycle = history[-1]

        if not latest_cycle:
            return RUL_MAX

        # Compute normalized deviation for each sensor with a baseline
        max_deviation = 0.0
        sensors_compared = 0

        for sensor_name, baseline in baselines.items():
            if sensor_name not in latest_cycle:
                continue
            if baseline.std == 0.0:
                # If std is 0, sensor is constant - any difference is significant
                if latest_cycle[sensor_name] != baseline.mean:
                    max_deviation = _MAX_DEVIATION_MULTIPLIER
                continue

            deviation = abs(latest_cycle[sensor_name] - baseline.mean) / baseline.std
            max_deviation = max(max_deviation, deviation)
            sensors_compared += 1

        if sensors_compared == 0:
            return RUL_MAX

        # Piecewise-linear model
        if max_deviation <= 1.0:
            # Within 1 std dev: RUL = 125 (Requirement 1.2)
            rul = RUL_MAX
        else:
            # Linear decrease from 125 to 0 as deviation goes from 1.0 to MAX
            fraction_remaining = 1.0 - (
                (max_deviation - 1.0) / (_MAX_DEVIATION_MULTIPLIER - 1.0)
            )
            rul = int(round(RUL_MAX * max(0.0, fraction_remaining)))

        # Cap to [0, 125] (Requirement 1.1)
        rul = max(RUL_MIN, min(RUL_MAX, rul))

        return rul

    def get_engine_state(self, engine_id: int) -> EngineRULState:
        """Return current RUL state for an engine.

        If no state exists yet, returns a default state with RUL = 125.
        """
        if engine_id in self._engine_states:
            return self._engine_states[engine_id]

        return EngineRULState(
            engine_id=engine_id,
            current_rul=RUL_MAX,
            cycle_count=0,
            baseline_established=False,
            last_update_cycle=0,
            is_incomplete=False,
        )

    async def _emit_urgent_attention(
        self, engine_id: int, rul: int, cycle_number: int
    ) -> None:
        """Emit urgent_attention event when RUL < 30.

        Broadcasts via WebSocket to alert the frontend of critical RUL.
        """
        logger.warning(
            "Urgent attention: low RUL",
            engine_id=engine_id,
            rul=rul,
            cycle=cycle_number,
        )
        await self._ws_manager.broadcast(
            "urgent_attention",
            {
                "engine_id": engine_id,
                "rul_cycles": rul,
                "cycle_number": cycle_number,
            },
        )

    async def _broadcast_rul_update(self, engine_id: int, cycle_number: int) -> None:
        """Broadcast RUL update via WebSocket."""
        state = self._engine_states.get(engine_id)
        if state is None:
            return

        await self._ws_manager.broadcast(
            "rul_update",
            {
                "engine_id": engine_id,
                "rul_cycles": state.current_rul,
                "cycle_number": cycle_number,
                "is_urgent": state.current_rul < URGENT_RUL_THRESHOLD,
            },
        )
