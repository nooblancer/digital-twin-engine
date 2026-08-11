"""Property-based tests for the API Gateway.

Uses the Hypothesis library to verify universal properties across many inputs.
"""

# Feature: digital-twin-telemetry-engine, Property 18: History Query Filtering, Ordering, and Pagination
# Feature: digital-twin-telemetry-engine, Property 19: API Parameter Validation

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import hypothesis.strategies as st
from hypothesis import given, settings, assume, HealthCheck
import pytest
from httpx import ASGITransport, AsyncClient

from digital_twin_engine.api.app import APIGateway
from digital_twin_engine.api.state_cache import StateCache
from digital_twin_engine.shared.models import TelemetryEvent
from digital_twin_engine.tsdb.writer import InMemoryTSDBBackend


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def valid_sensor_ids(draw):
    """Generate valid sensor identifiers."""
    prefix = draw(st.sampled_from(["sensor", "turbine", "pump", "valve"]))
    num = draw(st.integers(min_value=1, max_value=999))
    suffix = draw(st.sampled_from(["-temp", "-pressure", "-flow", "-vibration"]))
    return f"{prefix}-{num:03d}{suffix}"


@st.composite
def state_vector_sets(draw, min_count=1, max_count=50):
    """Generate a list of TelemetryEvents representing corrected state vectors
    stored in TSDB for a single sensor, with distinct timestamps."""
    count = draw(st.integers(min_value=min_count, max_value=max_count))
    sensor_id = draw(valid_sensor_ids())

    # Base time and generate events spread over a time range
    base_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Generate unique offsets (in seconds) to ensure distinct timestamps
    offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=86400),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    offsets.sort()

    events = []
    for offset in offsets:
        ts = base_ts + timedelta(seconds=offset)
        value = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
        events.append(TelemetryEvent(
            timestamp=ts,
            sensor_id=sensor_id,
            measurement_type="temperature",
            value=value,
        ))

    return sensor_id, events


@st.composite
def valid_pagination_params(draw):
    """Generate valid limit and offset parameters."""
    limit = draw(st.integers(min_value=1, max_value=1000))
    offset = draw(st.integers(min_value=0, max_value=200))
    return limit, offset


