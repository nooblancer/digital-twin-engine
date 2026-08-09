"""Property-based tests for WebSocket Broadcast Fan-Out.

Property 2: WebSocket Broadcast Fan-Out
For any number of connected WebSocket clients (1 to N) and for any broadcast
message, every connected client SHALL receive exactly one copy of the message,
and no client that was connected at broadcast time shall be missed.

**Validates: Requirements 1.7**
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import hypothesis.strategies as st
from hypothesis import given, settings, HealthCheck
import pytest

from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager


# ---------------------------------------------------------------------------
# Mock WebSocket
# ---------------------------------------------------------------------------


class MockWebSocket:
    """A mock WebSocket that tracks sent messages."""

    def __init__(self) -> None:
        self.sent_messages: list[str] = []

    async def accept(self) -> None:
        pass

    async def send_text(self, data: str) -> None:
        self.sent_messages.append(data)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def broadcast_payloads(draw):
    """Generate random payloads suitable for WebSocket broadcast messages."""
    payload = draw(
        st.dictionaries(
            keys=st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
                min_size=1,
                max_size=20,
            ),
            values=st.one_of(
                st.integers(min_value=-1_000_000, max_value=1_000_000),
                st.floats(
                    min_value=-1e6,
                    max_value=1e6,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                st.text(min_size=0, max_size=50),
                st.booleans(),
                st.none(),
            ),
            min_size=1,
            max_size=10,
        )
    )
    return payload


message_types = st.sampled_from(["correction", "prediction", "anomaly", "telemetry"])


# ---------------------------------------------------------------------------
# Property 2: WebSocket Broadcast Fan-Out
# ---------------------------------------------------------------------------


class TestProperty2WebSocketBroadcastFanOut:
    """Property 2: WebSocket Broadcast Fan-Out.

    For any number of connected WebSocket clients (1 to N) and for any
    broadcast message, every connected client SHALL receive exactly one
    copy of the message, and no client that was connected at broadcast
    time shall be missed.

    **Validates: Requirements 1.7**
    """

    @given(
        num_clients=st.integers(min_value=1, max_value=50),
        message_type=message_types,
        payload=broadcast_payloads(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
    def test_all_clients_receive_exactly_one_copy(
        self,
        num_clients: int,
        message_type: str,
        payload: dict,
    ):
        """Every connected client receives exactly one copy of the broadcast message."""
        manager = WebSocketBroadcastManager()
        clients = [MockWebSocket() for _ in range(num_clients)]

        async def run():
            # Connect all clients
            for client in clients:
                await manager.connect(client)

            # Broadcast the message
            await manager.broadcast(message_type, payload)

        asyncio.run(run())

        # Build expected message
        expected_message = json.dumps({"type": message_type, "payload": payload})

        # Verify each client received exactly one message
        for i, client in enumerate(clients):
            assert len(client.sent_messages) == 1, (
                f"Client {i} received {len(client.sent_messages)} messages, expected 1"
            )
            assert client.sent_messages[0] == expected_message, (
                f"Client {i} received incorrect message: "
                f"{client.sent_messages[0]} != {expected_message}"
            )

    @given(
        num_clients=st.integers(min_value=1, max_value=50),
        num_messages=st.integers(min_value=1, max_value=10),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_multiple_broadcasts_deliver_all_messages(
        self,
        num_clients: int,
        num_messages: int,
        data,
    ):
        """Multiple broadcast calls deliver exactly one copy of each message to each client."""
        manager = WebSocketBroadcastManager()
        clients = [MockWebSocket() for _ in range(num_clients)]

        # Generate multiple messages
        messages = []
        for _ in range(num_messages):
            msg_type = data.draw(message_types)
            payload = data.draw(broadcast_payloads())
            messages.append((msg_type, payload))

        async def run():
            # Connect all clients
            for client in clients:
                await manager.connect(client)

            # Broadcast each message
            for msg_type, payload in messages:
                await manager.broadcast(msg_type, payload)

        asyncio.run(run())

        # Build expected messages in order
        expected_messages = [
            json.dumps({"type": msg_type, "payload": payload})
            for msg_type, payload in messages
        ]

        # Verify each client received all messages in order
        for i, client in enumerate(clients):
            assert len(client.sent_messages) == num_messages, (
                f"Client {i} received {len(client.sent_messages)} messages, "
                f"expected {num_messages}"
            )
            for j, (sent, expected) in enumerate(
                zip(client.sent_messages, expected_messages)
            ):
                assert sent == expected, (
                    f"Client {i}, message {j}: received {sent} != expected {expected}"
                )

    @given(
        num_clients=st.integers(min_value=2, max_value=50),
        message_type=message_types,
        payload=broadcast_payloads(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_no_connected_client_is_missed(
        self,
        num_clients: int,
        message_type: str,
        payload: dict,
    ):
        """No client connected at broadcast time is missed — all receive the message."""
        manager = WebSocketBroadcastManager()
        clients = [MockWebSocket() for _ in range(num_clients)]

        async def run():
            for client in clients:
                await manager.connect(client)
            await manager.broadcast(message_type, payload)

        asyncio.run(run())

        # Verify no client was missed (received zero messages)
        clients_that_received = [c for c in clients if len(c.sent_messages) > 0]
        assert len(clients_that_received) == num_clients, (
            f"Only {len(clients_that_received)} out of {num_clients} clients "
            f"received the broadcast message"
        )
