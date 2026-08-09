"""Property-based tests for health status aggregation.

# Feature: digital-twin-telemetry-engine, Property 20: Health Status Aggregation

Tests that the compute_overall_status function correctly aggregates component
health statuses into an overall system status for all possible combinations.

**Validates: Requirements 8.2, 8.3**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from digital_twin_engine.api.health import COMPONENT_NAMES, compute_overall_status
from digital_twin_engine.shared.models import ComponentStatus


# Strategy to generate a ComponentStatus value
component_status_strategy = st.sampled_from(list(ComponentStatus))

# Strategy to generate a full dict of component statuses (5 components × 3 states)
component_statuses_strategy = st.fixed_dictionaries(
    {name: component_status_strategy for name in COMPONENT_NAMES}
)


class TestHealthStatusAggregationProperty:
    """Property 20: Health Status Aggregation.

    For any combination of component health statuses, the overall system status
    SHALL be:
    - "healthy" if all components are healthy
    - "down" if all components are down
    - "degraded" otherwise (any component degraded or down while at least one
      is still operational)

    **Validates: Requirements 8.2, 8.3**
    """

    @given(statuses=component_statuses_strategy)
    @settings(max_examples=300)
    def test_all_healthy_yields_healthy(self, statuses: dict) -> None:
        """If all statuses are HEALTHY, overall is HEALTHY."""
        all_healthy = {name: ComponentStatus.HEALTHY for name in COMPONENT_NAMES}
        result = compute_overall_status(all_healthy)
        assert result == ComponentStatus.HEALTHY

    @given(statuses=component_statuses_strategy)
    @settings(max_examples=300)
    def test_all_down_yields_down(self, statuses: dict) -> None:
        """If all statuses are DOWN, overall is DOWN."""
        all_down = {name: ComponentStatus.DOWN for name in COMPONENT_NAMES}
        result = compute_overall_status(all_down)
        assert result == ComponentStatus.DOWN

    @given(statuses=component_statuses_strategy)
    @settings(max_examples=300)
    def test_mixed_statuses_yield_degraded(self, statuses: dict) -> None:
        """If statuses are not all the same healthy or all down, overall is DEGRADED."""
        values = list(statuses.values())
        all_healthy = all(s == ComponentStatus.HEALTHY for s in values)
        all_down = all(s == ComponentStatus.DOWN for s in values)

        result = compute_overall_status(statuses)

        if all_healthy:
            assert result == ComponentStatus.HEALTHY
        elif all_down:
            assert result == ComponentStatus.DOWN
        else:
            assert result == ComponentStatus.DEGRADED

    @given(
        component_idx=st.integers(min_value=0, max_value=len(COMPONENT_NAMES) - 1)
    )
    @settings(max_examples=100)
    def test_single_degraded_among_healthy_yields_degraded(
        self, component_idx: int
    ) -> None:
        """Any single component being DEGRADED while others are HEALTHY → DEGRADED."""
        statuses = {name: ComponentStatus.HEALTHY for name in COMPONENT_NAMES}
        target_component = COMPONENT_NAMES[component_idx]
        statuses[target_component] = ComponentStatus.DEGRADED

        result = compute_overall_status(statuses)
        assert result == ComponentStatus.DEGRADED

    @given(
        component_idx=st.integers(min_value=0, max_value=len(COMPONENT_NAMES) - 1)
    )
    @settings(max_examples=100)
    def test_single_down_among_healthy_yields_degraded(
        self, component_idx: int
    ) -> None:
        """Any single component being DOWN while others are HEALTHY → DEGRADED."""
        statuses = {name: ComponentStatus.HEALTHY for name in COMPONENT_NAMES}
        target_component = COMPONENT_NAMES[component_idx]
        statuses[target_component] = ComponentStatus.DOWN

        result = compute_overall_status(statuses)
        assert result == ComponentStatus.DEGRADED
