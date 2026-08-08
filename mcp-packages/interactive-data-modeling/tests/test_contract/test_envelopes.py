from __future__ import annotations

from pathlib import Path

import pandas as pd

from shield_prediction_mcp.schemas.envelope import error, needs_input, ok, running
from shield_prediction_mcp.tools.predict_create_session import predict_create_session
from shield_prediction_mcp.tools.predict_get_status import predict_get_status
from shield_prediction_mcp.tools.predict_profile_data import predict_profile_data


ENVELOPE_KEYS = {
    "status",
    "session_id",
    "state",
    "data",
    "options",
    "needs_user_decision",
    "next_tool",
    "message",
    "error",
}


def assert_envelope(value: dict) -> None:
    assert set(value) == ENVELOPE_KEYS
    assert value["status"] in {"ok", "needs_input", "running", "error"}
    assert isinstance(value["data"], dict)
    assert isinstance(value["options"], dict)
    assert isinstance(value["needs_user_decision"], list)


def test_envelope_factories_are_uniform() -> None:
    for value in (ok(), needs_input(), running(), error()):
        assert_envelope(value)


def test_profile_returns_standard_decision_options(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODELING_MCP_WORKDIR", str(tmp_path / "runtime"))
    source = tmp_path / "sample.csv"
    pd.DataFrame({"x": [1, 2, 3], "target": [0, 1, 0]}).to_csv(source, index=False)
    created = predict_create_session(str(source))
    assert_envelope(created)
    assert created["status"] == "ok"
    assert created["session_id"].startswith("predict_sess_")

    profiled = predict_profile_data(created["session_id"])
    assert_envelope(profiled)
    assert profiled["status"] == "needs_input"
    assert profiled["state"] == "PROFILED"
    assert profiled["data"]["content_trust"] == "untrusted_data"
    assert set(profiled["needs_user_decision"]) == {"target", "features", "task_type"}
    for option in profiled["options"].values():
        assert option["type"] in {"single_select", "multi_select", "free_text", "confirm"}
        for candidate in option["candidates"]:
            assert {"value", "label", "reason"}.issubset(candidate)


def test_unknown_session_is_structured_and_recoverable() -> None:
    result = predict_get_status("predict_sess_" + "0" * 32)
    assert_envelope(result)
    assert result["status"] == "needs_input"
    assert result["error"]["code"] == "UNKNOWN_SESSION"
    assert result["error"]["recoverable"] is True
    assert result["error"]["suggestion"]
