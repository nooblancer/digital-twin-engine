"""Unit tests for the RootCauseAnalyzer class.

Tests cover:
- record_innovation: history accumulation, rolling window enforcement
- analyze_anomaly: sigma deviation computation, sorting, edge cases
- get_latest_analysis: returns inactive when no anomaly, returns latest when present

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
"""

from __future__ import annotations

import numpy as np
import pytest

from digital_twin_engine.alerting.root_cause import (
    AnomalyAnalysis,
    RootCauseAnalyzer,
    SensorContribution,
)


class TestRecordInnovation:
    """Tests for RootCauseAnalyzer.record_innovation()."""

    def test_records_single_observation(self):
        """Recording one innovation creates history entry for the sensor."""
        analyzer = RootCauseAnalyzer()
        analyzer.record_innovation(1, "hpc_outlet_temp_total", 3.5)

        # Verify history was recorded
        assert 1 in analyzer._history
        assert "hpc_outlet_temp_total" in analyzer._history[1]
        assert list(analyzer._history[1]["hpc_outlet_temp_total"]) == [3.5]

    def test_records_multiple_sensors_same_engine(self):
        """Multiple sensors on the same engine maintain separate histories."""
        analyzer = RootCauseAnalyzer()
        analyzer.record_innovation(1, "sensor_a", 1.0)
        analyzer.record_innovation(1, "sensor_b", 2.0)

        assert len(analyzer._history[1]) == 2
        assert list(analyzer._history[1]["sensor_a"]) == [1.0]
        assert list(analyzer._history[1]["sensor_b"]) == [2.0]

    def test_records_multiple_engines(self):
        """Different engines maintain separate history dictionaries."""
        analyzer = RootCauseAnalyzer()
        analyzer.record_innovation(1, "sensor_a", 1.0)
        analyzer.record_innovation(2, "sensor_a", 5.0)

        assert list(analyzer._history[1]["sensor_a"]) == [1.0]
        assert list(analyzer._history[2]["sensor_a"]) == [5.0]

    def test_rolling_window_enforced(self):
        """History is bounded by HISTORY_SIZE (200) using a deque."""
        analyzer = RootCauseAnalyzer()
        for i in range(250):
            analyzer.record_innovation(1, "sensor_a", float(i))

        history = analyzer._history[1]["sensor_a"]
        assert len(history) == RootCauseAnalyzer.HISTORY_SIZE
        # Oldest entries should be evicted; newest should be present
        assert history[-1] == 249.0
        assert history[0] == 50.0  # 250 - 200 = 50

    def test_appends_to_existing_history(self):
        """Subsequent calls append to the existing history deque."""
        analyzer = RootCauseAnalyzer()
        analyzer.record_innovation(1, "sensor_a", 1.0)
        analyzer.record_innovation(1, "sensor_a", 2.0)
        analyzer.record_innovation(1, "sensor_a", 3.0)

        assert list(analyzer._history[1]["sensor_a"]) == [1.0, 2.0, 3.0]


