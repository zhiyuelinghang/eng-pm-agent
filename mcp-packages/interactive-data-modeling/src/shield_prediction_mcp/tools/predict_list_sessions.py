from __future__ import annotations

from typing import Any

from .context import service
from .common import call_sync


def predict_list_sessions() -> dict[str, Any]:
    """只读探查工具：列出未过期会话。前置条件：无；无副作用。"""
    return call_sync(
        None,
        lambda: {"sessions": service.list_sessions(), "message": "会话列表已返回"},
    )
