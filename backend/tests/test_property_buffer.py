"""Property-based tests for In-Memory Buffer Size Invariant.

Uses the Hypothesis library to verify that the TelemetryPublisher's in-memory
buffer never exceeds the configured max_buffer_size, and that events arriving
when the buffer is full are handled without silent data loss (backpressure
or rejection via BackpressureError).
"""

# Feature: digital-twin-telemetry-engine, Property 5: In-Memory Buffer Size Invariant

import asyncio
from datetime import datetime, timezone

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings, assume

from digital_twin_engine.ingestion.publisher import (
    BackpressureError,
    BrokerType,
    TelemetryPublisher,
)
from digital_twin_engine.shared.models import TelemetryEvent


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for valid finite float64 values
valid_float_values = st.floats(
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=True,
    min_value=-1e300,
    max_value=1e300,
)

# Strategy for valid sensor_ids (1-256 chars, not whitespace-only)
valid_sensor_ids = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Strategy for valid measurement types
valid_measurement_types = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")


@st.composite
def telemetry_events(draw, min_count=1, max_count=15000):
    """Generate a list of valid TelemetryEvent objects of random length."""
    count = draw(st.integers(min_value=min_count, max_value=max_count))
    events = []
    for i in range(count):
        event = TelemetryEvent(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            sensor_id=draw(valid_sensor_ids),
            measurement_type=draw(valid_measurement_types),
            value=draw(valid_float_values),
        )
        events.append(event)
    return events


# Strategy for max_buffer_size values to test the invariant with various sizes
buffer_sizes = st.integers(min_value=1, max_value=10000)


# ---------------------------------------------------------------------------
# Property 5: In-Memory Buffer Size Invariant
# ---------------------------------------------------------------------------


class TestProperty5BufferSizeInvariant:
    """Property 5: In-Memory Buffer Size Invariant.

    For any sequence of Telemetry_Events received while the Message_Broker is
    unreachable, the Ingestion_Server's in-memory buffer SHALL never exceed
    10,000 events. Events arriving when the buffer is full SHALL be handled
    without silent data loss (backpressure or rejection).

    **Validates: Requirements 1.8**
    """

    @given(
        num_events=st.integers(min_value=1, max_value=15000),
        max_buffer_size=buffer_sizes,
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_buffer_never_exceeds_max_size(
        self, num_events: int, max_buffer_size: int
    ):
        """Buffer size shall never exceed max_buffer_size regardless of event count."""
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA,
            max_buffer_size=max_buffer_size,
        )
        publisher._started = True
        publisher._connected = False  # Broker unreachable

        event = TelemetryEvent(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            sensor_id="sensor-001",
            measurement_type="temperature",
            value=42.0,
        )

        backpressure_count = 0

        for _ in range(num_events):
            try:
                await publisher.publish(event)
            except BackpressureError:
                backpressure_count += 1

            # INVARIANT: buffer size must never exceed max_buffer_size
            assert publisher.buffer_size <= max_buffer_size, (
                f"Buffer size {publisher.buffer_size} exceeded max {max_buffer_size}"
            )

        # Final assertions
        assert publisher.buffer_size <= max_buffer_size

        # If we sent more events than buffer capacity, we must have gotten
        # backpressure errors (no silent drops)
        if num_events > max_buffer_size:
            assert backpressure_count == num_events - max_buffer_size, (
                f"Expected {num_events - max_buffer_size} backpressure errors, "
                f"got {backpressure_count}. Events were silently dropped!"
            )

    @given(
        num_events=st.integers(min_value=1, max_value=15000),
        max_buffer_size=buffer_sizes,
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_no_silent_data_loss(
        self, num_events: int, max_buffer_size: int
    ):
        """Events are never silently dropped — all are either buffered or rejected."""
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA,
            max_buffer_size=max_buffer_size,
        )
        publisher._started = True
        publisher._connected = False  # Broker unreachable

        event = TelemetryEvent(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            sensor_id="sensor-002",
            measurement_type="pressure",
            value=101.3,
        )

        buffered_count = 0
        rejected_count = 0

        for _ in range(num_events):
            try:
                await publisher.publish(event)
                buffered_count += 1
            except BackpressureError:
                rejected_count += 1

        # Every event must be accounted for: either buffered or rejected
        assert buffered_count + rejected_count == num_events, (
            f"Silent data loss detected! Sent {num_events}, "
            f"buffered {buffered_count}, rejected {rejected_count}, "
            f"lost {num_events - buffered_count - rejected_count}"
        )

        # Buffer should have exactly the buffered count of events
        assert publisher.buffer_size == buffered_count

        # The buffered count should be at most max_buffer_size
        assert buffered_count <= max_buffer_size

    @given(max_buffer_size=buffer_sizes)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_backpressure_raised_when_buffer_full(
        self, max_buffer_size: int
    ):
        """BackpressureError is raised (not silent drop) when buffer is full."""
        publisher = TelemetryPublisher(
            broker_type=BrokerType.KAFKA,
            max_buffer_size=max_buffer_size,
        )
        publisher._started = True
        publisher._connected = False  # Broker unreachable

        event = TelemetryEvent(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            sensor_id="sensor-003",
            measurement_type="humidity",
            value=65.5,
        )

        # Fill the buffer to capacity
        for _ in range(max_buffer_size):
            await publisher.publish(event)

        assert publisher.buffer_size == max_buffer_size

        # Next event MUST raise BackpressureError — never silently dropped
        with pytest.raises(BackpressureError) as exc_info:
            await publisher.publish(event)

        assert exc_info.value.buffer_size == max_buffer_size

        # Buffer size remains unchanged (event was rejected, not dropped)
        assert publisher.buffer_size == max_buffer_size