class TestAnalyzeAnomaly:
    """Tests for RootCauseAnalyzer.analyze_anomaly()."""

    def test_returns_anomaly_analysis_with_active_true(self):
        """analyze_anomaly returns AnomalyAnalysis with anomaly_active=True."""
        analyzer = RootCauseAnalyzer()
        # Build some history
        for i in range(10):
            analyzer.record_innovation(1, "sensor_a", 1.0 + i * 0.1)

        result = analyzer.analyze_anomaly(1, {"sensor_a": 5.0})

        assert isinstance(result, AnomalyAnalysis)
        assert result.engine_id == 1
        assert result.anomaly_active is True
        assert result.timestamp is not None

    def test_contributions_sorted_by_sigma_deviation_descending(self):
        """Contributions are sorted by sigma_deviation in descending order (Req 1.1)."""
        analyzer = RootCauseAnalyzer()
        # Build history with different std deviations
        for i in range(20):
            analyzer.record_innovation(1, "low_deviation", 1.0 + i * 0.01)
            analyzer.record_innovation(1, "high_deviation", 1.0 + i * 0.5)

        # High innovation for low-std sensor → high sigma
        # Low innovation for high-std sensor → low sigma
        result = analyzer.analyze_anomaly(
            1, {"low_deviation": 10.0, "high_deviation": 3.0}
        )

        sigmas = [c.sigma_deviation for c in result.contributions]
        assert sigmas == sorted(sigmas, reverse=True)
        # low_deviation sensor should rank higher (higher sigma_deviation)
        assert result.contributions[0].sensor_name == "low_deviation"

    def test_sigma_deviation_formula(self):
        """sigma_deviation = innovation_magnitude / std(history) (Req 1.5)."""
        analyzer = RootCauseAnalyzer()
        # Known history with known std
        history_values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for val in history_values:
            analyzer.record_innovation(1, "sensor_a", val)

        innovation = 10.0
        result = analyzer.analyze_anomaly(1, {"sensor_a": innovation})

        expected_std = float(np.std(history_values))
        expected_sigma = innovation / expected_std

        assert len(result.contributions) == 1
        assert result.contributions[0].innovation_magnitude == innovation
        assert result.contributions[0].sigma_deviation == pytest.approx(
            expected_sigma, rel=1e-6
        )

    def test_zero_std_returns_zero_sigma(self):
        """When history has std=0 (constant values), sigma_deviation is 0.0."""
        analyzer = RootCauseAnalyzer()
        # All same value → std = 0
        for _ in range(10):
            analyzer.record_innovation(1, "constant_sensor", 5.0)

        result = analyzer.analyze_anomaly(1, {"constant_sensor": 10.0})

        assert result.contributions[0].sigma_deviation == 0.0
        assert result.contributions[0].innovation_magnitude == 10.0

    def test_no_history_returns_zero_sigma(self):
        """Sensor with no recorded history gets sigma_deviation=0.0."""
        analyzer = RootCauseAnalyzer()
        # Don't record any history for the sensor
        result = analyzer.analyze_anomaly(1, {"unknown_sensor": 7.0})

        assert len(result.contributions) == 1
        assert result.contributions[0].sensor_name == "unknown_sensor"
        assert result.contributions[0].sigma_deviation == 0.0
        assert result.contributions[0].innovation_magnitude == 7.0

    def test_multiple_sensors_ranked_correctly(self):
        """Multiple sensors are ranked by sigma_deviation descending."""
        analyzer = RootCauseAnalyzer()
        # Sensor A: low std (tight history around 1.0)
        for i in range(20):
            analyzer.record_innovation(1, "sensor_a", 1.0 + i * 0.01)
        # Sensor B: high std (wide history)
        for i in range(20):
            analyzer.record_innovation(1, "sensor_b", 1.0 + i * 1.0)
        # Sensor C: medium std
        for i in range(20):
            analyzer.record_innovation(1, "sensor_c", 1.0 + i * 0.1)

        # Same innovation magnitude for all → sensor_a should rank highest (lowest std)
        result = analyzer.analyze_anomaly(
            1, {"sensor_a": 5.0, "sensor_b": 5.0, "sensor_c": 5.0}
        )

        assert len(result.contributions) == 3
        assert result.contributions[0].sensor_name == "sensor_a"
        assert result.contributions[2].sensor_name == "sensor_b"

    def test_stores_as_latest_analysis(self):
        """analyze_anomaly stores result as latest analysis for the engine."""
        analyzer = RootCauseAnalyzer()
        for i in range(5):
            analyzer.record_innovation(1, "s1", float(i))

        result = analyzer.analyze_anomaly(1, {"s1": 10.0})
        latest = analyzer.get_latest_analysis(1)

        assert latest is result
        assert latest.anomaly_active is True

    def test_overwrites_previous_analysis(self):
        """A new anomaly analysis overwrites the previous one for the same engine."""
        analyzer = RootCauseAnalyzer()
        for i in range(10):
            analyzer.record_innovation(1, "s1", float(i))

        analyzer.analyze_anomaly(1, {"s1": 5.0})
        second = analyzer.analyze_anomaly(1, {"s1": 20.0})

        latest = analyzer.get_latest_analysis(1)
        assert latest is second
        assert latest.contributions[0].innovation_magnitude == 20.0

    def test_different_engines_independent_analyses(self):
        """Analyses for different engines are stored independently."""
        analyzer = RootCauseAnalyzer()
        for i in range(10):
            analyzer.record_innovation(1, "s1", float(i))
            analyzer.record_innovation(2, "s1", float(i) * 2)

        analyzer.analyze_anomaly(1, {"s1": 5.0})
        analyzer.analyze_anomaly(2, {"s1": 50.0})

        analysis_1 = analyzer.get_latest_analysis(1)
        analysis_2 = analyzer.get_latest_analysis(2)

        assert analysis_1.engine_id == 1
        assert analysis_2.engine_id == 2
        assert analysis_1.contributions[0].innovation_magnitude == 5.0
        assert analysis_2.contributions[0].innovation_magnitude == 50.0


class TestGetLatestAnalysis:
    """Tests for RootCauseAnalyzer.get_latest_analysis()."""

    def test_no_anomaly_recorded_returns_inactive(self):
        """Returns anomaly_active=False when no anomaly has been analyzed (Req 1.3)."""
        analyzer = RootCauseAnalyzer()
        result = analyzer.get_latest_analysis(1)

        assert isinstance(result, AnomalyAnalysis)
        assert result.engine_id == 1
        assert result.anomaly_active is False
        assert result.timestamp is None
        assert result.contributions == []

    def test_returns_latest_after_anomaly(self):
        """Returns the stored analysis after analyze_anomaly was called."""
        analyzer = RootCauseAnalyzer()
        for i in range(10):
            analyzer.record_innovation(1, "s1", float(i))

        analyzer.analyze_anomaly(1, {"s1": 8.0})
        result = analyzer.get_latest_analysis(1)

        assert result.anomaly_active is True
        assert result.engine_id == 1
        assert len(result.contributions) == 1
        assert result.contributions[0].sensor_name == "s1"

    def test_unknown_engine_returns_inactive(self):
        """An engine with no history and no analysis returns inactive."""
        analyzer = RootCauseAnalyzer()
        # Record data for engine 1 only
        for i in range(5):
            analyzer.record_innovation(1, "s1", float(i))
        analyzer.analyze_anomaly(1, {"s1": 5.0})

        # Engine 99 has never been seen
        result = analyzer.get_latest_analysis(99)
        assert result.anomaly_active is False
        assert result.engine_id == 99
        assert result.contributions == []

    def test_timestamp_is_iso_format(self):
        """The timestamp on an active analysis is ISO 8601 formatted."""
        analyzer = RootCauseAnalyzer()
        for i in range(5):
            analyzer.record_innovation(1, "s1", float(i))

        analyzer.analyze_anomaly(1, {"s1": 5.0})
        result = analyzer.get_latest_analysis(1)

        # ISO 8601 format check — should contain 'T' and timezone info
        assert "T" in result.timestamp
        assert "+" in result.timestamp or "Z" in result.timestamp or result.timestamp.endswith("+00:00")
