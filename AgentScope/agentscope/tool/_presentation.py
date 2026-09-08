"""User-facing work metadata, resolved without model calls or tool execution."""
from __future__ import annotations

import re
from typing import Any


def tool_presentation(tool: Any = None, *, name: str = "", display_name: str | None = None,
                      category: str = "general", read_only: bool = False,
                      source: str = "registration") -> dict[str, str]:
    """Use declared labels only; descriptions, SQL and arguments are never inputs.

    This is display metadata, never an authorization decision. Missing or technical
    titles get a stable category fallback instead of exposing implementation names.
    """
    if tool is not None:
        name = tool.name
        display_name = getattr(tool, "display_name", None)
        category = getattr(tool, "presentation_category", getattr(tool, "category", "general"))
        read_only = bool(getattr(tool, "is_read_only", getattr(tool, "read_only", False)))
        if getattr(tool, "assignment_source", None) == "database":
            category, source = "database", "database_catalog"
        elif getattr(tool, "is_mcp", False):
            category, source = "mcp", "mcp_title"
    if category not in {"general", "workspace", "database", "mcp", "memory", "collaboration"}:
        category = "general"
    label = display_name.strip() if isinstance(display_name, str) else ""
    technical = name.split("__")[-1]
    valid = (bool(label) and len(label) <= 80 and label not in {name, technical}
             and not re.search(r"[\x00-\x1f<>`{}\\]|https?://|\b(?:SELECT|INSERT|UPDATE|DELETE)\b.*\b(?:FROM|INTO|SET)\b", label, re.I)
             and not re.fullmatch(r"[A-Za-z0-9_.:/-]+", label))
    if not valid:
        label = {
            "database": "查询业务数据" if read_only else "处理业务数据",
            "mcp": "查询外部资料" if read_only else "处理外部事项",
            "workspace": "查看工作文件" if read_only else "处理工作文件",
            "memory": "查找相关记忆" if read_only else "整理相关记忆",
            "collaboration": "协同处理任务",
        }.get(category, "查询相关信息" if read_only else "处理相关事项")
        source = "fallback"
    return {"label": label, "source": source, "category": category}
