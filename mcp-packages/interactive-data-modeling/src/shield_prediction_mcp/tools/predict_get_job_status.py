from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import jobs, service
from ..schemas.envelope import error, needs_input, ok, running
from ..schemas.errors import sanitize_error_details
from ..session.state_machine import public_state_name
from .common import failure, legacy_data, mapped_next_tool, normalized_state


def predict_get_job_status(
    job_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """只读探查工具：仅凭全局 job_id 读取异步任务状态、进度和结果；session_id 可选且仅用于加速定位；无副作用。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        # Preserve the v2.0 Python positional call form
        # predict_get_job_status(session_id, job_id) while exposing the standard
        # MCP signature predict_get_job_status(job_id, session_id?).
        if job_id.startswith("predict_sess_") and (session_id or "").startswith("predict_job_"):
            job_id, session_id = str(session_id), job_id
        record = jobs.get(job_id, session_id)
        owner = session_id or jobs._find_session_id(job_id)
        state = public_state_name(service.store.load(owner).get("stage"))
        if record["status"] == "running":
            return running(
                session_id=owner,
                state=state,
                data={
                    "job_id": job_id,
                    "job_status": "running",
                    "operation": record["operation"],
                    "progress": record["progress"],
                },
                next_tool="predict_get_job_status",
                message="任务仍在运行",
            )
        if record["status"] == "failed":
            details = sanitize_error_details(record.get("error") or {})
            if details["recoverable"]:
                return needs_input(
                    session_id=owner,
                    state=state,
                    data={
                        "job_id": job_id,
                        "job_status": "failed",
                        "operation": record["operation"],
                        "progress": 1.0,
                    },
                    options={
                        "correction": {
                            "type": "free_text",
                            "candidates": [
                                {
                                    "value": "correct_and_retry",
                                    "label": "修正后重试",
                                    "reason": details["suggestion"],
                                }
                            ],
                        }
                    },
                    needs_user_decision=["correction"],
                    next_tool={
                        "train": "predict_confirm_pipeline_plan",
                        "evaluate": "predict_evaluate_models",
                        "export": "predict_export_model",
                    }.get(record["operation"]),
                    message=details["message"],
                    error=details,
                )
            return error(
                session_id=owner,
                state=state,
                data={
                    "job_id": job_id,
                    "job_status": "failed",
                    "operation": record["operation"],
                    "progress": 1.0,
                },
                message="异步任务失败",
                error=details,
            )
        result = record.get("result") or {}
        return ok(
            session_id=owner,
            state=normalized_state(result, owner),
            data={
                "job_id": job_id,
                "job_status": "succeeded",
                "operation": record["operation"],
                "progress": 1.0,
                "result": legacy_data(result),
            },
            next_tool=mapped_next_tool(result.get("next_tool")),
            message=str(result.get("message", "异步任务已完成")),
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(session_id, DomainError("读取任务状态失败", code="INTERNAL_ERROR", recoverable=False))
