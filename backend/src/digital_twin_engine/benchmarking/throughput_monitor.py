"""Throughput Monitor — tracks processing rates as rolling 10-second averages.

Uses the same deque-based sliding window approach as simulator._RateTracker,
recording timestamps for events, predictions, and corrections and computing
rates by evicting old entries beyond the window.

Requirements: 4.3, 4.4, 4.6
"""

from dataclasses import dataclass
from collections import deque
import time


@dataclass
class ThroughputMetrics:
    """Current throughput rates as rolling averages."""

    events_per_second: float
    predictions_per_second: float
    corrections_per_second: float


class ThroughputMonitor:
    """Tracks processing rates as rolling 10-second averages.

    Uses the same deque-based window approach as simulator._RateTracker.
    Each call to record_*() appends the current timestamp to the relevant
    deque. On get_metrics(), old entries are evicted and rates computed
    as count_in_window / WINDOW_SECONDS.
    """

    WINDOW_SECONDS: float = 10.0

    def __init__(self) -> None:
        self._events: deque[float] = deque()
        self._predictions: deque[float] = deque()
        self._corrections: deque[float] = deque()

    def record_event(self) -> None:
        """Record a sensor event ingestion."""
        self._events.append(time.time())

    def record_prediction(self) -> None:
        """Record a prediction generation."""
        self._predictions.append(time.time())

    def record_correction(self) -> None:
        """Record an EnKF correction application."""
        self._corrections.append(time.time())

    def get_metrics(self) -> ThroughputMetrics:
        """Compute current rates from rolling windows."""
        now = time.time()
        return ThroughputMetrics(
            events_per_second=self._compute_rate(self._events, now),
            predictions_per_second=self._compute_rate(self._predictions, now),
            corrections_per_second=self._compute_rate(self._corrections, now),
        )

    def _compute_rate(self, timestamps: deque, now: float) -> float:
        """Evict old entries and compute events/sec.

        Removes all timestamps older than (now - WINDOW_SECONDS) from the
        left side of the deque, then returns the count of remaining
        timestamps divided by the window duration.
        """
        cutoff = now - self.WINDOW_SECONDS
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if not timestamps:
            return 0.0
        return len(timestamps) / self.WINDOW_SECONDS
