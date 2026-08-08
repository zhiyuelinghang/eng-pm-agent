from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..engine.errors import DomainError
from ..engine.utils import safe_name
from ..schemas.artifacts import public_artifact_metadata
from ..schemas.errors import ErrorCode
from .state_machine import LEGACY_STAGES, public_state_name, transition_allowed

STAGES = LEGACY_STAGES

SUPPORTED_DATA_SUFFIXES = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".json",
    ".jsonl",
    ".ndjson",
    ".parquet",
    ".pq",
}


WorkflowError = DomainError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_runtime_root() -> Path:
    platform_state_root = os.environ.get("AGENTSCOPE_MCP_STATE_DIR", "").strip()
    if platform_state_root:
        return Path(platform_state_root).expanduser().resolve()

    configured = (
        os.environ.get("PREDICT_MCP_WORKDIR")
        or os.environ.get("DATA_MODELING_MCP_WORKDIR")
        or os.environ.get("SHIELD_MCP_WORKDIR")
    )
    base = (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[3] / "runtime"
    )
    platform_session_id = os.environ.get("AGENTSCOPE_SESSION_ID", "").strip()
    if not platform_session_id:
        return base
    scope_source = "\0".join(
        (
            os.environ.get("AGENTSCOPE_USER_ID", ""),
            os.environ.get("AGENTSCOPE_AGENT_ID", ""),
            platform_session_id,
        ),
    )
    scope_id = hashlib.sha256(scope_source.encode("utf-8")).hexdigest()[:32]
    return base / "platform-scopes" / scope_id


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    return max(1, value)


def _allowed_roots(variable: str, defaults: list[Path]) -> tuple[Path, ...]:
    configured = os.environ.get(variable, "")
    raw = [Path(item) for item in configured.split(os.pathsep) if item.strip()] if configured else defaults
    return tuple(path.expanduser().resolve() for path in raw)


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


class SessionStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else default_runtime_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.imports_dir = self.root / "_imports"
        self.imports_dir.mkdir(parents=True, exist_ok=True)
        self.imports_index_path = self.imports_dir / "index.json"
        self.platform_scoped = bool(
            os.environ.get("AGENTSCOPE_MCP_STATE_DIR", "").strip()
            or os.environ.get("AGENTSCOPE_SESSION_ID", "").strip()
        )
        home = Path.home().resolve()
        self.allowed_data_roots = _allowed_roots(
            "PREDICT_ALLOWED_DATA_ROOTS",
            (
                [self.imports_dir]
                if self.platform_scoped
                else [home, Path(tempfile.gettempdir()).resolve(), Path.cwd().resolve()]
            ),
        )
        self.allowed_output_roots = _allowed_roots(
            "PREDICT_ALLOWED_OUTPUT_ROOTS",
            (
                [self.root]
                if self.platform_scoped
                else [self.root, home, Path(tempfile.gettempdir()).resolve()]
            ),
        )
        self.ttl_seconds = _positive_int("PREDICT_SESSION_TTL_SECONDS", 7 * 24 * 60 * 60)
        self.max_sessions = _positive_int("PREDICT_MAX_SESSIONS", 100)
        self.max_file_bytes = _positive_int("PREDICT_MAX_FILE_BYTES", 2 * 1024 * 1024 * 1024)
        self.max_runtime_bytes = _positive_int("PREDICT_MAX_RUNTIME_BYTES", 20 * 1024 * 1024 * 1024)
        self.import_ttl_seconds = _positive_int("PREDICT_IMPORT_TTL_SECONDS", 24 * 60 * 60)
        self.cleanup()
        self._cleanup_interval = _positive_int("PREDICT_CLEANUP_INTERVAL_SECONDS", 60)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="predict-session-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def session_dir(self, session_id: str) -> Path:
        if not re.fullmatch(r"(?:predict_sess_)?[0-9a-f]{32}", session_id):
            raise WorkflowError(
                "无效的 session_id",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="使用 predict_create_session 返回的 session_id",
            )
        return self.root / session_id

    def state_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def import_data(
        self,
        file_name: str,
        content_base64: str,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        """Stage one platform attachment without exposing its server path."""

        original_name = Path(file_name or "data").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_DATA_SUFFIXES:
            supported = "、".join(sorted(SUPPORTED_DATA_SUFFIXES))
            raise WorkflowError(
                f"不支持的数据格式；允许: {supported}",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="上传 CSV、TSV、Excel、JSON、JSONL 或 Parquet 文件",
            )
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise WorkflowError(
                "数据附件内容不是有效的 Base64",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="请重新选择本地文件上传",
            ) from exc
        if not content:
            raise WorkflowError(
                "数据附件为空",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="请选择包含数据的文件",
            )
        if len(content) > self.max_file_bytes:
            raise WorkflowError(
                "数据文件大小超出服务器上限",
                code=ErrorCode.RESOURCE_LIMIT.value,
                suggestion="缩小文件或由管理员调整 PREDICT_MAX_FILE_BYTES",
            )

        digest = hashlib.sha256(content).hexdigest()
        token = digest[:32]
        stored_name = f"{token}_{safe_name(original_name)}"
        target = (self.imports_dir / stored_name).resolve()
        if not _within(target, (self.imports_dir.resolve(),)):
            raise WorkflowError(
                "拒绝写入数据导入目录之外的位置",
                code=ErrorCode.INTERNAL_ERROR.value,
                recoverable=False,
            )
        with self._lock:
            if not target.is_file() or target.stat().st_size != len(content):
                temporary = self.imports_dir / f".{token}.{uuid.uuid4().hex}.tmp"
                temporary.write_bytes(content)
                os.replace(temporary, target)
            index = self._load_import_index()
            previous = index.get(token, {})
            previous_name = str(previous.get("stored_name", "")).strip()
            previous_target = (
                (self.imports_dir / previous_name).resolve()
                if previous_name
                else None
            )
            if (
                previous_target is not None
                and previous_target != target
                and _within(previous_target, (self.imports_dir.resolve(),))
                and previous_target.is_file()
            ):
                previous_target.unlink(missing_ok=True)
            index[token] = {
                "stored_name": stored_name,
                "file_name": original_name,
                "media_type": media_type,
                "sha256": digest,
                "size": len(content),
                "created_at": utc_now(),
            }
            self._save_import_index(index)
        return {
            "data_ref": f"predict-data://{token}",
            "file_name": original_name,
            "media_type": media_type,
            "size": len(content),
            "sha256": digest,
            "next_tool": "create_session",
            "message": "数据附件已安全导入",
        }

    def resolve_data_ref(self, data_ref: str) -> Path:
        match = re.fullmatch(r"predict-data://([0-9a-f]{32})", data_ref.strip())
        if match is None:
            raise WorkflowError(
                "无效的数据引用",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="使用平台附件导入结果中的 data_ref",
            )
        token = match.group(1)
        with self._lock:
            entry = self._load_import_index().get(token)
        if not entry:
            raise WorkflowError(
                "数据引用不存在或已过期",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="重新上传数据附件后再创建建模会话",
            )
        target = (self.imports_dir / str(entry.get("stored_name", ""))).resolve()
        if not _within(target, (self.imports_dir.resolve(),)) or not target.is_file():
            raise WorkflowError(
                "数据引用不存在或已过期",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="重新上传数据附件后再创建建模会话",
            )
        return target

    def create(
        self,
        data_path: str,
        output_dir: str | None = None,
        *,
        snapshot_source: bool = False,
    ) -> dict[str, Any]:
        source = Path(data_path).expanduser().resolve()
        if not source.is_file():
            raise WorkflowError(
                "数据文件不存在或不可访问",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="检查路径并确保文件位于允许的数据目录",
            )
        if not _within(source, self.allowed_data_roots):
            raise WorkflowError(
                "数据文件不在服务器允许的读取目录中",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="设置 PREDICT_ALLOWED_DATA_ROOTS 或移动文件到允许目录",
            )
        if source.suffix.lower() not in SUPPORTED_DATA_SUFFIXES:
            supported = "、".join(sorted(SUPPORTED_DATA_SUFFIXES))
            raise WorkflowError(
                f"不支持的数据格式；允许: {supported}",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="转换为受支持的表格格式后重新创建会话",
            )
        if source.stat().st_size > self.max_file_bytes:
            raise WorkflowError(
                "数据文件大小超出服务器上限",
                code=ErrorCode.RESOURCE_LIMIT.value,
                suggestion="缩小文件或由管理员调整 PREDICT_MAX_FILE_BYTES",
            )

        self.cleanup()
        self._enforce_capacity()
        self._enforce_runtime_capacity()
        session_id = f"predict_sess_{uuid.uuid4().hex}"
        session_dir = self.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=False)
        if snapshot_source:
            input_dir = session_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            snapshot = input_dir / safe_name(source.name)
            try:
                shutil.copy2(source, snapshot)
            except OSError:
                self._safe_remove_session(session_dir)
                raise
            source = snapshot.resolve()
        output_base = Path(output_dir).expanduser().resolve() if output_dir else None
        if output_base and not _within(output_base, self.allowed_output_roots):
            self._safe_remove_session(session_dir)
            raise WorkflowError(
                "输出目录不在服务器允许的写入目录中",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="设置 PREDICT_ALLOWED_OUTPUT_ROOTS 或使用默认输出目录",
            )
        # A custom root receives a server-owned per-session child.  TTL cleanup
        # can therefore remove this session's artifacts without touching any
        # unrelated files in the caller's directory.
        artifacts_dir = output_base / session_id if output_base else session_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / ".predict-session-owner").write_text(session_id, encoding="utf-8")
        state: dict[str, Any] = {
            "schema_version": 2,
            "session_id": session_id,
            "stage": "created",
            "state": "CREATED",
            "data_path": str(source),
            "session_dir": str(session_dir),
            "artifacts_dir": str(artifacts_dir),
            "managed_artifacts_dir": True,
            "inputs": {"dataset_ref": str(source)},
            "config": {},
            "jobs": {},
            "artifacts": {},
            "artifact_versions": {},
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "history": [{"stage": "created", "at": utc_now()}],
        }
        self.save(state)
        return state

    def load(self, session_id: str) -> dict[str, Any]:
        path = self.state_path(session_id)
        if not path.is_file():
            raise WorkflowError(
                "会话不存在或已过期",
                code=ErrorCode.UNKNOWN_SESSION.value,
                suggestion="调用 predict_create_session 重新创建会话",
            )
        with self._lock, path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if self._is_expired(state) and not self._has_running_job(state):
            # Read-only callers must remain side-effect free.  Expired data is
            # hidden immediately; the independent cleanup worker removes it.
            raise WorkflowError(
                "会话不存在或已过期",
                code=ErrorCode.UNKNOWN_SESSION.value,
                suggestion="调用 predict_create_session 重新创建会话",
            )
        state.setdefault("state", public_state_name(state.get("stage")))
        state.setdefault("schema_version", 1)
        state.setdefault("jobs", {})
        state.setdefault("artifacts", {})
        state.setdefault("artifact_versions", {})
        return state

    def save(self, state: dict[str, Any]) -> None:
        session_id = state["session_id"]
        session_dir = self.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        state["state"] = public_state_name(state.get("stage"))
        state["updated_at"] = utc_now()
        path = self.state_path(session_id)
        temp = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        with self._lock, temp.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, default=str)
        last_error: OSError | None = None
        for attempt in range(50):
            try:
                temp.replace(path)
                last_error = None
                break
            except PermissionError as exc:
                # Windows cannot replace a file while another process has it
                # briefly open for a read-only status poll.
                last_error = exc
                time.sleep(min(0.01 * (attempt + 1), 0.1))
        if last_error is not None:
            temp.unlink(missing_ok=True)
            raise last_error
        self._enforce_runtime_capacity(protected_session_id=session_id)

    def require_stage(self, state: dict[str, Any], *allowed: str) -> None:
        if state.get("stage") not in allowed:
            expected = "、".join(allowed)
            raise WorkflowError(
                f"当前阶段为 {state.get('stage')}，该操作仅允许在 {expected} 阶段执行。"
                "请按工作流顺序调用。"
            )

    def advance(self, state: dict[str, Any], stage: str, **updates: Any) -> dict[str, Any]:
        if stage not in STAGES:
            raise WorkflowError(f"未知阶段: {stage}")
        current = str(state.get("stage", ""))
        if not transition_allowed(current, stage):
            raise WorkflowError(
                f"当前状态 {public_state_name(current)} 不允许迁移到 {public_state_name(stage)}",
                code=ErrorCode.WRONG_STATE.value,
                suggestion="调用 predict_get_status 获取允许的下一步",
            )
        state.update(updates)
        state["stage"] = stage
        state["state"] = public_state_name(stage)
        state.setdefault("history", []).append({"stage": stage, "at": utc_now()})
        self.save(state)
        return state

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for child in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            state_path = child / "session.json"
            if not state_path.is_file():
                continue
            try:
                with state_path.open("r", encoding="utf-8") as handle:
                    state = json.load(handle)
                if self._is_expired(state) and not self._has_running_job(state):
                    continue
                sessions.append(
                    {
                        "session_id": state["session_id"],
                        "state": public_state_name(state["stage"]),
                        "updated_at": state["updated_at"],
                    }
                )
            except (OSError, KeyError, json.JSONDecodeError):
                continue
        return sessions

    def cleanup(self) -> None:
        if not self.root.exists():
            return
        with self._lock:
            for child in self.root.iterdir():
                state_path = child / "session.json"
                if not state_path.is_file():
                    continue
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if self._is_expired(state) and not self._has_running_job(state):
                        self._safe_remove_session(child)
                except (OSError, KeyError, ValueError, json.JSONDecodeError):
                    continue
            self._cleanup_imports()

    def _load_import_index(self) -> dict[str, dict[str, Any]]:
        if not self.imports_index_path.is_file():
            return {}
        try:
            value = json.loads(self.imports_index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(key): dict(item)
            for key, item in value.items()
            if isinstance(item, dict)
        }

    def _save_import_index(self, value: dict[str, dict[str, Any]]) -> None:
        temporary = self.imports_index_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.imports_index_path)

    def _cleanup_imports(self) -> None:
        index = self._load_import_index()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.import_ttl_seconds)
        retained: dict[str, dict[str, Any]] = {}
        for token, entry in index.items():
            try:
                created_at = datetime.fromisoformat(str(entry["created_at"]))
            except (KeyError, TypeError, ValueError):
                created_at = datetime.min.replace(tzinfo=timezone.utc)
            target = (self.imports_dir / str(entry.get("stored_name", ""))).resolve()
            if created_at >= cutoff and _within(target, (self.imports_dir.resolve(),)):
                retained[token] = entry
                continue
            if _within(target, (self.imports_dir.resolve(),)):
                target.unlink(missing_ok=True)
        if retained != index:
            self._save_import_index(retained)

    def _enforce_capacity(self) -> None:
        sessions = [
            child
            for child in self.root.iterdir()
            if child.is_dir() and (child / "session.json").is_file()
        ]
        if len(sessions) < self.max_sessions:
            return
        sessions.sort(key=lambda item: item.stat().st_mtime)
        for child in sessions[: len(sessions) - self.max_sessions + 1]:
            try:
                state = json.loads((child / "session.json").read_text(encoding="utf-8"))
                if any(job.get("status") == "running" for job in state.get("jobs", {}).values()):
                    continue
            except (OSError, json.JSONDecodeError):
                pass
            self._safe_remove_session(child)
        remaining = sum(
            1
            for child in self.root.iterdir()
            if child.is_dir() and (child / "session.json").is_file()
        )
        if remaining >= self.max_sessions:
            raise WorkflowError(
                "会话容量已达到上限，且现有会话正在运行任务",
                code=ErrorCode.RESOURCE_LIMIT.value,
                suggestion="等待任务完成或由管理员清理会话",
            )

    def runtime_size_bytes(self) -> int:
        total = 0
        paths = list(self.root.rglob("*"))
        for state in self._iter_states():
            managed = self._managed_external_artifacts(state)
            if managed:
                paths.extend(managed.rglob("*"))
        for path in paths:
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _enforce_runtime_capacity(self, protected_session_id: str | None = None) -> None:
        if self.runtime_size_bytes() <= self.max_runtime_bytes:
            return
        candidates = sorted(
            (
                child
                for child in self.root.iterdir()
                if child.is_dir() and (child / "session.json").is_file()
            ),
            key=lambda item: item.stat().st_mtime,
        )
        for child in candidates:
            if child.name == protected_session_id:
                continue
            try:
                state = json.loads((child / "session.json").read_text(encoding="utf-8"))
                if self._has_running_job(state):
                    continue
            except (OSError, json.JSONDecodeError):
                pass
            self._safe_remove_session(child)
            if self.runtime_size_bytes() <= self.max_runtime_bytes:
                return
        raise WorkflowError(
            "会话存储空间已达到上限",
            code=ErrorCode.RESOURCE_LIMIT.value,
            suggestion="缩小本次任务或由管理员调整 PREDICT_MAX_RUNTIME_BYTES",
        )

    def _safe_remove_session(self, target: Path) -> None:
        resolved = target.resolve()
        if resolved == self.root or self.root not in resolved.parents:
            raise WorkflowError(
                "拒绝清理会话根目录以外的路径",
                code=ErrorCode.INTERNAL_ERROR.value,
                recoverable=False,
            )
        state_path = resolved / "session.json"
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                managed = self._managed_external_artifacts(state)
                if managed:
                    shutil.rmtree(managed, ignore_errors=True)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        shutil.rmtree(resolved, ignore_errors=True)

    def rewind(
        self,
        state: dict[str, Any],
        target_stage: str,
        *,
        remove_keys: list[str],
        reason: str,
    ) -> dict[str, Any]:
        current = str(state.get("stage", ""))
        if not transition_allowed(current, target_stage):
            raise WorkflowError(
                f"当前状态 {public_state_name(current)} 不允许回退到 {public_state_name(target_stage)}",
                code=ErrorCode.WRONG_STATE.value,
                suggestion="调用 predict_get_status 获取允许的回退目标",
            )
        for key in remove_keys:
            state.pop(key, None)
        state["stage"] = target_stage
        state["state"] = public_state_name(target_stage)
        state.setdefault("history", []).append(
            {"stage": target_stage, "at": utc_now(), "rewind": True, "reason": reason}
        )
        self.save(state)
        return state

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(self._cleanup_interval)
            try:
                self.cleanup()
            except Exception:
                # Cleanup is best effort and must never terminate the server.
                continue

    def _is_expired(self, state: dict[str, Any]) -> bool:
        try:
            updated = datetime.fromisoformat(str(state["updated_at"]))
        except (KeyError, TypeError, ValueError):
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)
        return updated < cutoff

    @staticmethod
    def _has_running_job(state: dict[str, Any]) -> bool:
        return any(job.get("status") == "running" for job in state.get("jobs", {}).values())

    def _iter_states(self):
        if not self.root.exists():
            return
        for child in self.root.iterdir():
            state_path = child / "session.json"
            if not state_path.is_file():
                continue
            try:
                yield json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

    def _managed_external_artifacts(self, state: dict[str, Any]) -> Path | None:
        if not state.get("managed_artifacts_dir"):
            return None
        raw = state.get("artifacts_dir")
        if not raw:
            return None
        candidate = Path(raw).expanduser().resolve()
        session_dir = self.session_dir(str(state["session_id"])).resolve()
        if candidate == session_dir or session_dir in candidate.parents:
            return None
        if not _within(candidate, self.allowed_output_roots):
            return None
        marker = candidate / ".predict-session-owner"
        try:
            owner = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return candidate if owner == state.get("session_id") else None


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {
        "session_id": state["session_id"],
        "schema_version": state.get("schema_version", 1),
        "state": public_state_name(state.get("stage")),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "inputs": {"dataset_ref": "bound"},
        "config": state.get("config", {}),
        "variables": state.get("variables"),
        "preprocessing_config": state.get("preprocessing_config"),
        "selected_models": state.get("selected_models", []),
        "training_config": state.get("training_config"),
        "confirmed_pipeline_plan": state.get("confirmed_pipeline_plan"),
        "pipeline_plan_proposal": state.get("pipeline_plan_proposal"),
        "artifact_versions": state.get("artifact_versions", {}),
    }
    if state.get("profile"):
        public["profile"] = {
            key: value for key, value in state["profile"].items() if key != "missing_plot"
        }
    public["artifacts"] = {
        artifact_id: public_artifact_metadata(
            artifact,
            session_id=str(state["session_id"]),
        )
        for artifact_id, artifact in state.get("artifacts", {}).items()
    }
    public["jobs"] = {
        job_id: {
            "job_id": job_id,
            "operation": job.get("operation"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "updated_at": job.get("updated_at"),
        }
        for job_id, job in state.get("jobs", {}).items()
    }
    return {key: value for key, value in public.items() if value is not None}
