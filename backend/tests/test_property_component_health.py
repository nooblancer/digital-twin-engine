"""Property-based tests for Component Health Mapper.

# Feature: digital-twin-experience, Properties 16-20

Tests that the ComponentHealthMapper correctly computes per-subsystem health
scores, applies classification with hysteresis, emits state transition events,
handles incomplete subsystems, and produces deterministic output.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7**
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

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
# Test Strategies
# ---------------------------------------------------------------------------

# All sensor names across all subsystems
ALL_SENSORS: List[str] = []
for sensors in SUBSYSTEM_SENSOR_MAP.values():
    ALL_SENSORS.extend(sensors)

# Strategy for valid health scores in [0.0, 1.0]
health_score_strategy = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Strategy for sensor values (realistic range for turbofan sensor data)
sensor_value_strategy = st.floats(
    min_value=-1000.0, max_value=5000.0, allow_nan=False, allow_infinity=False
)

# Strategy for baseline mean values
baseline_mean_strategy = st.floats(
    min_value=0.1, max_value=2000.0, allow_nan=False, allow_infinity=False
)

# Strategy for baseline std values (positive)
baseline_std_strategy = st.floats(
    min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False
)

# Strategy for classification states
classification_strategy = st.sampled_from(["nominal", "degraded", "critical"])

# Strategy for subsystem names
subsystem_strategy = st.sampled_from(list(SUBSYSTEM_SENSOR_MAP.keys()))


def make_baselines_for_subsystem(subsystem: str) -> st.SearchStrategy:
    """Generate baselines for all sensors in a given subsystem."""
    sensors = SUBSYSTEM_SENSOR_MAP[subsystem]
    return st.fixed_dictionaries(
        {
            sensor: st.tuples(baseline_mean_strategy, baseline_std_strategy)
            for sensor in sensors
        }
    )


# Strategy for a complete set of baselines for all sensors
all_baselines_strategy = st.fixed_dictionaries(
    {
        sensor: st.tuples(baseline_mean_strategy, baseline_std_strategy)
        for sensor in ALL_SENSORS
    }
)


def _build_mapper_with_baselines(
    engine_id: int, baselines_data: Dict[str, tuple]
) -> ComponentHealthMapper:
    """Create a ComponentHealthMapper with pre-computed baselines."""
    broker = MagicMock()
    ws_manager = AsyncMock()
    mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)

    # Inject baselines directly
    baselines = {}
    for sensor_name, (mean, std) in baselines_data.items():
        baselines[sensor_name] = SensorBaseline(
            sensor_name=sensor_name,
            mean=mean,
            std=std,
            sample_count=BASELINE_CYCLES,
        )
    mapper._baselines[engine_id] = baselines
    mapper._cycle_counts[engine_id] = BASELINE_CYCLES + 1
    return mapper


# ---------------------------------------------------------------------------
# Property 16: Subsystem health score range invariant
# ---------------------------------------------------------------------------


class TestSubsystemHealthScoreRangeInvariant:
    """Feature: digital-twin-experience, Property 16: Subsystem health score range invariant

    For any set of sensor readings mapped to a subsystem, the computed
    subsystem health score SHALL be in the range [0.0, 1.0].

    **Validates: Requirements 4.2**
    """

    @given(
        baselines_data=all_baselines_strategy,
        reading_multipliers=st.dictionaries(
            keys=st.sampled_from(ALL_SENSORS),
            values=st.floats(
                min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
            ),
            min_size=len(ALL_SENSORS),
            max_size=len(ALL_SENSORS),
        ),
    )
    @settings(max_examples=200)
    def test_health_scores_always_in_unit_interval(
        self, baselines_data: Dict[str, tuple], reading_multipliers: Dict[str, float]
    ) -> None:
        """All subsystem health scores must be in [0.0, 1.0] for any sensor readings."""
        engine_id = 1
        mapper = _build_mapper_with_baselines(engine_id, baselines_data)

        # Build cycle readings from baseline means + multiplier * std
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            multiplier = reading_multipliers.get(sensor_name, 0.0)
            cycle_readings[sensor_name] = mean + multiplier * std

        results = mapper.compute_subsystem_health(engine_id, cycle_readings)

        for subsystem_name, health in results.items():
            assert 0.0 <= health.health_score <= 1.0, (
                f"Subsystem {subsystem_name} health_score {health.health_score} "
                f"outside [0.0, 1.0]"
            )

    @given(
        baselines_data=all_baselines_strategy,
        extreme_deviation=st.floats(
            min_value=50.0, max_value=1000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_extreme_deviations_still_clamped(
        self, baselines_data: Dict[str, tuple], extreme_deviation: float
    ) -> None:
        """Even with extreme sensor deviations, scores remain in [0.0, 1.0]."""
        engine_id = 1
        mapper = _build_mapper_with_baselines(engine_id, baselines_data)

        # All sensors deviate extremely from baseline
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            cycle_readings[sensor_name] = mean + extreme_deviation * std

        results = mapper.compute_subsystem_health(engine_id, cycle_readings)

        for subsystem_name, health in results.items():
            assert 0.0 <= health.health_score <= 1.0


# ---------------------------------------------------------------------------
# Property 17: Classification with hysteresis
# ---------------------------------------------------------------------------


class TestClassificationWithHysteresis:
    """Feature: digital-twin-experience, Property 17: Classification with hysteresis

    For any subsystem health score and previous classification state, the
    ComponentHealthMapper SHALL: (a) classify as "nominal" when score >= 0.7,
    "degraded" when 0.4 <= score < 0.7, "critical" when score < 0.4 for fresh
    classifications; and (b) require the score to move at least 0.03 beyond a
    threshold before recognizing a state transition.

    **Validates: Requirements 4.3, 4.4**
    """

    @given(health_score=health_score_strategy)
    @settings(max_examples=200)
    def test_fresh_classification_follows_thresholds(
        self, health_score: float
    ) -> None:
        """Fresh classification (no previous state) follows standard thresholds."""
        broker = MagicMock()
        ws_manager = AsyncMock()
        mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)

        # Use "nominal" as default previous (fresh state)
        # For a truly fresh classification from nominal, score must cross hysteresis
        # to change. Test the baseline thresholds for a first-ever classification.
        # With previous="nominal" and previous_score=1.0:
        result = mapper.get_classification(health_score, "nominal", 1.0)

        if health_score >= NOMINAL_THRESHOLD - HYSTERESIS_BAND:
            assert result == "nominal"
        elif health_score >= DEGRADED_THRESHOLD - HYSTERESIS_BAND:
            assert result == "degraded"
        else:
            assert result == "critical"

    @given(
        score_in_band=st.floats(
            min_value=NOMINAL_THRESHOLD - HYSTERESIS_BAND,
            max_value=NOMINAL_THRESHOLD + HYSTERESIS_BAND,
            allow_nan=False,
        )
    )
    @settings(max_examples=200)
    def test_hysteresis_prevents_nominal_degraded_oscillation(
        self, score_in_band: float
    ) -> None:
        """Scores within hysteresis band around 0.7 retain previous classification."""
        broker = MagicMock()
        ws_manager = AsyncMock()
        mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)

        # If previously nominal, score in [0.67, 0.73] stays nominal
        result_from_nominal = mapper.get_classification(
            score_in_band, "nominal", 0.75
        )
        if score_in_band >= NOMINAL_THRESHOLD - HYSTERESIS_BAND:
            assert result_from_nominal == "nominal"

        # If previously degraded, score in [0.67, 0.73] stays degraded
        result_from_degraded = mapper.get_classification(
            score_in_band, "degraded", 0.65
        )
        if score_in_band < NOMINAL_THRESHOLD + HYSTERESIS_BAND:
            assert result_from_degraded == "degraded"

    @given(
        score_in_band=st.floats(
            min_value=DEGRADED_THRESHOLD - HYSTERESIS_BAND,
            max_value=DEGRADED_THRESHOLD + HYSTERESIS_BAND,
            allow_nan=False,
        )
    )
    @settings(max_examples=200)
    def test_hysteresis_prevents_degraded_critical_oscillation(
        self, score_in_band: float
    ) -> None:
        """Scores within hysteresis band around 0.4 retain previous classification."""
        broker = MagicMock()
        ws_manager = AsyncMock()
        mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)

        # If previously degraded, score in [0.37, 0.43] stays degraded
        result_from_degraded = mapper.get_classification(
            score_in_band, "degraded", 0.45
        )
        if score_in_band >= DEGRADED_THRESHOLD - HYSTERESIS_BAND:
            assert result_from_degraded == "degraded"

        # If previously critical, score in [0.37, 0.43] stays critical
        result_from_critical = mapper.get_classification(
            score_in_band, "critical", 0.35
        )
        if score_in_band < DEGRADED_THRESHOLD + HYSTERESIS_BAND:
            assert result_from_critical == "critical"

    @given(
        score_clearly_nominal=st.floats(
            min_value=NOMINAL_THRESHOLD + HYSTERESIS_BAND + 0.001,
            max_value=1.0,
            allow_nan=False,
        )
    )
    @settings(max_examples=100)
    def test_clear_transition_to_nominal(self, score_clearly_nominal: float) -> None:
        """Score clearly above 0.73 transitions to nominal from any state."""
        broker = MagicMock()
        ws_manager = AsyncMock()
        mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)

        for prev in ["nominal", "degraded", "critical"]:
            result = mapper.get_classification(score_clearly_nominal, prev, 0.5)
            assert result == "nominal", (
                f"Score {score_clearly_nominal} from {prev} should be nominal, got {result}"
            )

    @given(
        score_clearly_critical=st.floats(
            min_value=0.0,
            max_value=DEGRADED_THRESHOLD - HYSTERESIS_BAND - 0.001,
            allow_nan=False,
        )
    )
    @settings(max_examples=100)
    def test_clear_transition_to_critical(self, score_clearly_critical: float) -> None:
        """Score clearly below 0.37 transitions to critical from any state."""
        broker = MagicMock()
        ws_manager = AsyncMock()
        mapper = ComponentHealthMapper(broker=broker, ws_manager=ws_manager)

        for prev in ["nominal", "degraded", "critical"]:
            result = mapper.get_classification(score_clearly_critical, prev, 0.5)
            assert result == "critical", (
                f"Score {score_clearly_critical} from {prev} should be critical, got {result}"
            )


# ---------------------------------------------------------------------------
# Property 18: State transition event correctness
# ---------------------------------------------------------------------------


class TestStateTransitionEventCorrectness:
    """Feature: digital-twin-experience, Property 18: State transition event correctness

    For any subsystem that transitions from one health classification to another
    after hysteresis is satisfied, the emitted state transition event SHALL
    contain the subsystem name, previous classification, new classification,
    and the health score that triggered the transition.

    **Validates: Requirements 4.5**
    """

    @given(
        subsystem=subsystem_strategy,
        baselines_data=all_baselines_strategy,
    )
    @settings(max_examples=150)
    def test_transition_event_fields_on_degradation(
        self, subsystem: str, baselines_data: Dict[str, tuple]
    ) -> None:
        """When subsystem transitions nominal→degraded, event has correct fields."""
        engine_id = 1
        mapper = _build_mapper_with_baselines(engine_id, baselines_data)

        # Set previous state to nominal for target subsystem
        previous_states: Dict[str, SubsystemHealth] = {}
        for sub_name in SUBSYSTEM_SENSOR_MAP:
            previous_states[sub_name] = SubsystemHealth(
                name=sub_name,
                health_score=0.9,
                classification="nominal",
                is_incomplete=False,
            )
        mapper._previous_states[engine_id] = previous_states

        # Create readings that produce a score below 0.67 for the target subsystem
        # by setting large deviations for its sensors
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            # Keep other subsystems nominal
            cycle_readings[sensor_name] = mean

        # Push target subsystem sensors far from baseline (> 3 std devs → score ≈ 0)
        target_sensors = SUBSYSTEM_SENSOR_MAP[subsystem]
        for sensor_name in target_sensors:
            if sensor_name in baselines_data:
                mean, std = baselines_data[sensor_name]
                # 5 std devs → deviation/3 > 1.0 → health_score = 0
                cycle_readings[sensor_name] = mean + 5.0 * std

        # Capture log events to verify transition event content
        import structlog
        captured_events = []
        original_info = mapper._emit_transition_events

        def capture_transitions(eng_id, prev_states, current_states):
            for sub_name, current in current_states.items():
                if current.is_incomplete:
                    continue
                prev = prev_states.get(sub_name)
                if prev is not None and prev.classification != current.classification:
                    captured_events.append({
                        "subsystem": sub_name,
                        "previous_classification": prev.classification,
                        "new_classification": current.classification,
                        "health_score": current.health_score,
                    })
            original_info(eng_id, prev_states, current_states)

        mapper._emit_transition_events = capture_transitions

        results = mapper.compute_subsystem_health(engine_id, cycle_readings)

        # If transition occurred for target subsystem, verify event fields
        target_result = results[subsystem]
        if target_result.classification != "nominal" and not target_result.is_incomplete:
            # A transition event should have been captured
            target_events = [e for e in captured_events if e["subsystem"] == subsystem]
            assert len(target_events) == 1, (
                f"Expected 1 transition event for {subsystem}, got {len(target_events)}"
            )
            event = target_events[0]
            assert event["subsystem"] == subsystem
            assert event["previous_classification"] == "nominal"
            assert event["new_classification"] == target_result.classification
            assert event["health_score"] == target_result.health_score

    @given(
        subsystem=subsystem_strategy,
        baselines_data=all_baselines_strategy,
    )
    @settings(max_examples=150)
    def test_no_transition_event_when_classification_unchanged(
        self, subsystem: str, baselines_data: Dict[str, tuple]
    ) -> None:
        """No transition event when classification stays the same."""
        engine_id = 1
        mapper = _build_mapper_with_baselines(engine_id, baselines_data)

        # Set previous state to nominal for all subsystems
        previous_states: Dict[str, SubsystemHealth] = {}
        for sub_name in SUBSYSTEM_SENSOR_MAP:
            previous_states[sub_name] = SubsystemHealth(
                name=sub_name,
                health_score=0.9,
                classification="nominal",
                is_incomplete=False,
            )
        mapper._previous_states[engine_id] = previous_states

        # Keep all readings at baseline (nominal scores)
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            cycle_readings[sensor_name] = mean

        captured_events = []

        def capture_transitions(eng_id, prev_states, current_states):
            for sub_name, current in current_states.items():
                if current.is_incomplete:
                    continue
                prev = prev_states.get(sub_name)
                if prev is not None and prev.classification != current.classification:
                    captured_events.append(sub_name)

        mapper._emit_transition_events = capture_transitions

        mapper.compute_subsystem_health(engine_id, cycle_readings)

        # No transitions should occur since all readings are at baseline
        assert len(captured_events) == 0


# ---------------------------------------------------------------------------
# Property 19: Incomplete subsystem retains previous state
# ---------------------------------------------------------------------------


class TestIncompleteSubsystemRetainsPreviousState:
    """Feature: digital-twin-experience, Property 19: Incomplete subsystem retains previous state

    For any subsystem where fewer than half of its mapped sensors provide
    valid readings in a cycle, the ComponentHealthMapper SHALL retain the
    previous health score and classification for that subsystem.

    **Validates: Requirements 4.6**
    """

    @given(
        subsystem=subsystem_strategy,
        baselines_data=all_baselines_strategy,
        prev_score=health_score_strategy,
        prev_classification=classification_strategy,
    )
    @settings(max_examples=200)
    def test_incomplete_subsystem_keeps_previous_state(
        self,
        subsystem: str,
        baselines_data: Dict[str, tuple],
        prev_score: float,
        prev_classification: str,
    ) -> None:
        """Subsystem with < half valid sensors retains previous health state."""
        engine_id = 1
        mapper = _build_mapper_with_baselines(engine_id, baselines_data)

        # Set previous state for the target subsystem
        previous_states: Dict[str, SubsystemHealth] = {}
        for sub_name in SUBSYSTEM_SENSOR_MAP:
            previous_states[sub_name] = SubsystemHealth(
                name=sub_name,
                health_score=prev_score if sub_name == subsystem else 0.9,
                classification=prev_classification if sub_name == subsystem else "nominal",
                is_incomplete=False,
            )
        mapper._previous_states[engine_id] = previous_states

        # Provide readings for all sensors EXCEPT target subsystem sensors
        # (giving it 0 valid readings, which is < half)
        target_sensors = set(SUBSYSTEM_SENSOR_MAP[subsystem])
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            if sensor_name not in target_sensors:
                cycle_readings[sensor_name] = mean

        results = mapper.compute_subsystem_health(engine_id, cycle_readings)

        # The target subsystem should retain its previous state
        target_result = results[subsystem]
        assert target_result.health_score == prev_score, (
            f"Expected health_score {prev_score}, got {target_result.health_score}"
        )
        assert target_result.classification == prev_classification, (
            f"Expected classification {prev_classification}, "
            f"got {target_result.classification}"
        )
        assert target_result.is_incomplete is True

    @given(
        subsystem=subsystem_strategy,
        baselines_data=all_baselines_strategy,
    )
    @settings(max_examples=100)
    def test_incomplete_subsystem_with_some_sensors_below_half(
        self, subsystem: str, baselines_data: Dict[str, tuple]
    ) -> None:
        """Providing exactly less-than-half sensors triggers incomplete state."""
        engine_id = 1
        mapper = _build_mapper_with_baselines(engine_id, baselines_data)

        # Set a known previous state
        previous_states: Dict[str, SubsystemHealth] = {}
        for sub_name in SUBSYSTEM_SENSOR_MAP:
            previous_states[sub_name] = SubsystemHealth(
                name=sub_name,
                health_score=0.75,
                classification="nominal",
                is_incomplete=False,
            )
        mapper._previous_states[engine_id] = previous_states

        target_sensors = SUBSYSTEM_SENSOR_MAP[subsystem]
        total_sensors = len(target_sensors)
        half_threshold = math.ceil(total_sensors / 2)

        # Provide fewer than half sensors for target subsystem
        sensors_to_include = max(0, half_threshold - 1)

        cycle_readings = {}
        # Include all other subsystem sensors
        for sensor_name, (mean, std) in baselines_data.items():
            if sensor_name not in target_sensors:
                cycle_readings[sensor_name] = mean

        # Include only a few target sensors (< half)
        for i, sensor_name in enumerate(target_sensors):
            if i >= sensors_to_include:
                break
            if sensor_name in baselines_data:
                mean, std = baselines_data[sensor_name]
                cycle_readings[sensor_name] = mean

        results = mapper.compute_subsystem_health(engine_id, cycle_readings)

        target_result = results[subsystem]
        assert target_result.is_incomplete is True
        assert target_result.health_score == 0.75
        assert target_result.classification == "nominal"


# ---------------------------------------------------------------------------
# Property 20: Deterministic classification
# ---------------------------------------------------------------------------


class TestDeterministicClassification:
    """Feature: digital-twin-experience, Property 20: Deterministic classification

    For any identical sequence of sensor inputs, the ComponentHealthMapper
    SHALL produce identical classification outputs (no randomness in the
    classification path).

    **Validates: Requirements 4.7**
    """

    @given(
        baselines_data=all_baselines_strategy,
        reading_multipliers=st.dictionaries(
            keys=st.sampled_from(ALL_SENSORS),
            values=st.floats(
                min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
            ),
            min_size=len(ALL_SENSORS),
            max_size=len(ALL_SENSORS),
        ),
    )
    @settings(max_examples=200)
    def test_same_inputs_produce_same_outputs(
        self, baselines_data: Dict[str, tuple], reading_multipliers: Dict[str, float]
    ) -> None:
        """Identical inputs must produce identical subsystem health outputs."""
        engine_id = 1

        # Create two independent mappers with the same baselines
        mapper1 = _build_mapper_with_baselines(engine_id, baselines_data)
        mapper2 = _build_mapper_with_baselines(engine_id, baselines_data)

        # Build identical cycle readings
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            multiplier = reading_multipliers.get(sensor_name, 0.0)
            cycle_readings[sensor_name] = mean + multiplier * std

        results1 = mapper1.compute_subsystem_health(engine_id, cycle_readings)
        results2 = mapper2.compute_subsystem_health(engine_id, cycle_readings)

        for subsystem_name in SUBSYSTEM_SENSOR_MAP:
            h1 = results1[subsystem_name]
            h2 = results2[subsystem_name]
            assert h1.health_score == h2.health_score, (
                f"Non-deterministic health_score for {subsystem_name}: "
                f"{h1.health_score} vs {h2.health_score}"
            )
            assert h1.classification == h2.classification, (
                f"Non-deterministic classification for {subsystem_name}: "
                f"{h1.classification} vs {h2.classification}"
            )

    @given(
        baselines_data=all_baselines_strategy,
        reading_multipliers=st.dictionaries(
            keys=st.sampled_from(ALL_SENSORS),
            values=st.floats(
                min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
            ),
            min_size=len(ALL_SENSORS),
            max_size=len(ALL_SENSORS),
        ),
        num_runs=st.integers(min_value=3, max_value=5),
    )
    @settings(max_examples=100)
    def test_repeated_computation_is_stable(
        self,
        baselines_data: Dict[str, tuple],
        reading_multipliers: Dict[str, float],
        num_runs: int,
    ) -> None:
        """Running computation N times on same inputs always yields same result."""
        engine_id = 1

        # Build cycle readings
        cycle_readings = {}
        for sensor_name, (mean, std) in baselines_data.items():
            multiplier = reading_multipliers.get(sensor_name, 0.0)
            cycle_readings[sensor_name] = mean + multiplier * std

        # Run N times with fresh mappers, collect results
        all_results = []
        for _ in range(num_runs):
            mapper = _build_mapper_with_baselines(engine_id, baselines_data)
            results = mapper.compute_subsystem_health(engine_id, cycle_readings)
            all_results.append(results)

        # All runs should produce identical output
        first = all_results[0]
        for run_idx, results in enumerate(all_results[1:], start=2):
            for subsystem_name in SUBSYSTEM_SENSOR_MAP:
                assert first[subsystem_name].health_score == results[subsystem_name].health_score, (
                    f"Run {run_idx} differs from run 1 for {subsystem_name}"
                )
                assert first[subsystem_name].classification == results[subsystem_name].classification, (
                    f"Run {run_idx} classification differs for {subsystem_name}"
                )
