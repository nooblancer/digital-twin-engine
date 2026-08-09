"""Unit tests for the ML Service model loader.

Tests cover:
- Successful model loading with mock files (LSTM and XGBoost)
- Fallback to stubs when model files are missing
- Fallback to stubs when model files are corrupted
- Default MODEL_DIR when environment variable is not set
- Custom MODEL_DIR from environment variable

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from digital_twin_engine.ml_service.ensemble_inference import (
    LSTMModel,
    StubLSTMModel,
    StubXGBoostModel,
    XGBoostModel,
)
from digital_twin_engine.ml_service.model_loader import (
    DEFAULT_MODEL_DIR,
    LSTM_FILENAME,
    XGBOOST_FILENAME,
    ModelLoader,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockLSTMModel(LSTMModel):
    """A concrete LSTMModel subclass for testing isinstance checks."""

    def predict(self, sequence):
        import numpy as np

        return np.array([1.0])


class MockXGBoostModel(XGBoostModel):
    """A concrete XGBoostModel subclass for testing isinstance checks."""

    def predict(self, features):
        import numpy as np

        return np.array([2.0])


def _patch_torch_load(return_value=None, side_effect=None):
    """Context manager that patches torch into model_loader as if torch is available.

    Since torch may not be installed in the test environment, we need to:
    1. Set _TORCH_AVAILABLE = True
    2. Create a mock torch module attribute with a mock load function
    """
    mock_torch = MagicMock()
    if side_effect is not None:
        mock_torch.load.side_effect = side_effect
    elif return_value is not None:
        mock_torch.load.return_value = return_value

    return (
        patch("digital_twin_engine.ml_service.model_loader._TORCH_AVAILABLE", True),
        patch(
            "digital_twin_engine.ml_service.model_loader.torch",
            mock_torch,
            create=True,
        ),
        mock_torch,
    )


# ---------------------------------------------------------------------------
# load_lstm tests
# ---------------------------------------------------------------------------


class TestLoadLSTM:
    """Tests for ModelLoader.load_lstm."""

    def test_successful_load(self, tmp_path: Path) -> None:
        """load_lstm returns a loaded LSTMModel when the file exists and is valid."""
        model_file = tmp_path / LSTM_FILENAME
        model_file.write_bytes(b"fake model data")

        mock_model = MockLSTMModel()
        patch_avail, patch_torch, mock_torch = _patch_torch_load(return_value=mock_model)

        with patch_avail, patch_torch:
            loader = ModelLoader(model_dir=tmp_path)
            result = loader.load_lstm()

        assert result is mock_model
        mock_torch.load.assert_called_once_with(
            model_file, map_location="cpu", weights_only=False
        )

    def test_file_not_found_returns_none(self, tmp_path: Path) -> None:
        """load_lstm returns None when the model file does not exist."""
        loader = ModelLoader(model_dir=tmp_path)
        result = loader.load_lstm()

        assert result is None

    def test_corrupted_file_returns_none(self, tmp_path: Path) -> None:
        """load_lstm returns None when torch.load raises an exception."""
        model_file = tmp_path / LSTM_FILENAME
        model_file.write_bytes(b"corrupted data")

        patch_avail, patch_torch, _ = _patch_torch_load(
            side_effect=RuntimeError("Corrupted file")
        )

        with patch_avail, patch_torch:
            loader = ModelLoader(model_dir=tmp_path)
            result = loader.load_lstm()

        assert result is None

    def test_wrong_model_type_returns_none(self, tmp_path: Path) -> None:
        """load_lstm returns None when the loaded object is not an LSTMModel."""
        model_file = tmp_path / LSTM_FILENAME
        model_file.write_bytes(b"fake data")

        patch_avail, patch_torch, _ = _patch_torch_load(return_value="not a model")

        with patch_avail, patch_torch:
            loader = ModelLoader(model_dir=tmp_path)
            result = loader.load_lstm()

        assert result is None

    @patch("digital_twin_engine.ml_service.model_loader._TORCH_AVAILABLE", False)
    def test_torch_unavailable_returns_none(self, tmp_path: Path) -> None:
        """load_lstm returns None when PyTorch is not installed."""
        model_file = tmp_path / LSTM_FILENAME
        model_file.write_bytes(b"fake data")

        loader = ModelLoader(model_dir=tmp_path)
        result = loader.load_lstm()

        assert result is None


# ---------------------------------------------------------------------------
# load_xgboost tests
# ---------------------------------------------------------------------------


class TestLoadXGBoost:
    """Tests for ModelLoader.load_xgboost."""

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_successful_load(self, mock_joblib: MagicMock, tmp_path: Path) -> None:
        """load_xgboost returns a loaded XGBoostModel when the file exists."""
        model_file = tmp_path / XGBOOST_FILENAME
        model_file.write_bytes(b"fake model data")

        mock_model = MockXGBoostModel()
        mock_joblib.load.return_value = mock_model

        loader = ModelLoader(model_dir=tmp_path)
        result = loader.load_xgboost()

        assert result is mock_model
        mock_joblib.load.assert_called_once_with(model_file)

    def test_file_not_found_returns_none(self, tmp_path: Path) -> None:
        """load_xgboost returns None when the model file does not exist."""
        loader = ModelLoader(model_dir=tmp_path)
        result = loader.load_xgboost()

        assert result is None

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_corrupted_file_returns_none(
        self, mock_joblib: MagicMock, tmp_path: Path
    ) -> None:
        """load_xgboost returns None when joblib.load raises an exception."""
        model_file = tmp_path / XGBOOST_FILENAME
        model_file.write_bytes(b"corrupted data")

        mock_joblib.load.side_effect = RuntimeError("Corrupted file")

        loader = ModelLoader(model_dir=tmp_path)
        result = loader.load_xgboost()

        assert result is None

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_wrong_model_type_returns_none(
        self, mock_joblib: MagicMock, tmp_path: Path
    ) -> None:
        """load_xgboost returns None when the loaded object is not an XGBoostModel."""
        model_file = tmp_path / XGBOOST_FILENAME
        model_file.write_bytes(b"fake data")

        mock_joblib.load.return_value = {"not": "a model"}

        loader = ModelLoader(model_dir=tmp_path)
        result = loader.load_xgboost()

        assert result is None


# ---------------------------------------------------------------------------
# load_all tests
# ---------------------------------------------------------------------------


class TestLoadAll:
    """Tests for ModelLoader.load_all (fallback behavior)."""

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_both_files_exist_returns_real_models(
        self, mock_joblib: MagicMock, tmp_path: Path
    ) -> None:
        """load_all returns both real models when both files exist and are valid."""
        lstm_file = tmp_path / LSTM_FILENAME
        lstm_file.write_bytes(b"lstm data")
        xgb_file = tmp_path / XGBOOST_FILENAME
        xgb_file.write_bytes(b"xgb data")

        mock_lstm = MockLSTMModel()
        mock_xgb = MockXGBoostModel()
        mock_joblib.load.return_value = mock_xgb

        patch_avail, patch_torch, _ = _patch_torch_load(return_value=mock_lstm)

        with patch_avail, patch_torch:
            loader = ModelLoader(model_dir=tmp_path)
            lstm_result, xgb_result = loader.load_all()

        assert lstm_result is mock_lstm
        assert xgb_result is mock_xgb

    def test_both_files_missing_returns_stubs(self, tmp_path: Path) -> None:
        """load_all returns stub models when both files are missing."""
        loader = ModelLoader(model_dir=tmp_path)
        lstm_result, xgb_result = loader.load_all()

        assert isinstance(lstm_result, StubLSTMModel)
        assert isinstance(xgb_result, StubXGBoostModel)

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_lstm_missing_xgb_exists_returns_stub_lstm_real_xgb(
        self, mock_joblib: MagicMock, tmp_path: Path
    ) -> None:
        """load_all returns StubLSTMModel + real XGBoost when LSTM file is missing."""
        # Only create XGBoost file, not LSTM
        xgb_file = tmp_path / XGBOOST_FILENAME
        xgb_file.write_bytes(b"xgb data")

        mock_xgb = MockXGBoostModel()
        mock_joblib.load.return_value = mock_xgb

        loader = ModelLoader(model_dir=tmp_path)
        lstm_result, xgb_result = loader.load_all()

        assert isinstance(lstm_result, StubLSTMModel)
        assert xgb_result is mock_xgb

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_xgb_missing_lstm_exists_returns_real_lstm_stub_xgb(
        self, mock_joblib: MagicMock, tmp_path: Path
    ) -> None:
        """load_all returns real LSTM + StubXGBoostModel when XGBoost file is missing."""
        # Only create LSTM file, not XGBoost
        lstm_file = tmp_path / LSTM_FILENAME
        lstm_file.write_bytes(b"lstm data")

        mock_lstm = MockLSTMModel()
        patch_avail, patch_torch, _ = _patch_torch_load(return_value=mock_lstm)

        with patch_avail, patch_torch:
            loader = ModelLoader(model_dir=tmp_path)
            lstm_result, xgb_result = loader.load_all()

        assert lstm_result is mock_lstm
        assert isinstance(xgb_result, StubXGBoostModel)

    @patch("digital_twin_engine.ml_service.model_loader.joblib")
    def test_load_all_with_custom_model_dir(
        self, mock_joblib: MagicMock, tmp_path: Path
    ) -> None:
        """load_all accepts a custom model_dir argument that overrides the instance dir."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        lstm_file = custom_dir / LSTM_FILENAME
        lstm_file.write_bytes(b"lstm data")
        xgb_file = custom_dir / XGBOOST_FILENAME
        xgb_file.write_bytes(b"xgb data")

        mock_lstm = MockLSTMModel()
        mock_xgb = MockXGBoostModel()
        mock_joblib.load.return_value = mock_xgb

        patch_avail, patch_torch, _ = _patch_torch_load(return_value=mock_lstm)

        with patch_avail, patch_torch:
            # Instance model_dir is empty; pass custom dir to load_all
            loader = ModelLoader(model_dir=tmp_path)
            lstm_result, xgb_result = loader.load_all(model_dir=custom_dir)

        assert lstm_result is mock_lstm
        assert xgb_result is mock_xgb


