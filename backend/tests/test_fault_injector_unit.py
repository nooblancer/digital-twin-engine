"""Unit tests for FaultInjector class and adapter integration.

Tests edge cases for the FaultInjector (composition, clear no-op, zero-duration
handling) and verifies adapter integration by mocking FaultInjector and
confirming apply() is called on each sensor reading in the adapter stream.

Validates: Requirements 1.1–1.8, 3.1–3.4
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from digital_twin_engine.simulation.fault_injector import FaultInjector
from digital_twin_engine.adapters.cmapss_replay import (
    CMAPSSConfig,
    CMAPSSReplayAdapter,
    EngineData,
)


# ---------------------------------------------------------------------------
# Tests: Edge Cases (Requirements 1.1–1.8)
# ---------------------------------------------------------------------------


class TestFaultInjectorEdgeCases:
    """Edge case testing for FaultInjector behavior."""

    def test_clear_nonexistent_id_is_noop(self) -> None:
        """Clearing a non-existent injection ID does nothing and does not raise."""
        fi = FaultInjector()
        # Should not raise
        fi.clear("nonexistent-id-12345")
        assert fi.get_active() == []

    def test_clear_already_cleared_id_is_noop(self) -> None:
        """Clearing an ID that was already cleared does not raise."""
        fi = FaultInjector()
        inj_id = fi.inject("sensor-a", "spike", 10.0, 5)
        fi.clear(inj_id)
        # Clear again — should be a no-op
        fi.clear(inj_id)
        assert fi.get_active() == []

    def test_multiple_faults_on_same_sensor_compose_additively(self) -> None:
        """Multiple spike faults on the same sensor compose additively.

        Two spike faults of 50% each on raw_value=100.0:
        - spike1 delta: 100.0 * (50 / 100) = 50.0
        - spike2 delta: 100.0 * (50 / 100) = 50.0
        - result = 100.0 + 50.0 + 50.0 = 200.0
        """
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 50.0, 10)
        fi.inject("sensor-a", "spike", 50.0, 10)

        result = fi.apply("sensor-a", 100.0)

        assert result == pytest.approx(200.0)

    def test_spike_and_drift_compose_on_same_sensor(self) -> None:
        """Spike and drift faults compose additively on the same sensor.

        spike of 50% on raw=100.0: delta_spike = 50.0
        drift of magnitude=10.0, duration=10 at elapsed=1: delta_drift = 10.0/10 * 1 = 1.0
        result = 100.0 + 50.0 + 1.0 = 151.0
        """
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 50.0, 10)
        fi.inject("sensor-a", "drift", 10.0, 10)

        result = fi.apply("sensor-a", 100.0)

        assert result == pytest.approx(151.0)

    def test_dropout_wins_over_spike_and_noise(self) -> None:
        """Dropout overrides all other faults — result is always 0.0."""
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 500.0, 10)
        fi.inject("sensor-a", "noise", 100.0, 10)
        fi.inject("sensor-a", "dropout", 0.0, 10)

        result = fi.apply("sensor-a", 999.0)

        assert result == 0.0

    def test_apply_returns_raw_value_when_no_faults(self) -> None:
        """With no active faults, apply returns raw_value unchanged."""
        fi = FaultInjector()
        raw = 42.123456789

        result = fi.apply("sensor-x", raw)

        assert result == raw

    def test_apply_returns_raw_for_different_sensor(self) -> None:
        """Faults on sensor-a don't affect sensor-b."""
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 50.0, 10)

        result = fi.apply("sensor-b", 100.0)

        assert result == 100.0

    def test_fault_auto_expires_after_duration(self) -> None:
        """After duration_cycles calls to apply, the fault is removed."""
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 50.0, 3)

        # Apply 3 times (fault should be active for all 3)
        for _ in range(3):
            result = fi.apply("sensor-a", 100.0)
            assert result != 100.0  # fault is active

        # After 3 applies, fault should have expired
        result = fi.apply("sensor-a", 100.0)
        assert result == 100.0
        assert fi.get_active() == []

    def test_spike_formula_correctness(self) -> None:
        """Spike adds raw_value * (magnitude / 100) to raw_value.

        For raw=200.0, magnitude=25: delta = 200.0 * 0.25 = 50.0
        result = 200.0 + 50.0 = 250.0
        """
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 25.0, 5)

        result = fi.apply("sensor-a", 200.0)

        assert result == pytest.approx(250.0)

    def test_drift_accumulates_linearly(self) -> None:
        """Drift increases linearly: magnitude/duration * elapsed_cycles.

        magnitude=10.0, duration=5:
        - apply 1: delta = 10/5 * 1 = 2.0 → raw + 2.0
        - apply 2: delta = 10/5 * 2 = 4.0 → raw + 4.0
        - apply 3: delta = 10/5 * 3 = 6.0 → raw + 6.0
        """
        fi = FaultInjector()
        fi.inject("sensor-a", "drift", 10.0, 5)

        r1 = fi.apply("sensor-a", 100.0)
        r2 = fi.apply("sensor-a", 100.0)
        r3 = fi.apply("sensor-a", 100.0)

        assert r1 == pytest.approx(102.0)
        assert r2 == pytest.approx(104.0)
        assert r3 == pytest.approx(106.0)

    def test_noise_modifies_value(self) -> None:
        """Noise fault modifies the raw value (non-deterministic but not equal)."""
        fi = FaultInjector()
        fi.inject("sensor-a", "noise", 50.0, 100)

        # With high std, over many samples at least one should differ
        raw = 100.0
        results = [fi.apply("sensor-a", raw) for _ in range(20)]

        # At least some results should differ from raw
        assert any(r != raw for r in results)

    def test_dropout_returns_zero_regardless_of_raw(self) -> None:
        """Dropout always returns 0.0 regardless of the raw value."""
        fi = FaultInjector()
        fi.inject("sensor-a", "dropout", 0.0, 5)

        assert fi.apply("sensor-a", 999.99) == 0.0
        assert fi.apply("sensor-a", -50.0) == 0.0
        assert fi.apply("sensor-a", 0.0) == 0.0

    def test_get_active_returns_correct_structure(self) -> None:
        """get_active() returns dicts with expected keys."""
        fi = FaultInjector()
        inj_id = fi.inject("sensor-a", "spike", 50.0, 10)

        active = fi.get_active()

        assert len(active) == 1
        entry = active[0]
        assert entry["injection_id"] == inj_id
        assert entry["sensor_id"] == "sensor-a"
        assert entry["fault_type"] == "spike"
        assert entry["magnitude"] == 50.0
        assert entry["remaining_cycles"] == 10
        assert entry["duration_cycles"] == 10

    def test_clear_all_removes_everything(self) -> None:
        """clear_all() empties all active injections."""
        fi = FaultInjector()
        fi.inject("sensor-a", "spike", 10.0, 100)
        fi.inject("sensor-b", "drift", 5.0, 50)
        fi.inject("sensor-c", "dropout", 0.0, 20)

        fi.clear_all()

        assert fi.get_active() == []
        # Values pass through unchanged after clear_all
        assert fi.apply("sensor-a", 42.0) == 42.0

    def test_inject_returns_unique_ids(self) -> None:
        """Each inject() call returns a unique ID."""
        fi = FaultInjector()
        ids = set()
        for _ in range(100):
            inj_id = fi.inject("sensor-a", "spike", 10.0, 5)
            ids.add(inj_id)

        assert len(ids) == 100

    def test_selective_clear_preserves_other_faults(self) -> None:
        """Clearing one injection preserves others on the same sensor."""
        fi = FaultInjector()
        id1 = fi.inject("sensor-a", "spike", 50.0, 10)
        id2 = fi.inject("sensor-a", "drift", 5.0, 10)

        fi.clear(id1)

        active = fi.get_active()
        assert len(active) == 1
        assert active[0]["injection_id"] == id2
        assert active[0]["fault_type"] == "drift"


