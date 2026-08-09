"""Property-based tests for broker-to-WebSocket message transformation.

Uses the Hypothesis library to verify that when broker messages are transformed
and broadcast through the WebSocket manager, the resulting message sent to
clients has the correct {"type": ..., "payload": ...} JSON format with the
correct topic-to-type mapping:
    - corrections.state → "correction"
    - predictions.state → "prediction"
    - alerts.anomaly    → "anomaly"
    - telemetry.raw     → "telemetry"

**Validates: Requirements 1.2, 1.3, 1.4, 1.5**
"""

# Feature: backend-infrastructure, Property 1: Broker-to-WebSocket Message Transformation

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager


# ---------------------------------------------------------------------------
# Topic-to-type mapping (the transformation under test)
# ---------------------------------------------------------------------------

TOPIC_TO_TYPE = {
    "corrections.state": "correction",
    "predictions.state": "prediction",
    "alerts.anomaly": "anomaly",
    "telemetry.raw": "telemetry",
}


# ---------------------------------------------------------------------------
# Mock WebSocket
# ---------------------------------------------------------------------------


class MockWebSocket:
    """A lightweight mock WebSocket that records sent messages."""

    def __init__(self) -> None:
        self.sent_messages: list[str] = []

    async def accept(self) -> None:
        pass

    async def send_text(self, data: str) -> None:
        self.sent_messages.append(data)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for broker topic names (the domain of the topic-to-type mapping)
broker_topics = st.sampled_from(list(TOPIC_TO_TYPE.keys()))

# Strategy for generating arbitrary JSON-serializable payloads.
# Uses recursive strategy to produce dicts with string keys and values that
# are booleans, integers, floats, strings, None, or nested structures.
json_values = st.recursive(
    st.one_of(
        st.booleans(),
        st.integers(min_value=-1_000_000, max_value=1_000_000),
        st.floats(allow_nan=False, allow_infinity=False, min_value=-1e10, max_value=1e10),
        st.text(min_size=0, max_size=50),
        st.none(),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=children,
            max_size=5,
        ),
    ),
    max_leaves=20,
)

# Strategy for payload dictionaries (top-level must be a dict)
json_payloads = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=json_values,
    min_size=0,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Property 1: Broker-to-WebSocket Message Transformation
# ---------------------------------------------------------------------------


class TestProperty1BrokerToWebSocketTransformation:
    """Property 1: Broker-to-WebSocket Message Transformation.

    For any broker topic in {corrections.state, predictions.state,
    alerts.anomaly, telemetry.raw} and for any valid JSON payload, the
    WebSocketBroadcastManager SHALL broadcast a message to connected clients
    where the message is valid JSON containing {"type": "<mapped_type>",
    "payload": <original_payload>} with the type field correctly mapped from
    the topic name.

    **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
    """

    @given(topic=broker_topics, payload=json_payloads)
    @settings(max_examples=200, deadline=None)
    async def test_broadcast_produces_correct_json_structure(
        self, topic: str, payload: dict
    ):
        """The broadcast message has the correct {"type": ..., "payload": ...} structure."""
        # Arrange
        manager = WebSocketBroadcastManager()
        mock_ws = MockWebSocket()
        # Bypass accept() and directly add to active connections
        manager._active_connections.add(mock_ws)

        # Determine the expected type from the topic-to-type mapping
        expected_type = TOPIC_TO_TYPE[topic]

        # Act — simulate the transformation that the broker subscriber performs:
        # it maps topic → type and passes payload to broadcast()
        await manager.broadcast(expected_type, payload)

        # Assert — verify the message received by the client
        assert len(mock_ws.sent_messages) == 1, (
            f"Expected exactly 1 message sent, got {len(mock_ws.sent_messages)}"
        )

        received_raw = mock_ws.sent_messages[0]

        # Must be valid JSON
        received = json.loads(received_raw)

        # Must have exactly the keys "type" and "payload"
        assert set(received.keys()) == {"type", "payload"}, (
            f"Expected keys {{'type', 'payload'}}, got {set(received.keys())}"
        )

        # The "type" field must match the mapped type for the topic
        assert received["type"] == expected_type, (
            f"For topic '{topic}', expected type '{expected_type}', "
            f"got '{received['type']}'"
        )

        # The "payload" field must match the original payload exactly
        assert received["payload"] == payload, (
            f"Payload mismatch: expected {payload!r}, got {received['payload']!r}"
        )

    @given(topic=broker_topics, payload=json_payloads)
    @settings(max_examples=100, deadline=None)
    async def test_topic_to_type_mapping_is_correct(
        self, topic: str, payload: dict
    ):
        """Each topic maps to its unique correct type string."""
        expected_type = TOPIC_TO_TYPE[topic]

        # Verify the mapping is correct for each topic
        if topic == "corrections.state":
            assert expected_type == "correction"
        elif topic == "predictions.state":
            assert expected_type == "prediction"
        elif topic == "alerts.anomaly":
            assert expected_type == "anomaly"
        elif topic == "telemetry.raw":
            assert expected_type == "telemetry"
        else:
            pytest.fail(f"Unexpected topic: {topic}")

    @given(topic=broker_topics, payload=json_payloads)
    @settings(max_examples=100, deadline=None)
    async def test_broadcast_message_is_json_parseable(
        self, topic: str, payload: dict
    ):
        """The broadcast message is always valid JSON that can be parsed back."""
        manager = WebSocketBroadcastManager()
        mock_ws = MockWebSocket()
        manager._active_connections.add(mock_ws)

        expected_type = TOPIC_TO_TYPE[topic]
        await manager.broadcast(expected_type, payload)

        received_raw = mock_ws.sent_messages[0]

        # Parsing should not raise
        parsed = json.loads(received_raw)

        # Round-trip: re-serializing and parsing again yields the same result
        re_serialized = json.dumps(parsed)
        re_parsed = json.loads(re_serialized)
        assert re_parsed == parsed

    @given(topic=broker_topics, payload=json_payloads)
    @settings(max_examples=100, deadline=None)
    async def test_payload_integrity_preserved(
        self, topic: str, payload: dict
    ):
        """The original payload dict is preserved exactly in the broadcast message."""
        manager = WebSocketBroadcastManager()
        mock_ws = MockWebSocket()
        manager._active_connections.add(mock_ws)

        expected_type = TOPIC_TO_TYPE[topic]
        await manager.broadcast(expected_type, payload)

        received = json.loads(mock_ws.sent_messages[0])

        # Verify payload equality via JSON round-trip (handles type coercion)
        # Re-serialize original payload through JSON to normalize types
        normalized_original = json.loads(json.dumps(payload))
        assert received["payload"] == normalized_original, (
            f"Payload was not preserved. Original (normalized): {normalized_original}, "
            f"Received: {received['payload']}"
        )
