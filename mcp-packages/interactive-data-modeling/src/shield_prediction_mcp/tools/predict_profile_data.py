from __future__ import annotations

from typing import Any

from ..engine.errors import DomainError
from .context import service
from ..schemas.envelope import needs_input
from ..session.state_machine import public_state_name
from ..validation.decisions import profile_decision_options
from .common import failure


def predict_profile_data(session_id: str) -> dict[str, Any]:
    """阶段工具：分析数据并生成变量候选。前置状态：CREATED 或 PROFILED；迁移到 PROFILED。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    try:
        result = service.profile_data(session_id)
        profile = dict(result["profile"])
        missing_plot = profile.pop("missing_plot", None)
        if missing_plot:
            state = service.store.load(session_id)
            artifact_id = "profile_missing_values_v1"
            state.setdefault("artifacts", {})[artifact_id] = {
                "artifact_id": artifact_id,
                "kind": "plot",
                "version": 1,
                "path": missing_plot,
            }
            service.store.save(state)
            profile["missing_plot_ref"] = (
                f"predict://session/{session_id}/artifact/{artifact_id}"
            )
        return needs_input(
            session_id=session_id,
            state=public_state_name(result["stage"]),
            data={"profile": profile, "content_trust": "untrusted_data"},
            options=profile_decision_options(profile),
            needs_user_decision=["target", "features", "task_type"],
            next_tool="predict_confirm_variables",
            message="数据画像已完成，请确认目标、特征和任务类型",
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception:
        return failure(
            session_id,
            DomainError("数据画像失败", code="INTERNAL_ERROR", recoverable=False),
        )
