"""Health Index Aggregator for Digital Twin Engine.

Computes a composite health score (0.0-1.0) per engine unit per cycle by
subscribing to the corrections.state broker topic, accumulating sensor
readings per engine per cycle, normalizing against baselines computed from
the first 10 cycles, and applying a weighted deviation formula.

Health Index Formula:
    HI = 1.0 - weighted_sum(|sensor_value - baseline_mean| / baseline_std)
    Clamped to [0.0, 1.0].

Weighting Scheme:
    - HPC outlet temperature (hpc_outlet_temp_total): 25%
    - Physical core speed (physical_core_speed_rpm): 15%
    - Corrected fan speed (corrected_fan_speed_rpm): 15%
    - Remaining 18 sensors: 45% distributed equally (~2.5% each)

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from digital_twin_engine.prognostics.degradation_tracker import DegradationCurveTracker

from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import CORRECTIONS_STATE
from digital_twin_engine.prognostics.models import EngineHealthState, SensorBaseline
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("health_index_aggregator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All 21 C-MAPSS sensor channel names
ALL_SENSORS: List[str] = [
    "fan_inlet_temp_total",
    "lpc_outlet_temp_total",
    "hpc_outlet_temp_total",
    "lpt_outlet_temp_total",
    "fan_inlet_pressure_total",
    "bypass_duct_pressure_total",
    "hpc_outlet_pressure_total",
    "physical_fan_speed_rpm",
    "physical_core_speed_rpm",
    "engine_pressure_ratio",
    "hpc_outlet_static_pressure",
    "fuel_flow_ratio_ps30",
    "corrected_fan_speed_rpm",
    "corrected_core_speed_rpm",
    "bypass_ratio",
    "burner_fuel_air_ratio",
    "bleed_enthalpy",
    "demanded_fan_speed_rpm",
    "demanded_corrected_fan_speed",
    "hpt_coolant_bleed",
    "lpt_coolant_bleed",
]

# High-weight sensors and their weights
HIGH_WEIGHT_SENSORS: Dict[str, float] = {
    "hpc_outlet_temp_total": 0.25,
    "physical_core_speed_rpm": 0.15,
    "corrected_fan_speed_rpm": 0.15,
}

# Number of remaining sensors
_REMAINING_COUNT = len(ALL_SENSORS) - len(HIGH_WEIGHT_SENSORS)  # 18

# Weight for each of the remaining 18 sensors
_REMAINING_WEIGHT = 0.45 / _REMAINING_COUNT  # ~0.025

# Minimum valid sensor readings required for a complete cycle
MIN_VALID_SENSORS = 14

# Baseline cycle count
BASELINE_CYCLES = 10

# Critical health threshold
CRITICAL_HEALTH_THRESHOLD = 0.4

# Regex to extract engine_id from sensor_id
_SENSOR_ID_PATTERN = re.compile(r"^engine-(\d{3})-(.+)$")


def get_sensor_weight(sensor_name: str) -> float:
    """Return the weight for a given sensor channel.

    Args:
        sensor_name: Name of the sensor channel.

    Returns:
        Weight as a float. High-weight sensors get 0.25/0.15/0.15,
        remaining sensors get ~0.025 each.
    """
    return HIGH_WEIGHT_SENSORS.get(sensor_name, _REMAINING_WEIGHT)


def build_weight_map() -> Dict[str, float]:
    """Build the complete sensor-to-weight mapping for all 21 sensors.

    Returns:
        Dict mapping each sensor name to its weight. Weights sum to 1.0.
    """
    weights: Dict[str, float] = {}
    for sensor in ALL_SENSORS:
        weights[sensor] = get_sensor_weight(sensor)
    return weights


# Pre-computed weight map
WEIGHT_MAP: Dict[str, float] = build_weight_map()


# ---------------------------------------------------------------------------
# Engine Cycle Accumulator
# ---------------------------------------------------------------------------


class _EngineCycleAccumulator:
    """Accumulates per-sensor readings for one engine within a cycle.

    Since sensor data arrives as individual messages, this collects readings
    until a full cycle is received (all 21 sensors or a timeout/new cycle).
    """

    def __init__(self) -> None:
        self.readings: Dict[str, float] = {}

    def add_reading(self, sensor_name: str, value: float) -> None:
        """Add a sensor reading to the current cycle accumulation."""
        self.readings[sensor_name] = value

    def is_complete(self) -> bool:
        """Check if we have received all 21 sensor readings."""
        return len(self.readings) >= len(ALL_SENSORS)

    def has_minimum_readings(self) -> bool:
        """Check if we have at least MIN_VALID_SENSORS readings."""
        return len(self.readings) >= MIN_VALID_SENSORS

    def get_readings(self) -> Dict[str, float]:
        """Return a copy of accumulated readings."""
        return dict(self.readings)

    def reset(self) -> None:
        """Clear accumulated readings for a new cycle."""
        self.readings.clear()


# ---------------------------------------------------------------------------
# Engine Baseline State
# ---------------------------------------------------------------------------


class _EngineBaselineState:
    """Tracks baseline computation state for a single engine.

    Accumulates sensor values over cycles and computes mean/std baselines
    once enough cycles are available.
    """

    def __init__(self) -> None:
        # sensor_name -> list of values across cycles
        self._history: Dict[str, List[float]] = {}
        self._cycle_count: int = 0
        self._baselines: Optional[Dict[str, SensorBaseline]] = None

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def baseline_established(self) -> bool:
        return self._cycle_count >= BASELINE_CYCLES

    def record_cycle(self, cycle_readings: Dict[str, float]) -> None:
        """Record a complete cycle of readings for baseline computation.

        Only the first BASELINE_CYCLES cycles contribute to baseline.
        """
        self._cycle_count += 1

        if self._cycle_count <= BASELINE_CYCLES:
            for sensor_name, value in cycle_readings.items():
                if sensor_name not in self._history:
                    self._history[sensor_name] = []
                self._history[sensor_name].append(value)

            # Recompute baselines with available data
            self._compute_baselines()

    def _compute_baselines(self) -> None:
        """Compute mean and std for each sensor from accumulated history."""
        baselines: Dict[str, SensorBaseline] = {}
        for sensor_name, values in self._history.items():
            n = len(values)
            if n == 0:
                continue
            mean = sum(values) / n
            if n > 1:
                variance = sum((v - mean) ** 2 for v in values) / (n - 1)
                std = math.sqrt(variance)
            else:
                # With only 1 sample, use a small default std to avoid division by zero
                std = 0.0
            baselines[sensor_name] = SensorBaseline(
                sensor_name=sensor_name,
                mean=mean,
                std=std,
                sample_count=n,
            )
        self._baselines = baselines

    def get_baselines(self) -> Optional[Dict[str, SensorBaseline]]:
        """Return computed baselines, or None if no cycles recorded yet."""
        return self._baselines


# ---------------------------------------------------------------------------
# Health Index Aggregator
# ---------------------------------------------------------------------------


class HealthIndexAggregator:
    """Computes composite health index (0.0-1.0) per engine per cycle.

    Subscribes to the corrections.state broker topic, accumulates sensor
    readings per engine, and computes a weighted deviation-based health index
    after each complete cycle.

    Weighting Scheme:
        - HPC outlet temperature: 25%
        - Physical core speed: 15%
        - Corrected fan speed: 15%
        - Remaining 18 sensors: ~2.5% each

    Health Index Formula:
        HI = 1.0 - weighted_sum(|value - mean| / std)
        Clamped to [0.0, 1.0].
    """

    def __init__(
        self,
        broker: BrokerBackend,
        ws_manager: WebSocketBroadcastManager,
        degradation_tracker: Optional["DegradationCurveTracker"] = None,
    ) -> None:
        self._broker = broker
        self._ws_manager = ws_manager
        self._degradation_tracker = degradation_tracker

        # Per-engine state
        self._accumulators: Dict[int, _EngineCycleAccumulator] = {}
        self._baseline_states: Dict[int, _EngineBaselineState] = {}
        self._health_states: Dict[int, EngineHealthState] = {}

    async def start(self) -> None:
        """Subscribe to corrections.state and begin processing."""
        await self._broker.subscribe(
            CORRECTIONS_STATE,
            "health_index_aggregator",
            self._on_correction,
        )
        logger.info("Health Index Aggregator started, subscribed to corrections.state")

    async def stop(self) -> None:
        """Clean shutdown."""
        logger.info("Health Index Aggregator stopped")

    async def _on_correction(self, topic: str, key: str, message: bytes) -> None:
        """Callback for each corrected state vector message.

        Parses the sensor_id to extract engine_id and sensor_name,
        accumulates readings, and triggers health index computation
        when a full cycle is received.

        Args:
            topic: The broker topic (corrections.state).
            key: The message key (sensor_id, e.g., "engine-001-hpc_outlet_temp_total").
            message: JSON-encoded message payload.
        """
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to decode correction message", error=str(exc))
            return

        sensor_id = data.get("sensor_id", key)

        # Parse engine_id and sensor_name from the sensor_id
        match = _SENSOR_ID_PATTERN.match(sensor_id)
        if not match:
            logger.warning(
                "Unrecognized sensor_id format",
                sensor_id=sensor_id,
            )
            return

        engine_id = int(match.group(1))
        sensor_name = match.group(2)

        # Extract the corrected value
        state_vector = data.get("corrected_state_vector", [])
        if not state_vector or not isinstance(state_vector, list):
            logger.warning(
                "Missing or invalid corrected_state_vector",
                sensor_id=sensor_id,
            )
            return

        value = state_vector[0]
        if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
            logger.warning(
                "Non-numeric or invalid sensor value",
                sensor_id=sensor_id,
                value=value,
            )
            return

        # Ensure engine state structures exist
        if engine_id not in self._accumulators:
            self._accumulators[engine_id] = _EngineCycleAccumulator()
            self._baseline_states[engine_id] = _EngineBaselineState()

        accumulator = self._accumulators[engine_id]

        # Detect new cycle: if this sensor already has a reading in the
        # current accumulation, a new cycle has started
        if sensor_name in accumulator.readings:
            # Process the previous cycle before starting a new one
            await self._process_cycle(engine_id)
            accumulator.reset()

        accumulator.add_reading(sensor_name, float(value))

        # Check if cycle is complete (all 21 sensors received)
        if accumulator.is_complete():
            await self._process_cycle(engine_id)
            accumulator.reset()

    async def _process_cycle(self, engine_id: int) -> None:
        """Process a complete (or partial) cycle of sensor readings.

        Computes health index if enough readings are available, otherwise
        retains the previous health index and flags as incomplete.

        Args:
            engine_id: The engine unit identifier.
        """
        accumulator = self._accumulators[engine_id]
        baseline_state = self._baseline_states[engine_id]
        cycle_readings = accumulator.get_readings()

        # Check if we have enough valid readings
        if not accumulator.has_minimum_readings():
            # Incomplete cycle: retain previous HI
            logger.info(
                "Incomplete cycle detected, retaining previous health index",
                engine_id=engine_id,
                readings_count=len(cycle_readings),
            )
            # If no previous state exists, create one with HI=1.0
            if engine_id not in self._health_states:
                self._health_states[engine_id] = EngineHealthState(
                    engine_id=engine_id,
                    health_index=1.0,
                    cycle_count=baseline_state.cycle_count,
                    is_provisional=not baseline_state.baseline_established,
                    last_update_cycle=baseline_state.cycle_count,
                )
            return

        # Record cycle for baseline computation
        baseline_state.record_cycle(cycle_readings)

        # Compute health index
        health_index = self.compute_health_index(engine_id, cycle_readings)

        # Determine provisional flag
        is_provisional = not baseline_state.baseline_established

        # Update health state
        self._health_states[engine_id] = EngineHealthState(
            engine_id=engine_id,
            health_index=health_index,
            cycle_count=baseline_state.cycle_count,
            is_provisional=is_provisional,
            last_update_cycle=baseline_state.cycle_count,
        )

        # Broadcast health index update via WebSocket
        await self._ws_manager.broadcast(
            "health_index_update",
            {
                "engine_id": engine_id,
                "health_index": health_index,
                "cycle_number": baseline_state.cycle_count,
                "is_provisional": is_provisional,
            },
        )

        # Feed the degradation tracker if wired
        if self._degradation_tracker is not None:
            await self._degradation_tracker.record_async(
                engine_id, baseline_state.cycle_count, health_index
            )

        # Emit critical health alert if HI < 0.4
        if health_index < CRITICAL_HEALTH_THRESHOLD:
            await self._emit_critical_health_alert(
                engine_id, health_index, baseline_state.cycle_count
            )

        logger.info(
            "Health index computed",
            engine_id=engine_id,
            health_index=round(health_index, 4),
            cycle=baseline_state.cycle_count,
            is_provisional=is_provisional,
        )

    def compute_health_index(
        self, engine_id: int, cycle_readings: Dict[str, float]
    ) -> float:
        """Compute weighted Health Index from normalized sensor deviations.

        Formula: HI = 1.0 - weighted_sum(|value - mean| / std)
        Clamped to [0.0, 1.0].

        Args:
            engine_id: The engine unit identifier.
            cycle_readings: Dict mapping sensor_name to current value.

        Returns:
            Float in [0.0, 1.0] representing overall engine health.
        """
        baseline_state = self._baseline_states.get(engine_id)
        if baseline_state is None:
            return 1.0

        baselines = baseline_state.get_baselines()
        if baselines is None:
            return 1.0

        weighted_deviation_sum = 0.0
        total_weight_used = 0.0

        for sensor_name, value in cycle_readings.items():
            if sensor_name not in baselines:
                continue
            if sensor_name not in WEIGHT_MAP:
                continue

            baseline = baselines[sensor_name]
            weight = WEIGHT_MAP[sensor_name]

            # Skip sensors with zero std (no variation in baseline)
            if baseline.std <= 0.0:
                continue

            # Normalized deviation (clamped to prevent extreme values from
            # low-sample-count baselines overwhelming the health index)
            deviation = abs(value - baseline.mean) / baseline.std
            deviation = min(deviation, 3.0)  # Cap at 3 std devs
            weighted_deviation_sum += weight * deviation
            total_weight_used += weight

        # If no sensors contributed, return 1.0 (no deviation measurable)
        if total_weight_used <= 0.0:
            return 1.0

        # Re-normalize if not all sensors contributed
        # This ensures the result reflects only the available sensors
        normalized_deviation = weighted_deviation_sum / total_weight_used
        health_index = 1.0 - normalized_deviation

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, health_index))

    def get_baselines(self, engine_id: int) -> Optional[Dict[str, SensorBaseline]]:
        """Return computed baselines for an engine.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            Dict mapping sensor_name to SensorBaseline, or None if no
            cycles have been recorded yet.
        """
        baseline_state = self._baseline_states.get(engine_id)
        if baseline_state is None:
            return None
        return baseline_state.get_baselines()

    def get_health_state(self, engine_id: int) -> Optional[EngineHealthState]:
        """Return current health state for an engine.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            EngineHealthState or None if engine not yet tracked.
        """
        return self._health_states.get(engine_id)

    async def _emit_critical_health_alert(
        self, engine_id: int, health_index: float, cycle_number: int
    ) -> None:
        """Emit a critical health alert when HI drops below threshold.

        Args:
            engine_id: The engine unit identifier.
            health_index: The computed health index value.
            cycle_number: The current cycle number.
        """
        logger.warning(
            "Critical health alert",
            engine_id=engine_id,
            health_index=round(health_index, 4),
            cycle_number=cycle_number,
        )
        await self._ws_manager.broadcast(
            "critical_health_alert",
            {
                "engine_id": engine_id,
                "health_index": health_index,
                "cycle_number": cycle_number,
            },
        )
