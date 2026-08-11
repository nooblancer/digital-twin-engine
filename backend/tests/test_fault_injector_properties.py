"""Property-based tests for FaultInjector.

# Feature: digital-twin-v1.3, Properties 1–6

Tests that the FaultInjector correctly transforms sensor readings, generates
unique injection IDs, preserves identity when no faults are active, auto-expires
faults, selectively clears faults, and empties all state on clear_all.

**Validates: Requirements 1.1–1.8**
"""

from __future__ import annotations

import math
from typing import List

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from digital_twin_engine.simulation.fault_injector import FaultInjection, FaultInjector


# ---------------------------------------------------------------------------
# Test Strategies
# ---------------------------------------------------------------------------

# Strategy for raw sensor values (realistic range, avoid extremes that break float math)
raw_value_strategy = st.floats(
    min_value=-10000.0, max_value=10000.0, allow_nan=False, allow_infinity=False
)

# Strategy for fault magnitudes (must be > 0 per API contract)
magnitude_strategy = st.floats(
    min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False
)

# Strategy for duration cycles (positive integers)
duration_strategy = st.integers(min_value=1, max_value=100)

# Strategy for sensor IDs
sensor_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=50,
)

# Strategy for fault types
fault_type_strategy = st.sampled_from(["spike", "drift", "dropout", "noise"])


# ---------------------------------------------------------------------------
# Property 1: Fault Application Transforms Correctly
# ---------------------------------------------------------------------------


