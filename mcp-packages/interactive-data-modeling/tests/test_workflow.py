from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shield_prediction_mcp.service import ShieldPredictionService
from shield_prediction_mcp.storage import WorkflowError


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    rng = np.random.default_rng(42)
    rows = 180
    torque = rng.normal(5200, 450, rows)
    pressure = rng.normal(2.4, 0.25, rows)
    speed = rng.normal(1.5, 0.2, rows)
    geology = np.where(np.arange(rows) % 3 == 0, "黏土", "砂层")
    thrust = 0.65 * torque + 850 * pressure - 400 * speed + (geology == "砂层") * 250 + rng.normal(0, 80, rows)
    pressure[5] = np.nan
    frame = pd.DataFrame(
        {
            "环号": np.arange(rows),
            "刀盘扭矩": torque,
            "土仓压力": pressure,
            "推进速度": speed,
            "地层类型": geology,
            "总推力": thrust,
        }
    )
    path = tmp_path / "shield.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def test_stage_guard_and_full_random_forest_workflow(tmp_path: Path, sample_csv: Path) -> None:
    service = ShieldPredictionService(tmp_path / "runtime")
    created = service.create_session(str(sample_csv))
    session_id = created["session_id"]

    with pytest.raises(WorkflowError):
        service.recommend_models(session_id)

    profile = service.profile_data(session_id)
    assert profile["profile"]["shape"] == {"rows": 180, "columns": 6}
    service.confirm_variables(
        session_id,
        target="总推力",
        features=["刀盘扭矩", "土仓压力", "推进速度", "地层类型"],
        task_type="regression",
    )
    review = service.inspect_preprocessing(session_id)
    assert any(item["column"] == "土仓压力" for item in review["review"]["missing"])
    processed = service.apply_preprocessing(
        session_id,
        missing_default="median",
        encoding={"地层类型": "onehot"},
        denoise={"method": "none"},
        confirm=True,
    )
    assert len(processed["summary"]["final_features"]) == 5
    service.recommend_models(session_id)
    service.select_models(session_id, ["random_forest", "linear"], confirm=True)
    service.configure_training(
        session_id,
        split_method="random",
        tuning="default",
        model_params={"random_forest": {"n_estimators": 20, "max_depth": 8}},
        confirm=True,
    )
    trained = service.train_models(session_id, confirm=True)
    assert {item["model"] for item in trained["models"]} == {"Random Forest", "Linear/Logistic Regression"}
    evaluated = service.evaluate_models(session_id, confirm=True)
    assert len(evaluated["evaluation"]["models"]) == 2
    exported = service.export_model(session_id, "random_forest", confirm=True)
    export_dir = Path(exported["export"]["export_dir"])
    assert (export_dir / "predict.py").is_file()
    assert (export_dir / "model_config.json").is_file()
    assert Path(exported["export"]["archive_path"]).is_file()
    config = json.loads((export_dir / "model_config.json").read_text(encoding="utf-8"))
    assert config["model_type"] == "random_forest"
    prediction_path = tmp_path / "predictions.csv"
    completed = subprocess.run(
        [
            sys.executable,
            str(export_dir / "predict.py"),
            "--input",
            str(sample_csv),
            "--output",
            str(prediction_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    predictions = pd.read_csv(prediction_path, encoding="utf-8-sig")
    assert len(predictions) == 180
    assert "prediction" in predictions.columns


def test_rewind_requires_earlier_stage(tmp_path: Path, sample_csv: Path) -> None:
    service = ShieldPredictionService(tmp_path / "runtime")
    session_id = service.create_session(str(sample_csv))["session_id"]
    service.profile_data(session_id)
    with pytest.raises(WorkflowError):
        service.rewind_session(session_id, "profiled")
