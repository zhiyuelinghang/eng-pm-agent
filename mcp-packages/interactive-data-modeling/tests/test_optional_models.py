from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shield_prediction_mcp.service import ShieldPredictionService


torch = pytest.importorskip("torch")
pytest.importorskip("xgboost")


def _time_series_csv(path: Path, rows: int = 140) -> Path:
    rng = np.random.default_rng(7)
    torque = 5000 + np.sin(np.arange(rows) / 8) * 500 + rng.normal(0, 50, rows)
    pressure = 2.5 + np.cos(np.arange(rows) / 11) * 0.3 + rng.normal(0, 0.03, rows)
    speed = 1.4 + np.sin(np.arange(rows) / 13) * 0.2
    thrust = 0.7 * torque + 900 * pressure - 300 * speed + rng.normal(0, 30, rows)
    frame = pd.DataFrame(
        {
            "环号": np.arange(rows),
            "刀盘扭矩": torque,
            "土仓压力": pressure,
            "推进速度": speed,
            "总推力": thrust,
        }
    )
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def test_xgboost_and_torch_models_train_evaluate_export_predict(tmp_path: Path) -> None:
    source = _time_series_csv(tmp_path / "timeseries.csv")
    service = ShieldPredictionService(tmp_path / "runtime")
    session_id = service.create_session(str(source))["session_id"]
    service.profile_data(session_id)
    service.confirm_variables(
        session_id,
        target="总推力",
        features=["刀盘扭矩", "土仓压力", "推进速度"],
        task_type="timeseries",
        time_column="环号",
    )
    service.inspect_preprocessing(session_id)
    service.apply_preprocessing(
        session_id,
        missing_default="median",
        denoise={"method": "moving_average", "columns": ["刀盘扭矩"], "window": 3},
        confirm=True,
    )
    service.recommend_models(session_id)
    service.select_models(session_id, ["xgboost", "mlp", "lstm", "cnn1d"], confirm=True)
    service.configure_training(
        session_id,
        split_method="sequential",
        tuning="default",
        model_params={
            "xgboost": {"n_estimators": 10, "max_depth": 3},
            "mlp": {"hidden_layers": [16, 8], "epochs": 2, "batch_size": 16},
            "lstm": {"hidden_size": 8, "num_layers": 1, "epochs": 2, "batch_size": 16, "seq_length": 5},
            "cnn1d": {"channels": [8], "epochs": 2, "batch_size": 16, "seq_length": 5},
        },
        confirm=True,
    )
    trained = service.train_models(session_id, confirm=True)
    assert len(trained["models"]) == 4
    evaluated = service.evaluate_models(session_id, confirm=True)
    assert len(evaluated["evaluation"]["models"]) == 4
    exported = service.export_model(session_id, "lstm", confirm=True)
    export_dir = Path(exported["export"]["export_dir"])
    output = tmp_path / "lstm_predictions.csv"
    completed = subprocess.run(
        [sys.executable, str(export_dir / "predict.py"), "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    predictions = pd.read_csv(output, encoding="utf-8-sig")
    assert len(predictions) == 135


def test_optuna_bayesian_search(tmp_path: Path) -> None:
    pytest.importorskip("optuna")
    source = _time_series_csv(tmp_path / "tabular.csv", rows=100)
    service = ShieldPredictionService(tmp_path / "runtime")
    session_id = service.create_session(str(source))["session_id"]
    service.profile_data(session_id)
    service.confirm_variables(
        session_id,
        target="总推力",
        features=["刀盘扭矩", "土仓压力", "推进速度"],
        task_type="regression",
    )
    service.inspect_preprocessing(session_id)
    service.apply_preprocessing(session_id, missing_default="median", denoise={"method": "none"}, confirm=True)
    service.recommend_models(session_id)
    service.select_models(session_id, ["random_forest"], confirm=True)
    service.configure_training(
        session_id,
        split_method="random",
        tuning="bayesian",
        n_trials=2,
        confirm=True,
    )
    trained = service.train_models(session_id, confirm=True)
    assert trained["models"][0]["params"]