class TestFaultApplicationTransformsCorrectly:
    """Feature: digital-twin-v1.3, Property 1: Fault Application Transforms Correctly

    For any raw sensor value and any fault injection with type "spike" and
    magnitude M, applying the fault SHALL return raw_value * (1 + M/100).
    For type "dropout", it SHALL return 0.0. For type "noise", it SHALL return
    a value != raw_value (with overwhelming probability for magnitude > 0).
    For type "drift" at elapsed cycle T of duration D, it SHALL return
    raw_value + (magnitude/D * T).

    **Validates: Requirements 1.1, 1.3**
    """

    @given(
        raw_value=raw_value_strategy,
        magnitude=magnitude_strategy,
        duration=duration_strategy,
    )
    @settings(max_examples=100)
    def test_spike_transform(
        self, raw_value: float, magnitude: float, duration: int
    ) -> None:
        """Spike fault returns raw_value * (1 + magnitude/100)."""
        injector = FaultInjector()
        sensor_id = "test-sensor-spike"

        injector.inject(sensor_id, "spike", magnitude, duration)
        result = injector.apply(sensor_id, raw_value)

        expected = raw_value * (1.0 + magnitude / 100.0)
        assert math.isclose(result, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Spike: expected {expected}, got {result} "
            f"(raw={raw_value}, magnitude={magnitude})"
        )

    @given(
        raw_value=raw_value_strategy,
        magnitude=magnitude_strategy,
        duration=duration_strategy,
    )
    @settings(max_examples=100)
    def test_dropout_transform(
        self, raw_value: float, magnitude: float, duration: int
    ) -> None:
        """Dropout fault always returns 0.0 regardless of raw_value."""
        injector = FaultInjector()
        sensor_id = "test-sensor-dropout"

        injector.inject(sensor_id, "dropout", magnitude, duration)
        result = injector.apply(sensor_id, raw_value)

        assert result == 0.0, (
            f"Dropout: expected 0.0, got {result} (raw={raw_value})"
        )

    @given(
        raw_value=raw_value_strategy,
        magnitude=magnitude_strategy,
        duration=duration_strategy,
    )
    @settings(max_examples=100)
    def test_noise_transform(
        self, raw_value: float, magnitude: float, duration: int
    ) -> None:
        """Noise fault returns a value != raw_value (with overwhelming probability)."""
        injector = FaultInjector()
        sensor_id = "test-sensor-noise"

        injector.inject(sensor_id, "noise", magnitude, duration)
        result = injector.apply(sensor_id, raw_value)

        # With magnitude > 0, noise samples from N(0, magnitude).
        # Probability of exactly 0 noise is essentially 0 for continuous distribution.
        assert result != raw_value, (
            f"Noise: expected result != {raw_value}, but got exact same value"
        )

    @given(
        raw_value=raw_value_strategy,
        magnitude=magnitude_strategy,
        duration=st.integers(min_value=1, max_value=50),
        target_cycle=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_drift_transform(
        self, raw_value: float, magnitude: float, duration: int, target_cycle: int
    ) -> None:
        """Drift fault at elapsed cycle T of duration D returns raw + (magnitude/D * T)."""
        # target_cycle must be <= duration (fault expires after duration cycles)
        assume(target_cycle <= duration)

        injector = FaultInjector()
        sensor_id = "test-sensor-drift"

        injector.inject(sensor_id, "drift", magnitude, duration)

        # Apply (target_cycle - 1) times on the same sensor to advance elapsed counter
        # The implementation increments elapsed each call, so at call N, elapsed = N
        for _ in range(target_cycle - 1):
            injector.apply(sensor_id, 0.0)  # discard results, just advancing state

        # At the target_cycle-th call, elapsed will be target_cycle
        result = injector.apply(sensor_id, raw_value)

        expected = raw_value + (magnitude / duration) * target_cycle
        assert math.isclose(result, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Drift: expected {expected}, got {result} "
            f"(raw={raw_value}, magnitude={magnitude}, duration={duration}, "
            f"elapsed={target_cycle})"
        )


# ---------------------------------------------------------------------------
# Property 2: Injection ID Uniqueness
# ---------------------------------------------------------------------------


class TestInjectionIDUniqueness:
    """Feature: digital-twin-v1.3, Property 2: Injection ID Uniqueness

    For any sequence of N inject() calls with arbitrary valid parameters,
    all N returned injection_id strings SHALL be distinct from each other.

    **Validates: Requirements 1.2**
    """

    @given(
        num_injections=st.integers(min_value=2, max_value=50),
        fault_types=st.lists(
            fault_type_strategy, min_size=1, max_size=4
        ),
        magnitudes=st.lists(
            magnitude_strategy, min_size=1, max_size=10
        ),
        durations=st.lists(
            duration_strategy, min_size=1, max_size=10
        ),
    )
    @settings(max_examples=100)
    def test_all_injection_ids_are_distinct(
        self,
        num_injections: int,
        fault_types: List[str],
        magnitudes: List[float],
        durations: List[int],
    ) -> None:
        """All injection IDs from N inject() calls must be unique."""
        injector = FaultInjector()
        ids: List[str] = []

        for i in range(num_injections):
            sid = f"sensor-{i % 5}"
            mag = magnitudes[i % len(magnitudes)]
            dur = durations[i % len(durations)]
            ft = fault_types[i % len(fault_types)]

            injection_id = injector.inject(sid, ft, mag, dur)
            ids.append(injection_id)

        assert len(ids) == len(set(ids)), (
            f"Duplicate injection IDs found among {num_injections} injections: "
            f"{len(ids) - len(set(ids))} duplicates"
        )


# ---------------------------------------------------------------------------
# Property 3: No-Fault Identity
# ---------------------------------------------------------------------------


class TestNoFaultIdentity:
    """Feature: digital-twin-v1.3, Property 3: No-Fault Identity

    For any sensor_id that has no active fault injections and any raw_value
    (float), calling apply(sensor_id, raw_value) SHALL return exactly
    raw_value (bitwise equality).

    **Validates: Requirements 1.4**
    """

    @given(
        sensor_id=sensor_id_strategy,
        raw_value=raw_value_strategy,
    )
    @settings(max_examples=100)
    def test_no_fault_returns_raw_value_unchanged(
        self, sensor_id: str, raw_value: float
    ) -> None:
        """apply() with no active faults returns raw_value unchanged (bitwise)."""
        injector = FaultInjector()

        result = injector.apply(sensor_id, raw_value)

        # Bitwise equality — no floating-point tolerance, must be exact
        assert result == raw_value, (
            f"No-fault identity violated: expected {raw_value!r}, got {result!r}"
        )

    @given(
        sensor_id=sensor_id_strategy,
        raw_value=raw_value_strategy,
        other_sensor=sensor_id_strategy,
        magnitude=magnitude_strategy,
        duration=duration_strategy,
        fault_type=fault_type_strategy,
    )
    @settings(max_examples=100)
    def test_fault_on_other_sensor_does_not_affect_this_sensor(
        self,
        sensor_id: str,
        raw_value: float,
        other_sensor: str,
        magnitude: float,
        duration: int,
        fault_type: str,
    ) -> None:
        """Fault on a different sensor does not affect this sensor's apply()."""
        assume(sensor_id != other_sensor)

        injector = FaultInjector()
        injector.inject(other_sensor, fault_type, magnitude, duration)

        result = injector.apply(sensor_id, raw_value)

        assert result == raw_value, (
            f"Fault on '{other_sensor}' affected '{sensor_id}': "
            f"expected {raw_value!r}, got {result!r}"
        )


# ---------------------------------------------------------------------------
# Property 4: Fault Auto-Expiration
# ---------------------------------------------------------------------------


class TestFaultAutoExpiration:
    """Feature: digital-twin-v1.3, Property 4: Fault Auto-Expiration

    For any fault injection with duration_cycles=N, after calling apply() on
    that sensor exactly N times, the injection SHALL no longer appear in
    get_active() and subsequent apply() calls SHALL return the raw value
    unchanged for that injection.

    **Validates: Requirements 1.5**
    """

    @given(
        duration=st.integers(min_value=1, max_value=30),
        raw_value=raw_value_strategy,
        magnitude=magnitude_strategy,
    )
    @settings(max_examples=100)
    def test_fault_expires_after_duration_cycles(
        self, duration: int, raw_value: float, magnitude: float
    ) -> None:
        """After N apply() calls, the fault is gone from get_active()."""
        injector = FaultInjector()
        sensor_id = "test-sensor-expire"

        injection_id = injector.inject(sensor_id, "spike", magnitude, duration)

        # Verify it's active before exhaustion
        active_ids = [f["injection_id"] for f in injector.get_active()]
        assert injection_id in active_ids

        # Apply exactly N times to exhaust the fault
        for _ in range(duration):
            injector.apply(sensor_id, raw_value)

        # After N applications, the fault should be expired
        active_ids = [f["injection_id"] for f in injector.get_active()]
        assert injection_id not in active_ids, (
            f"Fault {injection_id} still active after {duration} apply() calls"
        )

    @given(
        duration=st.integers(min_value=1, max_value=30),
        raw_value=raw_value_strategy,
        magnitude=magnitude_strategy,
    )
    @settings(max_examples=100)
    def test_apply_returns_raw_after_expiration(
        self, duration: int, raw_value: float, magnitude: float
    ) -> None:
        """After fault expires, apply() returns raw_value unchanged."""
        injector = FaultInjector()
        sensor_id = "test-sensor-expire-identity"

        injector.inject(sensor_id, "spike", magnitude, duration)

        # Exhaust the fault
        for _ in range(duration):
            injector.apply(sensor_id, 1.0)

        # Now apply with the actual test value — should be identity
        result = injector.apply(sensor_id, raw_value)
        assert result == raw_value, (
            f"After expiration, expected {raw_value!r}, got {result!r}"
        )


# ---------------------------------------------------------------------------
# Property 5: Selective Clear Preserves Others
# ---------------------------------------------------------------------------


class TestSelectiveClearPreservesOthers:
    """Feature: digital-twin-v1.3, Property 5: Selective Clear Preserves Others

    For any set of K active injections (K >= 2), clearing one injection by ID
    SHALL remove exactly that injection from get_active() while all other K-1
    injections remain active and unmodified.

    **Validates: Requirements 1.6**
    """

    @given(
        num_injections=st.integers(min_value=2, max_value=10),
        clear_index=st.integers(min_value=0, max_value=9),
        magnitudes=st.lists(
            magnitude_strategy, min_size=10, max_size=10
        ),
        durations=st.lists(
            st.integers(min_value=10, max_value=100), min_size=10, max_size=10
        ),
    )
    @settings(max_examples=100)
    def test_clearing_one_preserves_others(
        self,
        num_injections: int,
        clear_index: int,
        magnitudes: List[float],
        durations: List[int],
    ) -> None:
        """Clearing one injection leaves all others active and unmodified."""
        # Ensure clear_index is valid for the number of injections
        clear_index = clear_index % num_injections

        injector = FaultInjector()
        injection_ids: List[str] = []

        # Create K injections on different sensors to avoid interaction
        for i in range(num_injections):
            sid = f"sensor-{i}"
            ft = "spike"
            inj_id = injector.inject(sid, ft, magnitudes[i], durations[i])
            injection_ids.append(inj_id)

        # Record active state before clear
        active_before = injector.get_active()
        assert len(active_before) == num_injections

        # Clear one injection
        cleared_id = injection_ids[clear_index]
        injector.clear(cleared_id)

        # Verify cleared injection is gone
        active_after = injector.get_active()
        active_ids_after = {f["injection_id"] for f in active_after}

        assert cleared_id not in active_ids_after, (
            f"Cleared injection {cleared_id} still in get_active()"
        )

        # Verify all others remain
        expected_remaining = set(injection_ids) - {cleared_id}
        assert active_ids_after == expected_remaining, (
            f"Expected remaining IDs {expected_remaining}, got {active_ids_after}"
        )

        # Verify remaining injections are unmodified
        for fault in active_after:
            idx = injection_ids.index(fault["injection_id"])
            assert fault["magnitude"] == magnitudes[idx], (
                f"Magnitude changed for injection {fault['injection_id']}"
            )
            assert fault["duration_cycles"] == durations[idx], (
                f"Duration changed for injection {fault['injection_id']}"
            )


# ---------------------------------------------------------------------------
# Property 6: Clear-All Empties State
# ---------------------------------------------------------------------------


class TestClearAllEmptiesState:
    """Feature: digital-twin-v1.3, Property 6: Clear-All Empties State

    For any set of active injections (0 or more), calling clear_all() SHALL
    result in get_active() returning an empty list.

    **Validates: Requirements 1.7**
    """

    @given(
        num_injections=st.integers(min_value=0, max_value=20),
        fault_types=st.lists(
            fault_type_strategy, min_size=1, max_size=4
        ),
        magnitudes=st.lists(
            magnitude_strategy, min_size=1, max_size=10
        ),
        durations=st.lists(
            duration_strategy, min_size=1, max_size=10
        ),
    )
    @settings(max_examples=100)
    def test_clear_all_empties_active_list(
        self,
        num_injections: int,
        fault_types: List[str],
        magnitudes: List[float],
        durations: List[int],
    ) -> None:
        """After clear_all(), get_active() returns an empty list."""
        injector = FaultInjector()

        # Inject some faults
        for i in range(num_injections):
            sid = f"sensor-clearall-{i}"
            ft = fault_types[i % len(fault_types)]
            mag = magnitudes[i % len(magnitudes)]
            dur = durations[i % len(durations)]
            injector.inject(sid, ft, mag, dur)

        # Clear all
        injector.clear_all()

        # Verify empty
        active = injector.get_active()
        assert active == [], (
            f"After clear_all(), expected empty list, got {len(active)} active faults"
        )

    @given(
        num_injections=st.integers(min_value=1, max_value=10),
        raw_value=raw_value_strategy,
    )
    @settings(max_examples=100)
    def test_clear_all_makes_apply_identity(
        self, num_injections: int, raw_value: float
    ) -> None:
        """After clear_all(), apply() returns raw_value unchanged for all sensors."""
        injector = FaultInjector()
        sensor_ids: List[str] = []

        # Inject faults on various sensors
        for i in range(num_injections):
            sid = f"sensor-identity-{i}"
            sensor_ids.append(sid)
            injector.inject(sid, "spike", 50.0, 100)

        # Clear all
        injector.clear_all()

        # Verify apply() returns identity for all sensors
        for sid in sensor_ids:
            result = injector.apply(sid, raw_value)
            assert result == raw_value, (
                f"After clear_all(), sensor '{sid}' returned {result!r} "
                f"instead of raw_value {raw_value!r}"
            )
