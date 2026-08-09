"""Property-based tests for TSDB operations.

Uses the Hypothesis library to verify universal properties of the TSDB Writer:
- Write-read round-trip fidelity
- Temporal and measurement query correctness
- Write retry exhaustion behavior

Tests use the InMemoryTSDBBackend for deterministic, fast property verification.
"""

# Feature: digital-twin-telemetry-engine, Property 7: TSDB Write-Read Round-Trip
# Feature: digital-twin-telemetry-engine, Property 8: Temporal and Measurement Query Correctness
# Feature: digital-twin-telemetry-engine, Property 9: TSDB Write Retry Exhaustion

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings, assume

from digital_twin_engine.shared.models import TelemetryEvent
from digital_twin_engine.tsdb.writer import (
    InMemoryTSDBBackend,
    TSDBWriter,
    TSDBWriteError,
    WriteFailureLog,
)


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for valid sensor IDs
valid_sensor_ids = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Strategy for valid measurement types
valid_measurement_types = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Strategy for valid finite float64 values
valid_float_values = st.floats(
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
    min_value=-1e15,
    max_value=1e15,
)

# Strategy for timestamps within a bounded range
valid_timestamps = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


@st.composite
def valid_telemetry_events(draw):
    """Generate a single valid TelemetryEvent."""
    return TelemetryEvent(
        timestamp=draw(valid_timestamps),
        sensor_id=draw(valid_sensor_ids),
        measurement_type=draw(valid_measurement_types),
        value=draw(valid_float_values),
    )


