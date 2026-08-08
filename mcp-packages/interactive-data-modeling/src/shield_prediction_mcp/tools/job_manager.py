from __future__ import annotations

import multiprocessing as mp
import logging
import os
import queue
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..engine.errors import DomainError
from ..engine.utils import safe_name
from ..schemas.errors import ErrorCode, error_from_exception


LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _terminate_process(process: mp.Process, grace_seconds: float = 5) -> None:
    """Hard-stop a worker and wait until the OS confirms it has exited."""

    process.terminate()
    process.join(grace_seconds)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(grace_seconds)


def _job_worker(
    runtime_root: str,
    method_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result_queue: Any,
) -> None:
    """Run one service operation in a killable child process."""

    try:
        # Imported in the child to avoid importing the tool/orchestration layer
        # from the session module at server startup.
        from .orchestrator import InteractiveDataModelingService

        service = InteractiveDataModelingService(Path(runtime_root))
        method = getattr(service, method_name)
        result_queue.put({"kind": "result", "value": method(*args, **kwargs)})
    except DomainError as exc:
        result_queue.put({"kind": "error", "error": error_from_exception(exc)})
    except Exception:
        LOGGER.exception("异步任务子进程执行失败")
        result_queue.put(
            {
                "kind": "error",
                "error": {
                    "code": ErrorCode.JOB_FAILED.value,
                    "message": "异步任务执行失败",
                    "recoverable": False,
                    "suggestion": "稍后重试；若持续失败请联系管理员并提供 session_id 和 job_id",
                },
            }
        )


