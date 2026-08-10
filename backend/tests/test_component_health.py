"""Unit tests for the Component Health Mapper.

Tests the ComponentHealthMapper class which implements:
- Sensor-to-subsystem mapping (21 sensors → 6 subsystems)
- Per-subsystem health score computation via baseline normalization
- Classification with hysteresis (nominal/degraded/critical)
- Incomplete subsystem detection retaining previous state

Validates: Requirements 4.1, 4.3, 4.6
"""

from __future__ import annotations

import math
from typing import Dict

import pytest

from digital_twin_engine.prognostics.component_health import (
    BASELINE_CYCLES,
    ComponentHealthMapper,
    DEGRADED_THRESHOLD,
    HYSTERESIS_BAND,
    NOMINAL_THRESHOLD,
    SUBSYSTEM_SENSOR_MAP,
)
from digital_twin_engine.prognostics.models import SensorBaseline, SubsystemHealth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeBroker:
    """Minimal fake broker for unit tests (no real subscription needed)."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        pass

    async def subscribe(self, topic: str, group_id: str, callback) -> None:
        pass

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        pass


class FakeWSManager:
    """Minimal fake WebSocket manager for unit tests."""

    def __init__(self) -> None:
        self.broadcasts: list = []

    async def broadcast(self, msg_type: str, payload: dict) -> None:
        self.broadcasts.append((msg_type, payload))


def _make_mapper() -> ComponentHealthMapper:
    """Create a ComponentHealthMapper with fake dependencies."""
    return ComponentHealthMapper(broker=FakeBroker(), ws_manager=FakeWSManager())


def _all_sensors() -> list[str]:
    """Return a flat list of all sensors across all subsystems."""
    sensors = []
    for sensor_list in SUBSYSTEM_SENSOR_MAP.values():
        sensors.extend(sensor_list)
    return sensors


def _setup_baselines(
    mapper: ComponentHealthMapper,
    engine_id: int,
    mean: float = 100.0,
    std: float = 5.0,
) -> None:
    """Set up baselines for all sensors in the mapper for a given engine."""
    baselines: Dict[str, SensorBaseline] = {}
    for sensor_name in _all_sensors():
        baselines[sensor_name] = SensorBaseline(
            sensor_name=sensor_name,
            mean=mean,
            std=std,
            sample_count=BASELINE_CYCLES,
        )
    mapper._baselines[engine_id] = baselines


def _make_readings_at_baseline(mean: float = 100.0) -> Dict[str, float]:
    """Create cycle readings where all sensors are exactly at baseline mean."""
    return {sensor: mean for sensor in _all_sensors()}


def _make_readings_with_deviation(
    mean: float = 100.0, std: float = 5.0, deviation_factor: float = 0.0
) -> Dict[str, float]:
    """Create cycle readings with a uniform deviation from baseline.

    Args:
        mean: Baseline mean value for all sensors.
        std: Baseline std for all sensors.
        deviation_factor: How many standard deviations away from mean.
    """
    value = mean + std * deviation_factor
    return {sensor: value for sensor in _all_sensors()}


# ---------------------------------------------------------------------------
# Tests: Sensor-to-Subsystem Mapping Completeness (Requirement 4.1)
# ---------------------------------------------------------------------------


class TestSensorSubsystemMapping:
    """Tests that the sensor-to-subsystem mapping covers all 21 C-MAPSS sensors."""

    def test_total_sensor_count_is_21(self) -> None:
        """All 21 C-MAPSS sensors are mapped to subsystems."""
        total_sensors = sum(len(sensors) for sensors in SUBSYSTEM_SENSOR_MAP.values())
        assert total_sensors == 21

    def test_exactly_six_subsystems(self) -> None:
        """Mapping defines exactly 6 subsystems."""
        assert len(SUBSYSTEM_SENSOR_MAP) == 6
        expected_subsystems = {"fan", "lpc", "hpc", "hpt", "lpt", "combustor"}
        assert set(SUBSYSTEM_SENSOR_MAP.keys()) == expected_subsystems

    def test_no_duplicate_sensors_across_subsystems(self) -> None:
        """Each sensor is assigned to exactly one subsystem (no duplicates)."""
        all_sensors = _all_sensors()
        assert len(all_sensors) == len(set(all_sensors)), (
            "Duplicate sensors found across subsystems"
        )

    def test_fan_subsystem_sensors(self) -> None:
        """Fan subsystem contains expected sensors."""
        fan_sensors = SUBSYSTEM_SENSOR_MAP["fan"]
        assert "fan_inlet_temp_total" in fan_sensors
        assert "fan_inlet_pressure_total" in fan_sensors
        assert "physical_fan_speed_rpm" in fan_sensors
        assert "corrected_fan_speed_rpm" in fan_sensors

    def test_hpc_subsystem_sensors(self) -> None:
        """HPC subsystem contains expected sensors."""
        hpc_sensors = SUBSYSTEM_SENSOR_MAP["hpc"]
        assert "hpc_outlet_temp_total" in hpc_sensors
        assert "hpc_outlet_pressure_total" in hpc_sensors
        assert "hpc_outlet_static_pressure" in hpc_sensors
        assert "physical_core_speed_rpm" in hpc_sensors
        assert "corrected_core_speed_rpm" in hpc_sensors

    def test_lpt_subsystem_has_single_sensor(self) -> None:
        """LPT subsystem has exactly 1 sensor (smallest subsystem)."""
        assert len(SUBSYSTEM_SENSOR_MAP["lpt"]) == 1
        assert "lpt_coolant_bleed" in SUBSYSTEM_SENSOR_MAP["lpt"]

    def test_each_subsystem_has_at_least_one_sensor(self) -> None:
        """Every subsystem has at least one mapped sensor."""
        for subsystem_name, sensors in SUBSYSTEM_SENSOR_MAP.items():
            assert len(sensors) >= 1, f"{subsystem_name} has no sensors"


# ---------------------------------------------------------------------------
# Tests: Classification with Hysteresis (Requirements 4.3, 4.4)
# ---------------------------------------------------------------------------


class TestClassificationHysteresis:
    """Tests for threshold crossings with and without hysteresis."""

    def test_fresh_classification_nominal(self) -> None:
        """Score above nominal threshold with nominal previous → nominal."""
        mapper = _make_mapper()
        result = mapper.get_classification(0.8, "nominal", 0.8)
        assert result == "nominal"

    def test_fresh_classification_degraded(self) -> None:
        """Score in degraded range with degraded previous → degraded."""
        mapper = _make_mapper()
        result = mapper.get_classification(0.55, "degraded", 0.55)
        assert result == "degraded"

    def test_fresh_classification_critical(self) -> None:
        """Score below critical threshold with critical previous → critical."""
        mapper = _make_mapper()
        result = mapper.get_classification(0.2, "critical", 0.2)
        assert result == "critical"

    def test_nominal_to_degraded_requires_hysteresis(self) -> None:
        """Nominal → degraded requires score below 0.7 - 0.03 = 0.67."""
        mapper = _make_mapper()

        # Score at 0.68 (below 0.7 but not below 0.67) → stays nominal
        result = mapper.get_classification(0.68, "nominal", 0.8)
        assert result == "nominal"

        # Score at 0.66 (below 0.67) → transitions to degraded
        result = mapper.get_classification(0.66, "nominal", 0.8)
        assert result == "degraded"

    def test_degraded_to_nominal_requires_hysteresis(self) -> None:
        """Degraded → nominal requires score above 0.7 + 0.03 = 0.73."""
        mapper = _make_mapper()

        # Score at 0.72 (above 0.7 but not above 0.73) → stays degraded
        result = mapper.get_classification(0.72, "degraded", 0.55)
        assert result == "degraded"

        # Score at 0.74 (above 0.73) → transitions to nominal
        result = mapper.get_classification(0.74, "degraded", 0.55)
        assert result == "nominal"

    def test_degraded_to_critical_requires_hysteresis(self) -> None:
        """Degraded → critical requires score below 0.4 - 0.03 = 0.37."""
        mapper = _make_mapper()

        # Score at 0.38 (below 0.4 but not below 0.37) → stays degraded
        result = mapper.get_classification(0.38, "degraded", 0.55)
        assert result == "degraded"

        # Score at 0.36 (below 0.37) → transitions to critical
        result = mapper.get_classification(0.36, "degraded", 0.55)
        assert result == "critical"

    def test_critical_to_degraded_requires_hysteresis(self) -> None:
        """Critical → degraded requires score above 0.4 + 0.03 = 0.43."""
        mapper = _make_mapper()

        # Score at 0.42 (above 0.4 but not above 0.43) → stays critical
        result = mapper.get_classification(0.42, "critical", 0.2)
        assert result == "critical"

        # Score at 0.44 (above 0.43) → transitions to degraded
        result = mapper.get_classification(0.44, "critical", 0.2)
        assert result == "degraded"

    def test_exact_boundary_nominal_stays_nominal(self) -> None:
        """Score exactly at nominal threshold (0.7) stays nominal."""
        mapper = _make_mapper()
        result = mapper.get_classification(0.7, "nominal", 0.8)
        assert result == "nominal"

    def test_exact_boundary_hysteresis_point_nominal_to_degraded(self) -> None:
        """Score exactly at 0.67 (threshold - hysteresis) stays nominal."""
        mapper = _make_mapper()
        # Score at exactly 0.67 is NOT less than 0.67, so stays nominal
        result = mapper.get_classification(
            NOMINAL_THRESHOLD - HYSTERESIS_BAND, "nominal", 0.8
        )
        assert result == "nominal"

    def test_nominal_directly_to_critical(self) -> None:
        """Nominal can transition directly to critical if score drops far enough."""
        mapper = _make_mapper()
        # Score at 0.35 is below degraded threshold - hysteresis (0.37)
        result = mapper.get_classification(0.35, "nominal", 0.8)
        assert result == "critical"

    def test_critical_directly_to_nominal(self) -> None:
        """Critical can transition directly to nominal if score rises far enough."""
        mapper = _make_mapper()
        # Score at 0.74 is above nominal threshold + hysteresis (0.73)
        result = mapper.get_classification(0.74, "critical", 0.2)
        assert result == "nominal"

    def test_hysteresis_prevents_oscillation(self) -> None:
        """Score hovering near threshold doesn't cause state flipping."""
        mapper = _make_mapper()

        # Start nominal, drop to boundary zone
        result1 = mapper.get_classification(0.69, "nominal", 0.8)
        assert result1 == "nominal"  # Still in hysteresis zone

        # Still in boundary zone from nominal perspective
        result2 = mapper.get_classification(0.68, "nominal", 0.8)
        assert result2 == "nominal"

        # Drop below hysteresis band
        result3 = mapper.get_classification(0.66, "nominal", 0.8)
        assert result3 == "degraded"

        # Now from degraded, rise back to 0.69 (in hysteresis zone from degraded)
        result4 = mapper.get_classification(0.69, "degraded", 0.66)
        assert result4 == "degraded"  # Still degraded, hasn't crossed 0.73