@st.composite
def telemetry_event_batches(draw, min_size=1, max_size=20):
    """Generate a list of valid TelemetryEvents."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    events = []
    for _ in range(count):
        events.append(draw(valid_telemetry_events()))
    return events


@st.composite
def events_for_sensor(draw, sensor_id: str, measurement_type: str):
    """Generate events with a fixed sensor_id and measurement_type."""
    return TelemetryEvent(
        timestamp=draw(valid_timestamps),
        sensor_id=sensor_id,
        measurement_type=measurement_type,
        value=draw(valid_float_values),
    )


@st.composite
def time_range_query_scenario(draw):
    """Generate a set of events and a query time range for testing.

    Returns (events, sensor_id, measurement_type, start, end) where:
    - events is a list of TelemetryEvents with mixed sensors and types
    - query params filter to a specific subset
    """
    # Fixed sensor IDs and measurement types for controlled testing
    target_sensor = draw(valid_sensor_ids)
    other_sensor = draw(valid_sensor_ids.filter(lambda s: s != target_sensor))
    target_mtype = draw(valid_measurement_types)
    other_mtype = draw(valid_measurement_types.filter(lambda s: s != target_mtype))

    # Generate a time range
    base_time = draw(st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2024, 6, 1),
        timezones=st.just(timezone.utc),
    ))
    window_hours = draw(st.integers(min_value=1, max_value=48))
    start = base_time
    end = base_time + timedelta(hours=window_hours)

    # Generate events: some inside the window, some outside
    num_matching = draw(st.integers(min_value=1, max_value=10))
    num_outside_time = draw(st.integers(min_value=0, max_value=5))
    num_other_sensor = draw(st.integers(min_value=0, max_value=5))
    num_other_mtype = draw(st.integers(min_value=0, max_value=5))

    events: List[TelemetryEvent] = []

    # Matching events (correct sensor, type, and within time range)
    for _ in range(num_matching):
        ts = draw(st.datetimes(
            min_value=start.replace(tzinfo=None),
            max_value=end.replace(tzinfo=None),
            timezones=st.just(timezone.utc),
        ))
        events.append(TelemetryEvent(
            timestamp=ts,
            sensor_id=target_sensor,
            measurement_type=target_mtype,
            value=draw(valid_float_values),
        ))

    # Events outside time range (same sensor and type)
    for _ in range(num_outside_time):
        # Either before start or after end
        if draw(st.booleans()):
            ts = start - timedelta(hours=draw(st.integers(min_value=1, max_value=24)))
        else:
            ts = end + timedelta(hours=draw(st.integers(min_value=1, max_value=24)))
        events.append(TelemetryEvent(
            timestamp=ts,
            sensor_id=target_sensor,
            measurement_type=target_mtype,
            value=draw(valid_float_values),
        ))

    # Events with different sensor (same type, within time range)
    for _ in range(num_other_sensor):
        ts = draw(st.datetimes(
            min_value=start.replace(tzinfo=None),
            max_value=end.replace(tzinfo=None),
            timezones=st.just(timezone.utc),
        ))
        events.append(TelemetryEvent(
            timestamp=ts,
            sensor_id=other_sensor,
            measurement_type=target_mtype,
            value=draw(valid_float_values),
        ))

    # Events with different measurement type (same sensor, within time range)
    for _ in range(num_other_mtype):
        ts = draw(st.datetimes(
            min_value=start.replace(tzinfo=None),
            max_value=end.replace(tzinfo=None),
            timezones=st.just(timezone.utc),
        ))
        events.append(TelemetryEvent(
            timestamp=ts,
            sensor_id=target_sensor,
            measurement_type=other_mtype,
            value=draw(valid_float_values),
        ))

    return events, target_sensor, target_mtype, start, end, num_matching


# ---------------------------------------------------------------------------
# Property 7: TSDB Write-Read Round-Trip
# ---------------------------------------------------------------------------


class TestProperty7WriteReadRoundTrip:
    """Property 7: TSDB Write-Read Round-Trip.

    For any valid TelemetryEvent written to the TSDB by the TSDB_Writer,
    reading that event back by sensor_id and timestamp SHALL return an event
    with identical field values (timestamp, sensor_id, measurement_type, and
    value preserved without modification).

    **Validates: Requirements 4.1**
    """

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_single_event_round_trip(self, event: TelemetryEvent):
        """A single event written and read back has identical field values."""
        backend = InMemoryTSDBBackend()
        writer = TSDBWriter(backend=backend, batch_size=1)

        # Write the event
        await writer.write_event(event)

        # Read it back by sensor_id and timestamp range
        results = await writer.query_by_sensor_and_time(
            sensor_id=event.sensor_id,
            start=event.timestamp - timedelta(seconds=1),
            end=event.timestamp + timedelta(seconds=1),
        )

        # Should find exactly one matching event
        assert len(results) >= 1

        # Find the exact event by matching timestamp
        matching = [r for r in results if r.timestamp == event.timestamp]
        assert len(matching) >= 1

        restored = matching[0]

        # Verify identical field values - no modification
        assert restored.timestamp == event.timestamp
        assert restored.sensor_id == event.sensor_id
        assert restored.measurement_type == event.measurement_type
        assert restored.value == event.value

    @given(events=telemetry_event_batches(min_size=1, max_size=15))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_batch_write_read_round_trip(self, events: List[TelemetryEvent]):
        """Multiple events written in a batch preserve all field values."""
        backend = InMemoryTSDBBackend()
        writer = TSDBWriter(backend=backend, batch_size=len(events))

        # Write all events and flush
        for event in events:
            await writer.write_event(event)
        await writer.flush()

        # Verify each event can be read back with identical fields
        for event in events:
            results = await writer.query_by_sensor_and_time(
                sensor_id=event.sensor_id,
                start=event.timestamp - timedelta(seconds=1),
                end=event.timestamp + timedelta(seconds=1),
            )

            matching = [
                r for r in results
                if r.timestamp == event.timestamp
                and r.sensor_id == event.sensor_id
                and r.measurement_type == event.measurement_type
                and r.value == event.value
            ]
            assert len(matching) >= 1, (
                f"Event not found after write: sensor_id={event.sensor_id}, "
                f"timestamp={event.timestamp}, value={event.value}"
            )


# ---------------------------------------------------------------------------
# Property 8: Temporal and Measurement Query Correctness
# ---------------------------------------------------------------------------


class TestProperty8TemporalMeasurementQueryCorrectness:
    """Property 8: Temporal and Measurement Query Correctness.

    For any set of TelemetryEvents in the TSDB, and any query specifying a
    sensor_id (or set of sensor_ids), measurement_type, start timestamp, and
    end timestamp, the query SHALL return exactly the events matching all
    filter criteria, ordered chronologically by timestamp.

    **Validates: Requirements 4.2, 4.3**
    """

    @given(data=time_range_query_scenario())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_sensor_time_range_query_returns_exact_matches(self, data):
        """Query by sensor_id and time range returns exactly matching events."""
        events, target_sensor, target_mtype, start, end, expected_count = data

        backend = InMemoryTSDBBackend()
        writer = TSDBWriter(backend=backend, batch_size=len(events) + 1)

        # Write all events
        for event in events:
            await writer.write_event(event)
        await writer.flush()

        # Query by sensor_id and time range (no measurement_type filter)
        results = await writer.query_by_sensor_and_time(
            sensor_id=target_sensor,
            start=start,
            end=end,
        )

        # Verify: every result matches the sensor_id and time range
        for r in results:
            assert r.sensor_id == target_sensor
            assert start <= r.timestamp <= end

        # Verify: all events that should match ARE in the results
        expected_events = [
            e for e in events
            if e.sensor_id == target_sensor
            and start <= e.timestamp <= end
        ]
        assert len(results) == len(expected_events), (
            f"Expected {len(expected_events)} results, got {len(results)}"
        )

        # Verify chronological ordering
        for i in range(len(results) - 1):
            assert results[i].timestamp <= results[i + 1].timestamp

    @given(data=time_range_query_scenario())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_measurement_type_query_returns_exact_matches(self, data):
        """Query by sensor_id, measurement_type, and time range is exact."""
        events, target_sensor, target_mtype, start, end, expected_count = data

        backend = InMemoryTSDBBackend()
        writer = TSDBWriter(backend=backend, batch_size=len(events) + 1)

        # Write all events
        for event in events:
            await writer.write_event(event)
        await writer.flush()

        # Query with measurement_type filter
        results = await writer.query_by_sensor_and_time(
            sensor_id=target_sensor,
            start=start,
            end=end,
            measurement_type=target_mtype,
        )

        # Verify: every result matches all criteria
        for r in results:
            assert r.sensor_id == target_sensor
            assert r.measurement_type == target_mtype
            assert start <= r.timestamp <= end

        # Verify: results contain exactly the matching events
        expected_events = [
            e for e in events
            if e.sensor_id == target_sensor
            and e.measurement_type == target_mtype
            and start <= e.timestamp <= end
        ]
        assert len(results) == len(expected_events)

        # Verify chronological ordering
        for i in range(len(results) - 1):
            assert results[i].timestamp <= results[i + 1].timestamp

    @given(data=time_range_query_scenario())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_multi_sensor_measurement_type_query(self, data):
        """Query by measurement_type across multiple sensor_ids is correct."""
        events, target_sensor, target_mtype, start, end, _ = data

        backend = InMemoryTSDBBackend()
        writer = TSDBWriter(backend=backend, batch_size=len(events) + 1)

        # Write all events
        for event in events:
            await writer.write_event(event)
        await writer.flush()

        # Get all unique sensor IDs from the events
        all_sensor_ids = list(set(e.sensor_id for e in events))

        # Query across all sensors for the target measurement type
        results = await writer.query_by_measurement_type(
            sensor_ids=all_sensor_ids,
            measurement_type=target_mtype,
            start=start,
            end=end,
        )

        # Verify: every result matches all criteria
        for r in results:
            assert r.sensor_id in all_sensor_ids
            assert r.measurement_type == target_mtype
            assert start <= r.timestamp <= end

        # Verify: results contain exactly the matching events
        expected_events = [
            e for e in events
            if e.sensor_id in all_sensor_ids
            and e.measurement_type == target_mtype
            and start <= e.timestamp <= end
        ]
        assert len(results) == len(expected_events)

        # Verify chronological ordering
        for i in range(len(results) - 1):
            assert results[i].timestamp <= results[i + 1].timestamp


# ---------------------------------------------------------------------------
# Property 9: TSDB Write Retry Exhaustion
# ---------------------------------------------------------------------------


class FailNTimesTSDBBackend:
    """TSDB backend that fails a configurable number of times then succeeds.

    Used to test retry logic precisely.
    """

    def __init__(self, fail_count: int) -> None:
        self._fail_count = fail_count
        self._attempt_count = 0
        self._events: List[TelemetryEvent] = []

    @property
    def attempt_count(self) -> int:
        """Total number of write attempts made."""
        return self._attempt_count

    @property
    def events(self) -> List[TelemetryEvent]:
        """Events that were successfully written."""
        return list(self._events)

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Fail for the first fail_count attempts, then succeed."""
        self._attempt_count += 1
        if self._attempt_count <= self._fail_count:
            raise TSDBWriteError(
                f"Simulated failure (attempt {self._attempt_count}/{self._fail_count})",
                sensor_id=events[0].sensor_id if events else "",
                timestamp=str(events[0].timestamp) if events else "",
            )
        self._events.extend(events)

    async def query_by_sensor_and_time(self, sensor_id, start, end, measurement_type=None):
        return []

    async def query_by_measurement_type(self, sensor_ids, measurement_type, start, end):
        return []