class JobManager:
    """Persistent process-backed jobs with independently enforced timeouts."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.max_workers = max(1, int(os.environ.get("PREDICT_MAX_CONCURRENT_JOBS", "2")))
        self.max_queued_jobs = max(
            self.max_workers,
            int(os.environ.get("PREDICT_MAX_QUEUED_JOBS", "16")),
        )
        self._context = mp.get_context("spawn")
        self._slots = threading.BoundedSemaphore(self.max_workers)
        self._processes: dict[str, mp.Process] = {}
        self._monitors: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._recover_interrupted_jobs()

    def _recover_interrupted_jobs(self) -> None:
        """A process-local worker cannot resume after restart; persist an honest failure."""

        for summary in self.store.list_sessions():
            try:
                state = self.store.load(summary["session_id"])
            except Exception:
                continue
            changed = False
            for job in state.get("jobs", {}).values():
                if job.get("status") != "running":
                    continue
                job.update(
                    {
                        "status": "failed",
                        "progress": 1.0,
                        "updated_at": _now(),
                        "error": {
                            "code": ErrorCode.JOB_FAILED.value,
                            "message": "服务器重启导致后台任务中断",
                            "recoverable": True,
                            "suggestion": "调用 predict_get_status 后重新提交该阶段任务",
                        },
                    }
                )
                changed = True
            if changed:
                self.store.save(state)

    def submit(
        self,
        session_id: str,
        operation: str,
        *,
        method_name: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.store.load(session_id)
        with self._lock:
            outstanding = sum(thread.is_alive() for thread in self._monitors.values())
            if outstanding >= self.max_queued_jobs:
                raise DomainError(
                    "服务器异步任务队列已达到上限",
                    code=ErrorCode.RESOURCE_LIMIT.value,
                    suggestion="等待已有任务完成后重试",
                )

        job_id = f"predict_job_{uuid.uuid4().hex}"
        record = {
            "job_id": job_id,
            "operation": operation,
            "status": "running",
            "progress": 0.0,
            "created_at": _now(),
            "updated_at": _now(),
            "result": None,
            "error": None,
            "timeout_seconds": max(
                1,
                int(os.environ.get("PREDICT_JOB_TIMEOUT_SECONDS", "3600")),
            ),
        }
        state.setdefault("jobs", {})[job_id] = record
        self.store.save(state)

        monitor = threading.Thread(
            target=self._run_and_monitor,
            args=(
                session_id,
                job_id,
                operation,
                method_name,
                tuple(args),
                dict(kwargs or {}),
                int(record["timeout_seconds"]),
            ),
            name=f"predict-monitor-{job_id[-8:]}",
            daemon=True,
        )
        with self._lock:
            self._monitors[job_id] = monitor
        monitor.start()
        return deepcopy(record)

    def _run_and_monitor(
        self,
        session_id: str,
        job_id: str,
        operation: str,
        method_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        timeout_seconds: int,
    ) -> None:
        with self._slots:
            result_queue = self._context.Queue(maxsize=1)
            process = self._context.Process(
                target=_job_worker,
                args=(str(self.store.root), method_name, args, kwargs, result_queue),
                name=f"predict-job-{job_id[-8:]}",
            )
            with self._lock:
                self._processes[job_id] = process
            process.start()
            deadline = time.monotonic() + timeout_seconds
            limit_error: dict[str, Any] | None = None
            while process.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    limit_error = {
                        "code": ErrorCode.RESOURCE_LIMIT.value,
                        "message": "异步任务超过允许的最长运行时间，工作进程已终止",
                        "recoverable": True,
                        "suggestion": "降低训练强度或由管理员调整 PREDICT_JOB_TIMEOUT_SECONDS",
                    }
                    break
                process.join(min(0.25, remaining))
                try:
                    self.store._enforce_runtime_capacity(protected_session_id=session_id)
                except DomainError as exc:
                    limit_error = error_from_exception(exc)
                    break

            if limit_error is not None:
                if process.is_alive():
                    _terminate_process(process)
                payload = {
                    "kind": "error",
                    "error": limit_error,
                }
            else:
                try:
                    payload = result_queue.get(timeout=1)
                except queue.Empty:
                    payload = {
                        "kind": "error",
                        "error": {
                            "code": ErrorCode.JOB_FAILED.value,
                            "message": "异步任务异常退出且未返回结果",
                            "recoverable": False,
                            "suggestion": "稍后重试；若持续失败请联系管理员",
                        },
                    }

            try:
                result_queue.close()
                result_queue.join_thread()
            except Exception:
                pass
            self._complete(session_id, job_id, operation, payload)
            with self._lock:
                self._processes.pop(job_id, None)
                self._monitors.pop(job_id, None)

    def _complete(
        self,
        session_id: str,
        job_id: str,
        operation: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            state = self.store.load(session_id)
        except DomainError:
            return
        record = state.setdefault("jobs", {}).setdefault(job_id, {"job_id": job_id})
        if payload.get("kind") == "result":
            result = self._artifactize(
                state,
                session_id,
                record_operation=operation,
                value=payload.get("value"),
            )
            record.update(
                {
                    "status": "succeeded",
                    "progress": 1.0,
                    "updated_at": _now(),
                    "result": result,
                    "error": None,
                }
            )
        else:
            record.update(
                {
                    "status": "failed",
                    "progress": 1.0,
                    "updated_at": _now(),
                    "result": None,
                    "error": payload.get("error"),
                }
            )
        self.store.save(state)

    def _artifactize(
        self,
        state: dict[str, Any],
        session_id: str,
        *,
        record_operation: str,
        value: Any,
        parent_key: str = "result",
    ) -> Any:
        """Replace every returned absolute server path with an artifact reference."""

        if isinstance(value, dict):
            public: dict[str, Any] = {}
            for key, item in value.items():
                is_server_path = False
                if isinstance(item, str):
                    try:
                        is_server_path = Path(item).is_absolute()
                    except (OSError, ValueError):
                        is_server_path = False
                if is_server_path:
                    artifact_id = (
                        f"{safe_name(record_operation)}_{safe_name(key)}_{uuid.uuid4().hex[:8]}"
                    )
                    state.setdefault("artifacts", {})[artifact_id] = {
                        "artifact_id": artifact_id,
                        "kind": key.removesuffix("_path").removesuffix("_dir"),
                        "created_at": _now(),
                        "path": item,
                    }
                    clean_key = key.removesuffix("_path").removesuffix("_dir") + "_ref"
                    public[clean_key] = f"predict://session/{session_id}/artifact/{artifact_id}"
                else:
                    public[key] = self._artifactize(
                        state,
                        session_id,
                        record_operation=record_operation,
                        value=item,
                        parent_key=key,
                    )
            return public
        if isinstance(value, list):
            if parent_key == "plots":
                references = []
                for item in value:
                    artifact_id = f"{safe_name(record_operation)}_plot_{uuid.uuid4().hex[:8]}"
                    state.setdefault("artifacts", {})[artifact_id] = {
                        "artifact_id": artifact_id,
                        "kind": "plot",
                        "created_at": _now(),
                        "path": str(item),
                    }
                    references.append(f"predict://session/{session_id}/artifact/{artifact_id}")
                return references
            return [
                self._artifactize(
                    state,
                    session_id,
                    record_operation=record_operation,
                    value=item,
                    parent_key=parent_key,
                )
                for item in value
            ]
        return deepcopy(value)

    def get(self, job_id: str, session_id: str | None = None) -> dict[str, Any]:
        """Read a job record without mutating timeout or session state."""

        owner = session_id or self._find_session_id(job_id)
        state = self.store.load(owner)
        record = state.get("jobs", {}).get(job_id)
        if not record:
            raise DomainError(
                "指定的 job_id 不存在",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="调用 predict_get_status 查看当前会话的任务",
            )
        return deepcopy(record)

    def _find_session_id(self, job_id: str) -> str:
        if not job_id.startswith("predict_job_"):
            raise DomainError(
                "无效的 job_id",
                code=ErrorCode.INVALID_INPUT.value,
                suggestion="使用异步阶段工具返回的 job_id",
            )
        for summary in self.store.list_sessions():
            try:
                state = self.store.load(summary["session_id"])
            except DomainError:
                continue
            if job_id in state.get("jobs", {}):
                return str(summary["session_id"])
        raise DomainError(
            "指定的 job_id 不存在",
            code=ErrorCode.INVALID_INPUT.value,
            suggestion="检查 job_id 或重新提交任务",
        )
