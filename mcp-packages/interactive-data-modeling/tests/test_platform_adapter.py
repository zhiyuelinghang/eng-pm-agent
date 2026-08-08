from __future__ import annotations

import base64
from pathlib import Path

import pytest

from shield_prediction_mcp.engine.errors import DomainError
from shield_prediction_mcp.tools.orchestrator import (
    InteractiveDataModelingService,
)


def _encoded_csv() -> str:
    return base64.b64encode(b"feature,target\n1,0\n2,1\n").decode("ascii")


def test_imported_attachment_is_snapshotted_into_its_modeling_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTSCOPE_MCP_STATE_DIR", str(tmp_path / "state"))
    service = InteractiveDataModelingService(tmp_path / "state")

    imported = service.import_data("sample.csv", _encoded_csv(), "text/csv")
    created = service.create_session(data_ref=imported["data_ref"])
    state = service.store.load(created["session_id"])
    snapshot = Path(state["data_path"])

    assert snapshot.is_file()
    assert snapshot.parent == service.store.session_dir(created["session_id"]) / "input"
    assert snapshot.read_bytes() == b"feature,target\n1,0\n2,1\n"
    assert state["inputs"]["dataset_ref"] == str(snapshot)


def test_platform_scope_rejects_arbitrary_server_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTSCOPE_MCP_STATE_DIR", str(tmp_path / "state"))
    source = tmp_path / "outside.csv"
    source.write_bytes(b"feature,target\n1,0\n")
    service = InteractiveDataModelingService(tmp_path / "state")

    with pytest.raises(DomainError, match="允许的读取目录"):
        service.create_session(data_path=str(source))


def test_data_refs_are_isolated_between_platform_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTSCOPE_MCP_STATE_DIR", str(tmp_path / "scope-a"))
    first = InteractiveDataModelingService(tmp_path / "scope-a")
    imported = first.import_data("sample.csv", _encoded_csv(), "text/csv")

    monkeypatch.setenv("AGENTSCOPE_MCP_STATE_DIR", str(tmp_path / "scope-b"))
    second = InteractiveDataModelingService(tmp_path / "scope-b")

    with pytest.raises(DomainError, match="不存在或已过期"):
        second.create_session(data_ref=imported["data_ref"])


@pytest.mark.parametrize(
    ("file_name", "content"),
    [
        ("sample.txt", _encoded_csv()),
        ("sample.csv", "not-base64"),
        ("sample.csv", ""),
    ],
)
def test_invalid_platform_imports_are_rejected(
    tmp_path: Path,
    file_name: str,
    content: str,
) -> None:
    service = InteractiveDataModelingService(tmp_path / "state")

    with pytest.raises(DomainError):
        service.import_data(file_name, content, "text/csv")
