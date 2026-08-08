from __future__ import annotations

from typing import Any

from .common import call_sync
from .context import service


def predict_import_data(
    file_name: str,
    content_base64: str,
    media_type: str | None = None,
) -> dict[str, Any]:
    """阶段工具：安全导入平台上传的表格附件，返回不暴露服务器路径的 data_ref；不创建建模会话。该工具通常由平台附件流水线自动调用；随后使用 predict_create_session(data_ref=...) 创建建模会话。"""
    return call_sync(
        None,
        lambda: service.import_data(file_name, content_base64, media_type),
        message="数据附件已安全导入",
    )
