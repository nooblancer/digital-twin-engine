"""Message broker topic definitions for the Digital Twin Telemetry Engine.

All pipeline topics are defined here for consistency across components.
"""

# Validated Telemetry_Events from Ingestion_Server (partitioned by sensor_id)
TELEMETRY_RAW = "telemetry.raw"

# Predicted State_Vectors from ML_Service
PREDICTIONS_STATE = "predictions.state"

# Corrected State_Vectors from Correction_Engine
CORRECTIONS_STATE = "corrections.state"

# Anomaly detection events from Correction_Engine
ALERTS_ANOMALY = "alerts.anomaly"

# Pipeline metrics from all components
METRICS_PIPELINE = "metrics.pipeline"

# All topics as a tuple for iteration
ALL_TOPICS = (
    TELEMETRY_RAW,
    PREDICTIONS_STATE,
    CORRECTIONS_STATE,
    ALERTS_ANOMALY,
    METRICS_PIPELINE,
)
