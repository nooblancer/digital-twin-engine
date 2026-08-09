"""Pattern generators for synthetic telemetry data.

Each pattern generator is a standalone function for testability.
Supported patterns:
- Steady-state: base + gaussian noise(σ)
- Linear drift: base + rate × elapsed
- Sinusoidal: base + amplitude × sin(2π × elapsed / period)
- Step change: base + step_size × floor(elapsed / interval)
- Random walk: previous + uniform(-max_step, +max_step)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Union


class PatternType(str, Enum):
    """Supported simulation data patterns."""

    STEADY_STATE = "steady_state"
    LINEAR_DRIFT = "linear_drift"
    SINUSOIDAL = "sinusoidal"
    STEP_CHANGE = "step_change"
    RANDOM_WALK = "random_walk"


# ---------------------------------------------------------------------------
# Pattern configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SteadyStateConfig:
    """Configuration for steady-state pattern: base + gaussian noise(σ)."""

    base: float
    sigma: float  # Standard deviation of Gaussian noise

    def __post_init__(self) -> None:
        if self.sigma < 0:
            raise ValueError("sigma must be non-negative")


@dataclass(frozen=True)
class LinearDriftConfig:
    """Configuration for linear drift: base + rate × elapsed."""

    base: float
    rate: float  # Rate of change per second (positive = increasing, negative = decreasing)


@dataclass(frozen=True)
class SinusoidalConfig:
    """Configuration for sinusoidal oscillation: base + amplitude × sin(2π × elapsed / period)."""

    base: float
    amplitude: float
    period: float  # Period in seconds

    def __post_init__(self) -> None:
        if self.period <= 0:
            raise ValueError("period must be positive")


@dataclass(frozen=True)
class StepChangeConfig:
    """Configuration for step change: base + step_size × floor(elapsed / interval)."""

    base: float
    step_size: float
    interval: float  # Interval in seconds between steps

    def __post_init__(self) -> None:
        if self.interval <= 0:
            raise ValueError("interval must be positive")


@dataclass(frozen=True)
class RandomWalkConfig:
    """Configuration for random walk: previous + uniform(-max_step, +max_step)."""

    base: float  # Initial value (used as starting point)
    max_step: float  # Maximum step size per event

    def __post_init__(self) -> None:
        if self.max_step < 0:
            raise ValueError("max_step must be non-negative")


# Type alias for all pattern configs
PatternConfig = Union[
    SteadyStateConfig,
    LinearDriftConfig,
    SinusoidalConfig,
    StepChangeConfig,
    RandomWalkConfig,
]


# ---------------------------------------------------------------------------
# Pattern generator functions
# ---------------------------------------------------------------------------


def generate_steady_state(config: SteadyStateConfig, rng: random.Random | None = None) -> float:
    """Generate a steady-state value: base + gaussian noise(σ).

    Args:
        config: Steady-state configuration with base and sigma.
        rng: Optional Random instance for reproducibility.

    Returns:
        Generated value.
    """
    if rng is None:
        rng = random.Random()
    noise = rng.gauss(0.0, config.sigma) if config.sigma > 0 else 0.0
    return config.base + noise


def generate_linear_drift(config: LinearDriftConfig, elapsed_seconds: float) -> float:
    """Generate a linear drift value: base + rate × elapsed.

    Args:
        config: Linear drift configuration with base and rate.
        elapsed_seconds: Time elapsed since simulation start in seconds.

    Returns:
        Generated value.
    """
    return config.base + config.rate * elapsed_seconds


def generate_sinusoidal(config: SinusoidalConfig, elapsed_seconds: float) -> float:
    """Generate a sinusoidal value: base + amplitude × sin(2π × elapsed / period).

    Args:
        config: Sinusoidal configuration with base, amplitude, and period.
        elapsed_seconds: Time elapsed since simulation start in seconds.

    Returns:
        Generated value.
    """
    return config.base + config.amplitude * math.sin(
        2.0 * math.pi * elapsed_seconds / config.period
    )


def generate_step_change(config: StepChangeConfig, elapsed_seconds: float) -> float:
    """Generate a step change value: base + step_size × floor(elapsed / interval).

    Args:
        config: Step change configuration with base, step_size, and interval.
        elapsed_seconds: Time elapsed since simulation start in seconds.

    Returns:
        Generated value.
    """
    steps = math.floor(elapsed_seconds / config.interval)
    return config.base + config.step_size * steps


def generate_random_walk(
    config: RandomWalkConfig,
    previous_value: float,
    rng: random.Random | None = None,
) -> float:
    """Generate a random walk value: previous + uniform(-max_step, +max_step).

    Args:
        config: Random walk configuration with max_step.
        previous_value: The previous value in the walk.
        rng: Optional Random instance for reproducibility.

    Returns:
        Generated value.
    """
    if rng is None:
        rng = random.Random()
    if config.max_step == 0:
        return previous_value
    step = rng.uniform(-config.max_step, config.max_step)
    return previous_value + step


def generate_value(
    config: PatternConfig,
    elapsed_seconds: float = 0.0,
    previous_value: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Generate a value based on the pattern configuration.

    This is the unified entry point for all pattern generators.

    Args:
        config: Pattern-specific configuration.
        elapsed_seconds: Time elapsed since simulation start.
        previous_value: Previous value (used only for random walk).
        rng: Optional Random instance for reproducibility.

    Returns:
        Generated value.

    Raises:
        TypeError: If config type is not recognized.
    """
    if isinstance(config, SteadyStateConfig):
        return generate_steady_state(config, rng=rng)
    elif isinstance(config, LinearDriftConfig):
        return generate_linear_drift(config, elapsed_seconds)
    elif isinstance(config, SinusoidalConfig):
        return generate_sinusoidal(config, elapsed_seconds)
    elif isinstance(config, StepChangeConfig):
        return generate_step_change(config, elapsed_seconds)
    elif isinstance(config, RandomWalkConfig):
        if previous_value is None:
            previous_value = config.base
        return generate_random_walk(config, previous_value, rng=rng)
    else:
        raise TypeError(f"Unknown pattern config type: {type(config)}")