# ---------------------------------------------------------------------------
# MODEL_DIR configuration tests
# ---------------------------------------------------------------------------


class TestModelDirConfiguration:
    """Tests for MODEL_DIR environment variable and default handling."""

    def test_default_model_dir_when_env_not_set(self) -> None:
        """ModelLoader uses DEFAULT_MODEL_DIR when no env var is set."""
        with patch.dict("os.environ", {}, clear=False):
            # Ensure MODEL_DIR is not in environment
            import os

            os.environ.pop("MODEL_DIR", None)
            loader = ModelLoader()

        assert loader.model_dir == Path(DEFAULT_MODEL_DIR)

    def test_custom_model_dir_from_env_variable(self) -> None:
        """ModelLoader uses the MODEL_DIR env variable when set."""
        with patch.dict("os.environ", {"MODEL_DIR": "/opt/ml/models"}):
            loader = ModelLoader()

        assert loader.model_dir == Path("/opt/ml/models")

    def test_explicit_model_dir_overrides_env(self, tmp_path: Path) -> None:
        """Explicitly passing model_dir to __init__ overrides the env variable."""
        with patch.dict("os.environ", {"MODEL_DIR": "/opt/ml/models"}):
            loader = ModelLoader(model_dir=tmp_path)

        assert loader.model_dir == tmp_path
