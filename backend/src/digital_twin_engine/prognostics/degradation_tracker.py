"""Degradation Curve Tracker for engine health trajectory monitoring.

Stores health index history per engine unit and computes degradation rate
using linear least-squares regression over the most recent 20 cycles.
Emits accelerated degradation events when rate exceeds threshold.
Broadcasts degradation_update messages via WebSocket on every record.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from digital_twin_engine.prognostics.models import DegradationPoint
from digital_twin_engine.shared.logging import get_logger

if TYPE_CHECKING:
    from digital_twin_engine.api.websocket_manager import WebSocketBroadcastManager

logger = get_logger("degradation_tracker")

# Minimum number of stored cycles required to compute degradation rate
MIN_CYCLES_FOR_RATE = 20

# Degradation rate threshold for accelerated degradation event (HI units/cycle)
ACCELERATED_DEGRADATION_THRESHOLD = 0.02


class DegradationCurveTracker:
    """Tracks engine health index trajectories and computes degradation rates.

    Maintains an in-memory dictionary mapping engine IDs to their
    (cycle, health_index) history. Computes linear least-squares slope
    over the last 20 cycles to determine degradation rate.

    Storage is sufficient for C-MAPSS data: max 400 cycles × 100 engines
    ≈ 40,000 data points.
    """

    def __init__(self, ws_manager: Optional[WebSocketBroadcastManager] = None) -> None:
        """Initialize the tracker.

        Args:
            ws_manager: Optional WebSocket manager for broadcasting
                degradation_update messages to connected clients.
        """
        self._trajectories: Dict[int, List[DegradationPoint]] = {}
        self._ws_manager = ws_manager

    def record(self, engine_id: int, cycle: int, health_index: float) -> None:
        """Store a health index data point for an engine.

        The data point is appended to the engine's trajectory. After recording,
        if the engine has at least 20 cycles, the degradation rate is computed
        and an accelerated degradation event is emitted if the rate exceeds
        the threshold.

        Args:
            engine_id: The engine unit identifier.
            cycle: The operational cycle number.
            health_index: The health index value at this cycle (0.0 to 1.0).
        """
        if engine_id not in self._trajectories:
            self._trajectories[engine_id] = []

        point = DegradationPoint(cycle=cycle, health_index=health_index)
        self._trajectories[engine_id].append(point)

        # Sort by cycle to maintain ordering invariant
        self._trajectories[engine_id].sort(key=lambda p: p.cycle)

        # Compute degradation rate and check threshold.
        # The slope is negative when health declines. The "degradation rate"
        # in the requirements refers to how fast health is lost, so we check
        # if the absolute decline rate exceeds the threshold (slope < -threshold).
        rate = self.compute_degradation_rate(engine_id)

        # Broadcast degradation_update on every record (Requirements 8.3)
        self._broadcast_degradation_update(engine_id, rate, cycle)

        if rate is not None and (-rate) > ACCELERATED_DEGRADATION_THRESHOLD:
            logger.warning(
                "Accelerated degradation detected",
                engine_id=engine_id,
                degradation_rate=rate,
                cycle=cycle,
            )

    async def record_async(self, engine_id: int, cycle: int, health_index: float) -> None:
        """Async version of record that properly awaits WebSocket broadcast.

        Stores a health index data point, computes degradation rate, and
        broadcasts via WebSocket using async/await.

        Args:
            engine_id: The engine unit identifier.
            cycle: The operational cycle number.
            health_index: The health index value at this cycle (0.0 to 1.0).
        """
        if engine_id not in self._trajectories:
            self._trajectories[engine_id] = []

        point = DegradationPoint(cycle=cycle, health_index=health_index)
        self._trajectories[engine_id].append(point)

        # Sort by cycle to maintain ordering invariant
        self._trajectories[engine_id].sort(key=lambda p: p.cycle)

        # Compute degradation rate
        rate = self.compute_degradation_rate(engine_id)

        # Broadcast degradation_update via WebSocket (Requirements 8.3)
        await self._broadcast_degradation_update_async(engine_id, rate, cycle)

        if rate is not None and (-rate) > ACCELERATED_DEGRADATION_THRESHOLD:
            logger.warning(
                "Accelerated degradation detected",
                engine_id=engine_id,
                degradation_rate=rate,
                cycle=cycle,
            )

    def get_trajectory(self, engine_id: int) -> List[Tuple[int, float]]:
        """Return the full trajectory as (cycle, health_index) pairs sorted by cycle.

        Args:
            engine_id: The engine unit identifier.

        Returns:
            Ordered list of (cycle, health_index) tuples. Returns empty list
            if no data exists for the engine.
        """
        if engine_id not in self._trajectories:
            return []

        return [(p.cycle, p.health_index) for p in self._trajectories[engine_id]]

    def compute_degradation_rate(self, engine_id: int) -> Optional[float]:
        """Compute the degradation rate as linear least-squares slope.

        Uses the most recent 20 data points to fit a line and returns the
        slope of health index vs cycle. A negative slope indicates health
        is declining (engine is degrading). The raw slope is returned so
        that the caller can interpret the sign:
        - Negative slope = health declining (degradation)
        - Positive slope = health improving

        The accelerated degradation threshold check uses the negated slope
        (i.e., triggers when health declines faster than 0.02 HI units/cycle).

        Args:
            engine_id: The engine unit identifier.

        Returns:
            The slope of the linear fit over the last 20 cycles, or None
            if fewer than 20 cycles are stored for this engine.
        """
        if engine_id not in self._trajectories:
            return None

        points = self._trajectories[engine_id]
        if len(points) < MIN_CYCLES_FOR_RATE:
            return None

        # Take the last 20 points
        recent = points[-MIN_CYCLES_FOR_RATE:]

        # Linear least-squares regression: slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
        n = len(recent)
        sum_x = 0.0
        sum_y = 0.0
        sum_xy = 0.0
        sum_x2 = 0.0

        for point in recent:
            x = float(point.cycle)
            y = point.health_index
            sum_x += x
            sum_y += y
            sum_xy += x * y
            sum_x2 += x * x

        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0.0:
            # All x values are the same; slope is undefined
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope

    def _broadcast_degradation_update(
        self, engine_id: int, rate: Optional[float], cycle: int
    ) -> None:
        """Broadcast a degradation_update message via WebSocket.

        Publishes the current degradation rate (or null if < 20 cycles)
        for the given engine. Uses fire-and-forget async scheduling when
        called from synchronous context.

        The payload matches the DegradationUpdatePayload schema:
            {engine_id, degradation_rate, cycle_number}

        Args:
            engine_id: The engine unit identifier.
            rate: The computed degradation rate, or None if < 20 cycles.
            cycle: The cycle number at which this update was computed.
        """
        if self._ws_manager is None:
            return

        import asyncio

        payload = {
            "engine_id": engine_id,
            "degradation_rate": rate,
            "cycle_number": cycle,
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(
                    self._ws_manager.broadcast("degradation_update", payload)
                )
            else:
                loop.run_until_complete(
                    self._ws_manager.broadcast("degradation_update", payload)
                )
        except RuntimeError:
            # No event loop available; log and continue
            logger.debug(
                "No event loop available for degradation broadcast",
                engine_id=engine_id,
            )

    async def _broadcast_degradation_update_async(
        self, engine_id: int, rate: Optional[float], cycle: int
    ) -> None:
        """Async broadcast of degradation_update message via WebSocket.

        Properly awaits the WebSocket broadcast. Use this from async contexts.

        The payload matches the DegradationUpdatePayload schema:
            {engine_id, degradation_rate, cycle_number}

        Args:
            engine_id: The engine unit identifier.
            rate: The computed degradation rate, or None if < 20 cycles.
            cycle: The cycle number at which this update was computed.
        """
        if self._ws_manager is None:
            return

        payload = {
            "engine_id": engine_id,
            "degradation_rate": rate,
            "cycle_number": cycle,
        }
        await self._ws_manager.broadcast("degradation_update", payload)
