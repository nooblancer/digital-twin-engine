"""Broker Subscriber service for the API Gateway.

Subscribes to broker topics and dispatches incoming messages to the
state cache and WebSocket broadcast manager. Implements exponential
backoff retry on broker connection failure and supports degraded mode
operation when the broker is unavailable.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 13.1
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from digital_twin_engine.api.metrics import messages_processed_total
from digital_twin_engine.api.state_cache import StateCache
from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager
from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import (
    ALERTS_ANOMALY,
    CORRECTIONS_STATE,
    PREDICTIONS_STATE,
    TELEMETRY_RAW,
)
from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import Prediction

logger = get_logger("broker_subscriber")

# Topic-to-WebSocket message type mapping
TOPIC_TYPE_MAP: Dict[str, str] = {
    CORRECTIONS_STATE: "correction",
    PREDICTIONS_STATE: "prediction",
    ALERTS_ANOMALY: "anomaly",
    TELEMETRY_RAW: "telemetry",
}

# Consumer group ID for the API Gateway subscriber
_CONSUMER_GROUP = "api-gateway"

# Retry configuration
_MAX_RETRY_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 32.0


class BrokerSubscriber:
    """Subscribes to broker topics and dispatches to state cache + WebSocket broadcast.

    Accepts a BrokerBackend instance via dependency injection. On start,
    subscribes to corrections.state, predictions.state, alerts.anomaly,
    and telemetry.raw topics. Each received message updates the appropriate
    cache and is forwarded to all connected WebSocket clients.

    Implements exponential backoff retry (up to 5 attempts) on broker
    connection failure at startup. If the broker remains unavailable,
    the subscriber starts in degraded mode where cached data is still
    served via REST endpoints.

    If the broker connection is lost during operation, the subscriber
    attempts to reconnect with exponential backoff while the API Gateway
    continues to serve cached data.
    """

    def __init__(self) -> None:
        self._broker: Optional[BrokerBackend] = None
        self._state_cache: Optional[StateCache] = None
        self._ws_manager: Optional[WebSocketBroadcastManager] = None
        self._gateway_predictions_cache: Optional[Dict[str, List[Prediction]]] = None
        self._predictions_cache: Dict[str, List[dict]] = {}
        self._running: bool = False
        self._degraded: bool = False
        self._reconnect_task: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        """Whether the subscriber is currently running."""
        return self._running

    @property
    def degraded(self) -> bool:
        """Whether the subscriber is in degraded mode (broker unavailable)."""
        return self._degraded

    @property
    def predictions_cache(self) -> Dict[str, List[dict]]:
        """Access the predictions cache."""
        return self._predictions_cache

    async def start(
        self,
        broker: BrokerBackend,
        state_cache: StateCache,
        ws_manager: WebSocketBroadcastManager,
        predictions_cache: Optional[Dict[str, List[Prediction]]] = None,
    ) -> None:
        """Start subscribing to broker topics.

        Attempts to subscribe with exponential backoff retry. If the broker
        is unavailable after all retry attempts, starts in degraded mode.

        Args:
            broker: The BrokerBackend instance to subscribe through.
            state_cache: The StateCache to update on corrections.state messages.
            ws_manager: The WebSocketBroadcastManager for broadcasting messages.
            predictions_cache: Optional gateway predictions cache to populate
                with Prediction objects for the REST endpoint.
        """
        self._broker = broker
        self._state_cache = state_cache
        self._ws_manager = ws_manager
        self._gateway_predictions_cache = predictions_cache
        self._running = True
        self._degraded = False

        await self._subscribe_with_retry()

    async def stop(self) -> None:
        """Stop the subscriber and cancel any pending reconnection task."""
        self._running = False

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        logger.info("Broker subscriber stopped")

    async def _subscribe_with_retry(self) -> None:
        """Attempt to subscribe to all topics with exponential backoff.

        Retries up to _MAX_RETRY_ATTEMPTS times. If all attempts fail,
        enters degraded mode and logs an error.
        """
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                await self._subscribe_all()
                self._degraded = False
                logger.info(
                    "Successfully subscribed to all broker topics",
                    attempt=attempt,
                )
                return
            except Exception as exc:
                backoff = min(
                    _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    _MAX_BACKOFF_SECONDS,
                )
                logger.warning(
                    "Broker subscription attempt failed",
                    attempt=attempt,
                    max_attempts=_MAX_RETRY_ATTEMPTS,
                    backoff_seconds=backoff,
                    error=str(exc),
                )
                if attempt < _MAX_RETRY_ATTEMPTS:
                    await asyncio.sleep(backoff)

        # All attempts exhausted — enter degraded mode
        self._degraded = True
        logger.error(
            "Broker unavailable after all retry attempts, starting in degraded mode",
            max_attempts=_MAX_RETRY_ATTEMPTS,
        )

    async def _subscribe_all(self) -> None:
        """Subscribe to all required broker topics."""
        assert self._broker is not None

        topics = [CORRECTIONS_STATE, PREDICTIONS_STATE, ALERTS_ANOMALY, TELEMETRY_RAW]
        for topic in topics:
            await self._broker.subscribe(
                topic=topic,
                group_id=_CONSUMER_GROUP,
                callback=self._on_message,
            )

    async def _on_message(self, topic: str, key: str, message: bytes) -> None:
        """Handle an incoming broker message.

        Updates the appropriate cache and broadcasts to WebSocket clients.
        Transforms backend payload field names to match the frontend WebSocket
        protocol contract before broadcasting.

        Args:
            topic: The broker topic the message arrived on.
            key: The message key (typically sensor_id).
            message: The raw message payload bytes.
        """
        if not self._running:
            return

        try:
            payload = json.loads(message)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Failed to parse broker message",
                topic=topic,
                key=key,
                error=str(exc),
            )
            return

        # Increment Prometheus counter for processed messages (Requirement 9.5)
        messages_processed_total.labels(topic=topic).inc()

        # Update state cache for corrections
        if topic == CORRECTIONS_STATE and self._state_cache is not None:
            self._state_cache.update_from_message(key, message)

        # Update predictions cache
        if topic == PREDICTIONS_STATE:
            self._update_predictions_cache(key, payload)

        # Transform payload to match frontend WebSocket contract before broadcasting
        broadcast_payload = self._transform_payload(topic, payload)

        # Broadcast to WebSocket clients
        message_type = TOPIC_TYPE_MAP.get(topic)
        if message_type and self._ws_manager is not None:
            await self._ws_manager.broadcast(message_type, broadcast_payload)

    def _transform_payload(self, topic: str, payload: dict) -> dict:
        """Transform backend broker payload to frontend WebSocket contract.

        The backend services publish with internal field names; the frontend
        expects a specific schema per message type.
        """
        if topic == CORRECTIONS_STATE:
            # Backend: {sensor_id, correction_timestamp, corrected_state_vector, ensemble_spread, anomaly_flag}
            # Frontend expects: {sensor_id, timestamp, values, ensemble_spread, anomaly_flag}
            return {
                "sensor_id": payload.get("sensor_id", ""),
                "timestamp": payload.get("correction_timestamp", payload.get("timestamp", "")),
                "values": payload.get("corrected_state_vector", payload.get("values", [])),
                "ensemble_spread": payload.get("ensemble_spread", 0.0),
                "anomaly_flag": payload.get("anomaly_flag", False),
            }
        elif topic == PREDICTIONS_STATE:
            # Backend: {sensor_id, prediction_timestamp, prediction_horizon_seconds, values, ensemble_spread}
            # Frontend expects: {sensor_id, prediction_timestamp, state_vector, model_used, prediction_horizon_seconds}
            return {
                "sensor_id": payload.get("sensor_id", ""),
                "prediction_timestamp": payload.get("prediction_timestamp", ""),
                "state_vector": payload.get("values", []),
                "model_used": payload.get("source", "ensemble"),
                "prediction_horizon_seconds": payload.get("prediction_horizon_seconds", 0),
            }
        elif topic == ALERTS_ANOMALY:
            # Backend: {sensor_id, correction_timestamp, observed_value, predicted_value, innovation_magnitude, threshold}
            # Frontend expects: {sensor_id, timestamp, severity, description}
            innovation = payload.get("innovation_magnitude", 0.0)
            threshold = payload.get("threshold", 2.5)
            # Map severity based on how much the innovation exceeds the threshold
            if innovation > threshold * 2:
                severity = "critical"
            elif innovation > threshold * 1.5:
                severity = "warning"
            else:
                severity = "informational"
            observed = payload.get('observed_value', 'N/A')
            predicted = payload.get('predicted_value', 'N/A')
            obs_str = f"{observed:.4f}" if isinstance(observed, (int, float)) else str(observed)
            pred_str = f"{predicted:.4f}" if isinstance(predicted, (int, float)) else str(predicted)
            return {
                "sensor_id": payload.get("sensor_id", ""),
                "timestamp": payload.get("correction_timestamp", payload.get("timestamp", "")),
                "severity": severity,
                "description": (
                    f"Innovation magnitude {innovation:.3f} exceeds "
                    f"threshold {threshold:.1f} "
                    f"(observed={obs_str}, predicted={pred_str})"
                ),
            }
        # Default: pass through unchanged (telemetry.raw already matches)
        return payload

    def _update_predictions_cache(self, key: str, payload: dict) -> None:
        """Update the predictions cache from a predictions.state message.

        Populates both the local dict cache (for legacy use) and the gateway's
        Prediction-object cache (for the REST endpoint).

        Args:
            key: The message key (sensor_id).
            payload: The parsed JSON payload.
        """
        try:
            sensor_id = payload.get("sensor_id", key)
            predictions = payload.get("predictions", [])
            self._predictions_cache[sensor_id] = predictions

            # Also populate the gateway's typed predictions cache
            if self._gateway_predictions_cache is not None:
                try:
                    ts_str = payload.get("prediction_timestamp", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        ts = datetime.now(timezone.utc)

                    prediction = Prediction(
                        sensor_id=sensor_id,
                        prediction_timestamp=ts,
                        prediction_horizon_seconds=payload.get("prediction_horizon_seconds", 0),
                        state_vector=payload.get("values", payload.get("state_vector", [])),
                        model_used=payload.get("source", payload.get("model_used", "ensemble")),
                        ensemble_weights={"ensemble": 1.0},
                    )

                    # Keep last N predictions per sensor
                    if sensor_id not in self._gateway_predictions_cache:
                        self._gateway_predictions_cache[sensor_id] = []
                    cache = self._gateway_predictions_cache[sensor_id]
                    cache.append(prediction)
                    # Keep max 50 predictions per sensor
                    if len(cache) > 50:
                        self._gateway_predictions_cache[sensor_id] = cache[-50:]
                except Exception as exc:
                    logger.debug(
                        "Failed to create Prediction object for gateway cache",
                        sensor_id=sensor_id,
                        error=str(exc),
                    )

            logger.debug(
                "Predictions cache updated",
                sensor_id=sensor_id,
                prediction_count=len(predictions),
            )
        except (TypeError, AttributeError) as exc:
            logger.error(
                "Failed to update predictions cache",
                key=key,
                error=str(exc),
            )

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to the broker with exponential backoff.

        Called when the broker connection is lost during operation.
        Continues retrying until successful or the subscriber is stopped.
        """
        attempt = 0
        while self._running:
            attempt += 1
            backoff = min(
                _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                _MAX_BACKOFF_SECONDS,
            )
            logger.info(
                "Attempting broker reconnection",
                attempt=attempt,
                backoff_seconds=backoff,
            )

            try:
                await asyncio.sleep(backoff)
                if not self._running:
                    return

                await self._subscribe_all()
                self._degraded = False
                logger.info(
                    "Successfully reconnected to broker",
                    attempt=attempt,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Broker reconnection attempt failed",
                    attempt=attempt,
                    error=str(exc),
                )
                self._degraded = True

    def handle_connection_lost(self) -> None:
        """Trigger reconnection when broker connection is lost during operation.

        Enters degraded mode and spawns a background task to attempt
        reconnection with exponential backoff.
        """
        if not self._running:
            return

        self._degraded = True
        logger.warning("Broker connection lost, entering degraded mode")

        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._attempt_reconnect())
