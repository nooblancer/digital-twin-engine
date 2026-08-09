"""Property-based tests for TimescaleDB Write-Read Round Trip.

Property 7: TimescaleDB Write-Read Round Trip
For any list of valid TelemetryEvents written to the TSDB backend, querying
by the same sensor_id and a time range that encompasses all event timestamps
SHALL return all written events with identical sensor_id, measurement_type,
value, and timestamp (within microsecond precision).

Note: Test runs against InMemoryTSDBBackend (same interface) since TimescaleDB
service is unavailable; validates interface contract.

**Validates: Requirements 11.3**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

import hypothesis.strategies as st
from hypothesis import given, settings, HealthCheck
import pytest

from digital_twin_engine.shared.models import TelemetryEvent
from digital_twin_engine.tsdb import InMemoryTSDBBackend


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Generate valid sensor_ids (1-20 chars, alphanumeric, not whitespace-only)
sensor_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
)

# Generate valid measurement types
measurement_type_strategy = st.sampled_from(
    ["temperature", "pressure", "vibration", "humidity", "rpm", "voltage", "current"]
)

# Generate finite float values
value_strategy = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)

# Generate UTC timestamps within a reasonable range
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


def telemetry_event_strategy(
    sensor_id: st.SearchStrategy[str] | None = None,
) -> st.SearchStrategy[TelemetryEvent]:
    """Generate a valid TelemetryEvent with optional fixed sensor_id."""
    sid = sensor_id if sensor_id is not None else sensor_id_strategy
    return st.builds(
        TelemetryEvent,
        timestamp=timestamp_strategy,
        sensor_id=sid,
        measurement_type=measurement_type_strategy,
        value=value_strategy,
    )


# Generate a non-empty list of TelemetryEvents (1-20 events)
telemetry_events_strategy = st.lists(
    telemetry_event_strategy(),
    min_size=1,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property 7: TimescaleDB Write-Read Round Trip
# ---------------------------------------------------------------------------


class TestProperty7TSDBWriteReadRoundTrip:
    """Property 7: TimescaleDB Write-Read Round Trip.

    For any list of valid TelemetryEvents written to the TSDB backend,
    querying by the same sensor_id and a time range that encompasses all
    event timestamps SHALL return all written events with identical
    sensor_id, measurement_type, value, and timestamp (within microsecond
    precision).

    **Validates: Requirements 11.3**
    """

    @given(events=telemetry_events_strategy)
    @settings(
        max_examples=100,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
    )
    def test_write_read_round_trip_returns_all_events(
        self,
        events: List[TelemetryEvent],
    ):
        """All written events are returned when queried by sensor_id and encompassing time range."""

        async def run():
            backend = InMemoryTSDBBackend()
            await backend.start()

            try:
                # Write all events to the backend
                await backend.write_events(events)

                # Group events by sensor_id
                events_by_sensor: dict[str, List[TelemetryEvent]] = {}
                for event in events:
                    events_by_sensor.setdefault(event.sensor_id, []).append(event)

                # For each unique sensor_id, query with an encompassing time range
                for sensor_id, sensor_events in events_by_sensor.items():
                    timestamps = [e.timestamp for e in sensor_events]
                    min_ts = min(timestamps)
                    max_ts = max(timestamps)

                    # Expand range by 1 second on each side to avoid boundary issues
                    start = min_ts - timedelta(seconds=1)
                    end = max_ts + timedelta(seconds=1)

                    results = await backend.query_by_sensor_and_time(
                        sensor_id=sensor_id,
                        start=start,
                        end=end,
                    )

                    # Verify count matches
                    assert len(results) == len(sensor_events), (
                        f"Expected {len(sensor_events)} events for sensor '{sensor_id}', "
                        f"got {len(results)}"
                    )

                    # Sort both lists by timestamp for comparison
                    expected_sorted = sorted(sensor_events, key=lambda e: e.timestamp)
                    results_sorted = sorted(results, key=lambda e: e.timestamp)

                    # Verify all fields match
                    for expected, actual in zip(expected_sorted, results_sorted):
                        assert actual.sensor_id == expected.sensor_id, (
                            f"sensor_id mismatch: expected '{expected.sensor_id}', "
                            f"got '{actual.sensor_id}'"
                        )
                        assert actual.measurement_type == expected.measurement_type, (
                            f"measurement_type mismatch: expected '{expected.measurement_type}', "
                            f"got '{actual.measurement_type}'"
                        )
                        assert actual.value == expected.value, (
                            f"value mismatch: expected {expected.value}, "
                            f"got {actual.value}"
                        )
                        # Verify timestamp within microsecond precision
                        time_diff = abs(
                            (actual.timestamp - expected.timestamp).total_seconds()
                        )
                        assert time_diff < 0.000001, (
                            f"timestamp mismatch beyond microsecond precision: "
                            f"expected {expected.timestamp}, got {actual.timestamp}, "
                            f"diff={time_diff}s"
                        )
            finally:
                await backend.stop()

        asyncio.run(run())

    @given(
        sensor_id=sensor_id_strategy,
        events=st.lists(
            telemetry_event_strategy(),
            min_size=2,
            max_size=15,
        ),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
    )
    def test_query_returns_only_matching_sensor_events(
        self,
        sensor_id: str,
        events: List[TelemetryEvent],
    ):
        """Query for a specific sensor_id returns only events with that sensor_id."""

        async def run():
            backend = InMemoryTSDBBackend()
            await backend.start()

            try:
                # Create events: some with target sensor_id, some with others
                target_events = []
                other_events = []

                for i, event in enumerate(events):
                    if i % 2 == 0:
                        # Assign target sensor_id
                        target_event = TelemetryEvent(
                            timestamp=event.timestamp,
                            sensor_id=sensor_id,
                            measurement_type=event.measurement_type,
                            value=event.value,
                        )
                        target_events.append(target_event)
                    else:
                        # Use a different sensor_id
                        other_event = TelemetryEvent(
                            timestamp=event.timestamp,
                            sensor_id=f"other_{event.sensor_id}_{i}",
                            measurement_type=event.measurement_type,
                            value=event.value,
                        )
                        other_events.append(other_event)

                all_events = target_events + other_events
                await backend.write_events(all_events)

                if target_events:
                    timestamps = [e.timestamp for e in target_events]
                    start = min(timestamps) - timedelta(seconds=1)
                    end = max(timestamps) + timedelta(seconds=1)

                    results = await backend.query_by_sensor_and_time(
                        sensor_id=sensor_id,
                        start=start,
                        end=end,
                    )

                    # All results should have the target sensor_id
                    for r in results:
                        assert r.sensor_id == sensor_id

                    # Count should match target events
                    assert len(results) == len(target_events), (
                        f"Expected {len(target_events)} events for sensor '{sensor_id}', "
                        f"got {len(results)}"
                    )
            finally:
                await backend.stop()

        asyncio.run(run())
