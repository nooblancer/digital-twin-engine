"""NASA C-MAPSS Turbofan Engine Degradation Dataset - Replay Adapter.

Reads the C-MAPSS text files and replays them as a stream of TelemetryEvents,
simulating real-time sensor data from a fleet of turbofan engines degrading
toward failure.

The adapter supports:
- Configurable playback speed (1x = 1 cycle/second, up to 1000x)
- Multiple engines streaming concurrently
- All 21 sensor channels as independent telemetry streams
- Direct publish to broker (in-process) or WebSocket (remote server)

Usage:
    # As a module (publishes to broker directly):
    python -m digital_twin_engine.adapters.cmapss_replay

    # Programmatic usage:
    adapter = CMAPSSReplayAdapter(config)
    async for event in adapter.stream():
        # process event
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Tuple

from digital_twin_engine.shared.models import TelemetryEvent


# Sensor names matching the 21 measurement channels in C-MAPSS
SENSOR_NAMES: List[str] = [
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
]

SENSOR_NAMES_EXTENDED: List[str] = SENSOR_NAMES + [
    "demanded_fan_speed_rpm",
    "demanded_corrected_fan_speed",
    "hpt_coolant_bleed",
    "lpt_coolant_bleed",
]

# Operational settings (columns 3-5)
OPERATIONAL_SETTINGS: List[str] = [
    "altitude",
    "mach_number",
    "throttle_resolver_angle",
]


@dataclass
class CMAPSSConfig:
    """Configuration for the C-MAPSS replay adapter."""

    # Path to the data directory containing train_FD00X.txt files
    data_dir: str = "data/cmapss"

    # Which dataset to use (FD001, FD002, FD003, FD004)
    dataset: str = "FD001"

    # Which data split to use ("train" for full run-to-failure, "test" for partial)
    split: str = "train"

    # Engine IDs to stream (None = all engines in the dataset)
    engine_ids: Optional[List[int]] = None

    # Which sensors to include (None = all 21)
    sensors: Optional[List[str]] = None

    # Playback speed multiplier (1.0 = 1 cycle per second)
    speed: float = 10.0

    # Whether to include operational settings as sensor readings
    include_op_settings: bool = False

    # Whether to loop the dataset continuously
    loop: bool = False

    # Maximum number of cycles to replay (None = all)
    max_cycles: Optional[int] = None


@dataclass
class EngineData:
    """Parsed data for a single engine."""

    engine_id: int
    cycles: List[Dict[str, float]]  # Each cycle is a dict of sensor_name -> value
    total_cycles: int


def parse_cmapss_file(filepath: str) -> Dict[int, EngineData]:
    """Parse a C-MAPSS text file into structured engine data.

    Args:
        filepath: Path to the train_FD00X.txt or test_FD00X.txt file.

    Returns:
        Dictionary mapping engine_id to EngineData.
    """
    engines: Dict[int, List[Dict[str, float]]] = {}

    with open(filepath, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 26:
                continue

            values = [float(x) for x in parts]
            engine_id = int(values[0])
            cycle = int(values[1])

            # Build sensor readings dict
            readings: Dict[str, float] = {}

            # Operational settings (columns 3-5, index 2-4)
            for i, name in enumerate(OPERATIONAL_SETTINGS):
                readings[name] = values[2 + i]

            # 21 sensor measurements (columns 6-26, index 5-25)
            for i, name in enumerate(SENSOR_NAMES_EXTENDED):
                readings[name] = values[5 + i]

            readings["_cycle"] = float(cycle)

            if engine_id not in engines:
                engines[engine_id] = []
            engines[engine_id].append(readings)

    # Convert to EngineData
    result: Dict[int, EngineData] = {}
    for eid, cycles in engines.items():
        result[eid] = EngineData(
            engine_id=eid,
            cycles=cycles,
            total_cycles=len(cycles),
        )

    return result


class CMAPSSReplayAdapter:
    """Replays NASA C-MAPSS data as a stream of TelemetryEvents.

    Each engine becomes a set of sensors (one per measurement channel).
    Sensor IDs follow the pattern: engine-{id:03d}-{sensor_name}

    Usage:
        config = CMAPSSConfig(dataset="FD001", speed=10.0)
        adapter = CMAPSSReplayAdapter(config)
        await adapter.load()

        async for event in adapter.stream():
            print(event)
    """

    def __init__(self, config: CMAPSSConfig) -> None:
        self._config = config
        self._engines: Dict[int, EngineData] = {}
        self._loaded = False
        self._total_events_emitted = 0
        self._start_time: float = 0.0

    @property
    def config(self) -> CMAPSSConfig:
        return self._config

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def engine_count(self) -> int:
        return len(self._engines)

    @property
    def total_events_emitted(self) -> int:
        return self._total_events_emitted

    def load(self) -> None:
        """Load and parse the C-MAPSS data file."""
        filename = f"{self._config.split}_{self._config.dataset}.txt"
        filepath = os.path.join(self._config.data_dir, filename)

        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"C-MAPSS data file not found: {filepath}\n"
                f"Run 'python download_cmapss.py' to download the dataset."
            )

        all_engines = parse_cmapss_file(filepath)

        # Filter to requested engine IDs
        if self._config.engine_ids:
            self._engines = {
                eid: data
                for eid, data in all_engines.items()
                if eid in self._config.engine_ids
            }
        else:
            self._engines = all_engines

        self._loaded = True

    def get_sensor_list(self) -> List[str]:
        """Get the list of sensor names that will be streamed."""
        sensors = list(SENSOR_NAMES_EXTENDED)
        if self._config.include_op_settings:
            sensors = OPERATIONAL_SETTINGS + sensors
        if self._config.sensors:
            sensors = [s for s in sensors if s in self._config.sensors]
        return sensors

    async def stream(self) -> AsyncIterator[TelemetryEvent]:
        """Stream TelemetryEvents from the loaded dataset.

        Yields events at the configured playback speed. Each cycle produces
        one event per sensor per engine, simulating real-time telemetry.

        Yields:
            TelemetryEvent objects in chronological order.
        """
        if not self._loaded:
            raise RuntimeError("Call load() before streaming")

        sensor_list = self.get_sensor_list()
        cycle_interval = 1.0 / self._config.speed  # seconds between cycles
        self._start_time = time.monotonic()
        self._total_events_emitted = 0

        base_time = datetime.now(timezone.utc)
        cycle_idx = 0

        while True:
            any_data = False

            for engine_id, engine_data in self._engines.items():
                if cycle_idx >= engine_data.total_cycles:
                    continue  # This engine has finished its run

                if self._config.max_cycles and cycle_idx >= self._config.max_cycles:
                    continue

                any_data = True
                cycle_data = engine_data.cycles[cycle_idx]

                # Generate timestamp for this cycle
                ts = base_time + timedelta(seconds=cycle_idx * cycle_interval)

                # Emit one event per sensor
                for sensor_name in sensor_list:
                    if sensor_name in cycle_data:
                        sensor_id = f"engine-{engine_id:03d}-{sensor_name}"
                        event = TelemetryEvent(
                            timestamp=ts,
                            sensor_id=sensor_id,
                            measurement_type=sensor_name,
                            value=cycle_data[sensor_name],
                        )
                        self._total_events_emitted += 1
                        yield event

            if not any_data:
                if self._config.loop:
                    cycle_idx = 0
                    base_time = datetime.now(timezone.utc)
                    continue
                else:
                    break

            cycle_idx += 1

            # Pace the replay according to speed
            elapsed = time.monotonic() - self._start_time
            expected_elapsed = cycle_idx * cycle_interval
            sleep_time = expected_elapsed - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def summary(self) -> Dict[str, object]:
        """Return a summary of the loaded dataset."""
        if not self._loaded:
            return {"loaded": False}

        total_cycles = sum(e.total_cycles for e in self._engines.values())
        return {
            "loaded": True,
            "dataset": self._config.dataset,
            "split": self._config.split,
            "engines": len(self._engines),
            "total_cycles": total_cycles,
            "sensors_per_cycle": len(self.get_sensor_list()),
            "total_events_available": total_cycles * len(self.get_sensor_list()),
            "playback_speed": f"{self._config.speed}x",
            "estimated_duration_seconds": total_cycles / self._config.speed,
        }
