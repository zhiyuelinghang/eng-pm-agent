from __future__ import annotations

import base64
import importlib
from pathlib import Path

import pytest

from shield_prediction_mcp.schemas.envelope import ENVELOPE_KEYS
from shield_prediction_mcp.schemas.errors import error_from_exception
from shield_prediction_mcp.engine.errors import DomainError
from shield_prediction_mcp.tools import PUBLIC_TOOLS
from shield_prediction_mcp.tools.predict_check_health import predict_check_health
from shield_prediction_mcp.tools.predict_confirm_pipeline_plan import predict_confirm_pipeline_plan
from shield_prediction_mcp.tools.predict_confirm_variables import predict_confirm_variables
from shield_prediction_mcp.tools.predict_create_session import predict_create_session
from shield_prediction_mcp.tools.predict_evaluate_models import predict_evaluate_models
from shield_prediction_mcp.tools.predict_export_model import predict_export_model
from shield_prediction_mcp.tools.predict_get_job_status import predict_get_job_status
from shield_prediction_mcp.tools.predict_get_status import predict_get_status
from shield_prediction_mcp.tools.predict_import_data import predict_import_data
from shield_prediction_mcp.tools.predict_list_sessions import predict_list_sessions
from shield_prediction_mcp.tools.predict_profile_data import predict_profile_data
from shield_prediction_mcp.tools.predict_propose_pipeline_plan import predict_propose_pipeline_plan
from shield_prediction_mcp.tools.predict_rewind_session import predict_rewind_session


UNKNOWN_SESSION = "predict_sess_" + "0" * 32


def _assert_envelope(value: dict) -> None:
    assert set(value) == set(ENVELOPE_KEYS)
    assert value["status"] in {"ok", "needs_input", "running", "error"}
    assert isinstance(value["data"], dict)
    assert isinstance(value["options"], dict)
    assert isinstance(value["needs_user_decision"], list)
    if value["error"] is not None:
        assert set(value["error"]) == {"code", "message", "recoverable", "suggestion"}


def test_registry_contains_exactly_the_thirteen_public_tools() -> None:
    tools = tuple(PUBLIC_TOOLS)
    assert len(tools) == 13
    assert len({tool.__name__ for tool in tools}) == 13
    assert all(tool.__name__.startswith("predict_") for tool in tools)


def test_no_session_tools_return_standard_success_envelopes() -> None:
    for result in (predict_check_health(), predict_list_sessions()):
        _assert_envelope(result)
        assert result["status"] == "ok"


def test_platform_data_import_returns_an_opaque_reference(tmp_path, monkeypatch) -> None:
    from shield_prediction_mcp.tools.orchestrator import (
        InteractiveDataModelingService,
    )

    import_module = importlib.import_module(
        "shield_prediction_mcp.tools.predict_import_data",
    )
    monkeypatch.setattr(
        import_module,
        "service",
        InteractiveDataModelingService(tmp_path / "state"),
    )

    result = import_module.predict_import_data(
        "sample.csv",
        base64.b64encode(b"x,target\n1,0\n").decode("ascii"),
        "text/csv",
    )

    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["data"]["data_ref"].startswith("predict-data://")
    assert "path" not in str(result["data"]).lower()


def test_input_and_domain_validation_errors_are_distinguished() -> None:
    invalid = error_from_exception(DomainError("max_models 必须为 1 到 3 的整数"))
    domain = error_from_exception(DomainError("时序任务禁止随机划分"))
    assert invalid["code"] == "INVALID_INPUT"
    assert domain["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "invoke",
    [
        lambda: predict_import_data("sample.csv", "not-base64"),
        lambda: predict_create_session(str(Path("definitely-missing.csv"))),
        lambda: predict_profile_data(UNKNOWN_SESSION),
        lambda: predict_confirm_variables(UNKNOWN_SESSION, "target", ["x"], "classification"),
        lambda: predict_propose_pipeline_plan(UNKNOWN_SESSION),
        lambda: predict_confirm_pipeline_plan(UNKNOWN_SESSION, "proposal", confirm=True),
        lambda: predict_evaluate_models(UNKNOWN_SESSION, confirm=True),
        lambda: predict_export_model(UNKNOWN_SESSION, "linear", confirm=True),
        lambda: predict_rewind_session(UNKNOWN_SESSION, "profiled"),
        lambda: predict_get_status(UNKNOWN_SESSION),
        lambda: predict_get_job_status("predict_job_" + "0" * 32),
    ],
)
def test_every_fallible_public_tool_returns_a_structured_error(invoke) -> None:
    result = invoke()
    _assert_envelope(result)
    assert result["status"] in {"needs_input", "error"}
    assert result["error"] is not None
    assert result["error"]["code"] in {
        "UNKNOWN_SESSION",
        "INVALID_INPUT",
        "WRONG_STATE",
        "VALIDATION_FAILED",
        "INTERNAL_ERROR",
    }
