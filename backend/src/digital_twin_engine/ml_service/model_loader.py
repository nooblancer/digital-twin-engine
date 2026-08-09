"""Model loader for the ML Service.

Loads pre-trained LSTM (.pt) and XGBoost (.joblib) models from disk.
Falls back to stub models if files are missing or corrupted.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

import joblib

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

from digital_twin_engine.ml_service.ensemble_inference import (
    LSTMModel,
    StubLSTMModel,
    StubXGBoostModel,
    XGBoostModel,
)
from digital_twin_engine.shared.logging import get_logger

logger = get_logger("model_loader")

DEFAULT_MODEL_DIR = "./models/"
LSTM_FILENAME = "lstm_model.pt"
XGBOOST_FILENAME = "xgb_model.joblib"


class ModelLoader:
    """Loads pre-trained LSTM (.pt) and XGBoost (.joblib) models from disk.

    Reads the MODEL_DIR environment variable to determine the directory
    where model files are stored. Falls back to stub models when files
    are missing or corrupted.
    """

    def __init__(self, model_dir: Optional[Path] = None) -> None:
        """Initialize the model loader.

        Args:
            model_dir: Path to the model directory. If None, reads from
                       the MODEL_DIR environment variable (default: ./models/).
        """
        if model_dir is not None:
            self._model_dir = model_dir
        else:
            self._model_dir = Path(os.environ.get("MODEL_DIR", DEFAULT_MODEL_DIR))

    @property
    def model_dir(self) -> Path:
        """The directory from which models are loaded."""
        return self._model_dir

    def load_lstm(self, path: Optional[Path] = None) -> Optional[LSTMModel]:
        """Attempt to load an LSTM model from a .pt file.

        Args:
            path: Path to the .pt file. If None, uses model_dir / lstm_model.pt.

        Returns:
            The loaded LSTMModel instance, or None on failure.
        """
        if path is None:
            path = self._model_dir / LSTM_FILENAME

        if not _TORCH_AVAILABLE:
            logger.warning(
                "PyTorch is not installed; cannot load LSTM model",
                path=str(path),
            )
            return None

        if not path.exists():
            logger.warning(
                "LSTM model file not found; predictions will use stub model",
                path=str(path),
            )
            return None

        try:
            model = torch.load(path, map_location="cpu", weights_only=False)
            if not isinstance(model, LSTMModel):
                logger.error(
                    "Loaded LSTM file does not conform to LSTMModel interface",
                    path=str(path),
                    loaded_type=type(model).__name__,
                )
                return None
            logger.info("LSTM model loaded successfully", path=str(path))
            return model
        except Exception as exc:
            logger.error(
                "Failed to load LSTM model; file may be corrupted or incompatible",
                path=str(path),
                error=str(exc),
            )
            return None

    def load_xgboost(self, path: Optional[Path] = None) -> Optional[XGBoostModel]:
        """Attempt to load an XGBoost model from a .joblib file.

        Args:
            path: Path to the .joblib file. If None, uses model_dir / xgb_model.joblib.

        Returns:
            The loaded XGBoostModel instance, or None on failure.
        """
        if path is None:
            path = self._model_dir / XGBOOST_FILENAME

        if not path.exists():
            logger.warning(
                "XGBoost model file not found; predictions will use stub model",
                path=str(path),
            )
            return None

        try:
            model = joblib.load(path)
            if not isinstance(model, XGBoostModel):
                logger.error(
                    "Loaded XGBoost file does not conform to XGBoostModel interface",
                    path=str(path),
                    loaded_type=type(model).__name__,
                )
                return None
            logger.info("XGBoost model loaded successfully", path=str(path))
            return model
        except Exception as exc:
            logger.error(
                "Failed to load XGBoost model; file may be corrupted or incompatible",
                path=str(path),
                error=str(exc),
            )
            return None

    def load_all(self, model_dir: Optional[Path] = None) -> Tuple[LSTMModel, XGBoostModel]:
        """Load both LSTM and XGBoost models, falling back to stubs on failure.

        Args:
            model_dir: Directory containing model files. If None, uses the
                       instance's model_dir.

        Returns:
            A tuple of (LSTMModel, XGBoostModel). Each entry is either the
            loaded pre-trained model or a stub fallback.
        """
        if model_dir is not None:
            lstm_path = model_dir / LSTM_FILENAME
            xgb_path = model_dir / XGBOOST_FILENAME
        else:
            lstm_path = self._model_dir / LSTM_FILENAME
            xgb_path = self._model_dir / XGBOOST_FILENAME

        lstm_model = self.load_lstm(lstm_path)
        xgb_model = self.load_xgboost(xgb_path)

        # Fall back to stubs for any failures
        if lstm_model is None:
            lstm_model = StubLSTMModel()
            logger.info("Using StubLSTMModel as fallback")

        if xgb_model is None:
            xgb_model = StubXGBoostModel()
            logger.info("Using StubXGBoostModel as fallback")

        return lstm_model, xgb_model
