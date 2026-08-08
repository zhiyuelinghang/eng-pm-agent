from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from shield_prediction_mcp.data import (
    transform_features,
    validate_preprocessing_config,
)
from shield_prediction_mcp.modeling import (
    train_selected_models,
    validate_training_configuration,
)
from shield_prediction_mcp.preprocessing_runtime import _apply_denoise
from shield_prediction_mcp.service import InteractiveDataModelingService
from shield_prediction_mcp.storage import WorkflowError


def _regression_frame(rows: int = 100) -> pd.DataFrame:
    x = np.arange(rows, dtype=float)
    return pd.DataFrame(
        {
            "time": np.arange(rows),
            "x": x,
            "category": np.where(x < 85, "known", "test_only"),
            "target": 2.0 * x + 3.0,
        }
    )


def _preprocessing_config(frame: pd.DataFrame, *, causal: bool = False) -> dict:
    return validate_preprocessing_config(
        frame,
        ["x", "category"],
        "target",
        "median",
        None,
        {"category": "onehot"},
        {"method": "moving_average", "columns": ["x"], "window": 3} if causal else {"method": "none"},
        causal=causal,
    )


def test_preprocessor_is_fitted_only_on_training_partition(tmp_path: Path) -> None:
    frame = _regression_frame()
    frame.loc[5, "x"] = np.nan
    frame.loc[90, "x"] = np.nan
    # This category exists only in the sequential test partition.
    config = _preprocessing_config(frame)
    results = train_selected_models(
        frame,
        ["x", "category"],
        "target",
        "regression",
        ["linear"],
        {
            "split_method": "sequential",
            "tuning": "default",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
            "n_trials": 2,
            "model_params": {},
        },
        tmp_path / "training",
        preprocessing_config=config,
    )

    artifact = joblib.load(results["preprocessor_path"])
    assert artifact["fitted_scope"] == "training_partition"
    assert artifact["missing"]["fill_values"]["x"] == pytest.approx(35.0)
    assert artifact["encoding"]["category"]["categories"] == ["known"]
    assert results["split_info"]["preprocessor_fit_rows"] == 70


def test_timeseries_denoising_is_causal_and_rejects_future_window_methods() -> None:
    values = pd.Series([1.0, 100.0, 1.0])
    result = _apply_denoise(values, {"method": "moving_average", "window": 3})
    assert result.tolist() == pytest.approx([1.0, 50.5, 34.0])

    frame = _regression_frame()
    with pytest.raises(WorkflowError, match="禁止"):
        validate_preprocessing_config(
            frame,
            ["x"],
            "target",
            "median",
            None,
            None,
            {"method": "savgol", "columns": ["x"]},
            causal=True,
        )


def test_kfold_runs_real_cross_validation_with_held_out_test(tmp_path: Path) -> None:
    frame = _regression_frame(120)
    config = validate_preprocessing_config(
        frame,
        ["x"],
        "target",
        "median",
        None,
        None,
        {"method": "none"},
        causal=False,
    )
    results = train_selected_models(
        frame,
        ["x"],
        "target",
        "regression",
        ["linear"],
        {
            "split_method": "kfold",
            "tuning": "default",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
            "n_trials": 2,
            "model_params": {},
        },
        tmp_path / "kfold",
        preprocessing_config=config,
    )
    assert results["split_info"]["cross_validation_folds"] == 5
    assert results["split_info"]["test_set_held_out"] is True
    assert results["models"][0]["tuning_score"] is not None


@pytest.mark.parametrize(
    "params,match",
    [
        ({"random_forest": {"n_estimators": 0}}, "n_estimators"),
        ({"random_forest": {"random_state": 7}}, "不支持"),
        ({"unknown": {}}, "未选择"),
    ],
)
def test_training_parameters_are_validated(params: dict, match: str) -> None:
    with pytest.raises(WorkflowError, match=match):
        validate_training_configuration(
            ["random_forest"],
            "regression",
            "random",
            "default",
            0.7,
            0.15,
            0.15,
            10,
            params,
        )


def test_deep_models_reject_unsupported_global_search() -> None:
    with pytest.raises(WorkflowError, match="仅支持传统模型"):
        validate_training_configuration(
            ["mlp"],
            "regression",
            "random",
            "bayesian",
            0.7,
            0.15,
            0.15,
            10,
            None,
        )


def test_create_session_accepts_every_documented_format(tmp_path: Path) -> None:
    frame = _regression_frame(25)
    json_path = tmp_path / "data.json"
    parquet_path = tmp_path / "data.parquet"
    frame.to_json(json_path, orient="records")
    frame.to_parquet(parquet_path, index=False)
    service = InteractiveDataModelingService(tmp_path / "runtime")

    assert service.create_session(str(json_path))["stage"] == "created"
    assert service.create_session(str(parquet_path))["stage"] == "created"


def test_exported_predictor_matches_training_runtime(tmp_path: Path) -> None:
    frame = _regression_frame(80)
    source = tmp_path / "data.jsonl"
    frame.to_json(source, orient="records", lines=True)
    service = InteractiveDataModelingService(tmp_path / "runtime")
    session_id = service.create_session(str(source))["session_id"]
    service.profile_data(session_id)
    service.confirm_variables(
        session_id,
        target="target",
        features=["x", "category"],
        task_type="regression",
    )
    service.inspect_preprocessing(session_id)
    service.apply_preprocessing(
        session_id,
        missing_default="median",
        encoding={"category": "onehot"},
        denoise={"method": "none"},
        confirm=True,
    )
    service.recommend_models(session_id)
    service.select_models(session_id, ["linear"], confirm=True)
    service.configure_training(session_id, split_method="random", confirm=True)
    service.train_models(session_id, confirm=True)
    service.evaluate_models(session_id, confirm=True)
    exported = service.export_model(session_id, "linear", confirm=True)["export"]
    export_dir = Path(exported["export_dir"])

    config = json.loads((export_dir / "model_config.json").read_text(encoding="utf-8"))
    artifact = joblib.load(export_dir / config["preprocessor_path"])
    transformed, kept_index = transform_features(frame, artifact)
    expected = joblib.load(export_dir / config["model_path"]).predict(transformed.to_numpy(dtype=float))

    output = tmp_path / "predictions.csv"
    completed = subprocess.run(
        [sys.executable, str(export_dir / "predict.py"), "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    actual = pd.read_csv(output, encoding="utf-8-sig")
    assert actual.index.size == kept_index.size
    assert actual["prediction"].to_numpy() == pytest.approx(expected)
    assert (export_dir / "preprocessing_runtime.py").is_file()
