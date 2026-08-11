"""Failure Probability Cache — background task for precomputing projections.

Periodically recomputes failure probability curves for all active engines
using MonteCarloProjector and caches the results. The GET endpoint
/engines/{id}/failure-probability reads from this cache to respond instantly
without blocking on Monte Carlo computation.

Background loop interval: 30 seconds.
Skips engines that raise ValueError (insufficient data / < 20 cycles).

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from digital_twin_engine.shared.logging import get_logger

if TYPE_CHECKING:
    from digital_twin_engine.prognostics.degradation_tracker import (
        DegradationCurveTracker,
    )
    from digital_twin_engine.prognostics.health_index import HealthIndexAggregator
    from digital_twin_engine.simulation.monte_carlo_projector import (
        MonteCarloProjector,
    )

logger = get_logger("failure_prob_cache")

# Recomputation interval in seconds
RECOMPUTE_INTERVAL_SECONDS = 30


@dataclass
class CachedFailureProbability:
    """A cached failure probability result for one engine.

    Attributes:
        engine_id: The engine unit identifier.
        failure_probability_by_cycle: Per-cycle cumulative failure probability.
        expected_rul: Median RUL from Monte Carlo crossing distribution, or None.
        confidence_interval_90: (5th percentile RUL, 95th percentile RUL), or None.
        computed_at: ISO timestamp of when this projection was computed.
    """

    engine_id: int
    failure_probability_by_cycle: List[float]
    expected_rul: Optional[int]
    confidence_interval_90: Optional[Tuple[int, int]]
    computed_at: str  # ISO 8601 timestamp


class FailureProbabilityCache:
    """Background cache that precomputes failure probability for all active engines.

    Runs an asyncio background loop every 30 seconds that iterates over all
    engines tracked by the HealthIndexAggregator, runs MonteCarloProjector.project()
    for each, and stores the result. Engines that raise ValueError (insufficient
    data, < 20 cycles in DegradationCurveTracker) are silently skipped.

    The API router reads from the `.cache` property to serve GET requests
    instantly without triggering new computations.

    Usage:
        cache = FailureProbabilityCache(projector, health_aggregator, degradation_tracker)
        await cache.start()   # call during app startup
        ...
        await cache.stop()    # call during app shutdown
    """

    def __init__(
        self,
        projector: MonteCarloProjector,
        health_index_aggregator: HealthIndexAggregator,
        degradation_tracker: DegradationCurveTracker,
    ) -> None:
        """Initialize the cache.

        Args:
            projector: MonteCarloProjector instance for running projections.
            health_index_aggregator: Provides set of active engines (those with
                health states) via internal _health_states dict.
            degradation_tracker: Provides active engine IDs via internal
                _trajectories dict.
        """
        self._projector = projector
        self._health_aggregator = health_index_aggregator
        self._degradation_tracker = degradation_tracker
        self._cache: Dict[int, CachedFailureProbability] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def cache(self) -> Dict[int, CachedFailureProbability]:
        """Expose the cached results for the API router to read.

        Returns:
            Dict mapping engine_id to CachedFailureProbability.
        """
        return self._cache

    def get(self, engine_id: int) -> Optional[Dict[str, Any]]:
        """Get cached failure probability for a specific engine as a dict.

        Returns a dict with keys matching the API response schema, or None
        if no cached data exists for the engine.

        Args:
            engine_id: The engine to look up.

        Returns:
            Dict with failure_probability_by_cycle, expected_rul,
            confidence_interval_90, and computed_at — or None.
        """
        entry = self._cache.get(engine_id)
        if entry is None:
            return None
        return {
            "failure_probability_by_cycle": entry.failure_probability_by_cycle,
            "expected_rul": entry.expected_rul,
            "confidence_interval_90": entry.confidence_interval_90,
            "computed_at": entry.computed_at,
        }

    async def start(self) -> None:
        """Start the background recomputation loop.

        Creates an asyncio task that runs _recompute_loop() indefinitely
        until stop() is called. Safe to call multiple times (no-op if
        already running).
        """
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._recompute_loop())
        logger.info(
            "FailureProbabilityCache started",
            interval_seconds=RECOMPUTE_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Stop the background recomputation loop.

        Cancels the asyncio task and waits for it to finish.
        Safe to call multiple times (no-op if not running).
        """
        if not self._running:
            return

        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("FailureProbabilityCache stopped")

    def compute_for_engine(self, engine_id: int) -> Optional[CachedFailureProbability]:
        """Compute and cache failure probability for a single engine.

        Runs MonteCarloProjector.project() synchronously for the given engine
        and stores the result in the cache. Returns the cached entry, or None
        if the engine raises ValueError (insufficient data).

        This method can be called on-demand (e.g., when an engine first receives
        correction data) in addition to the periodic background loop.

        Args:
            engine_id: The engine to compute failure probability for.

        Returns:
            CachedFailureProbability if successful, None if insufficient data.
        """
        try:
            result = self._projector.project(engine_id=engine_id)
        except ValueError as exc:
            logger.debug(
                "Skipping engine — insufficient data",
                engine_id=engine_id,
                reason=str(exc),
            )
            return None

        computed_at = datetime.now(timezone.utc).isoformat()

        entry = CachedFailureProbability(
            engine_id=engine_id,
            failure_probability_by_cycle=result.failure_probability_by_cycle,
            expected_rul=result.expected_rul,
            confidence_interval_90=result.confidence_interval_90,
            computed_at=computed_at,
        )
        self._cache[engine_id] = entry

        logger.debug(
            "Cached failure probability",
            engine_id=engine_id,
            expected_rul=result.expected_rul,
            computed_at=computed_at,
        )
        return entry

    async def _recompute_loop(self) -> None:
        """Background loop that recomputes failure probabilities every 30s.

        Iterates over all engines known to the HealthIndexAggregator,
        calls compute_for_engine() for each, and sleeps for the configured
        interval. Engines that raise ValueError are skipped silently.
        """
        while self._running:
            try:
                await self._recompute_all()
            except Exception as exc:
                logger.error(
                    "Error in failure probability recomputation loop",
                    error=str(exc),
                )

            try:
                await asyncio.sleep(RECOMPUTE_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _recompute_all(self) -> None:
        """Recompute failure probability for all active engines.

        Gets the set of active engines from HealthIndexAggregator's internal
        _health_states dict. For each engine, runs the projection in a thread
        pool to avoid blocking the event loop (since MonteCarloProjector uses
        NumPy which can take up to ~50ms per engine).
        """
        # Get all engine IDs that have health state data
        active_engine_ids = list(self._health_aggregator._health_states.keys())

        if not active_engine_ids:
            return

        loop = asyncio.get_event_loop()

        for engine_id in active_engine_ids:
            if not self._running:
                break

            # Run projection in thread pool to avoid blocking event loop
            await loop.run_in_executor(None, self.compute_for_engine, engine_id)

        logger.debug(
            "Recomputation cycle complete",
            engines_processed=len(active_engine_ids),
            engines_cached=len(self._cache),
        )
