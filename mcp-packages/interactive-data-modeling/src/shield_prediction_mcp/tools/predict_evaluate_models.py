from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import jobs, service
from ..schemas.envelope import needs_input, running
from ..session.state_machine import public_state_name
from .common import failure


def predict_evaluate_models(session_id: str, confirm: bool = False) -> dict[str, Any]:
    """阶段工具：异步评估保留测试集。前置状态：TRAINED；成功后迁移到 EVALUATED。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        state = service.store.load(session_id)
        service.store.require_stage(state, "trained", "evaluated")
        if not confirm:
            return needs_input(
                session_id=session_id,
                state=public_state_name(state["stage"]),
                options={
                    "evaluation_confirmation": {
                        "type": "confirm",
                        "candidates": [
                            {"value": True, "label": "开始评估", "reason": "使用隔离测试集计算最终指标"},
                            {"value": False, "label": "返回调整", "reason": "不读取测试集并回退修改方案"},
                        ],
                    }
                },
                needs_user_decision=["evaluation_confirmation"],
                next_tool="predict_evaluate_models",
                message="读取保留测试集前需要用户确认",
            )
        record = jobs.submit(
            session_id,
            "evaluate",
            method_name="evaluate_models",
            args=(session_id, True),
        )
        return running(
            session_id=session_id,
            state=public_state_name(state["stage"]),
            data={
                "job_id": record["job_id"],
                "job_status": "running",
                "progress": 0.0,
                "operation": "evaluate",
            },
            next_tool="predict_get_job_status",
            message="评估任务已提交",
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(session_id, DomainError("评估任务提交失败", code="INTERNAL_ERROR", recoverable=False))
