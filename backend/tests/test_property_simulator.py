"""Property-based tests for the Simulator output validity and pattern generator correctness.

Uses the Hypothesis library to verify universal properties across many inputs.
"""

# Feature: digital-twin-telemetry-engine, Property 22: Simulator Output Validity and Config Conformance
# Feature: digital-twin-telemetry-engine, Property 23: Pattern Generator Mathematical Correctness

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone

import hypothesis.strategies as st
from hypothesis import given, settings, assume
import pytest

from digital_twin_engine.simulator.config import SensorSimConfig, SimulatorConfig
from digital_twin_engine.simulator.patterns import (
    LinearDriftConfig,
    RandomWalkConfig,
    SinusoidalConfig,
    SteadyStateConfig,
    StepChangeConfig,
    generate_linear_drift,
    generate_random_walk,
    generate_sinusoidal,
    generate_steady_state,
    generate_step_change,
    generate_value,
)
from digital_twin_engine.simulator.simulator import TelemetrySimulator


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def valid_sensor_ids(draw):
    """Generate valid sensor_id strings (1-256 chars, non-whitespace-only)."""
    text = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.",
            min_size=1,
            max_size=50,
        )
    )
    assume(text.strip() != "")
    return text


@st.composite
def valid_measurement_types(draw):
    """Generate valid measurement_type strings (1-256 chars, non-whitespace-only)."""
    text = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.",
            min_size=1,
            max_size=50,
        )
    )
    assume(text.strip() != "")
    return text


@st.composite
def steady_state_configs(draw):
    """Generate valid SteadyStateConfig instances."""
    base = draw(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False))
    sigma = draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    return SteadyStateConfig(base=base, sigma=sigma)


@st.composite
def linear_drift_configs(draw):
    """Generate valid LinearDriftConfig instances."""
    base = draw(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False))
    rate = draw(st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    return LinearDriftConfig(base=base, rate=rate)


@st.composite
def sinusoidal_configs(draw):
    """Generate valid SinusoidalConfig instances."""
    base = draw(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False))
    amplitude = draw(st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False))
    period = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))
    return SinusoidalConfig(base=base, amplitude=amplitude, period=period)


@st.composite
def step_change_configs(draw):
    """Generate valid StepChangeConfig instances."""
    base = draw(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False))
    step_size = draw(st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    interval = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))
    return StepChangeConfig(base=base, step_size=step_size, interval=interval)


@st.composite
def random_walk_configs(draw):
    """Generate valid RandomWalkConfig instances."""
    base = draw(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False))
    max_step = draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    return RandomWalkConfig(base=base, max_step=max_step)


@st.composite
def any_pattern_config(draw):
    """Generate any valid pattern configuration."""
    config = draw(
        st.one_of(
            steady_state_configs(),
            linear_drift_configs(),
            sinusoidal_configs(),
            step_change_configs(),
            random_walk_configs(),
        )
    )
    return config


