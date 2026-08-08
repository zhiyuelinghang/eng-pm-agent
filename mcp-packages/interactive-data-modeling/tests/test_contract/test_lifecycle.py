from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from shield_prediction_mcp.engine.errors import DomainError
from shield_prediction_mcp.tools.job_manager import JobManager, _terminate_process
from shield_prediction_mcp.session.store import SessionStore


def test_expired_session_is_hidden_read_only_then_cleanup_removes_all_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PREDICT_SESSION_TTL_SECONDS", "1")
    output_root = tmp_path / "external-output"
    monkeypatch.setenv("PREDICT_ALLOWED_OUTPUT_ROOTS", str(output_root))
    source = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2], "target": [0, 1]}).to_csv(source, index=False)
    store = SessionStore(tmp_path / "runtime")
    state = store.create(str(source), str(output_root))
    session_dir = Path(state["session_dir"])
    artifacts_dir = Path(state["artifacts_dir"])
    (artifacts_dir / "model.bin").write_bytes(b"model")

    state_path = session_dir / "session.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    persisted["updated_at"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    state_path.write_text(json.dumps(persisted), encoding="utf-8")

    with pytest.raises(DomainError) as caught:
        store.load(state["session_id"])
    assert caught.value.code == "UNKNOWN_SESSION"
    assert session_dir.exists(), "read-only load must not delete files"
    assert state["session_id"] not in {item["session_id"] for item in store.list_sessions()}
    assert session_dir.exists(), "read-only list must not delete files"

    store.cleanup()
    assert not session_dir.exists()
    assert not artifacts_dir.exists()


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self._alive = True

    def terminate(self) -> None:
        self.terminated = True

    def join(self, timeout: float) -> None:
        if self.killed:
            self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def kill(self) -> None:
        self.killed = True


def test_timeout_termination_escalates_until_worker_is_dead() -> None:
    process = _FakeProcess()
    _terminate_process(process, grace_seconds=0)
    assert process.terminated is True
    assert process.killed is True
    assert process.is_alive() is False


def test_job_status_read_does_not_mutate_an_overdue_record(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2], "target": [0, 1]}).to_csv(source, index=False)
    store = SessionStore(tmp_path / "runtime")
    manager = JobManager(store)
    state = store.create(str(source))
    job_id = "predict_job_" + "1" * 32
    state["jobs"][job_id] = {
        "job_id": job_id,
        "operation": "train",
        "status": "running",
        "progress": 0.0,
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "timeout_seconds": 1,
        "result": None,
        "error": None,
    }
    store.save(state)
    state_path = store.state_path(state["session_id"])
    before = state_path.read_bytes()
    record = manager.get(job_id, state["session_id"])
    after = state_path.read_bytes()
    assert record["status"] == "running"
    assert after == before
