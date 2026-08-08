from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import service
from ..schemas.envelope import needs_input
from ..session.state_machine import public_state_name
from ..validation.decisions import pipeline_decision_options
from .common import CONTROL_KEYS, failure


def predict_propose_pipeline_plan(
    session_id: str,
    objective: str = "balanced",
    search_intensity: str = "fast",
    max_models: int = 2,
    max_training_minutes: float | None = None,
    explainability_required: bool = False,
) -> dict[str, Any]:
    """阶段工具：基于数据画像生成完整流水线推荐及全部选项。前置状态：VARIABLES_CONFIRMED；迁移到 PIPELINE_PROPOSED。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        result = service.propose_pipeline_plan(
            session_id,
            objective,
            search_intensity,
            max_models,
            max_training_minutes,
            explainability_required,
        )
        data = {key: value for key, value in result.items() if key not in CONTROL_KEYS}
        return needs_input(
            session_id=session_id,
            state=public_state_name(result["stage"]),
            data=data,
            options=pipeline_decision_options(result),
            needs_user_decision=["pipeline_confirmation"],
            next_tool="predict_confirm_pipeline_plan",
            message="已生成数据自适应推荐和全部可选方案，请让用户接受、修改或暂停",
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(
            session_id,
            DomainError("生成流水线方案失败", code="INTERNAL_ERROR", recoverable=False),
        )
