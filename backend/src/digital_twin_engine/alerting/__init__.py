"""Alerting package for digital twin engine intelligent diagnostics.

Provides anomaly root cause analysis and predictive maintenance alerting.
Modules:
    - root_cause: Ranks contributing sensors by innovation magnitude on anomaly events.
    - predictive_alerts: Generates severity-classified maintenance recommendations
      using MonteCarloProjector forward projection.
"""

from digital_twin_engine.alerting.predictive_alerts import (
    AlertSeverity,
    MaintenanceRecommendation,
    PredictiveAlertSystem,
)
from digital_twin_engine.alerting.root_cause import (
    AnomalyAnalysis,
    RootCauseAnalyzer,
    SensorContribution,
)

__all__: list[str] = [
    "AlertSeverity",
    "AnomalyAnalysis",
    "MaintenanceRecommendation",
    "PredictiveAlertSystem",
    "RootCauseAnalyzer",
    "SensorContribution",
]
