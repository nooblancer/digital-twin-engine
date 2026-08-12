"""Unit tests for the Health Index Baseline Calibration Fix.

Tests that the HealthIndexAggregator correctly reports HI=1.0 during the
first 10 baseline cycles, does not feed the DegradationCurveTracker during
that period, transitions correctly at cycle 11, and that the trajectory
returned via the snapshot API contains no false low values.

Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from digital_twin_engine.broker.memory_backend import InMemoryBrokerBackend
from digital_twin_engine.broker.topics import CORRECTIONS_STATE
from digital_twin_engine.prognostics.health_index import (
    ALL_SENSORS,
    BASELINE_CYCLES,
    HealthIndexAggregator,
    _EngineBaselineState,
)
from digital_twin_engine.prognostics.models import EngineHealthState


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class CaptureWebSocketManager:
    """Mock WebSocket manager that captures broadcast calls."""

    def __init__(self) -> None:
        self.broadcasts: List[Tuple[str, Dict[str, Any]]] = []

    async def broadcast(self, message_type: str, payload: dict) -> None:
        self.broadcasts.append((message_type, payload))

    def get_messages_of_type(self, message_type: str) -> List[Dict[str, Any]]:
        return [p for t, p in self.broadcasts if t == message_type]

    def clear(self) -> None:
        self.broadcasts.clear()


class SpyDegradationTracker:
    """Mock DegradationCurveTracker that records all calls."""

    def __init__(self) -> None:
        self.record_calls: List[Tuple[int, int, float]] = []

    async def record_async(
        self, engine_id: int, cycle: int, health_index: float
    ) -> None:
        self.record_calls.append((engine_id, cycle, health_index))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_correction_message(sensor_id: str, value: float, cycle: int) -> bytes:
    """Build a JSON correction message matching the expected format."""
    payload = {
        "sensor_id": sensor_id,
        "corrected_state_vector": [value],
        "cycle": cycle,
    }
    return json.dumps(payload).encode()


async def _publish_full_cycle(
    broker: InMemoryBrokerBackend,
    engine_id: int,
    cycle: int,
    base_value: float = 500.0,
    deviation_factor: float = 0.0,
) -> None:
    """Publish a full cycle of 21 sensor readings for an engine.

    Uses a Gaussian-style jitter seeded by cycle number to ensure sufficient
    variation in the baseline period for meaningful std computation, while
    keeping post-baseline cycles within reasonable deviation.
    """
    import random

    rng = random.Random(cycle * 1000 + engine_id)
    for i, sensor_name in enumerate(ALL_SENSORS):
        # Each sensor gets a slightly different base value
        sensor_base = base_value + (i * 10.0)
        # Add Gaussian noise proportional to the sensor value (~1% variation)
        noise = rng.gauss(0, sensor_base * 0.01)
        value = sensor_base + noise + (deviation_factor * i * 5.0)
        sensor_key = f"engine-{engine_id:03d}-{sensor_name}"
        message = _build_correction_message(sensor_key, value, cycle)
        await broker.publish(CORRECTIONS_STATE, sensor_key, message)


async def _drain_broker(broker: InMemoryBrokerBackend) -> None:
    """Wait for all pending broker delivery tasks to complete."""
    for _ in range(10):
        await asyncio.sleep(0.01)
        if hasattr(broker, "_pending_tasks"):
            pending = [t for t in broker._pending_tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            else:
                break


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def broker() -> InMemoryBrokerBackend:
    return InMemoryBrokerBackend()


@pytest.fixture
def ws_manager() -> CaptureWebSocketManager:
    return CaptureWebSocketManager()


@pytest.fixture
def degradation_tracker() -> SpyDegradationTracker:
    return SpyDegradationTracker()


@pytest.fixture
def aggregator(
    broker: InMemoryBrokerBackend,
    ws_manager: CaptureWebSocketManager,
    degradation_tracker: SpyDegradationTracker,
) -> HealthIndexAggregator:
    return HealthIndexAggregator(
        broker=broker,
        ws_manager=ws_manager,
        degradation_tracker=degradation_tracker,
    )


# ---------------------------------------------------------------------------
# Tests: HI=1.0 during baseline period (Requirement 15.1)
# ---------------------------------------------------------------------------


class TestBaselineHIEqualsOne:
    """HI must be 1.0 for cycles 1 through 10 (baseline period)."""

    @pytest.mark.asyncio
    async def test_hi_is_one_for_all_baseline_cycles(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """HI=1.0 is reported for each of cycles 1 through 10."""
        await aggregator.start()
        engine_id = 1

        for cycle in range(1, BASELINE_CYCLES + 1):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        # Check all health_index_update broadcasts during baseline
        hi_updates = ws_manager.get_messages_of_type("health_index_update")
        assert len(hi_updates) == BASELINE_CYCLES

        for update in hi_updates:
            assert update["health_index"] == 1.0
            assert update["engine_id"] == engine_id

        await aggregator.stop()

    @pytest.mark.asyncio
    async def test_health_state_is_one_during_baseline(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """get_health_state() returns HI=1.0 during baseline."""
        await aggregator.start()
        engine_id = 1

        # Process 5 cycles (mid-baseline)
        for cycle in range(1, 6):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        state = aggregator.get_health_state(engine_id)
        assert state is not None
        assert state.health_index == 1.0

        await aggregator.stop()


# ---------------------------------------------------------------------------
# Tests: DegradationCurveTracker NOT called during baseline (Requirement 15.2)
# ---------------------------------------------------------------------------


class TestDegradationTrackerNotCalledDuringBaseline:
    """DegradationCurveTracker must not receive any values during baseline."""

    @pytest.mark.asyncio
    async def test_degradation_tracker_not_called_for_first_10_cycles(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        degradation_tracker: SpyDegradationTracker,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """DegradationCurveTracker.record_async() is never called during baseline."""
        await aggregator.start()
        engine_id = 1

        for cycle in range(1, BASELINE_CYCLES + 1):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        assert len(degradation_tracker.record_calls) == 0

        await aggregator.stop()


# ---------------------------------------------------------------------------
# Tests: First real HI computed at cycle 11 (Requirement 15.3, 15.4)
# ---------------------------------------------------------------------------


class TestFirstRealHIAtCycle11:
    """First real health index computation should happen at cycle 11."""

    @pytest.mark.asyncio
    async def test_cycle_11_produces_real_hi(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        degradation_tracker: SpyDegradationTracker,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """Cycle 11 triggers a real HI computation with full 10-cycle baseline."""
        await aggregator.start()
        engine_id = 1

        # Process 10 baseline cycles
        for cycle in range(1, BASELINE_CYCLES + 1):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        # Process cycle 11 — this should produce a real HI
        await _publish_full_cycle(broker, engine_id, BASELINE_CYCLES + 1)
        await _drain_broker(broker)

        # Degradation tracker should now have been called once (cycle 11)
        assert len(degradation_tracker.record_calls) == 1
        call = degradation_tracker.record_calls[0]
        assert call[0] == engine_id  # engine_id
        assert call[1] == BASELINE_CYCLES + 1  # cycle
        # The real HI should be a float between 0 and 1 (but not necessarily 1.0)
        assert 0.0 <= call[2] <= 1.0

        await aggregator.stop()

    @pytest.mark.asyncio
    async def test_cycle_11_hi_uses_full_baseline(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """Cycle 11 HI is computed against baselines from all 10 cycles."""
        await aggregator.start()
        engine_id = 1

        # Process 10 baseline cycles with consistent values
        for cycle in range(1, BASELINE_CYCLES + 1):
            await _publish_full_cycle(broker, engine_id, cycle, base_value=500.0)
            await _drain_broker(broker)

        # Cycle 11 with same distribution should produce a real (non-provisional) HI
        await _publish_full_cycle(broker, engine_id, BASELINE_CYCLES + 1, base_value=500.0)
        await _drain_broker(broker)

        # The last health_index_update should be the real cycle 11 value
        hi_updates = ws_manager.get_messages_of_type("health_index_update")
        cycle_11_update = hi_updates[-1]
        assert cycle_11_update["cycle_number"] == BASELINE_CYCLES + 1
        assert cycle_11_update["is_provisional"] is False
        # Real HI must be a valid value in [0, 1] — the exact value depends
        # on how much cycle 11 data deviates from the 10-cycle baseline
        assert 0.0 <= cycle_11_update["health_index"] <= 1.0

        await aggregator.stop()


# ---------------------------------------------------------------------------
# Tests: is_provisional flag (Requirement 15.5)
# ---------------------------------------------------------------------------


class TestProvisionalFlag:
    """is_provisional must be True during baseline, False after."""

    @pytest.mark.asyncio
    async def test_is_provisional_true_during_baseline(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """All HI updates during baseline have is_provisional=True."""
        await aggregator.start()
        engine_id = 1

        for cycle in range(1, BASELINE_CYCLES + 1):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        hi_updates = ws_manager.get_messages_of_type("health_index_update")
        for update in hi_updates:
            assert update["is_provisional"] is True

        await aggregator.stop()

    @pytest.mark.asyncio
    async def test_is_provisional_false_after_baseline(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """HI updates after baseline have is_provisional=False."""
        await aggregator.start()
        engine_id = 1

        # Process baseline + 1 post-baseline cycle
        for cycle in range(1, BASELINE_CYCLES + 2):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        hi_updates = ws_manager.get_messages_of_type("health_index_update")
        # Last update should be cycle 11 (post-baseline)
        last_update = hi_updates[-1]
        assert last_update["is_provisional"] is False
        assert last_update["cycle_number"] == BASELINE_CYCLES + 1

        await aggregator.stop()

    @pytest.mark.asyncio
    async def test_health_state_provisional_flag_transitions(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """get_health_state().is_provisional transitions from True to False."""
        await aggregator.start()
        engine_id = 1

        # Mid-baseline check
        for cycle in range(1, 6):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        state = aggregator.get_health_state(engine_id)
        assert state is not None
        assert state.is_provisional is True

        # Complete baseline + one real cycle
        for cycle in range(6, BASELINE_CYCLES + 2):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        state = aggregator.get_health_state(engine_id)
        assert state is not None
        assert state.is_provisional is False

        await aggregator.stop()


# ---------------------------------------------------------------------------
# Tests: Trajectory has no false low values (Requirement 15.6)
# ---------------------------------------------------------------------------


class TestTrajectoryNoFalseLowValues:
    """Trajectory from snapshot API must not contain HI values below 0.9 in first 10 cycles."""

    @pytest.mark.asyncio
    async def test_trajectory_first_10_cycles_no_low_values(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        degradation_tracker: SpyDegradationTracker,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """DegradationCurveTracker only receives HI from cycle 11+, so trajectory has no false lows.

        Since the DegradationCurveTracker is not fed during baseline, its
        trajectory will only contain post-baseline values. The first 10
        cycles effectively have HI=1.0 (provisional) but those are NOT
        stored in the degradation tracker trajectory.

        Requirement 15.6: trajectory SHALL NOT contain false low HI values
        from the calibration period.
        """
        await aggregator.start()
        engine_id = 1

        # Process 15 cycles total (10 baseline + 5 real)
        for cycle in range(1, 16):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        # The degradation tracker should only have records from cycles 11-15
        assert len(degradation_tracker.record_calls) == 5

        # All recorded cycles must be > BASELINE_CYCLES (no baseline values leaked)
        for engine, cycle, hi in degradation_tracker.record_calls:
            assert cycle > BASELINE_CYCLES, (
                f"Degradation tracker received cycle {cycle} which is in the "
                "baseline period — baseline guard is not working"
            )
            # HI values should be valid floats in [0, 1]
            assert 0.0 <= hi <= 1.0

        # Verify the WebSocket broadcasts show HI=1.0 for first 10 cycles
        hi_updates = ws_manager.get_messages_of_type("health_index_update")
        baseline_updates = [u for u in hi_updates if u["cycle_number"] <= BASELINE_CYCLES]
        for update in baseline_updates:
            assert update["health_index"] >= 0.9, (
                f"Cycle {update['cycle_number']} reported HI={update['health_index']} "
                "during baseline — should be 1.0"
            )

        await aggregator.stop()

    @pytest.mark.asyncio
    async def test_no_values_below_threshold_in_early_trajectory(
        self,
        broker: InMemoryBrokerBackend,
        ws_manager: CaptureWebSocketManager,
        degradation_tracker: SpyDegradationTracker,
        aggregator: HealthIndexAggregator,
    ) -> None:
        """The trajectory should contain no HI below 0.9 for the first 10 cycles.

        This verifies the fix: before the fix, cycles 1-10 would produce
        garbage HI values (near 0.0) because the baseline std was near-zero
        with insufficient data. Now they report HI=1.0 and don't feed the
        tracker.
        """
        await aggregator.start()
        engine_id = 1

        # Process exactly the baseline period
        for cycle in range(1, BASELINE_CYCLES + 1):
            await _publish_full_cycle(broker, engine_id, cycle)
            await _drain_broker(broker)

        # Degradation tracker should have ZERO entries for the baseline period
        assert len(degradation_tracker.record_calls) == 0

        # But the HI reported via WebSocket was always 1.0
        hi_updates = ws_manager.get_messages_of_type("health_index_update")
        for update in hi_updates:
            assert update["health_index"] >= 0.9

        await aggregator.stop()