@st.composite
def valid_time_ranges(draw, events: List[TelemetryEvent]):
    """Generate a valid time range that overlaps with the events' time span."""
    if not events:
        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        return base, base + timedelta(hours=1)

    min_ts = min(e.timestamp for e in events)
    max_ts = max(e.timestamp for e in events)

    # Generate start and end within and around the event range
    total_span = (max_ts - min_ts).total_seconds()
    margin = max(total_span * 0.2, 60.0)

    start_offset = draw(st.floats(
        min_value=-margin,
        max_value=total_span + margin,
        allow_nan=False,
        allow_infinity=False,
    ))
    end_offset = draw(st.floats(
        min_value=start_offset,
        max_value=total_span + margin + 3600,
        allow_nan=False,
        allow_infinity=False,
    ))

    start_dt = min_ts + timedelta(seconds=start_offset)
    end_dt = min_ts + timedelta(seconds=end_offset)
    assume(start_dt <= end_dt)
    return start_dt, end_dt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ts(dt: datetime) -> str:
    """Format a datetime as ISO 8601 string for query params."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _create_gateway_with_data(
    sensor_id: str,
    events: List[TelemetryEvent],
) -> APIGateway:
    """Create an APIGateway with pre-populated TSDB data."""
    tsdb = InMemoryTSDBBackend()
    # Write events synchronously
    asyncio.run(tsdb.write_events(events))

    state_cache = StateCache()
    state_cache.register_sensor(sensor_id)

    gateway = APIGateway(tsdb_backend=tsdb, state_cache=state_cache)
    return gateway


# ===========================================================================
# Property 18: History Query Filtering, Ordering, and Pagination
# ===========================================================================


class TestProperty18HistoryQueryFilteringOrderingPagination:
    """Property 18: History Query Filtering, Ordering, and Pagination.

    For any set of corrected StateVectors stored for a sensor_id, and any
    valid query with start timestamp, end timestamp, limit, and offset
    parameters, the API response SHALL contain exactly the StateVectors
    within [start, end] ordered chronologically, sliced at the specified
    offset and limited to the specified limit, with accurate pagination
    metadata (total_count reflecting the full filtered set, current offset,
    and current limit).

    **Validates: Requirements 7.2, 7.7**
    """

    @given(
        data=st.data(),
        dataset=state_vector_sets(min_count=1, max_count=30),
        pagination=valid_pagination_params(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_history_returns_correct_filtered_ordered_paginated_results(
        self,
        data,
        dataset: tuple,
        pagination: tuple,
    ):
        """API response contains exactly the StateVectors within [start, end],
        ordered chronologically, sliced at offset and limited to limit,
        with accurate pagination metadata."""
        sensor_id, events = dataset
        limit, offset = pagination

        # Generate a time range
        min_ts = min(e.timestamp for e in events)
        max_ts = max(e.timestamp for e in events)
        total_span = (max_ts - min_ts).total_seconds()
        margin = max(total_span * 0.2, 60.0)

        start_offset = data.draw(st.floats(
            min_value=-margin,
            max_value=total_span + margin,
            allow_nan=False,
            allow_infinity=False,
        ))
        end_offset = data.draw(st.floats(
            min_value=start_offset + 0.001,
            max_value=total_span + margin + 3600,
            allow_nan=False,
            allow_infinity=False,
        ))

        start_dt = min_ts + timedelta(seconds=start_offset)
        end_dt = min_ts + timedelta(seconds=end_offset)
        assume(start_dt < end_dt)

        # Compute expected results manually
        filtered = [e for e in events if start_dt <= e.timestamp <= end_dt]
        filtered.sort(key=lambda e: e.timestamp)
        total_count = len(filtered)
        expected_page = filtered[offset: offset + limit]

        # Set up gateway and make request
        gateway = _create_gateway_with_data(sensor_id, events)

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/sensors/{sensor_id}/state/history",
                    params={
                        "start": _fmt_ts(start_dt),
                        "end": _fmt_ts(end_dt),
                        "limit": limit,
                        "offset": offset,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()

        # Check pagination metadata
        assert body["pagination"]["total_count"] == total_count
        assert body["pagination"]["offset"] == offset
        assert body["pagination"]["limit"] == limit

        # Check result count
        assert len(body["results"]) == len(expected_page)

        # Check ordering (chronological)
        timestamps = [r["timestamp"] for r in body["results"]]
        assert timestamps == sorted(timestamps), "Results not in chronological order"

        # Check that returned values match expected page
        for i, (result, expected_event) in enumerate(zip(body["results"], expected_page)):
            assert result["state_vector"] == [expected_event.value], (
                f"Result {i}: expected value {expected_event.value}, "
                f"got {result['state_vector']}"
            )

    @given(
        dataset=state_vector_sets(min_count=5, max_count=20),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_full_range_query_returns_all_events(self, dataset: tuple):
        """Querying the full time range with large limit returns all events."""
        sensor_id, events = dataset

        min_ts = min(e.timestamp for e in events) - timedelta(seconds=1)
        max_ts = max(e.timestamp for e in events) + timedelta(seconds=1)

        gateway = _create_gateway_with_data(sensor_id, events)

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/sensors/{sensor_id}/state/history",
                    params={
                        "start": _fmt_ts(min_ts),
                        "end": _fmt_ts(max_ts),
                        "limit": 1000,
                        "offset": 0,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 200
        body = resp.json()
        assert body["pagination"]["total_count"] == len(events)
        assert len(body["results"]) == len(events)

    @given(
        dataset=state_vector_sets(min_count=5, max_count=20),
        limit=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_pagination_offset_slices_correctly(self, dataset: tuple, limit: int):
        """Consecutive offset pages cover all results without gaps or overlaps."""
        sensor_id, events = dataset

        min_ts = min(e.timestamp for e in events) - timedelta(seconds=1)
        max_ts = max(e.timestamp for e in events) + timedelta(seconds=1)

        gateway = _create_gateway_with_data(sensor_id, events)

        all_results = []
        offset = 0

        async def fetch_page(off: int):
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/sensors/{sensor_id}/state/history",
                    params={
                        "start": _fmt_ts(min_ts),
                        "end": _fmt_ts(max_ts),
                        "limit": limit,
                        "offset": off,
                    },
                )
                return resp

        # Collect all pages
        total_count = None
        while True:
            resp = asyncio.run(fetch_page(offset))
            assert resp.status_code == 200
            body = resp.json()

            if total_count is None:
                total_count = body["pagination"]["total_count"]

            page_results = body["results"]
            if not page_results:
                break

            all_results.extend(page_results)
            offset += limit

            if offset >= total_count:
                break

        # All events should be covered
        assert len(all_results) == total_count
        # Check chronological ordering across all pages
        all_timestamps = [r["timestamp"] for r in all_results]
        assert all_timestamps == sorted(all_timestamps)


# ===========================================================================
# Property 19: API Parameter Validation
# ===========================================================================


class TestProperty19APIParameterValidation:
    """Property 19: API Parameter Validation.

    For any API request to the history endpoint, the API_Gateway SHALL
    return HTTP 400 if: (a) the start timestamp is after the end timestamp,
    OR (b) start or end is missing or not valid ISO 8601, OR (c) limit is
    less than 1 or greater than 1000, OR (d) offset is less than 0.
    The error response SHALL contain an error_code and descriptive message.

    **Validates: Requirements 7.6, 7.8, 7.9**
    """

    def _make_gateway(self) -> APIGateway:
        """Create a gateway with a known sensor registered."""
        state_cache = StateCache()
        state_cache.register_sensor("test-sensor-001")
        tsdb = InMemoryTSDBBackend()
        return APIGateway(tsdb_backend=tsdb, state_cache=state_cache)

    @given(
        start_offset=st.floats(min_value=1.0, max_value=86400.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_start_after_end_returns_400(self, start_offset: float):
        """HTTP 400 returned when start timestamp is after end timestamp."""
        gateway = self._make_gateway()

        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        end_dt = base
        start_dt = base + timedelta(seconds=start_offset)
        assume(start_dt > end_dt)

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params={
                        "start": _fmt_ts(start_dt),
                        "end": _fmt_ts(end_dt),
                        "limit": 100,
                        "offset": 0,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        body = resp.json()
        assert "error_code" in body
        assert "message" in body

    @given(
        invalid_start=st.sampled_from([
            "not-a-date",
            "2024-13-01T00:00:00Z",
            "yesterday",
            "12345",
            "",
            "2024/01/15",
            "abc123xyz",
        ]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_invalid_start_iso_returns_400(self, invalid_start: str):
        """HTTP 400 returned when start is not valid ISO 8601."""
        gateway = self._make_gateway()

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params={
                        "start": invalid_start,
                        "end": "2024-01-15T12:00:00Z",
                        "limit": 100,
                        "offset": 0,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 400, f"Expected 400 for start='{invalid_start}', got {resp.status_code}"
        body = resp.json()
        assert "error_code" in body
        assert "message" in body

    @given(
        invalid_end=st.sampled_from([
            "not-a-date",
            "2024-13-01T00:00:00Z",
            "tomorrow",
            "99999",
            "",
            "2024/01/15",
            "xyz789abc",
        ]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_invalid_end_iso_returns_400(self, invalid_end: str):
        """HTTP 400 returned when end is not valid ISO 8601."""
        gateway = self._make_gateway()

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params={
                        "start": "2024-01-15T10:00:00Z",
                        "end": invalid_end,
                        "limit": 100,
                        "offset": 0,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 400, f"Expected 400 for end='{invalid_end}', got {resp.status_code}"
        body = resp.json()
        assert "error_code" in body
        assert "message" in body

    @given(
        missing=st.sampled_from(["start", "end", "both"]),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_missing_start_or_end_returns_400(self, missing: str):
        """HTTP 400 returned when start or end query parameter is missing."""
        gateway = self._make_gateway()

        params: dict = {"limit": 100, "offset": 0}
        if missing == "start":
            params["end"] = "2024-01-15T12:00:00Z"
        elif missing == "end":
            params["start"] = "2024-01-15T10:00:00Z"
        # "both" - neither start nor end

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params=params,
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 400, f"Expected 400 for missing={missing}, got {resp.status_code}"
        body = resp.json()
        assert "error_code" in body
        assert "message" in body

    @given(
        invalid_limit=st.one_of(
            st.integers(min_value=-100, max_value=0),
            st.integers(min_value=1001, max_value=10000),
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_invalid_limit_returns_400(self, invalid_limit: int):
        """HTTP 400 returned when limit < 1 or limit > 1000."""
        gateway = self._make_gateway()

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params={
                        "start": "2024-01-15T10:00:00Z",
                        "end": "2024-01-15T12:00:00Z",
                        "limit": invalid_limit,
                        "offset": 0,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 400, f"Expected 400 for limit={invalid_limit}, got {resp.status_code}"
        body = resp.json()
        assert "error_code" in body
        assert "message" in body

    @given(
        invalid_offset=st.integers(min_value=-1000, max_value=-1),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_negative_offset_returns_400(self, invalid_offset: int):
        """HTTP 400 returned when offset < 0."""
        gateway = self._make_gateway()

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params={
                        "start": "2024-01-15T10:00:00Z",
                        "end": "2024-01-15T12:00:00Z",
                        "limit": 100,
                        "offset": invalid_offset,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 400, f"Expected 400 for offset={invalid_offset}, got {resp.status_code}"
        body = resp.json()
        assert "error_code" in body
        assert "message" in body

    @given(
        limit=st.integers(min_value=1, max_value=1000),
        offset=st.integers(min_value=0, max_value=500),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_valid_params_do_not_return_400(self, limit: int, offset: int):
        """Valid parameters SHALL NOT produce HTTP 400."""
        gateway = self._make_gateway()

        async def do_request():
            transport = ASGITransport(app=gateway.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/sensors/test-sensor-001/state/history",
                    params={
                        "start": "2024-01-15T10:00:00Z",
                        "end": "2024-01-15T12:00:00Z",
                        "limit": limit,
                        "offset": offset,
                    },
                )
                return resp

        resp = asyncio.run(do_request())

        assert resp.status_code == 200, (
            f"Expected 200 for valid params (limit={limit}, offset={offset}), "
            f"got {resp.status_code}: {resp.text}"
        )
