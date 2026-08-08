from __future__ import annotations

from typing import Any

from .context import service
from .common import call_sync


def predict_create_session(
    data_path: str | None = None,
    output_dir: str | None = None,
    data_ref: str | None = None,
) -> dict[str, Any]:
    """阶段工具：创建预测建模会话并迁移到 CREATED。平台聊天附件必须使用预处理阶段返回的 data_ref；独立客户端可继续使用本地 data_path。下一步调用 predict_profile_data。当返回 needs_user_decision 时，必须把 options 呈现给用户并等待其选择，不得替用户决定、不得跳过。"""
    return call_sync(
        None,
        lambda: service.create_session(data_path, output_dir, data_ref),
    )