# ---------------------------------------------------------------------------
# Tests: Adapter Integration (Requirements 3.1–3.4)
# ---------------------------------------------------------------------------


class TestAdapterFaultInjectorIntegration:
    """Test that CMAPSSReplayAdapter calls FaultInjector.apply on each reading."""

    @pytest.mark.asyncio
    async def test_adapter_calls_apply_on_each_sensor_reading(self) -> None:
        """Verify FaultInjector.apply() is called for every sensor event in the stream."""
        mock_fi = MagicMock(spec=FaultInjector)
        mock_fi.apply = MagicMock(side_effect=lambda sensor_id, raw_value: raw_value)

        config = CMAPSSConfig(
            data_dir="data/cmapss",
            dataset="FD001",
            speed=1000.0,
            engine_ids=[1],
            max_cycles=1,
        )
        adapter = CMAPSSReplayAdapter(config, fault_injector=mock_fi)

        # Manually inject engine data to avoid needing the actual file
        adapter._engines = {
            1: EngineData(
                engine_id=1,
                cycles=[{
                    "hpc_outlet_temp_total": 500.0,
                    "physical_core_speed_rpm": 9000.0,
                }],
                total_cycles=1,
            )
        }
        adapter._loaded = True

        events = []
        async for event in adapter.stream():
            events.append(event)

        # apply() should have been called once per sensor reading
        assert mock_fi.apply.call_count == 2

        # Verify it was called with correct sensor_id and raw_value
        calls = mock_fi.apply.call_args_list
        call_args = [(c[0][0], c[0][1]) for c in calls]
        assert ("engine-001-hpc_outlet_temp_total", 500.0) in call_args
        assert ("engine-001-physical_core_speed_rpm", 9000.0) in call_args

    @pytest.mark.asyncio
    async def test_adapter_uses_transformed_value_from_fault_injector(self) -> None:
        """Verify adapter yields the value returned by FaultInjector.apply(), not raw."""
        mock_fi = MagicMock(spec=FaultInjector)
        # Return a fixed corrupted value
        mock_fi.apply = MagicMock(return_value=999.0)

        config = CMAPSSConfig(
            data_dir="data/cmapss",
            dataset="FD001",
            speed=1000.0,
            engine_ids=[1],
            max_cycles=1,
        )
        adapter = CMAPSSReplayAdapter(config, fault_injector=mock_fi)

        adapter._engines = {
            1: EngineData(
                engine_id=1,
                cycles=[{"hpc_outlet_temp_total": 500.0}],
                total_cycles=1,
            )
        }
        adapter._loaded = True

        events = []
        async for event in adapter.stream():
            events.append(event)

        assert len(events) == 1
        # The event value should be the corrupted value (999.0), not the raw (500.0)
        assert events[0].value == 999.0

    @pytest.mark.asyncio
    async def test_adapter_passes_raw_value_when_no_fault_injector(self) -> None:
        """Without a FaultInjector, adapter yields raw values unchanged."""
        config = CMAPSSConfig(
            data_dir="data/cmapss",
            dataset="FD001",
            speed=1000.0,
            engine_ids=[1],
            max_cycles=1,
        )
        adapter = CMAPSSReplayAdapter(config, fault_injector=None)

        adapter._engines = {
            1: EngineData(
                engine_id=1,
                cycles=[{"hpc_outlet_temp_total": 512.7}],
                total_cycles=1,
            )
        }
        adapter._loaded = True

        events = []
        async for event in adapter.stream():
            events.append(event)

        assert len(events) == 1
        assert events[0].value == 512.7

    @pytest.mark.asyncio
    async def test_adapter_calls_apply_for_multiple_cycles(self) -> None:
        """Verify apply() is called on every reading across multiple cycles."""
        mock_fi = MagicMock(spec=FaultInjector)
        mock_fi.apply = MagicMock(side_effect=lambda sid, rv: rv)

        config = CMAPSSConfig(
            data_dir="data/cmapss",
            dataset="FD001",
            speed=1000.0,
            engine_ids=[1],
            max_cycles=3,
        )
        adapter = CMAPSSReplayAdapter(config, fault_injector=mock_fi)

        adapter._engines = {
            1: EngineData(
                engine_id=1,
                cycles=[
                    {"hpc_outlet_temp_total": 500.0},
                    {"hpc_outlet_temp_total": 501.0},
                    {"hpc_outlet_temp_total": 502.0},
                ],
                total_cycles=3,
            )
        }
        adapter._loaded = True

        events = []
        async for event in adapter.stream():
            events.append(event)

        # 1 sensor × 3 cycles = 3 apply() calls
        assert mock_fi.apply.call_count == 3
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_adapter_sensor_id_format(self) -> None:
        """Verify sensor_id passed to apply() follows engine-{id:03d}-{name} format."""
        mock_fi = MagicMock(spec=FaultInjector)
        mock_fi.apply = MagicMock(side_effect=lambda sid, rv: rv)

        config = CMAPSSConfig(
            data_dir="data/cmapss",
            dataset="FD001",
            speed=1000.0,
            engine_ids=[5],
            max_cycles=1,
        )
        adapter = CMAPSSReplayAdapter(config, fault_injector=mock_fi)

        adapter._engines = {
            5: EngineData(
                engine_id=5,
                cycles=[{"fan_inlet_temp_total": 300.0}],
                total_cycles=1,
            )
        }
        adapter._loaded = True

        async for _ in adapter.stream():
            pass

        # Sensor ID should be zero-padded engine ID
        sensor_id_arg = mock_fi.apply.call_args_list[0][0][0]
        assert sensor_id_arg == "engine-005-fan_inlet_temp_total"
