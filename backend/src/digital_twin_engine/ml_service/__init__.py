"""ML service - LSTM + XGBoost ensemble prediction engine.

Provides batch accumulation, prediction triggering, and ensemble inference
(LSTM + XGBoost) for generating State_Vector predictions from telemetry data.
"""

from digital_twin_engine.ml_service.batch_accumulator import (
    BatchAccumulator,
    PredictionFunc,
    SensorBuffer,
)
from digital_twin_engine.ml_service.ensemble_inference import (
    EnsembleInference,
    LSTMModel,
    StubLSTMModel,
    StubXGBoostModel,
    XGBoostModel,
    create_ensemble_predict_fn,
    extract_xgboost_features,
)

__all__ = [
    "BatchAccumulator",
    "EnsembleInference",
    "LSTMModel",
    "PredictionFunc",
    "SensorBuffer",
    "StubLSTMModel",
    "StubXGBoostModel",
    "XGBoostModel",
    "create_ensemble_predict_fn",
    "extract_xgboost_features",
]
