"""Fault injection for demonstrating EnKF resilience.

Injects artificial sensor faults as a transform layer between raw sensor data
and the ingestion pipeline. The EnKF sees the corrupted data and must filter
it out, proving its adaptive filtering capability.

Supported fault types:
- spike: Sudden percentage increase (raw * (1 + magnitude/100))
- drift: Gradual linear deviation (raw + magnitude/duration * elapsed_cycles)
- dropout: Sensor reports 0.0 (wins over all other transforms)
- noise: Gaussian noise added (raw + N(0, magnitude))

Multiple faults on the same sensor compose additively, except dropout which
wins over all other transforms (if a sensor is dead, it reports 0).

Performance: apply() is pure computation — no awaits, no I/O. Called
synchronously inside the adapter's event yield loop. With no active faults
for a sensor, returns immediately after a dict lookup (fast path).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


@dataclass
class FaultInjection:
    """Represents an active fault injection."""

    injection_id: str
    sensor_id: str
    fault_type: str  # "spike" | "drift" | "dropout" | "noise"
    magnitude: float
    duration_cycles: int
    remaining_cycles: int
    elapsed_cycles: int = 0


class FaultInjector:
    """Injects artificial sensor faults to demonstrate EnKF resilience.

    Active faults are applied as a transform layer between raw sensor data
    and the ingestion pipeline. Multiple faults can be active simultaneously
    on the same sensor (they compose additively, except dropout wins).

    Thread-safety: This class is NOT thread-safe. It is designed to be called
    from the adapter's event loop (single-threaded async context).
    """

    def __init__(self) -> None:
        # Primary storage: injection_id -> FaultInjection
        self._injections: Dict[str, FaultInjection] = {}
        # Index for fast lookup: sensor_id -> set of injection_ids
        self._sensor_index: Dict[str, set] = defaultdict(set)

    def inject(
        self,
        sensor_id: str,
        fault_type: str,
        magnitude: float,
        duration_cycles: int,
    ) -> str:
        """Start a fault injection, return unique injection_id.

        Args:
            sensor_id: Target sensor (e.g., "engine-001-hpc_outlet_temp_total")
            fault_type: One of "spike", "drift", "dropout", "noise"
            magnitude: Fault intensity:
                - spike: percentage increase (e.g., 50 means +50%)
                - drift: total drift magnitude over duration
                - dropout: ignored (sensor reports 0)
                - noise: standard deviation of Gaussian noise
            duration_cycles: How many apply() calls the fault remains active

        Returns:
            Unique injection_id string for later reference/clearing.
        """
        injection_id = str(uuid.uuid4())
        injection = FaultInjection(
            injection_id=injection_id,
            sensor_id=sensor_id,
            fault_type=fault_type,
            magnitude=magnitude,
            duration_cycles=duration_cycles,
            remaining_cycles=duration_cycles,
            elapsed_cycles=0,
        )
        self._injections[injection_id] = injection
        self._sensor_index[sensor_id].add(injection_id)
        return injection_id

    def apply(self, sensor_id: str, raw_value: float) -> float:
        """Apply all active faults for a sensor to the raw value.

        Called by the adapter on every sensor reading. If no faults active
        for this sensor, returns raw_value unchanged immediately (fast path).

        Composition rules:
        - spike, drift, noise each compute a delta from raw_value
        - Deltas compose additively: result = raw + sum(deltas)
        - dropout replaces with 0.0 (wins over all other transforms)

        Formulas:
        - spike: delta = raw_value * (magnitude / 100)
        - drift: delta = magnitude / duration_cycles * elapsed_cycles
        - noise: delta = N(0, magnitude)

        Auto-expires injections when remaining_cycles reaches 0.

        Args:
            sensor_id: The sensor being read
            raw_value: The original sensor measurement

        Returns:
            Transformed value (corrupted if faults active, original otherwise)
        """
        # Fast path: no faults for this sensor
        active_ids = self._sensor_index.get(sensor_id)
        if not active_ids:
            return raw_value

        delta = 0.0
        has_dropout = False
        expired_ids: List[str] = []

        for inj_id in list(active_ids):
            inj = self._injections.get(inj_id)
            if inj is None or inj.remaining_cycles <= 0:
                expired_ids.append(inj_id)
                continue

            if inj.fault_type == "spike":
                # Percentage increase relative to raw value
                delta += raw_value * (inj.magnitude / 100.0)
            elif inj.fault_type == "drift":
                # Gradual linear deviation: magnitude/duration * elapsed
                elapsed = inj.elapsed_cycles + 1
                delta += inj.magnitude / inj.duration_cycles * elapsed
            elif inj.fault_type == "dropout":
                has_dropout = True
            elif inj.fault_type == "noise":
                delta += np.random.normal(0.0, inj.magnitude)

            # Decrement remaining, increment elapsed
            inj.remaining_cycles -= 1
            inj.elapsed_cycles += 1

            # Check if just expired
            if inj.remaining_cycles <= 0:
                expired_ids.append(inj_id)

        # Dropout wins over all other transforms
        if has_dropout:
            result = 0.0
        else:
            result = raw_value + delta

        # Clean up expired injections
        for inj_id in expired_ids:
            self._remove_injection(inj_id)

        return result

    def clear(self, injection_id: str) -> None:
        """Remove a specific active injection. No-op if ID doesn't exist."""
        self._remove_injection(injection_id)

    def clear_all(self) -> None:
        """Remove all active injections."""
        self._injections.clear()
        self._sensor_index.clear()

    def get_active(self) -> List[dict]:
        """Return list of all currently active fault injections.

        Returns:
            List of dicts with injection details for API serialization.
        """
        return [
            {
                "injection_id": inj.injection_id,
                "sensor_id": inj.sensor_id,
                "fault_type": inj.fault_type,
                "magnitude": inj.magnitude,
                "remaining_cycles": inj.remaining_cycles,
                "duration_cycles": inj.duration_cycles,
            }
            for inj in self._injections.values()
            if inj.remaining_cycles > 0
        ]

    def _remove_injection(self, injection_id: str) -> None:
        """Remove an injection from both primary storage and sensor index."""
        inj = self._injections.pop(injection_id, None)
        if inj is not None:
            sensor_ids = self._sensor_index.get(inj.sensor_id)
            if sensor_ids is not None:
                sensor_ids.discard(injection_id)
                if not sensor_ids:
                    del self._sensor_index[inj.sensor_id]
