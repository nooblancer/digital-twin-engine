"""Unit tests for the telemetry simulator.

Tests pattern generators, configuration validation, and simulator behavior.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from digital_twin_engine.simulator.patterns import (
    LinearDriftConfig,
    PatternType,
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
from digital_twin_engine.simulator.config import SensorSimConfig, SimulatorConfig
from digital_twin_engine.simulator.simulator import (
    TelemetrySimulator,
    _RateTracker,
)


# ---------------------------------------------------------------------------
# Pattern generator tests
# ---------------------------------------------------------------------------


class TestSteadyState:
    """Tests for the steady-state pattern generator."""

    def test_base_value_with_zero_sigma(self):
        """With sigma=0, output should always equal base."""
        config = SteadyStateConfig(base=42.0, sigma=0.0)
        rng = random.Random(123)
        for _ in range(100):
            assert generate_steady_state(config, rng=rng) == 42.0

    def test_output_varies_with_nonzero_sigma(self):
        """With sigma>0, outputs should vary around base."""
        config = SteadyStateConfig(base=100.0, sigma=5.0)
        rng = random.Random(42)
        values = [generate_steady_state(config, rng=rng) for _ in range(1000)]
        # Mean should be close to base
        mean = sum(values) / len(values)
        assert abs(mean - 100.0) < 1.0  # Within ~1 for 1000 samples
        # Some values should deviate from base
        assert any(abs(v - 100.0) > 1.0 for v in values)

    def test_negative_sigma_raises(self):
        """Negative sigma should raise ValueError."""
        with pytest.raises(ValueError, match="sigma must be non-negative"):
            SteadyStateConfig(base=0.0, sigma=-1.0)

    def test_reproducible_with_seed(self):
        """Same seed should produce same sequence."""
        config = SteadyStateConfig(base=10.0, sigma=2.0)
        rng1 = random.Random(999)
        rng2 = random.Random(999)
        v1 = [generate_steady_state(config, rng=rng1) for _ in range(50)]
        v2 = [generate_steady_state(config, rng=rng2) for _ in range(50)]
        assert v1 == v2


class TestLinearDrift:
    """Tests for the linear drift pattern generator."""

    def test_value_at_zero_elapsed(self):
        """At elapsed=0, value should equal base."""
        config = LinearDriftConfig(base=50.0, rate=2.0)
        assert generate_linear_drift(config, 0.0) == 50.0

    def test_increasing_drift(self):
        """Positive rate should produce increasing values."""
        config = LinearDriftConfig(base=0.0, rate=1.5)
        assert generate_linear_drift(config, 10.0) == 15.0
        assert generate_linear_drift(config, 20.0) == 30.0

    def test_decreasing_drift(self):
        """Negative rate should produce decreasing values."""
        config = LinearDriftConfig(base=100.0, rate=-0.5)
        assert generate_linear_drift(config, 10.0) == 95.0

    def test_formula_correctness(self):
        """Value should be exactly base + rate * elapsed."""
        config = LinearDriftConfig(base=3.14, rate=2.718)
        elapsed = 7.5
        expected = 3.14 + 2.718 * 7.5
        assert math.isclose(generate_linear_drift(config, elapsed), expected)


class TestSinusoidal:
    """Tests for the sinusoidal pattern generator."""

    def test_value_at_zero_elapsed(self):
        """At elapsed=0, sin(0)=0, so value should equal base."""
        config = SinusoidalConfig(base=20.0, amplitude=5.0, period=10.0)
        assert generate_sinusoidal(config, 0.0) == 20.0

    def test_peak_value(self):
        """At elapsed=period/4, sin(π/2)=1, value should be base + amplitude."""
        config = SinusoidalConfig(base=20.0, amplitude=5.0, period=10.0)
        value = generate_sinusoidal(config, 2.5)  # period/4
        assert math.isclose(value, 25.0, abs_tol=1e-10)

    def test_trough_value(self):
        """At elapsed=3*period/4, sin(3π/2)=-1, value should be base - amplitude."""
        config = SinusoidalConfig(base=20.0, amplitude=5.0, period=10.0)
        value = generate_sinusoidal(config, 7.5)  # 3*period/4
        assert math.isclose(value, 15.0, abs_tol=1e-10)

    def test_periodicity(self):
        """Value at elapsed should equal value at elapsed + period."""
        config = SinusoidalConfig(base=0.0, amplitude=3.0, period=4.0)
        v1 = generate_sinusoidal(config, 1.7)
        v2 = generate_sinusoidal(config, 1.7 + 4.0)
        assert math.isclose(v1, v2, abs_tol=1e-10)

    def test_invalid_period_raises(self):
        """Zero or negative period should raise ValueError."""
        with pytest.raises(ValueError, match="period must be positive"):
            SinusoidalConfig(base=0.0, amplitude=1.0, period=0.0)
        with pytest.raises(ValueError, match="period must be positive"):
            SinusoidalConfig(base=0.0, amplitude=1.0, period=-1.0)


class TestStepChange:
    """Tests for the step change pattern generator."""

    def test_value_before_first_step(self):
        """Before elapsed reaches interval, value should equal base."""
        config = StepChangeConfig(base=10.0, step_size=5.0, interval=3.0)
        assert generate_step_change(config, 0.0) == 10.0
        assert generate_step_change(config, 2.9) == 10.0

    def test_value_after_one_step(self):
        """After one interval, value should be base + step_size."""
        config = StepChangeConfig(base=10.0, step_size=5.0, interval=3.0)
        assert generate_step_change(config, 3.0) == 15.0
        assert generate_step_change(config, 5.9) == 15.0

    def test_multiple_steps(self):
        """Multiple intervals produce cumulative steps."""
        config = StepChangeConfig(base=0.0, step_size=2.0, interval=1.0)
        assert generate_step_change(config, 3.5) == 6.0  # floor(3.5/1) * 2 = 6

    def test_negative_step_size(self):
        """Negative step_size produces decreasing steps."""
        config = StepChangeConfig(base=100.0, step_size=-10.0, interval=5.0)
        assert generate_step_change(config, 15.0) == 70.0  # floor(15/5) * -10

    def test_invalid_interval_raises(self):
        """Zero or negative interval should raise ValueError."""
        with pytest.raises(ValueError, match="interval must be positive"):
            StepChangeConfig(base=0.0, step_size=1.0, interval=0.0)


class TestRandomWalk:
    """Tests for the random walk pattern generator."""

    def test_step_bounded(self):
        """Each step should be within [-max_step, +max_step]."""
        config = RandomWalkConfig(base=50.0, max_step=1.0)
        rng = random.Random(42)
        prev = 50.0
        for _ in range(1000):
            value = generate_random_walk(config, prev, rng=rng)
            assert abs(value - prev) <= 1.0 + 1e-10
            prev = value

    def test_zero_max_step(self):
        """With max_step=0, value should never change."""
        config = RandomWalkConfig(base=25.0, max_step=0.0)
        rng = random.Random(42)
        assert generate_random_walk(config, 25.0, rng=rng) == 25.0

    def test_negative_max_step_raises(self):
        """Negative max_step should raise ValueError."""
        with pytest.raises(ValueError, match="max_step must be non-negative"):
            RandomWalkConfig(base=0.0, max_step=-1.0)

    def test_walk_varies(self):
        """Random walk should produce varying values."""
        config = RandomWalkConfig(base=0.0, max_step=5.0)
        rng = random.Random(123)
        values = [0.0]
        for _ in range(100):
            values.append(generate_random_walk(config, values[-1], rng=rng))
        # Values shouldn't all be the same
        assert len(set(values)) > 1


class TestGenerateValue:
    """Tests for the unified generate_value function."""

    def test_dispatch_steady_state(self):
        """Should dispatch to steady_state generator."""
        config = SteadyStateConfig(base=5.0, sigma=0.0)
        assert generate_value(config) == 5.0

    def test_dispatch_linear_drift(self):
        """Should dispatch to linear drift generator."""
        config = LinearDriftConfig(base=1.0, rate=2.0)
        assert generate_value(config, elapsed_seconds=3.0) == 7.0

    def test_dispatch_sinusoidal(self):
        """Should dispatch to sinusoidal generator."""
        config = SinusoidalConfig(base=0.0, amplitude=1.0, period=4.0)
        value = generate_value(config, elapsed_seconds=1.0)
        assert math.isclose(value, 1.0, abs_tol=1e-10)

    def test_dispatch_step_change(self):
        """Should dispatch to step change generator."""
        config = StepChangeConfig(base=0.0, step_size=3.0, interval=2.0)
        assert generate_value(config, elapsed_seconds=5.0) == 6.0

    def test_dispatch_random_walk(self):
        """Should dispatch to random walk generator."""
        config = RandomWalkConfig(base=10.0, max_step=1.0)
        rng = random.Random(42)
        value = generate_value(config, previous_value=10.0, rng=rng)
        assert abs(value - 10.0) <= 1.0 + 1e-10

    def test_random_walk_uses_base_when_no_previous(self):
        """Random walk should use config.base when previous_value is None."""
        config = RandomWalkConfig(base=100.0, max_step=0.5)
        rng = random.Random(42)
        value = generate_value(config, rng=rng)
        assert abs(value - 100.0) <= 0.5 + 1e-10

    def test_unknown_config_type_raises(self):
        """Unknown config type should raise TypeError."""
        with pytest.raises(TypeError, match="Unknown pattern config type"):
            generate_value("not_a_config")


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestSensorSimConfig:
    """Tests for SensorSimConfig validation."""

    def test_valid_config(self):
        """Valid config should instantiate without errors."""
        cfg = SensorSimConfig(
            sensor_id="sensor-001",
            measurement_type="temperature",
            pattern_config=SteadyStateConfig(base=25.0, sigma=1.0),
        )
        assert cfg.sensor_id == "sensor-001"

    def test_empty_sensor_id_raises(self):
        """Empty sensor_id should raise."""
        with pytest.raises(ValueError, match="sensor_id must not be empty"):
            SensorSimConfig(
                sensor_id="",
                measurement_type="temp",
                pattern_config=SteadyStateConfig(base=0.0, sigma=0.0),
            )

    def test_whitespace_sensor_id_raises(self):
        """Whitespace-only sensor_id should raise."""
        with pytest.raises(ValueError, match="sensor_id must not be empty"):
            SensorSimConfig(
                sensor_id="   ",
                measurement_type="temp",
                pattern_config=SteadyStateConfig(base=0.0, sigma=0.0),
            )

    def test_empty_measurement_type_raises(self):
        """Empty measurement_type should raise."""
        with pytest.raises(ValueError, match="measurement_type must not be empty"):
            SensorSimConfig(
                sensor_id="s1",
                measurement_type="",
                pattern_config=SteadyStateConfig(base=0.0, sigma=0.0),
            )

    def test_negative_emission_rate_raises(self):
        """Negative emission_rate should raise."""
        with pytest.raises(ValueError, match="emission_rate must be positive"):
            SensorSimConfig(
                sensor_id="s1",
                measurement_type="temp",
                pattern_config=SteadyStateConfig(base=0.0, sigma=0.0),
                emission_rate=-1.0,
            )


class TestSimulatorConfig:
    """Tests for SimulatorConfig validation."""

    def _make_sensor(self, sensor_id: str = "s1") -> SensorSimConfig:
        return SensorSimConfig(
            sensor_id=sensor_id,
            measurement_type="temperature",
            pattern_config=SteadyStateConfig(base=25.0, sigma=1.0),
        )

    def test_valid_config(self):
        """Valid config should instantiate."""
        cfg = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=[self._make_sensor()],
            emission_rate=100.0,
            duration_seconds=60.0,
        )
        assert cfg.emission_rate == 100.0

    def test_no_sensors_raises(self):
        """Empty sensor list should raise."""
        with pytest.raises(ValueError, match="At least one sensor"):
            SimulatorConfig(
                server_url="ws://localhost:8080",
                sensors=[],
                emission_rate=100.0,
            )

    def test_emission_rate_too_low_raises(self):
        """Emission rate below 1 should raise."""
        with pytest.raises(ValueError, match="emission_rate must be between"):
            SimulatorConfig(
                server_url="ws://localhost:8080",
                sensors=[self._make_sensor()],
                emission_rate=0.5,
            )

    def test_emission_rate_too_high_raises(self):
        """Emission rate above 10,000 should raise."""
        with pytest.raises(ValueError, match="emission_rate must be between"):
            SimulatorConfig(
                server_url="ws://localhost:8080",
                sensors=[self._make_sensor()],
                emission_rate=10_001.0,
            )

    def test_duration_too_low_raises(self):
        """Duration below 1 should raise."""
        with pytest.raises(ValueError, match="duration_seconds must be between"):
            SimulatorConfig(
                server_url="ws://localhost:8080",
                sensors=[self._make_sensor()],
                duration_seconds=0.5,
            )

    def test_duration_too_high_raises(self):
        """Duration above 86,400 should raise."""
        with pytest.raises(ValueError, match="duration_seconds must be between"):
            SimulatorConfig(
                server_url="ws://localhost:8080",
                sensors=[self._make_sensor()],
                duration_seconds=86_401.0,
            )

    def test_per_sensor_rate_even_distribution(self):
        """Without explicit rates, emission should be distributed evenly."""
        cfg = SimulatorConfig(
            server_url="ws://localhost:8080",
            sensors=[self._make_sensor("s1"), self._make_sensor("s2")],
            emission_rate=100.0,
        )
        assert cfg.per_sensor_rate == 50.0

    def test_per_sensor_rate_with_explicit(self):
        """Sensors with explicit rates should not share the pool."""
        s1 = SensorSimConfig(
            sensor_id="s1",
            measurement_type="temp",
            pattern_config=SteadyStateConfig(base=0.0, sigma=0.0),
            emission_rate=30.0,
        )
        s2 = self._make_sensor("s2")
        s3 = self._make_sensor("s3")
        cfg = SimulatorConfig(
            server_url="ws://localhost:8080",
            sensors=[s1, s2, s3],
            emission_rate=100.0,
        )
        # s1 takes 30, remaining 70 split between s2 and s3
        assert cfg.get_sensor_rate(s1) == 30.0
        assert cfg.get_sensor_rate(s2) == 35.0
        assert cfg.get_sensor_rate(s3) == 35.0


# ---------------------------------------------------------------------------
# Rate tracker tests
# ---------------------------------------------------------------------------


class TestRateTracker:
    """Tests for the internal rate tracking utility."""

    def test_empty_tracker(self):
        """Empty tracker should return rate 0."""
        tracker = _RateTracker()
        assert tracker.current_rate() == 0.0

    def test_single_event(self):
        """Single event should return rate 0."""
        tracker = _RateTracker()
        tracker.record_event(1.0)
        assert tracker.current_rate() == 0.0

    def test_rate_calculation(self):
        """Rate should be events/duration in window."""
        tracker = _RateTracker(window_seconds=10.0)
        # 10 events over 1 second = ~10/s
        for i in range(10):
            tracker.record_event(1.0 + i * 0.1)
        rate = tracker.current_rate()
        assert math.isclose(rate, 10.0 / 0.9, rel_tol=0.01)

    def test_window_pruning(self):
        """Events outside the window should be pruned."""
        tracker = _RateTracker(window_seconds=5.0)
        # Old events
        for i in range(5):
            tracker.record_event(float(i))
        # New events at t=10+
        for i in range(5):
            tracker.record_event(10.0 + float(i))
        # Only new events should remain
        assert tracker.events_in_window() == 5


# ---------------------------------------------------------------------------
# Simulator integration-style tests (with mocked WebSocket)
# ---------------------------------------------------------------------------


class TestTelemetrySimulatorEventGeneration:
    """Tests for event generation logic (no actual WebSocket needed)."""

    def test_generate_event_format(self):
        """Generated events should conform to TelemetryEvent JSON schema."""
        sensors = [
            SensorSimConfig(
                sensor_id="test-sensor-001",
                measurement_type="temperature_celsius",
                pattern_config=SteadyStateConfig(base=25.0, sigma=0.0),
            )
        ]
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=sensors,
            emission_rate=10.0,
            duration_seconds=5.0,
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()

        event_json = sim._generate_event("test-sensor-001", 1.0)
        event = json.loads(event_json)

        assert "timestamp" in event
        assert event["sensor_id"] == "test-sensor-001"
        assert event["measurement_type"] == "temperature_celsius"
        assert isinstance(event["value"], float)
        # With sigma=0, value should be exactly base
        assert event["value"] == 25.0

    def test_generate_event_linear_drift(self):
        """Linear drift should produce correct values at different elapsed times."""
        sensors = [
            SensorSimConfig(
                sensor_id="drift-sensor",
                measurement_type="pressure",
                pattern_config=LinearDriftConfig(base=100.0, rate=2.0),
            )
        ]
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=sensors,
            emission_rate=10.0,
            duration_seconds=5.0,
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()

        event1 = json.loads(sim._generate_event("drift-sensor", 0.0))
        event2 = json.loads(sim._generate_event("drift-sensor", 5.0))

        assert event1["value"] == 100.0
        assert event2["value"] == 110.0

    def test_generate_event_random_walk_bounded_steps(self):
        """Random walk steps should be bounded by max_step."""
        sensors = [
            SensorSimConfig(
                sensor_id="walk-sensor",
                measurement_type="vibration",
                pattern_config=RandomWalkConfig(base=0.0, max_step=1.0),
            )
        ]
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=sensors,
            emission_rate=10.0,
            duration_seconds=5.0,
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()

        prev = 0.0
        for i in range(100):
            event = json.loads(sim._generate_event("walk-sensor", float(i) * 0.1))
            value = event["value"]
            assert abs(value - prev) <= 1.0 + 1e-10
            prev = value

    def test_concurrent_sensors_independent(self):
        """Multiple sensors should have independent state."""
        sensors = [
            SensorSimConfig(
                sensor_id="s1",
                measurement_type="temp",
                pattern_config=LinearDriftConfig(base=0.0, rate=1.0),
            ),
            SensorSimConfig(
                sensor_id="s2",
                measurement_type="pressure",
                pattern_config=LinearDriftConfig(base=100.0, rate=-1.0),
            ),
        ]
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=sensors,
            emission_rate=10.0,
            duration_seconds=5.0,
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()

        e1 = json.loads(sim._generate_event("s1", 5.0))
        e2 = json.loads(sim._generate_event("s2", 5.0))

        assert e1["value"] == 5.0  # 0 + 1*5
        assert e2["value"] == 95.0  # 100 + (-1)*5

    def test_many_sensors_supported(self):
        """Should support 100+ sensor configurations."""
        sensors = [
            SensorSimConfig(
                sensor_id=f"sensor-{i:04d}",
                measurement_type="temperature",
                pattern_config=SteadyStateConfig(base=float(i), sigma=0.1),
            )
            for i in range(150)
        ]
        config = SimulatorConfig(
            server_url="ws://localhost:8080/ws/telemetry",
            sensors=sensors,
            emission_rate=1000.0,
            duration_seconds=10.0,
        )
        sim = TelemetrySimulator(config, seed=42)
        sim._init_sensor_states()
        assert len(sim._sensor_states) == 150
