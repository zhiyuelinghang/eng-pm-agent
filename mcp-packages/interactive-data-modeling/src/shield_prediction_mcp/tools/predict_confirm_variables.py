from __future__ import annotations

from typing import Any

from .context import service
from .common import call_sync


def predict_confirm_variables(
    session_id: str,
    target: str,
    features: list[str] | None = None,
    feature_mode: str = "manual",
    task_type: str = "auto",
    time_column: str | None = None,
) -> dict[str, Any]:
    """阶段工具：确认目标、特征和任务类型。前置状态：PROFILED；迁移到 VARIABLES_CONFIRMED。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    return call_sync(
        session_id,
        lambda: service.confirm_variables(
            session_id, target, features, feature_mode, task_type, time_column
        ),
    )
