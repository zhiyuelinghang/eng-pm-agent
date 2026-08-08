from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shield_prediction_mcp.service import InteractiveDataModelingService
from shield_prediction_mcp.storage import WorkflowError


def _classification_csv(path: Path, rows: int = 180) -> Path:
    rng = np.random.default_rng(12)
    age = rng.integers(18, 70, rows)
    spend = rng.normal(400, 120, rows)
    segment = np.where(age < 35, "new", np.where(age < 55, "loyal", "premium")).astype(object)
    segment[3] = None
    spend[5] = np.nan
    churned = np.where(np.nan_to_num(spend, nan=400) < 360, "yes", "no")
    pd.DataFrame(
        {
            "age": age,
            "monthly_spend": spend,
            "segment": segment,
            "churned": churned,
        }
    ).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _prepare_service(
    tmp_path: Path,
    *,
    timeseries: bool = False,
) -> tuple[InteractiveDataModelingService, str]:
    service = InteractiveDataModelingService(tmp_path / "runtime")
    if timeseries:
        rows = 160
        signal = np.sin(np.arange(rows) / 10)
        signal[4] = np.nan
        frame = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=rows, freq="h"),
                "signal": signal,
                "target": np.cos(np.arange(rows) / 12),
            }
        )
        source = tmp_path / "timeseries.csv"
        frame.to_csv(source, index=False, encoding="utf-8-sig")
        features = ["signal"]
        target = "target"
        task_type = "timeseries"
        time_column = "time"
    else:
        source = _classification_csv(tmp_path / "classification.csv")
        features = ["age", "monthly_spend", "segment"]
        target = "churned"
        task_type = "classification"
        time_column = None

    session_id = service.create_session(str(source))["session_id"]
    service.profile_data(session_id)
    confirmed = service.confirm_variables(
        session_id,
        target=target,
        features=features,
        task_type=task_type,
        time_column=time_column,
    )
    assert confirmed["next_tool"] == "propose_pipeline_plan"
    assert confirmed["intervention_required"] is False
    return service, session_id


def test_proposal_contains_complete_recommendation_and_all_options(tmp_path: Path) -> None:
    service, session_id = _prepare_service(tmp_path)
    result = service.propose_pipeline_plan(
        session_id,
        objective="balanced",
        search_intensity="fast",
        max_models=2,
    )

    assert result["intervention_required"] is True
    assert result["confirmation_scope"] == "complete_pipeline_and_start_training"
    assert result["next_tool"] == "confirm_pipeline_plan"
    assert set(result["recommended_plan"]) == {"preprocessing", "models", "training"}
    preprocessing = result["recommended_plan"]["preprocessing"]
    assert preprocessing["missing_per_column"]["monthly_spend"] == "median"
    assert preprocessing["missing_per_column"]["segment"] == "mode"
    assert preprocessing["encoding"]["segment"] == "onehot"
    assert preprocessing["denoise"] is None
    assert 1 <= len(result["recommended_plan"]["models"]) <= 2
    assert result["recommendation_reasons"]["preprocessing"]
    assert result["recommendation_reasons"]["models_and_training"]

    options = result["available_options"]
    assert {item["method"] for item in options["preprocessing"]["missing_methods"]} == {
        "mean",
        "median",
        "interpolate",
        "drop",
        "knn",
        "ffill",
        "mode",
    }
    assert {item["method"] for item in options["preprocessing"]["encoding_methods"]} == {
        "onehot",
        "label",
        "drop",
    }
    assert {item["method"] for item in options["preprocessing"]["denoise_methods"]} == {
        "none",
        "moving_average",
        "wavelet",
        "savgol",
    }
    assert len(options["models"]) == 7
    assert {item["method"] for item in options["split_methods"]} == {
        "random",
        "sequential",
        "kfold",
    }
    assert {item["method"] for item in options["tuning_methods"]} == {
        "default",
        "grid",
        "random",
        "bayesian",
    }
    assert options["custom_ratios"]["available"] is True
    assert set(options["manual_model_params"]["by_model"]) == {
        "xgboost",
        "random_forest",
        "svm",
        "linear",
        "lstm",
        "cnn1d",
        "mlp",
    }

    assert "user_facing_plan_markdown" not in result
    assert "agent_display_contract" not in result
    assert all(item.get("reason") for item in options["models"])
    assert all(item.get("reason") for item in options["split_methods"])
    assert all(item.get("reason") for item in options["tuning_methods"])


