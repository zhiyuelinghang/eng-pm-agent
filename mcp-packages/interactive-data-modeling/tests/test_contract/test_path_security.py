from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from shield_prediction_mcp.engine.errors import DomainError
from shield_prediction_mcp.engine.preprocessing_runtime import load_data as runtime_load_data
from shield_prediction_mcp.schemas.errors import _without_internal_paths, error_from_exception
from shield_prediction_mcp.session.store import SessionStore, public_state
from shield_prediction_mcp.tools.context import jobs, service
from shield_prediction_mcp.tools.predict_get_job_status import predict_get_job_status
from shield_prediction_mcp.tools.predict_list_sessions import predict_list_sessions


@pytest.mark.parametrize(
    "internal_path",
    [
        r"C:\internal folder\private model.pkl",
        r"C:\internal (secret)\private model.pkl",
        r"C:\internal[secret]\private model.pkl",
        r"C:\internal{secret}\private model.pkl",
        r"C:\internal,secret;private!model.pkl",
        r"\\server\private share\model.pkl",
        "//server/private share/model.pkl",
        "/srv/private folder/model.pkl",
        "/srv/internal[secret]/private model.pkl",
        "/srv/internal;secret!/private model.pkl",
        "/srv/internal\nsecret/private model.pkl",
        "file:///C:/private%20folder/model.pkl",
        "file:/srv/private folder/model.pkl",
    ],
)
def test_error_message_and_suggestion_redact_complete_paths(internal_path: str) -> None:
    details = error_from_exception(
        DomainError(
            f"待导出文件不存在: {internal_path}；请重试",
            suggestion=f"检查 {internal_path} 后重试",
        )
    )
    for value in (details["message"], details["suggestion"]):
        assert "<server-path>" in value
        assert "private" not in value
        assert "model.pkl" not in value


def test_protocol_urls_are_not_misclassified_as_filesystem_paths() -> None:
    message = "查看 https://example.com/help、predict://workflow 和 profile:/public"
    assert _without_internal_paths(message) == message


def test_parser_error_never_embeds_path_or_raw_library_error(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "internal (secret)" / "private[data].csv"

    def fail_read(*args, **kwargs):
        raise pd.errors.ParserError(f"raw parser detail leaked {source}")

    monkeypatch.setattr(pd, "read_csv", fail_read)
    with pytest.raises(ValueError) as caught:
        runtime_load_data(source)
    message = str(caught.value)
    assert message == "无法解析数据文件；请检查编码、分隔符和文件结构"
    assert "secret" not in message
    assert "private" not in message


@pytest.mark.parametrize(
    "internal",
    [
        "//server/private (secret)[scope]/model.pkl",
        "file:/srv/private (secret)[scope]/model.pkl",
    ],
)
def test_public_tool_error_redacts_punctuated_path(monkeypatch, internal: str) -> None:

    def fail_list():
        raise DomainError(
            f"读取失败: {internal}",
            suggestion=f"检查 {internal} 后重试",
        )

    monkeypatch.setattr(service, "list_sessions", fail_list)
    result = predict_list_sessions()
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "needs_input"
    assert "<server-path>" in serialized
    assert "secret" not in serialized
    assert "private" not in serialized


def test_persisted_job_error_is_redacted_again_at_public_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2], "target": [0, 1]}).to_csv(source, index=False)
    store = SessionStore(tmp_path / "runtime")
    monkeypatch.setattr(service, "store", store)
    monkeypatch.setattr(jobs, "store", store)
    state = store.create(str(source))
    job_id = "predict_job_" + "7" * 32
    internal = r"C:\internal[secret]\private model.pkl"
    state["jobs"][job_id] = {
        "job_id": job_id,
        "operation": "train",
        "status": "failed",
        "progress": 1.0,
        "error": {
            "code": "JOB_FAILED",
            "message": f"任务失败: {internal}",
            "recoverable": False,
            "suggestion": f"检查 {internal}",
        },
    }
    store.save(state)
    result = predict_get_job_status(job_id, state["session_id"])
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "error"
    assert "<server-path>" in serialized
    assert "secret" not in serialized
    assert "private" not in serialized


def test_public_session_artifacts_use_allowlisted_metadata(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2], "target": [0, 1]}).to_csv(source, index=False)
    store = SessionStore(tmp_path / "runtime")
    state = store.create(str(source))
    state["artifacts"]["plot1"] = {
        "artifact_id": "plot1",
        "kind": "plot",
        "version": 1,
        "path": r"C:\internal folder\plot.png",
        "export_dir": r"C:\internal folder\exports",
        "source": "/srv/private/source.csv",
    }
    public = public_state(state)["artifacts"]["plot1"]
    assert public == {
        "artifact_id": "plot1",
        "kind": "plot",
        "version": 1,
        "resource_ref": f"predict://session/{state['session_id']}/artifact/plot1",
    }


@pytest.mark.asyncio
async def test_artifact_resource_never_returns_internal_storage_fields(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    source = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2], "target": [0, 1]}).to_csv(source, index=False)
    store = SessionStore(runtime)
    state = store.create(str(source))
    state["artifacts"]["plot1"] = {
        "artifact_id": "plot1",
        "kind": "plot",
        "version": 1,
        "path": r"C:\internal folder\plot.png",
        "archive_path": r"C:\internal folder\plot.zip",
        "directory": "/srv/private/artifacts",
    }
    store.save(state)

    environment = os.environ.copy()
    environment["PREDICT_MCP_WORKDIR"] = str(runtime)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "shield_prediction_mcp.server"],
        env=environment,
    )
    uri = f"predict://session/{state['session_id']}/artifact/plot1"
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
    payload = json.loads(result.contents[0].text)
    assert payload == {
        "artifact_id": "plot1",
        "kind": "plot",
        "version": 1,
        "resource_ref": uri,
    }
    serialized = json.dumps(payload)
    assert "internal" not in serialized
    assert "private" not in serialized
    assert "path" not in serialized
