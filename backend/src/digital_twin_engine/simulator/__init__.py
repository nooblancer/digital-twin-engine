"""Simulator - Mock telemetry event generator for local development and testing.

Provides:
- Pattern generators for synthetic data (steady-state, linear drift, sinusoidal, step change, random walk)
- Configurable sensor simulation with independent parameters
- Async WebSocket client for streaming events to the Ingestion Server
"""

from digital_twin_engine.simulator.patterns import (
    PatternType,
    PatternConfig,
    SteadyStateConfig,
    LinearDriftConfig,
    SinusoidalConfig,
    StepChangeConfig,
    RandomWalkConfig,
    generate_value,
)
from digital_twin_engine.simulator.config import SensorSimConfig, SimulatorConfig
from digital_twin_engine.simulator.simulator import TelemetrySimulator

__all__ = [
    "PatternType",
    "PatternConfig",
    "SteadyStateConfig",
    "LinearDriftConfig",
    "SinusoidalConfig",
    "StepChangeConfig",
    "RandomWalkConfig",
    "generate_value",
    "SensorSimConfig",
    "SimulatorConfig",
    "TelemetrySimulator",
]