# ---------------------------------------------------------------------------
# Tests: Incomplete Subsystem Behavior (Requirement 4.6)
# ---------------------------------------------------------------------------


class TestIncompleteSubsystem:
    """Tests for incomplete subsystem detection and state retention."""

    def test_incomplete_subsystem_retains_previous_state(self) -> None:
        """When < half sensors valid, previous state is retained."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id)

        # First: establish a previous state with full readings
        full_readings = _make_readings_at_baseline()
        mapper.compute_subsystem_health(engine_id, full_readings)

        # Now provide readings with only 1 sensor for fan (needs 3 of 5)
        partial_readings = {sensor: 100.0 for sensor in _all_sensors()}
        # Remove enough fan sensors to make it incomplete (< ceil(5/2) = 3 valid)
        fan_sensors = SUBSYSTEM_SENSOR_MAP["fan"]
        for sensor in fan_sensors[:3]:  # remove 3 out of 5 → only 2 left
            del partial_readings[sensor]

        results = mapper.compute_subsystem_health(engine_id, partial_readings)

        # Fan should be marked incomplete and retain previous state
        assert results["fan"].is_incomplete is True

    def test_incomplete_subsystem_uses_default_when_no_previous(self) -> None:
        """When < half sensors valid and no previous state, defaults to nominal."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id)

        # Provide readings with no fan sensors at all
        readings = _make_readings_at_baseline()
        for sensor in SUBSYSTEM_SENSOR_MAP["fan"]:
            del readings[sensor]

        results = mapper.compute_subsystem_health(engine_id, readings)

        # Fan should be incomplete with default nominal state
        assert results["fan"].is_incomplete is True
        assert results["fan"].classification == "nominal"
        assert results["fan"].health_score == 1.0

    def test_lpt_single_sensor_complete_when_present(self) -> None:
        """LPT with its single sensor present is NOT incomplete (1 >= ceil(1/2))."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id)

        readings = _make_readings_at_baseline()
        results = mapper.compute_subsystem_health(engine_id, readings)

        # LPT has 1 sensor, needs ceil(1/2) = 1 → complete when sensor is present
        assert results["lpt"].is_incomplete is False

    def test_lpt_single_sensor_incomplete_when_absent(self) -> None:
        """LPT without its sensor is incomplete (0 < ceil(1/2) = 1)."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id)

        readings = _make_readings_at_baseline()
        del readings["lpt_coolant_bleed"]

        # First compute to establish previous state
        mapper.compute_subsystem_health(engine_id, _make_readings_at_baseline())

        # Now compute with missing LPT sensor
        results = mapper.compute_subsystem_health(engine_id, readings)
        assert results["lpt"].is_incomplete is True

    def test_incomplete_retains_degraded_state(self) -> None:
        """Incomplete subsystem retains a previously-degraded classification."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id, mean=100.0, std=5.0)

        # Set up a degraded state for fan by providing deviated readings
        # Deviation of 2 std → sensor_health = 1.0 - (2.0 / 3.0) ≈ 0.333
        # That's critical. Let's use ~1.2 std → 1.0 - 1.2/3.0 = 0.6 → degraded
        degraded_readings = _make_readings_at_baseline()
        for sensor in SUBSYSTEM_SENSOR_MAP["fan"]:
            degraded_readings[sensor] = 100.0 + 5.0 * 1.2  # 1.2 std devs away

        # Establish a degraded state for fan
        # Since this is first invocation, previous is "nominal"
        # Score will be ~0.6, and from nominal to degraded requires < 0.67
        results1 = mapper.compute_subsystem_health(engine_id, degraded_readings)
        assert results1["fan"].classification == "degraded"

        # Now make fan incomplete by removing sensors
        partial_readings = _make_readings_at_baseline()
        for sensor in SUBSYSTEM_SENSOR_MAP["fan"][:3]:
            del partial_readings[sensor]

        results2 = mapper.compute_subsystem_health(engine_id, partial_readings)

        # Fan retains degraded classification
        assert results2["fan"].is_incomplete is True
        assert results2["fan"].classification == "degraded"

    def test_complete_subsystems_unaffected_by_other_incomplete(self) -> None:
        """Incomplete subsystem doesn't affect other complete subsystems."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id)

        # Establish initial state
        mapper.compute_subsystem_health(engine_id, _make_readings_at_baseline())

        # Remove all fan sensors (making fan incomplete) but keep all others
        readings = _make_readings_at_baseline()
        for sensor in SUBSYSTEM_SENSOR_MAP["fan"]:
            del readings[sensor]

        results = mapper.compute_subsystem_health(engine_id, readings)

        # Fan is incomplete
        assert results["fan"].is_incomplete is True

        # Other subsystems still compute normally
        assert results["hpc"].is_incomplete is False
        assert results["lpc"].is_incomplete is False
        assert results["combustor"].is_incomplete is False


