"""In-memory cache of latest corrected states per sensor.

Maintains the most recent corrected StateVector for each sensor_id,
updated from the corrections.state broker topic. This cache enables
sub-100ms responses for the /sensors/{sensor_id}/state/current endpoint.

Requirements: 7.1, 7.4, 7.5
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel

from digital_twin_engine.shared.logging import get_logger
from digital_twin_engine.shared.models import StateVector

logger = get_logger("api_state_cache")


class CachedState(BaseModel):
    """Cached corrected state for a single sensor."""

    sensor_id: str
    timestamp: datetime
    state_vector: List[float]
    ensemble_spread: float
    anomaly_flag: bool


class StateCache:
    """Thread-safe in-memory cache of latest corrected states per sensor.

    The cache is updated by consuming messages from the corrections.state
    broker topic. Each sensor_id maps to its most recent corrected state.
    """

    def __init__(self) -> None:
        self._states: Dict[str, CachedState] = {}
        self._known_sensors: set[str] = set()

    @property
    def known_sensors(self) -> set[str]:
        """Set of all sensor IDs that have ever been seen."""
        return set(self._known_sensors)

    def register_sensor(self, sensor_id: str) -> None:
        """Register a sensor as known (even if no state has been received yet)."""
        self._known_sensors.add(sensor_id)

    def is_known_sensor(self, sensor_id: str) -> bool:
        """Check if a sensor_id has been registered."""
        return sensor_id in self._known_sensors

    def update(self, state: CachedState) -> None:
        """Update the cache with a new corrected state.

        Only updates if the new state is more recent than the cached one.
        """
        self._known_sensors.add(state.sensor_id)
        existing = self._states.get(state.sensor_id)
        if existing is None or state.timestamp >= existing.timestamp:
            self._states[state.sensor_id] = state
            logger.debug(
                "Cache updated",
                sensor_id=state.sensor_id,
                timestamp=state.timestamp.isoformat(),
            )

    def get_current(self, sensor_id: str) -> Optional[CachedState]:
        """Get the latest corrected state for a sensor.

        Returns None if no corrected state has been received for this sensor.
        """
        return self._states.get(sensor_id)

    def update_from_message(self, key: str, payload: bytes) -> None:
        """Update cache from a corrections.state broker message.

        Parses the JSON payload and updates the cache.

        Args:
            key: The sensor_id (partition key).
            payload: JSON-encoded corrected state message.
        """
        try:
            data = json.loads(payload)
            state = CachedState(
                sensor_id=data["sensor_id"],
                timestamp=datetime.fromisoformat(
                    data["correction_timestamp"].replace("Z", "+00:00")
                ),
                state_vector=data["corrected_state_vector"],
                ensemble_spread=data.get("ensemble_spread", 0.0),
                anomaly_flag=data.get("anomaly_flag", False),
            )
            self.update(state)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error(
                "Failed to parse corrections.state message",
                error=str(exc),
                key=key,
            )

    def clear(self) -> None:
        """Clear all cached states."""
        self._states.clear()
        self._known_sensors.clear()
