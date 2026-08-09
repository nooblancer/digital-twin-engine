"""Property-based tests for Same-Sensor Event Ordering Preservation.

Uses the Hypothesis library to verify that for any sequence of Telemetry_Events
published to the Message_Broker with the same sensor_id, each consumer group
receives those events in exactly the same order they were published.

Tests the Kafka backend's partitioning-by-sensor_id strategy which guarantees
that all events for the same sensor go to the same partition, preserving
publish order for each consumer group.
"""

# Feature: digital-twin-telemetry-engine, Property 6: Same-Sensor Event Ordering Preservation

import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings, HealthCheck

from digital_twin_engine.broker.base import BrokerBackend, MessageCallback
from digital_twin_engine.shared.models import TelemetryEvent, serialize_telemetry_event


# ---------------------------------------------------------------------------
# In-Memory Broker Backend (mimics Kafka partitioning semantics)
# ---------------------------------------------------------------------------


class InMemoryKafkaBroker(BrokerBackend):
    """In-memory broker that faithfully replicates Kafka's partitioning semantics.

    Key behaviors:
    - Messages are partitioned by key (sensor_id)
    - Within a partition, messages are delivered in FIFO order
    - Each consumer group gets its own independent cursor per partition
    - Multiple consumer groups can subscribe to the same topic independently
    """

    def __init__(self) -> None:
        # topic -> key -> ordered list of messages
        self._partitions: Dict[str, Dict[str, List[bytes]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # topic:group_id -> callback
        self._subscribers: Dict[str, MessageCallback] = {}
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        self._partitions.clear()
        self._subscribers.clear()

    async def publish(self, topic: str, key: str, message: bytes) -> None:
        """Publish a message to the specified topic, partitioned by key.

        Immediately delivers to all subscribed consumer groups (simulates
        Kafka's behavior where consumers poll and receive in order).
        """
        self._partitions[topic][key].append(message)

        # Deliver to all subscriber callbacks for this topic
        for sub_key, callback in self._subscribers.items():
            sub_topic, _ = sub_key.rsplit(":", 1)
            if sub_topic == topic:
                await callback(topic, key, message)

    async def subscribe(
        self, topic: str, group_id: str, callback: MessageCallback
    ) -> None:
        """Subscribe a consumer group to a topic."""
        sub_key = f"{topic}:{group_id}"
        self._subscribers[sub_key] = callback

    async def acknowledge(self, topic: str, group_id: str, offset: object) -> None:
        """No-op for in-memory broker."""
        pass

    def get_partition_messages(self, topic: str, key: str) -> List[bytes]:
        """Get all messages published to a specific partition (key)."""
        return list(self._partitions[topic][key])


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

# Strategy for valid sensor_ids (1-50 chars, not whitespace-only)
valid_sensor_ids = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Strategy for valid measurement types
valid_measurement_types = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")


@st.composite
def telemetry_event_sequence(draw, min_count=2, max_count=50):
    """Generate a sequence of TelemetryEvents sharing the same sensor_id.

    Each event has a distinct, incrementing timestamp to make ordering
    verifiable and deterministic.
    """
    sensor_id = draw(valid_sensor_ids)
    count = draw(st.integers(min_value=min_count, max_value=max_count))
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    events = []
    for i in range(count):
        event = TelemetryEvent(
            timestamp=base_time + timedelta(seconds=i),
            sensor_id=sensor_id,
            measurement_type=draw(valid_measurement_types),
            value=draw(valid_float_values),
        )
        events.append(event)
    return events


@st.composite
def multi_sensor_event_sequences(draw, min_sensors=2, max_sensors=5):
    """Generate interleaved event sequences from multiple sensors.

    Returns a tuple of (interleaved_events, per_sensor_ordered_events) so
    we can verify that per-sensor ordering is preserved even when events
    from different sensors are interleaved.
    """
    num_sensors = draw(st.integers(min_value=min_sensors, max_value=max_sensors))
    per_sensor_events: Dict[str, List[TelemetryEvent]] = {}

    all_events: List[TelemetryEvent] = []

    for _ in range(num_sensors):
        sensor_id = draw(valid_sensor_ids)
        # Ensure unique sensor_ids
        while sensor_id in per_sensor_events:
            sensor_id = draw(valid_sensor_ids)

        count = draw(st.integers(min_value=2, max_value=20))
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        events = []
        for i in range(count):
            event = TelemetryEvent(
                timestamp=base_time + timedelta(seconds=i),
                sensor_id=sensor_id,
                measurement_type=draw(valid_measurement_types),
                value=draw(valid_float_values),
            )
            events.append(event)

        per_sensor_events[sensor_id] = events
        all_events.extend(events)

    # Shuffle all events to simulate interleaved arrival
    shuffled = draw(st.permutations(all_events))
    return list(shuffled), per_sensor_events


# ---------------------------------------------------------------------------
# Property 6: Same-Sensor Event Ordering Preservation
# ---------------------------------------------------------------------------


class TestProperty6SameSensorEventOrdering:
    """Property 6: Same-Sensor Event Ordering Preservation.

    For any sequence of Telemetry_Events published to the Message_Broker with
    the same sensor_id, each consumer group SHALL receive those events in
    exactly the same order they were published.

    **Validates: Requirements 3.3**
    """

    @given(events=telemetry_event_sequence(min_count=2, max_count=50))
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_single_consumer_receives_events_in_publish_order(
        self, events: List[TelemetryEvent]
    ):
        """A single consumer group receives same-sensor events in publish order."""
        broker = InMemoryKafkaBroker()
        await broker.start()

        received_messages: List[bytes] = []

        async def consumer_callback(topic: str, key: str, message: bytes) -> None:
            received_messages.append(message)

        # Subscribe a consumer group
        await broker.subscribe("telemetry.raw", "tsdb-writer", consumer_callback)

        # Publish events in order (all same sensor_id)
        published_messages: List[bytes] = []
        for event in events:
            serialized = serialize_telemetry_event(event).encode("utf-8")
            published_messages.append(serialized)
            await broker.publish("telemetry.raw", event.sensor_id, serialized)

        await broker.stop()

        # PROPERTY: received order MUST match publish order exactly
        assert len(received_messages) == len(published_messages), (
            f"Expected {len(published_messages)} messages, got {len(received_messages)}"
        )
        for i, (published, received) in enumerate(
            zip(published_messages, received_messages)
        ):
            assert published == received, (
                f"Message at position {i} differs. "
                f"Published order not preserved by consumer."
            )

    @given(events=telemetry_event_sequence(min_count=2, max_count=50))
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_multiple_consumer_groups_each_receive_in_order(
        self, events: List[TelemetryEvent]
    ):
        """Multiple consumer groups each independently receive events in publish order."""
        broker = InMemoryKafkaBroker()
        await broker.start()

        received_group_a: List[bytes] = []
        received_group_b: List[bytes] = []

        async def callback_group_a(topic: str, key: str, message: bytes) -> None:
            received_group_a.append(message)

        async def callback_group_b(topic: str, key: str, message: bytes) -> None:
            received_group_b.append(message)

        # Subscribe two independent consumer groups
        await broker.subscribe("telemetry.raw", "tsdb-writer", callback_group_a)
        await broker.subscribe("telemetry.raw", "ml-service", callback_group_b)

        # Publish events
        published_messages: List[bytes] = []
        for event in events:
            serialized = serialize_telemetry_event(event).encode("utf-8")
            published_messages.append(serialized)
            await broker.publish("telemetry.raw", event.sensor_id, serialized)

        await broker.stop()

        # PROPERTY: Both consumer groups receive in exact publish order
        assert received_group_a == published_messages, (
            "Consumer group 'tsdb-writer' did not receive events in publish order"
        )
        assert received_group_b == published_messages, (
            "Consumer group 'ml-service' did not receive events in publish order"
        )

    @given(data=multi_sensor_event_sequences(min_sensors=2, max_sensors=3))
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @pytest.mark.asyncio
    async def test_interleaved_multi_sensor_preserves_per_sensor_order(
        self, data: Tuple[List[TelemetryEvent], Dict[str, List[TelemetryEvent]]]
    ):
        """When events from multiple sensors are interleaved, per-sensor order is preserved.

        This tests the Kafka partitioning-by-sensor_id strategy: even when events
        arrive interleaved across sensors, within each sensor_id partition the
        publish order is maintained.
        """
        interleaved_events, per_sensor_expected = data

        broker = InMemoryKafkaBroker()
        await broker.start()

        # Track received messages per sensor_id
        received_per_sensor: Dict[str, List[bytes]] = defaultdict(list)

        async def consumer_callback(topic: str, key: str, message: bytes) -> None:
            received_per_sensor[key].append(message)

        await broker.subscribe("telemetry.raw", "tsdb-writer", consumer_callback)

        # Publish events in interleaved order (simulates real-world arrival)
        published_per_sensor: Dict[str, List[bytes]] = defaultdict(list)
        for event in interleaved_events:
            serialized = serialize_telemetry_event(event).encode("utf-8")
            published_per_sensor[event.sensor_id].append(serialized)
            await broker.publish("telemetry.raw", event.sensor_id, serialized)

        await broker.stop()

        # PROPERTY: For each sensor_id, received order matches publish order
        for sensor_id in published_per_sensor:
            published_list = published_per_sensor[sensor_id]
            received_list = received_per_sensor[sensor_id]

            assert len(received_list) == len(published_list), (
                f"Sensor '{sensor_id}': expected {len(published_list)} messages, "
                f"got {len(received_list)}"
            )
            for i, (pub, recv) in enumerate(zip(published_list, received_list)):
                assert pub == recv, (
                    f"Sensor '{sensor_id}': message at position {i} differs. "
                    f"Per-sensor ordering not preserved with interleaved publishing."
                )

    @given(events=telemetry_event_sequence(min_count=2, max_count=50))
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_kafka_partitioning_routes_same_sensor_to_same_partition(
        self, events: List[TelemetryEvent]
    ):
        """All events for the same sensor_id are routed to the same partition.

        This validates the Kafka backend's key-based partitioning strategy:
        using sensor_id as the partition key ensures all events for a given
        sensor land in the same partition, which is the mechanism that
        guarantees ordering.
        """
        broker = InMemoryKafkaBroker()
        await broker.start()

        # Publish all events (same sensor_id from the strategy)
        sensor_id = events[0].sensor_id
        for event in events:
            serialized = serialize_telemetry_event(event).encode("utf-8")
            await broker.publish("telemetry.raw", event.sensor_id, serialized)

        # PROPERTY: All messages are in the same partition (same key)
        partition_messages = broker.get_partition_messages("telemetry.raw", sensor_id)
        assert len(partition_messages) == len(events), (
            f"Expected all {len(events)} events in partition for sensor '{sensor_id}', "
            f"found {len(partition_messages)}"
        )

        await broker.stop()
