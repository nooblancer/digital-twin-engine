"""Simulator configuration models.

Defines the configuration for individual sensor simulations and the overall simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from digital_twin_engine.simulator.patterns import PatternConfig, PatternType


@dataclass
class SensorSimConfig:
    """Configuration for a single simulated sensor.

    Attributes:
        sensor_id: Unique identifier for the sensor.
        measurement_type: Type of measurement this sensor produces.
        pattern_config: Configuration for the data generation pattern.
        emission_rate: Events per second for this sensor (contributes to total rate).
                       If None, the global rate is distributed evenly.
    """

    sensor_id: str
    measurement_type: str
    pattern_config: PatternConfig
    emission_rate: float | None = None  # Events/s for this sensor; None = share global rate

    def __post_init__(self) -> None:
        if not self.sensor_id or not self.sensor_id.strip():
            raise ValueError("sensor_id must not be empty or whitespace-only")
        if not self.measurement_type or not self.measurement_type.strip():
            raise ValueError("measurement_type must not be empty or whitespace-only")
        if self.emission_rate is not None and self.emission_rate <= 0:
            raise ValueError("emission_rate must be positive if specified")


@dataclass
class SimulatorConfig:
    """Configuration for the telemetry simulator.

    Attributes:
        server_url: WebSocket URL of the Ingestion Server (e.g., ws://localhost:8080/ws/telemetry).
        sensors: List of sensor configurations.
        emission_rate: Target aggregate emission rate in events per second (1-10,000).
        duration_seconds: Duration of the simulation in seconds (1-86,400).
        connect_timeout_seconds: Timeout for WebSocket connection attempts.
        max_connect_retries: Maximum number of connection retry attempts.
        retry_delay_seconds: Delay between retry attempts.
    """

    server_url: str
    sensors: List[SensorSimConfig]
    emission_rate: float = 100.0  # events per second (1-10,000)
    duration_seconds: float = 60.0  # (1-86,400)
    connect_timeout_seconds: float = 5.0
    max_connect_retries: int = 3
    retry_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not self.sensors:
            raise ValueError("At least one sensor configuration is required")
        if not (1 <= self.emission_rate <= 10_000):
            raise ValueError("emission_rate must be between 1 and 10,000 events/s")
        if not (1 <= self.duration_seconds <= 86_400):
            raise ValueError("duration_seconds must be between 1 and 86,400")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        if self.max_connect_retries < 0:
            raise ValueError("max_connect_retries must be non-negative")
        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")

    @property
    def per_sensor_rate(self) -> float:
        """Calculate the per-sensor emission rate when evenly distributed."""
        # Sensors with explicit rates don't count toward the shared pool
        explicit_total = sum(
            s.emission_rate for s in self.sensors if s.emission_rate is not None
        )
        shared_sensors = [s for s in self.sensors if s.emission_rate is None]
        remaining_rate = max(0.0, self.emission_rate - explicit_total)
        if not shared_sensors:
            return 0.0
        return remaining_rate / len(shared_sensors)

    def get_sensor_rate(self, sensor: SensorSimConfig) -> float:
        """Get the effective emission rate for a specific sensor."""
        if sensor.emission_rate is not None:
            return sensor.emission_rate
        return self.per_sensor_rate