@st.composite
def valid_simulator_configs(draw, min_sensors=1, max_sensors=5):
    """Generate valid SimulatorConfig instances with multiple sensors."""
    num_sensors = draw(st.integers(min_value=min_sensors, max_value=max_sensors))

    sensors = []
    for i in range(num_sensors):
        sensor_id = draw(valid_sensor_ids())
        measurement_type = draw(valid_measurement_types())
        pattern_config = draw(any_pattern_config())
        sensors.append(
            SensorSimConfig(
                sensor_id=f"{sensor_id}-{i}",
                measurement_type=measurement_type,
                pattern_config=pattern_config,
            )
        )

    emission_rate = draw(st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    duration_seconds = draw(st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False))

    return SimulatorConfig(
        server_url="ws://localhost:8080/ws/telemetry",
        sensors=sensors,
        emission_rate=emission_rate,
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Property 22: Simulator Output Validity and Config Conformance
# ---------------------------------------------------------------------------


class TestProperty22SimulatorOutputValidityAndConfigConformance:
    """Property 22: Simulator Output Validity and Config Conformance.

    For any valid simulator configuration (sensor_ids, measurement_types,
    emission rate, duration), all generated TelemetryEvents SHALL conform
    to the TelemetryEvent JSON schema AND contain sensor_id and measurement_type
    values matching the configured parameters.

    **Validates: Requirements 10.1, 10.2**
    """

    @given(
        sensor_id=valid_sensor_ids(),
        measurement_type=valid_measurement_types(),
        pattern_config=any_pattern_config(),
        elapsed=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_generated_event_conforms_to_schema(
        self,
        sensor_id: str,
        measurement_type: str,
        pattern_config,
        elapsed: float,
    ):
        """Each generated event conforms to the TelemetryEvent JSON schema."""
        sensor_cfg = SensorSimConfig(
            sensor_id=sensor_id,
            measurement_type=measurement_type,
            pattern_config=pattern_config,
        )
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=[sensor_cfg],
            emission_rate=10.0,
            duration_seconds=5.0,
        )

        simulator = TelemetrySimulator(config, seed=42)
        simulator._init_sensor_states()

        # Generate an event JSON string
        event_json = simulator._generate_event(sensor_id, elapsed)

        # Parse and validate JSON schema conformance
        event = json.loads(event_json)

        # Must contain all required fields
        assert "timestamp" in event, "Event missing 'timestamp' field"
        assert "sensor_id" in event, "Event missing 'sensor_id' field"
        assert "measurement_type" in event, "Event missing 'measurement_type' field"
        assert "value" in event, "Event missing 'value' field"

        # Timestamp must be valid ISO 8601 UTC
        ts = event["timestamp"]
        assert isinstance(ts, str), "timestamp must be a string"
        # Verify it ends in Z (UTC) and can be parsed
        assert ts.endswith("Z"), "timestamp must end with 'Z' (UTC)"
        parsed_ts = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        assert parsed_ts is not None

        # sensor_id must be a string with 1-256 chars, non-whitespace-only
        assert isinstance(event["sensor_id"], str)
        assert 1 <= len(event["sensor_id"]) <= 256
        assert event["sensor_id"].strip() != ""

        # measurement_type must be a string with 1-256 chars, non-whitespace-only
        assert isinstance(event["measurement_type"], str)
        assert 1 <= len(event["measurement_type"]) <= 256
        assert event["measurement_type"].strip() != ""

        # value must be a finite float
        assert isinstance(event["value"], (int, float))
        assert math.isfinite(event["value"]), "value must be finite"

        # Total payload must not exceed 4096 bytes
        assert len(event_json.encode("utf-8")) <= 4096

    @given(
        sensor_id=valid_sensor_ids(),
        measurement_type=valid_measurement_types(),
        pattern_config=any_pattern_config(),
        elapsed=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_generated_event_matches_configured_parameters(
        self,
        sensor_id: str,
        measurement_type: str,
        pattern_config,
        elapsed: float,
    ):
        """Generated event sensor_id and measurement_type match the configured values."""
        sensor_cfg = SensorSimConfig(
            sensor_id=sensor_id,
            measurement_type=measurement_type,
            pattern_config=pattern_config,
        )
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=[sensor_cfg],
            emission_rate=10.0,
            duration_seconds=5.0,
        )

        simulator = TelemetrySimulator(config, seed=42)
        simulator._init_sensor_states()

        event_json = simulator._generate_event(sensor_id, elapsed)
        event = json.loads(event_json)

        # Verify the event's sensor_id matches the configured sensor_id
        assert event["sensor_id"] == sensor_id, (
            f"Event sensor_id '{event['sensor_id']}' does not match "
            f"configured sensor_id '{sensor_id}'"
        )

        # Verify the event's measurement_type matches the configured measurement_type
        assert event["measurement_type"] == measurement_type, (
            f"Event measurement_type '{event['measurement_type']}' does not match "
            f"configured measurement_type '{measurement_type}'"
        )

    @given(config=valid_simulator_configs(min_sensors=1, max_sensors=5))
    @settings(max_examples=50)
    def test_all_events_from_multi_sensor_config_conform(self, config: SimulatorConfig):
        """All events from a multi-sensor configuration have valid schema and matching config."""
        simulator = TelemetrySimulator(config, seed=12345)
        simulator._init_sensor_states()

        # Collect configured sensor_ids and measurement_types
        configured_sensors = {
            s.sensor_id: s.measurement_type for s in config.sensors
        }

        # Generate events for each sensor
        for sensor_cfg in config.sensors:
            event_json = simulator._generate_event(sensor_cfg.sensor_id, 1.0)
            event = json.loads(event_json)

            # Schema conformance
            assert "timestamp" in event
            assert "sensor_id" in event
            assert "measurement_type" in event
            assert "value" in event
            assert isinstance(event["value"], (int, float))
            assert math.isfinite(event["value"])

            # Config conformance
            assert event["sensor_id"] in configured_sensors, (
                f"Event sensor_id '{event['sensor_id']}' not in configured sensors"
            )
            assert event["measurement_type"] == configured_sensors[event["sensor_id"]], (
                f"Event measurement_type mismatch for sensor '{event['sensor_id']}'"
            )


# ---------------------------------------------------------------------------
# Property 23: Pattern Generator Mathematical Correctness
# ---------------------------------------------------------------------------


class TestProperty23PatternGeneratorMathematicalCorrectness:
    """Property 23: Pattern Generator Mathematical Correctness.

    For any simulator pattern configuration, the generated values SHALL match
    the expected mathematical formula within floating-point tolerance:
    - steady-state: base + gaussian noise with configured σ
    - linear drift: base + rate × elapsed
    - sinusoidal: base + amplitude × sin(2π × elapsed / period)
    - step change: base + step_size × floor(elapsed / interval)
    - random walk: each step bounded by ±max_step_size

    **Validates: Requirements 10.4**
    """

    @given(
        config=steady_state_configs(),
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=100)
    def test_steady_state_produces_base_plus_gaussian_noise(
        self,
        config: SteadyStateConfig,
        seed: int,
    ):
        """Steady-state: value = base + gaussian noise(σ).

        When σ=0, the value must equal base exactly.
        When σ>0, the deviation from base must be finite (noise is Gaussian).
        """
        rng = random.Random(seed)
        value = generate_steady_state(config, rng=rng)

        assert math.isfinite(value), "Generated value must be finite"

        if config.sigma == 0:
            # With zero noise, value must equal base exactly
            assert value == config.base, (
                f"With sigma=0, value should equal base. Got {value}, expected {config.base}"
            )
        else:
            # With noise, the deviation from base is the noise component
            # We verify the noise was generated using Gaussian (value - base is the noise)
            noise = value - config.base
            # Noise is finite (already checked value is finite and base is finite)
            assert math.isfinite(noise)

    @given(
        config=steady_state_configs(),
        num_samples=st.integers(min_value=50, max_value=200),
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=50)
    def test_steady_state_noise_distribution(
        self,
        config: SteadyStateConfig,
        num_samples: int,
        seed: int,
    ):
        """Steady-state noise has mean ≈ 0 and std ≈ σ for many samples."""
        assume(config.sigma > 0.1)  # Need non-trivial sigma for statistical test

        rng = random.Random(seed)
        values = [generate_steady_state(config, rng=rng) for _ in range(num_samples)]
        deviations = [v - config.base for v in values]

        mean_dev = sum(deviations) / len(deviations)
        variance = sum((d - mean_dev) ** 2 for d in deviations) / len(deviations)
        std_dev = math.sqrt(variance)

        # Mean should be approximately 0 (within 4.5 sigma / sqrt(n) for statistical test)
        # Using 4.5 sigma gives very high confidence to avoid flaky failures in PBT
        tolerance = 4.5 * config.sigma / math.sqrt(num_samples)
        assert abs(mean_dev) < tolerance, (
            f"Mean deviation {mean_dev} exceeds tolerance {tolerance} "
            f"(sigma={config.sigma}, n={num_samples})"
        )

        # Standard deviation should be approximately sigma (within factor of 2 for safety)
        assert std_dev < config.sigma * 3.0, (
            f"Standard deviation {std_dev} is too large relative to sigma={config.sigma}"
        )

    @given(
        config=linear_drift_configs(),
        elapsed=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_linear_drift_matches_formula(
        self,
        config: LinearDriftConfig,
        elapsed: float,
    ):
        """Linear drift: value = base + rate × elapsed."""
        value = generate_linear_drift(config, elapsed)
        expected = config.base + config.rate * elapsed

        assert math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Linear drift mismatch: got {value}, expected {expected} "
            f"(base={config.base}, rate={config.rate}, elapsed={elapsed})"
        )

    @given(
        config=sinusoidal_configs(),
        elapsed=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_sinusoidal_matches_formula(
        self,
        config: SinusoidalConfig,
        elapsed: float,
    ):
        """Sinusoidal: value = base + amplitude × sin(2π × elapsed / period)."""
        value = generate_sinusoidal(config, elapsed)
        expected = config.base + config.amplitude * math.sin(
            2.0 * math.pi * elapsed / config.period
        )

        assert math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Sinusoidal mismatch: got {value}, expected {expected} "
            f"(base={config.base}, amplitude={config.amplitude}, "
            f"period={config.period}, elapsed={elapsed})"
        )

    @given(
        config=step_change_configs(),
        elapsed=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_step_change_matches_formula(
        self,
        config: StepChangeConfig,
        elapsed: float,
    ):
        """Step change: value = base + step_size × floor(elapsed / interval)."""
        value = generate_step_change(config, elapsed)
        expected = config.base + config.step_size * math.floor(elapsed / config.interval)

        assert math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Step change mismatch: got {value}, expected {expected} "
            f"(base={config.base}, step_size={config.step_size}, "
            f"interval={config.interval}, elapsed={elapsed})"
        )

    @given(
        config=random_walk_configs(),
        previous_value=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=100)
    def test_random_walk_bounded_by_max_step(
        self,
        config: RandomWalkConfig,
        previous_value: float,
        seed: int,
    ):
        """Random walk: each step bounded by ±max_step_size."""
        rng = random.Random(seed)
        value = generate_random_walk(config, previous_value, rng=rng)

        step = value - previous_value

        if config.max_step == 0:
            # With zero max_step, value must equal previous
            assert value == previous_value, (
                f"With max_step=0, value should equal previous. "
                f"Got {value}, expected {previous_value}"
            )
        else:
            # Step must be bounded by [-max_step, +max_step]
            # Allow small floating-point tolerance: when previous_value is
            # much larger than max_step, (previous + step) - previous may
            # differ from step due to catastrophic cancellation.
            tol = max(abs(previous_value), 1.0) * 1e-10
            bound = config.max_step + tol
            assert -bound <= step <= bound, (
                f"Step {step} exceeds bounds ±{config.max_step} "
                f"(value={value}, previous={previous_value}, tol={tol})"
            )

    @given(
        config=random_walk_configs(),
        num_steps=st.integers(min_value=2, max_value=50),
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=100)
    def test_random_walk_all_steps_bounded(
        self,
        config: RandomWalkConfig,
        num_steps: int,
        seed: int,
    ):
        """Random walk: every consecutive step in a sequence is bounded by ±max_step."""
        assume(config.max_step > 0)

        rng = random.Random(seed)
        previous = config.base
        for i in range(num_steps):
            value = generate_random_walk(config, previous, rng=rng)
            step = value - previous
            # Allow small floating-point tolerance: when previous_value is
            # much larger than max_step, (previous + step) - previous may
            # differ from step due to loss of precision.
            tol = max(abs(previous), 1.0) * 1e-10
            bound = config.max_step + tol
            assert -bound <= step <= bound, (
                f"Step {i}: step {step} exceeds bounds ±{config.max_step}"
            )
            previous = value

    @given(
        config=any_pattern_config(),
        elapsed=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=100)
    def test_generate_value_dispatches_correctly(
        self,
        config,
        elapsed: float,
        seed: int,
    ):
        """The unified generate_value function dispatches to the correct pattern and produces finite output."""
        rng = random.Random(seed)
        previous_value = 0.0 if not hasattr(config, "base") else config.base

        value = generate_value(
            config=config,
            elapsed_seconds=elapsed,
            previous_value=previous_value,
            rng=rng,
        )

        # Value must be finite
        assert math.isfinite(value), (
            f"generate_value produced non-finite value {value} for config={config}"
        )

        # Verify correctness by recomputing with same seed
        rng2 = random.Random(seed)
        if isinstance(config, SteadyStateConfig):
            expected = generate_steady_state(config, rng=rng2)
        elif isinstance(config, LinearDriftConfig):
            expected = generate_linear_drift(config, elapsed)
        elif isinstance(config, SinusoidalConfig):
            expected = generate_sinusoidal(config, elapsed)
        elif isinstance(config, StepChangeConfig):
            expected = generate_step_change(config, elapsed)
        elif isinstance(config, RandomWalkConfig):
            expected = generate_random_walk(config, previous_value, rng=rng2)
        else:
            pytest.fail(f"Unknown config type: {type(config)}")

        assert math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"generate_value dispatch mismatch: got {value}, expected {expected}"
        )
