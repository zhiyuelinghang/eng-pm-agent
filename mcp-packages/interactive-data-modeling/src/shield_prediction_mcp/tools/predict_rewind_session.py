from __future__ import annotations

from typing import Any

from .context import service
from .common import call_sync


def predict_rewind_session(
    session_id: str,
    target_state: str,
    reason: str = "user_revision",
) -> dict[str, Any]:
    """阶段工具：回退到较早决策状态。前置条件：目标状态早于当前状态；迁移到指定状态。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    return call_sync(
        session_id,
        lambda: service.rewind_session(session_id, target_state.lower(), reason),
    )