# ---------------------------------------------------------------------------
# Tests: Health Score Computation
# ---------------------------------------------------------------------------


class TestHealthScoreComputation:
    """Tests that per-subsystem health scores are computed correctly."""

    def test_perfect_health_at_baseline(self) -> None:
        """All sensors at baseline mean produces health score of 1.0."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id, mean=100.0, std=5.0)

        readings = _make_readings_at_baseline(mean=100.0)
        results = mapper.compute_subsystem_health(engine_id, readings)

        for subsystem_name, health in results.items():
            assert health.health_score == pytest.approx(1.0), (
                f"{subsystem_name} should be 1.0 at baseline"
            )

    def test_health_score_decreases_with_deviation(self) -> None:
        """Health score decreases as sensors deviate from baseline."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id, mean=100.0, std=5.0)

        # Readings at 1 std dev away
        readings_1std = _make_readings_with_deviation(
            mean=100.0, std=5.0, deviation_factor=1.0
        )
        results_1std = mapper.compute_subsystem_health(engine_id, readings_1std)

        # Readings at 2 std devs away
        readings_2std = _make_readings_with_deviation(
            mean=100.0, std=5.0, deviation_factor=2.0
        )
        results_2std = mapper.compute_subsystem_health(engine_id, readings_2std)

        # Health at 2 std should be lower than at 1 std
        for subsystem_name in SUBSYSTEM_SENSOR_MAP:
            assert results_2std[subsystem_name].health_score < results_1std[subsystem_name].health_score

    def test_health_score_clamped_to_zero(self) -> None:
        """Health score is clamped to 0.0 for extreme deviations."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id, mean=100.0, std=5.0)

        # Readings at 10 std devs away → deviation = 10.0, health = 1.0 - 10/3 < 0 → 0.0
        readings = _make_readings_with_deviation(
            mean=100.0, std=5.0, deviation_factor=10.0
        )
        results = mapper.compute_subsystem_health(engine_id, readings)

        for subsystem_name, health in results.items():
            assert health.health_score == 0.0

    def test_health_score_in_valid_range(self) -> None:
        """Health scores are always in [0.0, 1.0]."""
        mapper = _make_mapper()
        engine_id = 1
        _setup_baselines(mapper, engine_id, mean=100.0, std=5.0)

        readings = _make_readings_with_deviation(
            mean=100.0, std=5.0, deviation_factor=1.5
        )
        results = mapper.compute_subsystem_health(engine_id, readings)

        for subsystem_name, health in results.items():
            assert 0.0 <= health.health_score <= 1.0
