"""Component Health Mapper for per-subsystem health assessment.

Maps 21 C-MAPSS sensor channels to 6 turbofan engine subsystems (fan, LPC,
HPC, HPT, LPT, combustor) and computes per-subsystem health scores with
classification and hysteresis-based state transitions.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import CORRECTIONS_STATE
from digital_twin_engine.prognostics.models import SensorBaseline, SubsystemHealth
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("component_health_mapper")

# ---------------------------------------------------------------------------
# Sensor-to-Subsystem Mapping (21 sensors → 6 subsystems)
# ---------------------------------------------------------------------------

SUBSYSTEM_SENSOR_MAP: Dict[str, List[str]] = {
    "fan": [
        "fan_inlet_temp_total",
        "fan_inlet_pressure_total",
        "physical_fan_speed_rpm",
        "corrected_fan_speed_rpm",
        "demanded_fan_speed_rpm",
    ],
    "lpc": [
        "lpc_outlet_temp_total",
        "bypass_ratio",
    ],
    "hpc": [
        "hpc_outlet_temp_total",
        "hpc_outlet_pressure_total",
        "hpc_outlet_static_pressure",
        "physical_core_speed_rpm",
        "corrected_core_speed_rpm",
    ],
    "hpt": [
        "lpt_outlet_temp_total",
        "hpt_coolant_bleed",
        "demanded_corrected_fan_speed",
    ],
    "lpt": [
        "lpt_coolant_bleed",
    ],
    "combustor": [
        "fuel_flow_ratio_ps30",
        "burner_fuel_air_ratio",
        "engine_pressure_ratio",
        "bleed_enthalpy",
        "bypass_duct_pressure_total",
    ],
}

# Classification thresholds
NOMINAL_THRESHOLD = 0.7
DEGRADED_THRESHOLD = 0.4
HYSTERESIS_BAND = 0.03

# Number of baseline cycles
BASELINE_CYCLES = 10


class ComponentHealthMapper:
    """Maps sensor channels to engine subsystems and computes health scores.

    Subscribes to the corrections.state broker topic, accumulates per-engine
    per-cycle sensor readings, computes per-subsystem health scores by
    normalizing sensor deviations from baseline, and classifies subsystem
    health with hysteresis-based state transitions.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """

    def __init__(self, broker: BrokerBackend, ws_manager: Any) -> None:
        """Initialize the Component Health Mapper.

        Args:
            broker: Message broker backend for subscribing to correction events.
            ws_manager: WebSocket broadcast manager for emitting updates.
        """
        self._broker = broker
        self._ws_manager = ws_manager

        # Per-engine baseline accumulation: {engine_id: {sensor_name: [values]}}
        self._baseline_accumulator: Dict[int, Dict[str, List[float]]] = {}

        # Per-engine computed baselines: {engine_id: {sensor_name: SensorBaseline}}
        self._baselines: Dict[int, Dict[str, SensorBaseline]] = {}

        # Per-engine cycle count
        self._cycle_counts: Dict[int, int] = {}

        # Per-engine current cycle accumulation: {engine_id: {sensor_name: value}}
        self._current_cycle: Dict[int, Dict[str, float]] = {}

        # Per-engine previous subsystem states: {engine_id: {subsystem: SubsystemHealth}}
        self._previous_states: Dict[int, Dict[str, SubsystemHealth]] = {}

        # Track which cycle we're currently accumulating
        self._current_cycle_id: Dict[int, Optional[int]] = {}

    async def start(self) -> None:
        """Subscribe to corrections.state and begin processing."""
        await self._broker.subscribe(
            CORRECTIONS_STATE,
            "component_health_mapper",
            self._on_correction,
        )
        logger.info("ComponentHealthMapper started, subscribed to corrections.state")

    async def stop(self) -> None:
        """Clean shutdown."""
        logger.info("ComponentHealthMapper stopped")

    async def _on_correction(self, topic: str, key: str, message: bytes) -> None:
        """Callback for each corrected state vector message.

        Messages arrive per-sensor with key format: "engine-{id:03d}-{sensor_name}"
        Accumulates readings per engine per cycle and triggers computation
        when a duplicate sensor is detected (indicating a new cycle has started).
        """
        try:
            payload = json.loads(message)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Failed to decode correction message", error=str(exc))
            return

        # Parse engine_id and sensor_name from the key
        engine_id, sensor_name = self._parse_sensor_key(key)
        if engine_id is None or sensor_name is None:
            return

        # Extract sensor value from corrected_state_vector
        state_vector = payload.get("corrected_state_vector", [])
        if not state_vector or not isinstance(state_vector, list):
            # Fallback: try legacy "value" field
            value = payload.get("value")
        else:
            value = state_vector[0]

        # Check if value is valid (numeric and finite)
        if value is None or not isinstance(value, (int, float)):
            return
        if math.isnan(value) or math.isinf(value):
            return

        # Detect cycle boundary — if this sensor was already seen in the
        # current cycle, a new cycle has started. Finalize the previous one.
        if engine_id not in self._current_cycle:
            self._current_cycle[engine_id] = {}

        if sensor_name in self._current_cycle.get(engine_id, {}):
            # Finalize the previous cycle
            cycle_num = self._current_cycle_id.get(engine_id, 0)
            await self._process_cycle(engine_id, cycle_num)
            # Reset for new cycle
            self._current_cycle[engine_id] = {}
            self._current_cycle_id[engine_id] = cycle_num + 1

        # Accumulate sensor reading for current cycle
        self._current_cycle[engine_id][sensor_name] = float(value)
        if engine_id not in self._current_cycle_id:
            self._current_cycle_id[engine_id] = 0

    def _parse_sensor_key(self, key: str) -> Tuple[Optional[int], Optional[str]]:
        """Parse engine ID and sensor name from sensor key.

        Expected format: "engine-{id:03d}-{sensor_name}"
        e.g., "engine-001-hpc_outlet_temp_total"

        Returns:
            Tuple of (engine_id, sensor_name) or (None, None) if parsing fails.
        """
        if not key.startswith("engine-"):
            logger.warning("Unexpected key format", key=key)
            return None, None

        parts = key.split("-", 2)
        if len(parts) < 3:
            logger.warning("Unexpected key format", key=key)
            return None, None

        try:
            engine_id = int(parts[1])
        except ValueError:
            logger.warning("Invalid engine ID in key", key=key)
            return None, None

        sensor_name = parts[2]
        return engine_id, sensor_name

    async def _process_cycle(self, engine_id: int, cycle: int) -> None:
        """Process a completed cycle of sensor data for an engine.

        Accumulates baselines during the first 10 cycles, then computes
        subsystem health scores and classifications.
        """
        readings = self._current_cycle.get(engine_id, {})
        if not readings:
            return

        # Update cycle count
        self._cycle_counts[engine_id] = self._cycle_counts.get(engine_id, 0) + 1
        cycle_count = self._cycle_counts[engine_id]

        # Accumulate baselines during first 10 cycles
        if cycle_count <= BASELINE_CYCLES:
            self._accumulate_baseline(engine_id, readings)

        # Compute baselines after 10 cycles if not yet established
        if cycle_count == BASELINE_CYCLES and engine_id not in self._baselines:
            self._compute_baselines(engine_id)

        # Compute subsystem health if baselines are established
        if engine_id in self._baselines:
            subsystem_health = self.compute_subsystem_health(engine_id, readings)

            # Broadcast update
            await self._broadcast_update(engine_id, cycle, subsystem_health)

        # Clear current cycle readings for this engine
        self._current_cycle[engine_id] = {}

    def _accumulate_baseline(
        self, engine_id: int, readings: Dict[str, float]
    ) -> None:
        """Accumulate sensor readings for baseline computation."""
        if engine_id not in self._baseline_accumulator:
            self._baseline_accumulator[engine_id] = {}

        for sensor_name, value in readings.items():
            if sensor_name not in self._baseline_accumulator[engine_id]:
                self._baseline_accumulator[engine_id][sensor_name] = []
            self._baseline_accumulator[engine_id][sensor_name].append(value)

    def _compute_baselines(self, engine_id: int) -> None:
        """Compute sensor baselines (mean + std) from accumulated data."""
        accumulator = self._baseline_accumulator.get(engine_id, {})
        baselines: Dict[str, SensorBaseline] = {}

        for sensor_name, values in accumulator.items():
            if not values:
                continue
            n = len(values)
            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
            std = math.sqrt(variance)

            baselines[sensor_name] = SensorBaseline(
                sensor_name=sensor_name,
                mean=mean,
                std=std,
                sample_count=n,
            )

        self._baselines[engine_id] = baselines
        logger.info(
            "Baselines computed for engine",
            engine_id=engine_id,
            sensor_count=len(baselines),
        )

    def compute_subsystem_health(
        self, engine_id: int, cycle_readings: Dict[str, float]
    ) -> Dict[str, SubsystemHealth]:
        """Compute health for each of 6 subsystems.

        For each subsystem, normalizes sensor deviations from baseline and
        averages the normalized scores. Applies classification with hysteresis
        and handles incomplete subsystems.

        Args:
            engine_id: The engine unit identifier.
            cycle_readings: Dict mapping sensor_name to current reading value.

        Returns:
            Dict mapping subsystem name to SubsystemHealth.
        """
        baselines = self._baselines.get(engine_id, {})
        previous_states = self._previous_states.get(engine_id, {})
        results: Dict[str, SubsystemHealth] = {}

        for subsystem_name, sensor_list in SUBSYSTEM_SENSOR_MAP.items():
            total_sensors = len(sensor_list)
            half_threshold = math.ceil(total_sensors / 2)

            # Collect valid normalized deviations for this subsystem
            valid_scores: List[float] = []
            for sensor_name in sensor_list:
                if sensor_name not in cycle_readings:
                    continue
                if sensor_name not in baselines:
                    continue

                baseline = baselines[sensor_name]
                value = cycle_readings[sensor_name]

                # Normalize deviation: score = 1.0 - |value - mean| / std
                # When std is 0, sensor is constant → any deviation is significant
                if baseline.std > 0:
                    deviation = abs(value - baseline.mean) / baseline.std
                else:
                    # If std is 0, the sensor never varied; deviation from mean means degradation
                    deviation = 0.0 if value == baseline.mean else 1.0

                # Convert deviation to health score: 1.0 = nominal, approaches 0.0 as deviation grows
                # Cap deviation at a maximum to keep score in [0, 1]
                sensor_health = max(0.0, 1.0 - deviation / 3.0)
                valid_scores.append(sensor_health)

            # Check for incomplete subsystem (< half valid sensors)
            valid_count = len(valid_scores)
            is_incomplete = valid_count < half_threshold

            if is_incomplete:
                # Retain previous state if available
                if subsystem_name in previous_states:
                    prev = previous_states[subsystem_name]
                    results[subsystem_name] = SubsystemHealth(
                        name=subsystem_name,
                        health_score=prev.health_score,
                        classification=prev.classification,
                        is_incomplete=True,
                    )
                else:
                    # No previous state, default to nominal
                    results[subsystem_name] = SubsystemHealth(
                        name=subsystem_name,
                        health_score=1.0,
                        classification="nominal",
                        is_incomplete=True,
                    )
                continue

            # Compute average health score for subsystem
            health_score = sum(valid_scores) / len(valid_scores)
            health_score = max(0.0, min(1.0, health_score))

            # Apply classification with hysteresis
            prev_state = previous_states.get(subsystem_name)
            previous_classification = prev_state.classification if prev_state else "nominal"
            previous_score = prev_state.health_score if prev_state else 1.0

            classification = self.get_classification(
                health_score, previous_classification, previous_score
            )

            results[subsystem_name] = SubsystemHealth(
                name=subsystem_name,
                health_score=health_score,
                classification=classification,
                is_incomplete=False,
            )

        # Emit state transition events for classification changes
        self._emit_transition_events(engine_id, previous_states, results)

        # Store current states as previous for next cycle
        self._previous_states[engine_id] = results

        return results

    def get_classification(
        self, health_score: float, previous: str, previous_score: float
    ) -> str:
        """Apply thresholds with hysteresis to determine classification.

        Hysteresis prevents oscillation at boundaries by requiring the score
        to move at least 0.03 beyond a threshold before recognizing a transition.

        Transition rules:
        - nominal → degraded: score must drop below 0.7 - 0.03 = 0.67
        - degraded → nominal: score must rise above 0.7 + 0.03 = 0.73
        - degraded → critical: score must drop below 0.4 - 0.03 = 0.37
        - critical → degraded: score must rise above 0.4 + 0.03 = 0.43

        Args:
            health_score: Current subsystem health score [0.0, 1.0].
            previous: Previous classification ("nominal", "degraded", "critical").
            previous_score: Previous health score (unused but available for reference).

        Returns:
            Classification string: "nominal", "degraded", or "critical".
        """
        if previous == "nominal":
            # To transition to degraded, must drop below threshold - hysteresis
            if health_score < NOMINAL_THRESHOLD - HYSTERESIS_BAND:
                # Check if we should go directly to critical
                if health_score < DEGRADED_THRESHOLD - HYSTERESIS_BAND:
                    return "critical"
                return "degraded"
            return "nominal"

        elif previous == "degraded":
            # To transition to nominal, must rise above threshold + hysteresis
            if health_score >= NOMINAL_THRESHOLD + HYSTERESIS_BAND:
                return "nominal"
            # To transition to critical, must drop below threshold - hysteresis
            if health_score < DEGRADED_THRESHOLD - HYSTERESIS_BAND:
                return "critical"
            return "degraded"

        elif previous == "critical":
            # To transition to degraded, must rise above threshold + hysteresis
            if health_score >= DEGRADED_THRESHOLD + HYSTERESIS_BAND:
                # Check if we should go directly to nominal
                if health_score >= NOMINAL_THRESHOLD + HYSTERESIS_BAND:
                    return "nominal"
                return "degraded"
            return "critical"

        # Default (should not reach here with valid inputs)
        if health_score >= NOMINAL_THRESHOLD:
            return "nominal"
        elif health_score >= DEGRADED_THRESHOLD:
            return "degraded"
        return "critical"

    def _emit_transition_events(
        self,
        engine_id: int,
        previous_states: Dict[str, SubsystemHealth],
        current_states: Dict[str, SubsystemHealth],
    ) -> None:
        """Emit state transition events when classification changes after hysteresis.

        Requirements: 4.5
        """
        for subsystem_name, current in current_states.items():
            if current.is_incomplete:
                continue

            prev = previous_states.get(subsystem_name)
            if prev is None:
                # First time seeing this subsystem, no transition
                continue

            if prev.classification != current.classification:
                logger.info(
                    "Subsystem state transition",
                    engine_id=engine_id,
                    subsystem=subsystem_name,
                    previous_classification=prev.classification,
                    new_classification=current.classification,
                    health_score=current.health_score,
                )

    async def _broadcast_update(
        self,
        engine_id: int,
        cycle: int,
        subsystem_health: Dict[str, SubsystemHealth],
    ) -> None:
        """Broadcast subsystem health update via WebSocket.

        Requirements: 8.3
        """
        payload = {
            "engine_id": engine_id,
            "cycle_number": cycle,
            "subsystems": [
                {
                    "name": sh.name,
                    "health_score": sh.health_score,
                    "classification": sh.classification,
                    "is_incomplete": sh.is_incomplete,
                }
                for sh in subsystem_health.values()
            ],
        }
        await self._ws_manager.broadcast("subsystem_health_update", payload)

    def get_subsystem_health(
        self, engine_id: int
    ) -> Optional[Dict[str, SubsystemHealth]]:
        """Return current subsystem health states for an engine.

        Returns None if no health data has been computed yet.
        """
        return self._previous_states.get(engine_id)

    def get_baselines(
        self, engine_id: int
    ) -> Optional[Dict[str, SensorBaseline]]:
        """Return computed baselines for an engine.

        Returns None if baselines have not yet been established (< 10 cycles).
        """
        return self._baselines.get(engine_id)
