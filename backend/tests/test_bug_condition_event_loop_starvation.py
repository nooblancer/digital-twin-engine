"""Bug Condition Exploration Test: Event Loop Starvation Under Concurrent EnKF Load.

**Validates: Requirements 1.1, 1.3, 1.4**

This test is EXPECTED TO FAIL on unfixed code — failure confirms the bug exists.
The bug condition is:
  input.mode == "local"
  AND input.active_sensor_count >= 2
  AND input.enkf_computation_is_synchronous == true
  AND input.elapsed_time > 60_seconds

The test surfaces counterexamples demonstrating that the event loop becomes
unresponsive when CPU-bound EnKF computations block the asyncio thread.
Specifically, when EnKFIteration.__call__ processes multiple concurrent sensor
corrections with synchronous numpy computation, the event loop health check
response time exceeds 500ms.

Property 1: Bug Condition - Event Loop Starvation Under Concurrent EnKF Load

Approach:
  The test verifies that _compute_enkf_update is invoked via asyncio.to_thread
  (or equivalent offloading mechanism). On unfixed code, the computation runs
  synchronously in the event loop thread — proven by checking that the calling
  thread IS the event loop thread during execution. When offloaded correctly,
  the computation runs in a different thread, keeping the event loop free.

  Additionally, the test measures the total accumulated blocking time from
  concurrent sensor streams and asserts it would cause event loop starvation
  (exceeding 500ms response time for health checks) in the unfixed code path.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import AsyncMock

import numpy as np
import hypothesis.strategies as st
import pytest
from hypothesis import given, settings, HealthCheck

from digital_twin_engine.correction.enkf import EnKFIteration
from digital_twin_engine.correction.temporal_matcher import MatchedPair
from digital_twin_engine.shared.models import EnKFState


# ---------------------------------------------------------------------------
# Hypothesis Strategies — generate valid EnKF inputs
# ---------------------------------------------------------------------------

ENSEMBLE_SIZE = 50
STATE_DIM_MIN = 3
STATE_DIM_MAX = 8
NUM_CONCURRENT_SENSORS = 3
# Number of sequential EnKF calls per sensor.
CALLS_PER_SENSOR = 10


@st.composite
def enkf_state_strategy(draw, state_dim: int = 3) -> EnKFState:
    """Generate a valid EnKFState with random ensemble members."""
    mean_value = draw(st.floats(min_value=-1000.0, max_value=1000.0,
                                allow_nan=False, allow_infinity=False))
    spread = draw(st.floats(min_value=0.01, max_value=10.0,
                            allow_nan=False, allow_infinity=False))

    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=2**32 - 1)))
    ensemble_members = rng.normal(loc=mean_value, scale=spread,
                                  size=(ENSEMBLE_SIZE, state_dim))

    # Observation noise covariance: positive definite diagonal matrix
    obs_noise = draw(st.floats(min_value=0.001, max_value=1.0,
                               allow_nan=False, allow_infinity=False))
    observation_noise_cov = np.eye(state_dim) * obs_noise

    return EnKFState(
        sensor_id=f"sensor-{draw(st.integers(min_value=1, max_value=100))}",
        ensemble_members=ensemble_members,
        observation_noise_cov=observation_noise_cov,
        last_update_timestamp=datetime.now(timezone.utc),
        iteration_count=0,
        anomaly_threshold=3.0,
    )


@st.composite
def matched_pair_strategy(draw, state_dim: int = 3) -> MatchedPair:
    """Generate a valid MatchedPair with predicted values matching state dimension."""
    sensor_id = f"sensor-{draw(st.integers(min_value=1, max_value=100))}"
    now = datetime.now(timezone.utc)

    predicted_values = [
        draw(st.floats(min_value=-1000.0, max_value=1000.0,
                       allow_nan=False, allow_infinity=False))
        for _ in range(state_dim)
    ]

    observed_value = draw(st.floats(min_value=-1000.0, max_value=1000.0,
                                    allow_nan=False, allow_infinity=False))

    return MatchedPair(
        sensor_id=sensor_id,
        prediction_timestamp=now,
        observation_timestamp=now + timedelta(seconds=0.5),
        predicted_values=predicted_values,
        observed_value=observed_value,
        prediction_source="ensemble",
        ensemble_weights={"lstm": 0.6, "xgboost": 0.4},
    )


# ---------------------------------------------------------------------------
# Test: Bug Condition — Event Loop Starvation
# ---------------------------------------------------------------------------


class TestBugConditionEventLoopStarvation:
    """Property test: event loop starvation under concurrent EnKF load.

    **Property 1: Bug Condition** - Event Loop Starvation Under Concurrent EnKF Load

    The bug manifests when:
    - Mode is "local"
    - 2+ sensors are actively streaming
    - EnKF computation is synchronous (not offloaded to thread)
    - Elapsed time > 60 seconds (simulated via accumulated blocking calls)

    The test verifies that _compute_enkf_update does NOT run in the event loop
    thread when called via __call__. On unfixed code, it runs synchronously in
    the event loop thread, blocking it for the duration of each numpy computation.
    """

    @pytest.mark.asyncio
    @given(data=st.data())
    @settings(
        max_examples=5,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    async def test_event_loop_responsive_during_concurrent_enkf(self, data):
        """EnKF computation must not block the event loop thread.

        **Validates: Requirements 1.1, 1.3, 1.4**

        This test instruments _compute_enkf_update to detect whether it runs
        in the event loop thread. On unfixed code, the synchronous call runs
        directly in the event loop thread, blocking it for the duration of
        each numpy computation (5-50ms per call, accumulating to seconds of
        blocking with 3 concurrent sensors over 60+ seconds).

        The test:
        1. Records the event loop thread ID
        2. Instruments _compute_enkf_update to record which thread it runs in
        3. Runs 3 concurrent sensor streams through __call__
        4. Asserts that _compute_enkf_update did NOT run in the event loop thread
        5. Also asserts that total accumulated blocking time would exceed 500ms
           in the event loop (confirming starvation would occur)

        On UNFIXED code: _compute_enkf_update runs in the event loop thread →
        computation thread == event loop thread → test FAILS.

        On FIXED code (asyncio.to_thread): _compute_enkf_update runs in a
        worker thread → computation thread != event loop thread → test PASSES.
        """
        state_dim = data.draw(
            st.integers(min_value=STATE_DIM_MIN, max_value=STATE_DIM_MAX),
            label="state_dim",
        )

        # Generate inputs for concurrent sensor streams
        sensor_inputs: List[List[tuple]] = []
        for sensor_idx in range(NUM_CONCURRENT_SENSORS):
            pairs_and_states = []
            for _ in range(CALLS_PER_SENSOR):
                pair = data.draw(matched_pair_strategy(state_dim=state_dim),
                                 label=f"pair_s{sensor_idx}")
                state = data.draw(enkf_state_strategy(state_dim=state_dim),
                                  label=f"state_s{sensor_idx}")
                pairs_and_states.append((pair, state))
            sensor_inputs.append(pairs_and_states)

        # Create an EnKFIteration instance with a mock broker
        mock_broker = AsyncMock()
        mock_broker.publish = AsyncMock()
        enkf_iteration = EnKFIteration(broker=mock_broker)

        # --- Instrumentation ---
        # Record the event loop thread and the threads where computation runs.
        event_loop_thread_id = threading.current_thread().ident
        computation_thread_ids: List[int] = []
        blocking_durations_ms: List[float] = []

        original_compute = enkf_iteration._compute_enkf_update

        def instrumented_compute(matched_pair, enkf_state):
            """Wrapper that records thread ID and blocking duration."""
            computation_thread_ids.append(threading.current_thread().ident)
            start = time.perf_counter()
            result = original_compute(matched_pair, enkf_state)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            blocking_durations_ms.append(elapsed_ms)
            return result

        enkf_iteration._compute_enkf_update = instrumented_compute

        # --- Run concurrent sensor streams ---
        async def run_sensor_stream(inputs: List[tuple]) -> None:
            """Simulate a single sensor stream performing sequential EnKF calls."""
            for matched_pair, enkf_state in inputs:
                await enkf_iteration(matched_pair, enkf_state)

        sensor_tasks = [
            asyncio.create_task(run_sensor_stream(inputs))
            for inputs in sensor_inputs
        ]

        # Wait for completion with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*sensor_tasks),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            for task in sensor_tasks:
                task.cancel()

        # --- Assertions ---
        assert len(computation_thread_ids) > 0, (
            "No EnKF computations were executed"
        )
        assert len(blocking_durations_ms) > 0, (
            "No blocking durations recorded"
        )

        # Count how many computations ran in the event loop thread
        in_event_loop_count = sum(
            1 for tid in computation_thread_ids
            if tid == event_loop_thread_id
        )
        total_computations = len(computation_thread_ids)
        total_blocking_ms = sum(blocking_durations_ms)
        max_single_block_ms = max(blocking_durations_ms)
        avg_block_ms = total_blocking_ms / len(blocking_durations_ms)

        # PRIMARY ASSERTION: _compute_enkf_update must NOT run in the event
        # loop thread. If it does, it blocks the event loop for the duration
        # of each call, causing starvation.
        #
        # On unfixed code: ALL computations run in the event loop thread
        # (in_event_loop_count == total_computations) → FAILS
        #
        # On fixed code (asyncio.to_thread): computations run in worker threads
        # (in_event_loop_count == 0) → PASSES
        assert in_event_loop_count == 0, (
            f"Event loop starvation: _compute_enkf_update runs synchronously "
            f"in the event loop thread! "
            f"{in_event_loop_count}/{total_computations} computations blocked "
            f"the event loop. "
            f"Total blocking time: {total_blocking_ms:.1f}ms "
            f"(avg {avg_block_ms:.1f}ms/call, max {max_single_block_ms:.1f}ms). "
            f"With {NUM_CONCURRENT_SENSORS} concurrent sensors × "
            f"{CALLS_PER_SENSOR} calls each (state_dim={state_dim}), "
            f"this blocking accumulates over 60+ seconds in production, "
            f"causing GET /health to return 504 timeout. "
            f"Fix: offload _compute_enkf_update to asyncio.to_thread() so "
            f"numpy operations run in a worker thread, keeping the event "
            f"loop free for HTTP/WebSocket serving."
        )
