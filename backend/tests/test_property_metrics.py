"""Property-based tests for Metrics Counter Accuracy.

Property 6: Metrics Counter Accuracy
For any sequence of N telemetry events processed by a service, the
`messages_processed_total` counter metric SHALL equal N after processing
completes.

**Validates: Requirements 9.5**
"""

from __future__ import annotations

import asyncio
import json

import hypothesis.strategies as st
from hypothesis import given, settings, HealthCheck
import pytest

from digital_twin_engine.api.broker_subscriber import BrokerSubscriber
from digital_twin_engine.api.metrics import messages_processed_total
from digital_twin_engine.api.state_cache import StateCache
from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.memory_backend import InMemoryBrokerBackend
from digital_twin_engine.broker.topics import (
    CORRECTIONS_STATE,
    PREDICTIONS_STATE,
    ALERTS_ANOMALY,
    TELEMETRY_RAW,
)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

topics_strategy = st.sampled_from(
    [CORRECTIONS_STATE, PREDICTIONS_STATE, ALERTS_ANOMALY, TELEMETRY_RAW]
)


# Simple payload generator — minimal valid JSON that passes broker message parsing.
simple_payload = st.fixed_dictionaries({
    "sensor_id": st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=10,
    ),
    "value": st.floats(
        min_value=-1e6, max_value=1e6,
        allow_nan=False, allow_infinity=False,
    ),
    "timestamp": st.integers(min_value=0, max_value=2_000_000_000),
})


# ---------------------------------------------------------------------------
# Helper to get counter value for a specific topic label
# ---------------------------------------------------------------------------


def _get_counter_value(topic: str) -> float:
    """Read the current value of messages_processed_total for a given topic label."""
    return messages_processed_total.labels(topic=topic)._value.get()


# ---------------------------------------------------------------------------
# Property 6: Metrics Counter Accuracy
# ---------------------------------------------------------------------------


class TestProperty6MetricsCounterAccuracy:
    """Property 6: Metrics Counter Accuracy.

    For any sequence of N telemetry events processed by a service, the
    messages_processed_total counter metric SHALL equal N after processing
    completes.

    **Validates: Requirements 9.5**
    """

    @given(
        n=st.integers(min_value=1, max_value=1000),
        topic=topics_strategy,
        payload=simple_payload,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
    )
    def test_counter_increments_by_n_after_n_events(
        self,
        n: int,
        topic: str,
        payload: dict,
    ):
        """Processing N events increments messages_processed_total counter by exactly N."""
        # Read counter before processing
        before = _get_counter_value(topic)

        # Create broker subscriber with in-memory broker
        subscriber = BrokerSubscriber()
        broker = InMemoryBrokerBackend()
        state_cache = StateCache()
        ws_manager = WebSocketBroadcastManager()

        # Encode the payload once and reuse for all N messages
        message_bytes = json.dumps(payload).encode("utf-8")
        key = payload.get("sensor_id", "test-sensor")

        async def run():
            await broker.start()
            await subscriber.start(broker, state_cache, ws_manager)

            # Publish N messages to the selected topic
            for _ in range(n):
                await broker.publish(topic, key, message_bytes)

            await subscriber.stop()
            await broker.stop()

        asyncio.run(run())

        # Read counter after processing
        after = _get_counter_value(topic)

        # Verify the counter increased by exactly N
        delta = after - before
        assert delta == n, (
            f"Expected counter to increase by {n} for topic '{topic}', "
            f"but delta was {delta} (before={before}, after={after})"
        )
