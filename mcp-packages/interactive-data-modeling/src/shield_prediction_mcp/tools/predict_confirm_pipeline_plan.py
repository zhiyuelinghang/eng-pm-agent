from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import jobs, service
from ..schemas.envelope import needs_input, running
from ..session.state_machine import public_state_name
from .common import failure


def predict_confirm_pipeline_plan(
    session_id: str,
    proposal_id: str,
    missing_default: str | None = None,
    missing_per_column: dict[str, str] | None = None,
    encoding: dict[str, str] | None = None,
    denoise: dict[str, Any] | None = None,
    models: list[str] | None = None,
    split_method: str | None = None,
    tuning: str | None = None,
    train_ratio: float | None = None,
    val_ratio: float | None = None,
    test_ratio: float | None = None,
    n_trials: int | None = None,
    model_params: dict[str, dict[str, Any]] | None = None,
    user_adjustment_note: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """阶段工具：确认完整方案并异步训练。前置状态：PIPELINE_PROPOSED；成功后迁移到 TRAINED。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        state = service.store.load(session_id)
        service.store.require_stage(state, "pipeline_proposed")
        proposal = state.get("pipeline_plan_proposal")
        if not proposal:
            raise DomainError(
                "当前会话没有完整流水线方案",
                code="WRONG_STATE",
                suggestion="调用 predict_propose_pipeline_plan 生成方案",
            )
        if proposal_id != proposal.get("proposal_id"):
            raise DomainError(
                "proposal_id 已过期或不属于当前会话",
                code="VALIDATION_FAILED",
                suggestion="重新调用 predict_propose_pipeline_plan 并使用最新 proposal_id",
            )
        if not confirm:
            return needs_input(
                session_id=session_id,
                state=public_state_name(state["stage"]),
                options={
                    "pipeline_confirmation": {
                        "type": "confirm",
                        "candidates": [
                            {
                                "value": True,
                                "label": "确认并开始训练",
                                "reason": "按推荐方案或本次调用中的修改异步训练",
                            },
                            {
                                "value": False,
                                "label": "暂不训练",
                                "reason": "保留当前方案，稍后继续",
                            },
                        ],
                    }
                },
                needs_user_decision=["pipeline_confirmation"],
                next_tool="predict_confirm_pipeline_plan",
                message="开始训练前需要用户明确确认",
            )
        record = jobs.submit(
            session_id,
            "train",
            method_name="confirm_pipeline_plan",
            args=(
                session_id,
                proposal_id,
                missing_default,
                missing_per_column,
                encoding,
                denoise,
                models,
                split_method,
                tuning,
                train_ratio,
                val_ratio,
                test_ratio,
                n_trials,
                model_params,
                user_adjustment_note,
                True,
            ),
        )
        return running(
            session_id=session_id,
            state=public_state_name(state["stage"]),
            data={
                "job_id": record["job_id"],
                "job_status": "running",
                "progress": record["progress"],
                "operation": "train",
            },
            next_tool="predict_get_job_status",
            message="训练任务已提交",
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(session_id, DomainError("训练任务提交失败", code="INTERNAL_ERROR", recoverable=False))
