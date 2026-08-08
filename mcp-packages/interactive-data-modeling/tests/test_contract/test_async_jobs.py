from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from shield_prediction_mcp.runtime import jobs, service
from shield_prediction_mcp.storage import SessionStore
from shield_prediction_mcp.tools.predict_confirm_pipeline_plan import predict_confirm_pipeline_plan
from shield_prediction_mcp.tools.predict_confirm_variables import predict_confirm_variables
from shield_prediction_mcp.tools.predict_check_health import predict_check_health
from shield_prediction_mcp.tools.predict_create_session import predict_create_session
from shield_prediction_mcp.tools.predict_evaluate_models import predict_evaluate_models
from shield_prediction_mcp.tools.predict_export_model import predict_export_model
from shield_prediction_mcp.tools.predict_get_job_status import predict_get_job_status
from shield_prediction_mcp.tools.predict_get_status import predict_get_status
from shield_prediction_mcp.tools.predict_list_sessions import predict_list_sessions
from shield_prediction_mcp.tools.predict_profile_data import predict_profile_data
from shield_prediction_mcp.tools.predict_propose_pipeline_plan import predict_propose_pipeline_plan
from shield_prediction_mcp.tools.predict_rewind_session import predict_rewind_session


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _poll(job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = predict_get_job_status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    return status


def test_training_returns_job_and_completes_without_changing_model_behavior(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "runtime")
    service.store = store
    jobs.store = store
    rng = np.random.default_rng(9)
    x = rng.normal(size=100)
    source = tmp_path / "training.csv"
    pd.DataFrame({"x": x, "target": (x > 0).astype(int)}).to_csv(source, index=False)

    created = predict_create_session(str(source))
    session_id = created["session_id"]
    predict_profile_data(session_id)
    confirmed = predict_confirm_variables(
        session_id,
        target="target",
        features=["x"],
        task_type="classification",
    )
    assert confirmed["status"] == "ok"
    proposal = predict_propose_pipeline_plan(session_id, objective="speed", max_models=1)
    assert proposal["status"] == "needs_input"
    assert "available_options" not in proposal
    assert "intervention_required" not in proposal
    assert "user_facing_plan_markdown" not in proposal["data"]
    assert proposal["options"]["pipeline_confirmation"]["type"] == "confirm"
    assert {
        "missing_method",
        "encoding_method",
        "denoise_method",
        "models",
        "split_method",
        "ratio_preset",
        "custom_ratios",
        "tuning",
        "model_params",
        "pipeline_confirmation",
    } == set(proposal["options"])
    for option in proposal["options"].values():
        assert option["type"] in {"single_select", "multi_select", "free_text", "confirm"}
        assert option["candidates"]
        assert all({"value", "label", "reason"}.issubset(item) for item in option["candidates"])

    stale = predict_confirm_pipeline_plan(
        session_id,
        proposal_id="stale-proposal",
        confirm=True,
    )
    assert stale["status"] == "needs_input"
    assert stale["error"]["code"] == "VALIDATION_FAILED"

    submitted = predict_confirm_pipeline_plan(
        session_id,
        proposal_id=proposal["data"]["proposal_id"],
        confirm=True,
    )
    assert submitted["status"] == "running"
    assert submitted["next_tool"] == "predict_get_job_status"
    job_id = submitted["data"]["job_id"]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = predict_get_job_status(session_id, job_id)
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert status["status"] == "ok", status
    assert status["state"] == "TRAINED"
    assert status["data"]["result"]["models"][0]["model"] == "Linear/Logistic Regression"
    assert not any(key.endswith("_path") for key in _keys(status["data"]["result"]))
    assert status["data"]["result"]["models"][0]["model_ref"].startswith("predict://")


def test_every_public_tool_has_a_real_success_path_and_exports_are_versioned(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "runtime")
    service.store = store
    jobs.store = store
    rng = np.random.default_rng(23)
    x = rng.normal(size=120)
    source = tmp_path / "full-contract.csv"
    pd.DataFrame({"x": x, "target": (x > 0).astype(int)}).to_csv(source, index=False)

    assert predict_check_health()["status"] == "ok"
    created = predict_create_session(str(source))
    session_id = created["session_id"]
    assert predict_list_sessions()["data"]["sessions"][0]["session_id"] == session_id
    assert predict_profile_data(session_id)["status"] == "needs_input"
    assert predict_confirm_variables(
        session_id,
        target="target",
        features=["x"],
        task_type="classification",
    )["status"] == "ok"
    proposal = predict_propose_pipeline_plan(session_id, objective="speed", max_models=1)
    submitted = predict_confirm_pipeline_plan(
        session_id,
        proposal_id=proposal["data"]["proposal_id"],
        confirm=True,
    )
    trained = _poll(submitted["data"]["job_id"])
    assert trained["status"] == "ok", trained
    assert trained["data"]["job_status"] == "succeeded"
    assert predict_get_status(session_id)["state"] == "TRAINED"

    evaluation_job = predict_evaluate_models(session_id, confirm=True)
    evaluated = _poll(evaluation_job["data"]["job_id"])
    assert evaluated["status"] == "ok", evaluated
    assert evaluated["state"] == "EVALUATED"

    export_job_1 = predict_export_model(session_id, "linear", confirm=True)
    exported_1 = _poll(export_job_1["data"]["job_id"])
    assert exported_1["status"] == "ok", exported_1
    assert not any(key.endswith(("_path", "_dir")) for key in _keys(exported_1))
    export_job_2 = predict_export_model(session_id, "linear", confirm=True)
    exported_2 = _poll(export_job_2["data"]["job_id"])
    assert exported_2["status"] == "ok", exported_2

    internal = store.load(session_id)
    assert internal["artifact_versions"]["linear"] == 2
    first, second = internal["exports"][-2:]
    assert first["export_dir"] != second["export_dir"]
    assert first["archive_path"] != second["archive_path"]
    assert Path(first["archive_path"]).is_file()
    assert Path(second["archive_path"]).is_file()

    rewound = predict_rewind_session(session_id, "PIPELINE_PROPOSED")
    assert rewound["status"] == "ok"
    assert rewound["state"] == "PIPELINE_PROPOSED"
