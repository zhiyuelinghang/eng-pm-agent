from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import jobs, service
from ..schemas.envelope import needs_input, running
from ..session.state_machine import public_state_name
from .common import failure


def predict_export_model(
    session_id: str,
    model_type: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """阶段工具：异步导出指定模型。前置状态：EVALUATED；成功后迁移到 EXPORTED。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        state = service.store.load(session_id)
        service.store.require_stage(state, "evaluated", "exported")
        if not confirm:
            models = list(state.get("selected_models", []))
            return needs_input(
                session_id=session_id,
                state=public_state_name(state["stage"]),
                options={
                    "export_confirmation": {
                        "type": "confirm",
                        "candidates": [
                            {"value": True, "label": "确认导出", "reason": f"导出模型 {model_type}"},
                            {"value": False, "label": "重新选择", "reason": f"可选模型：{models}"},
                        ],
                    }
                },
                needs_user_decision=["export_confirmation"],
                next_tool="predict_export_model",
                message="导出前需要用户确认模型",
            )
        record = jobs.submit(
            session_id,
            "export",
            method_name="export_model",
            args=(session_id, model_type, True),
        )
        return running(
            session_id=session_id,
            state=public_state_name(state["stage"]),
            data={
                "job_id": record["job_id"],
                "job_status": "running",
                "progress": 0.0,
                "operation": "export",
            },
            next_tool="predict_get_job_status",
            message="导出任务已提交",
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(session_id, DomainError("导出任务提交失败", code="INTERNAL_ERROR", recoverable=False))