def test_single_confirmation_accepts_plan_and_trains_immediately(tmp_path: Path) -> None:
    service, session_id = _prepare_service(tmp_path)
    proposal = service.propose_pipeline_plan(
        session_id,
        objective="speed",
        max_models=1,
    )
    assert proposal["recommended_plan"]["models"] == ["linear"]

    with pytest.raises(WorkflowError, match="confirm"):
        service.confirm_pipeline_plan(
            session_id,
            proposal_id=proposal["proposal_id"],
            confirm=False,
        )
    with pytest.raises(WorkflowError, match="过期"):
        service.confirm_pipeline_plan(
            session_id,
            proposal_id="stale-proposal",
            confirm=True,
        )

    trained = service.confirm_pipeline_plan(
        session_id,
        proposal_id=proposal["proposal_id"],
        user_adjustment_note="接受完整推荐方案",
        confirm=True,
    )
    assert trained["stage"] == "trained"
    assert trained["final_plan"] == proposal["recommended_plan"]
    assert trained["changes_from_recommendation"] == {}
    assert trained["models"][0]["model"] == "Linear/Logistic Regression"
    assert trained["next_tool"] == "evaluate_models"

    state = service.get_session_state(session_id)
    assert state["stage"] == "trained"
    assert state["confirmed_pipeline_plan"]["source"] == "recommended"
    assert state["preprocessor_path"]
    assert state["training_results_path"]


def test_user_can_override_preprocessing_model_and_training_in_one_call(tmp_path: Path) -> None:
    service, session_id = _prepare_service(tmp_path)
    proposal = service.propose_pipeline_plan(session_id)
    trained = service.confirm_pipeline_plan(
        session_id,
        proposal_id=proposal["proposal_id"],
        missing_per_column={"monthly_spend": "mean"},
        encoding={"segment": "label"},
        models=["random_forest"],
        split_method="kfold",
        model_params={"random_forest": {"n_estimators": 10, "max_depth": 4}},
        user_adjustment_note="一次性修改预处理、模型和划分",
        confirm=True,
    )

    final = trained["final_plan"]
    assert final["preprocessing"]["missing_per_column"]["monthly_spend"] == "mean"
    assert final["preprocessing"]["missing_per_column"]["segment"] == "mode"
    assert final["preprocessing"]["encoding"]["segment"] == "label"
    assert final["models"] == ["random_forest"]
    assert final["training"]["split_method"] == "kfold"
    assert set(trained["changes_from_recommendation"]) == {
        "preprocessing",
        "models",
        "training",
    }
    state = service.get_session_state(session_id)
    assert state["confirmed_pipeline_plan"]["source"] == "user_modified"


def test_timeseries_plan_is_causal_and_recommends_sequential(tmp_path: Path) -> None:
    service, session_id = _prepare_service(tmp_path, timeseries=True)
    proposal = service.propose_pipeline_plan(session_id)
    preprocessing = proposal["recommended_plan"]["preprocessing"]
    assert preprocessing["causal"] is True
    assert preprocessing["missing_per_column"]["signal"] == "ffill"
    assert proposal["recommended_plan"]["training"]["split_method"] == "sequential"
    random_option = next(
        item
        for item in proposal["available_options"]["split_methods"]
        if item["method"] == "random"
    )
    assert random_option["available"] is False
    wavelet = next(
        item
        for item in proposal["available_options"]["preprocessing"]["denoise_methods"]
        if item["method"] == "wavelet"
    )
    assert wavelet["available"] is False
    assert "非因果" in wavelet["unavailable_reason"]


def test_changed_source_data_invalidates_pipeline_plan(tmp_path: Path) -> None:
    service, session_id = _prepare_service(tmp_path)
    proposal = service.propose_pipeline_plan(session_id)
    state = service.get_session_state(session_id)
    source = Path(state["data_path"])
    changed = pd.read_csv(source, encoding="utf-8-sig")
    changed.loc[0, "age"] = 99
    changed.to_csv(source, index=False, encoding="utf-8-sig")

    with pytest.raises(WorkflowError, match="发生变化"):
        service.confirm_pipeline_plan(
            session_id,
            proposal_id=proposal["proposal_id"],
            confirm=True,
        )


def test_workflow_resource_enforces_one_complete_confirmation() -> None:
    service = InteractiveDataModelingService()
    workflow = json.loads(service.workflow_description())
    assert workflow["recommended_workflow"] == [
        "predict_create_session",
        "predict_profile_data",
        "predict_confirm_variables",
        "predict_propose_pipeline_plan",
        "predict_confirm_pipeline_plan",
        "predict_get_job_status",
        "predict_evaluate_models",
        "predict_export_model",
    ]
    assert workflow["interaction"]["single_confirmation"]
    assert "options" in workflow["interaction"]["display_contract"]
    assert {
        "inspect_preprocessing",
        "apply_preprocessing",
        "propose_training_plan",
        "configure_training_plan",
        "train_models",
        "recommend_models",
        "select_models",
        "configure_training",
    } == set(workflow["removed_legacy_tools"])
