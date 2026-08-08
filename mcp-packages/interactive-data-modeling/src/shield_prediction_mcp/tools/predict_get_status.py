from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import service
from ..schemas.envelope import needs_input, ok, running
from ..session.store import public_state
from ..validation.decisions import pipeline_decision_options, profile_decision_options
from .common import failure


NEXT_BY_STATE = {
    "CREATED": "predict_profile_data",
    "PROFILED": "predict_confirm_variables",
    "VARIABLES_CONFIRMED": "predict_propose_pipeline_plan",
    "PIPELINE_PROPOSED": "predict_confirm_pipeline_plan",
    "TRAINED": "predict_evaluate_models",
    "EVALUATED": "predict_export_model",
}


def predict_get_status(session_id: str) -> dict[str, Any]:
    """只读探查工具：返回当前状态、已有配置和缺失决策。前置条件：会话存在；无副作用。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        raw = service.store.load(session_id)
        state = str(raw["state"])
        visible = public_state(raw)
        running_jobs = [
            {"job_id": job_id, "operation": job["operation"], "progress": job["progress"]}
            for job_id, job in raw.get("jobs", {}).items()
            if job.get("status") == "running"
        ]
        if running_jobs:
            return running(
                session_id=session_id,
                state=state,
                data={"session": visible, "jobs": running_jobs},
                next_tool="predict_get_job_status",
                message="会话存在运行中的任务",
            )
        missing: list[str] = []
        options: dict[str, Any] = {}
        if state == "PROFILED":
            missing = ["target", "features", "task_type"]
            options = profile_decision_options(raw.get("profile", {}))
        elif state == "PIPELINE_PROPOSED":
            missing = ["pipeline_confirmation"]
            options = pipeline_decision_options(raw["pipeline_plan_proposal"])
        elif state == "TRAINED":
            missing = ["evaluation_confirmation"]
            options = {
                "evaluation_confirmation": {
                    "type": "confirm",
                    "candidates": [
                        {
                            "value": True,
                            "label": "评估保留测试集",
                            "reason": "计算最终泛化指标并生成评估产物",
                        },
                        {
                            "value": False,
                            "label": "返回修改方案",
                            "reason": "不读取测试集，先调整模型或训练配置",
                        },
                    ],
                }
            }
        elif state == "EVALUATED":
            missing = ["export_model", "export_confirmation"]
            options = {
                "export_model": {
                    "type": "single_select",
                    "candidates": [
                        {
                            "value": model,
                            "label": model,
                            "reason": "该模型已完成训练和隔离测试集评估",
                        }
                        for model in raw.get("selected_models", [])
                    ],
                },
                "export_confirmation": {
                    "type": "confirm",
                    "candidates": [
                        {"value": True, "label": "确认导出", "reason": "生成版本化部署包"},
                        {"value": False, "label": "暂不导出", "reason": "保留评估结果，稍后继续"},
                    ],
                },
            }
        elif state in {
            "PREPROCESSING_REVIEWED",
            "PREPROCESSED",
            "MODELS_RECOMMENDED",
            "MODELS_SELECTED",
            "TRAINING_CONFIGURED",
        }:
            missing = ["legacy_session_migration"]
            options = {
                "legacy_session_migration": {
                    "type": "confirm",
                    "candidates": [
                        {
                            "value": "VARIABLES_CONFIRMED",
                            "label": "迁移到统一流水线",
                            "reason": "回退到变量已确认状态，再生成符合新契约的完整方案",
                        },
                        {
                            "value": "pause",
                            "label": "暂不迁移",
                            "reason": "保留旧会话文件，不执行计算",
                        },
                    ],
                }
            }
        function = needs_input if missing else ok
        return function(
            session_id=session_id,
            state=state,
            data={"session": visible, "missing_decisions": missing},
            options=options,
            needs_user_decision=missing,
            next_tool=(
                "predict_rewind_session"
                if "legacy_session_migration" in missing
                else NEXT_BY_STATE.get(state)
            ),
            message=("仍有决策需要用户确认" if missing else "当前状态无需补充决策"),
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(session_id, DomainError("读取会话状态失败", code="INTERNAL_ERROR", recoverable=False))
