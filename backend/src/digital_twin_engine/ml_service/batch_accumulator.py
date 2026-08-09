"""Batch accumulation and prediction trigger logic for the ML Service.

This module implements:
- An async consumer reading from the `telemetry.raw` topic
- Per-sensor event buffers with configurable min/max batch sizes
- Prediction triggering when batch reaches minimum size OR max wait time elapses
- Publishing predicted StateVector to `predictions.state` topic

Requirements: 5.1, 5.6, 5.7
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from digital_twin_engine.broker.base import BrokerBackend
from digital_twin_engine.broker.topics import PREDICTIONS_STATE, TELEMETRY_RAW
from digital_twin_engine.shared.models import (
    EngineConfig,
    StateVector,
    TelemetryEvent,
    deserialize_telemetry_event,
)


class SensorBuffer:
    """Per-sensor event buffer with timing metadata.

    Accumulates TelemetryEvents for a single sensor and tracks when
    the first event was added to enable timeout-based triggers.
    """

    def __init__(self) -> None:
        self.events: List[TelemetryEvent] = []
        self.first_event_time: Optional[float] = None

    def add(self, event: TelemetryEvent) -> None:
        """Add an event to the buffer, recording time of first event."""
        if not self.events:
            self.first_event_time = time.monotonic()
        self.events.append(event)

    def clear(self) -> None:
        """Reset the buffer, removing all events and timing data."""
        self.events.clear()
        self.first_event_time = None

    @property
    def size(self) -> int:
        """Current number of events in the buffer."""
        return len(self.events)

    @property
    def is_empty(self) -> bool:
        """True if the buffer contains no events."""
        return len(self.events) == 0

    def elapsed_since_first(self) -> float:
        """Seconds elapsed since the first event was added.

        Returns 0.0 if the buffer is empty.
        """
        if self.first_event_time is None:
            return 0.0
        return time.monotonic() - self.first_event_time

    def drain(self) -> List[TelemetryEvent]:
        """Remove and return all events from the buffer.

        Resets the buffer to empty state.
        """
        events = list(self.events)
        self.clear()
        return events


# Type for the prediction function that ML models will implement
PredictionFunc = Callable[
    [str, List[TelemetryEvent], EngineConfig],
    Coroutine[Any, Any, Optional[StateVector]],
]


class BatchAccumulator:
    """Manages per-sensor batch accumulation and prediction triggering.

    Reads from the telemetry.raw topic, accumulates events per sensor,
    and triggers predictions when:
    - The batch reaches the configured minimum batch size, OR
    - The configured max wait time elapses since the first event in the buffer

    Predictions are published to the predictions.state topic.

    Args:
        broker: The message broker backend for consuming/publishing.
        config: Engine configuration with batch size and timing parameters.
        predict_fn: Async callable that generates a StateVector from a batch.
                    Signature: (sensor_id, events, config) -> Optional[StateVector]
        consumer_group: Consumer group ID for the broker subscription.
    """

    def __init__(
        self,
        broker: BrokerBackend,
        config: EngineConfig,
        predict_fn: PredictionFunc,
        consumer_group: str = "ml_service",
    ) -> None:
        self._broker = broker
        self._config = config
        self._predict_fn = predict_fn
        self._consumer_group = consumer_group
        self._buffers: Dict[str, SensorBuffer] = {}
        self._running = False
        self._timer_task: Optional[asyncio.Task[None]] = None

    @property
    def buffers(self) -> Dict[str, SensorBuffer]:
        """Access to per-sensor buffers (for testing/inspection)."""
        return self._buffers

    @property
    def running(self) -> bool:
        """Whether the accumulator is currently running."""
        return self._running

    def _get_or_create_buffer(self, sensor_id: str) -> SensorBuffer:
        """Get the buffer for a sensor, creating one if it doesn't exist."""
        if sensor_id not in self._buffers:
            self._buffers[sensor_id] = SensorBuffer()
        return self._buffers[sensor_id]

    async def start(self) -> None:
        """Start consuming from telemetry.raw and processing batches.

        Subscribes to the broker topic and starts the timeout checker task.
        """
        self._running = True
        await self._broker.subscribe(
            TELEMETRY_RAW,
            self._consumer_group,
            self._on_message,
        )
        self._timer_task = asyncio.create_task(self._timeout_checker())

    async def stop(self) -> None:
        """Stop the accumulator, cancelling the timeout checker."""
        self._running = False
        if self._timer_task is not None:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
            self._timer_task = None

    async def _on_message(self, topic: str, key: str, message: bytes) -> None:
        """Callback for messages received from the telemetry.raw topic.

        Deserializes the event, adds it to the appropriate sensor buffer,
        and triggers prediction if the buffer reaches minimum batch size.
        """
        try:
            event = deserialize_telemetry_event(message.decode("utf-8"))
        except Exception:
            # Skip malformed messages - they should have been validated upstream
            return

        sensor_id = event.sensor_id
        buffer = self._get_or_create_buffer(sensor_id)
        buffer.add(event)

        # Trigger prediction if buffer reaches minimum batch size
        if buffer.size >= self._config.min_batch_size:
            await self._trigger_prediction(sensor_id)

    async def _timeout_checker(self) -> None:
        """Periodically check buffers for timeout-based prediction triggers.

        Runs every 0.1 seconds to check if any sensor buffer has exceeded
        the max_batch_wait_seconds since its first event was added.
        """
        try:
            while self._running:
                await asyncio.sleep(0.1)
                await self._check_timeouts()
        except asyncio.CancelledError:
            pass

    async def _check_timeouts(self) -> None:
        """Check all buffers and trigger predictions for timed-out batches."""
        max_wait = self._config.max_batch_wait_seconds
        # Iterate over a copy of keys since _trigger_prediction may modify dict
        sensor_ids = list(self._buffers.keys())
        for sensor_id in sensor_ids:
            buffer = self._buffers.get(sensor_id)
            if buffer is None or buffer.is_empty:
                continue
            if buffer.elapsed_since_first() >= max_wait:
                await self._trigger_prediction(sensor_id)

    async def _trigger_prediction(self, sensor_id: str) -> None:
        """Drain the sensor buffer and generate + publish a prediction.

        Drains up to max_batch_size events from the buffer. If the buffer
        has more events than max_batch_size, only max_batch_size events
        are consumed and the remainder stay in the buffer.

        Args:
            sensor_id: The sensor whose buffer to process.
        """
        buffer = self._buffers.get(sensor_id)
        if buffer is None or buffer.is_empty:
            return

        # Take up to max_batch_size events
        max_size = self._config.max_batch_size
        if buffer.size <= max_size:
            events = buffer.drain()
        else:
            events = buffer.events[:max_size]
            remaining = buffer.events[max_size:]
            buffer.clear()
            for evt in remaining:
                buffer.add(evt)

        # Generate prediction
        state_vector = await self._predict_fn(sensor_id, events, self._config)

        if state_vector is not None:
            await self._publish_prediction(state_vector)

    async def _publish_prediction(self, state_vector: StateVector) -> None:
        """Publish a predicted StateVector to the predictions.state topic.

        Serializes the StateVector with sensor_id, prediction_timestamp,
        and prediction_horizon, then publishes to the broker.
        """
        payload = {
            "sensor_id": state_vector.sensor_id,
            "prediction_timestamp": state_vector.timestamp.isoformat(),
            "prediction_horizon_seconds": self._config.prediction_horizon_seconds,
            "values": state_vector.values,
            "ensemble_spread": state_vector.ensemble_spread,
            "anomaly_flag": state_vector.anomaly_flag,
            "source": state_vector.source,
        }
        message = json.dumps(payload).encode("utf-8")
        await self._broker.publish(
            PREDICTIONS_STATE,
            state_vector.sensor_id,
            message,
        )