class AlwaysFailTSDBBackend:
    """TSDB backend that always fails on writes."""

    def __init__(self) -> None:
        self._attempt_count = 0

    @property
    def attempt_count(self) -> int:
        """Total number of write attempts made."""
        return self._attempt_count

    async def write_events(self, events: List[TelemetryEvent]) -> None:
        """Always fail."""
        self._attempt_count += 1
        raise TSDBWriteError(
            f"Permanent failure (attempt {self._attempt_count})",
            sensor_id=events[0].sensor_id if events else "",
            timestamp=str(events[0].timestamp) if events else "",
        )

    async def query_by_sensor_and_time(self, sensor_id, start, end, measurement_type=None):
        return []

    async def query_by_measurement_type(self, sensor_ids, measurement_type, start, end):
        return []


class TestProperty9WriteRetryExhaustion:
    """Property 9: TSDB Write Retry Exhaustion.

    For any TelemetryEvent write that fails, the TSDB_Writer SHALL retry up
    to exactly 3 times with exponential backoff (starting at 100ms). After 3
    failed retries, the event SHALL be logged as a permanent write failure
    with sensor_id, timestamp, and failure reason. No more than 3 retry
    attempts SHALL occur.

    **Validates: Requirements 4.6**
    """

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_retries_exactly_3_times_on_permanent_failure(
        self, event: TelemetryEvent
    ):
        """After initial attempt fails, exactly 3 retries occur (4 total attempts)."""
        backend = AlwaysFailTSDBBackend()
        writer = TSDBWriter(
            backend=backend,
            batch_size=1,
            max_retries=3,
            initial_retry_delay_ms=1,  # Use 1ms for fast tests
        )

        await writer.write_event(event)

        # Total attempts: 1 initial + 3 retries = 4
        assert backend.attempt_count == 4, (
            f"Expected exactly 4 attempts (1 initial + 3 retries), "
            f"got {backend.attempt_count}"
        )

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_permanent_failure_logged_with_required_fields(
        self, event: TelemetryEvent
    ):
        """After retry exhaustion, failure is logged with sensor_id, timestamp, reason."""
        backend = AlwaysFailTSDBBackend()
        writer = TSDBWriter(
            backend=backend,
            batch_size=1,
            max_retries=3,
            initial_retry_delay_ms=1,
        )

        await writer.write_event(event)

        # Verify failure was logged
        assert len(writer.failure_log) == 1

        failure = writer.failure_log[0]
        assert failure.sensor_id == event.sensor_id
        assert failure.timestamp == event.timestamp
        assert failure.failure_reason != ""
        assert failure.retry_count == 3

    @given(
        event=valid_telemetry_events(),
        fail_count=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failures(
        self, event: TelemetryEvent, fail_count: int
    ):
        """If write succeeds within 3 retries, no permanent failure is logged."""
        backend = FailNTimesTSDBBackend(fail_count=fail_count)
        writer = TSDBWriter(
            backend=backend,
            batch_size=1,
            max_retries=3,
            initial_retry_delay_ms=1,
        )

        await writer.write_event(event)

        # Should have succeeded (fail_count <= 3, so retries will recover)
        assert len(writer.failure_log) == 0
        assert len(backend.events) == 1
        assert backend.events[0].sensor_id == event.sensor_id
        assert backend.events[0].value == event.value

        # Total attempts should be fail_count + 1 (the successful one)
        assert backend.attempt_count == fail_count + 1

    @given(event=valid_telemetry_events())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_more_than_3_retries(self, event: TelemetryEvent):
        """No more than 3 retry attempts SHALL occur (total 4 attempts max)."""
        backend = AlwaysFailTSDBBackend()
        writer = TSDBWriter(
            backend=backend,
            batch_size=1,
            max_retries=3,
            initial_retry_delay_ms=1,
        )

        await writer.write_event(event)

        # Invariant: never more than 4 total attempts (1 initial + 3 retries)
        assert backend.attempt_count <= 4, (
            f"More than 3 retries occurred! Total attempts: {backend.attempt_count}"
        )
        # Exactly 4 in the always-fail case
        assert backend.attempt_count == 4

    @given(events=telemetry_event_batches(min_size=1, max_size=5))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_each_failed_event_in_batch_logged(
        self, events: List[TelemetryEvent]
    ):
        """When a batch write fails permanently, ALL events in the batch are logged."""
        backend = AlwaysFailTSDBBackend()
        writer = TSDBWriter(
            backend=backend,
            batch_size=len(events),
            max_retries=3,
            initial_retry_delay_ms=1,
        )

        # Write all events and flush
        for event in events:
            writer._buffer.append(event)
        await writer.flush()

        # Each event in the batch should have a failure log entry
        assert len(writer.failure_log) == len(events)

        for i, event in enumerate(events):
            failure = writer.failure_log[i]
            assert failure.sensor_id == event.sensor_id
            assert failure.timestamp == event.timestamp
            assert failure.retry_count == 3
