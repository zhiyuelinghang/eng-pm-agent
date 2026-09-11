"""Capability boundaries, independent of editable database-tool policies.

This module never judges material correctness. Only the MCP service can publish
a verdict, and only the human confirmation endpoint can write formal data.
"""
from typing import Any

from fastapi import HTTPException


DRAFT_TABLE = "project_initialization_drafts"
SECTION_TABLE = "project_initialization_draft_sections"
SYSTEM_TABLES = frozenset({
    "project_initialization_draft_records", "project_initialization_validation_runs",
    "project_initialization_validation_issues", "project_initialization_change_previews",
    "project_initialization_applied_changes",
})
SYSTEM_FIELDS = {
    DRAFT_TABLE: frozenset({"status", "payload", "validation_issues", "revision", "applied_at", "applied_by"}),
    SECTION_TABLE: frozenset({"revision"}),
}


def agent_writable_fields(table_name: str, fields: list[str] | set[str]) -> set[str]:
    if table_name in SYSTEM_TABLES:
        return set()
    return set(fields) - SYSTEM_FIELDS.get(table_name, frozenset())


def require_initialization_tool_authority(
    table_name: str, operation: str, context: Any, values: dict[str, Any],
    fixed_values: dict[str, Any], bound_values: dict[str, Any],
) -> None:
    if operation == "read":
        return
    if table_name in SYSTEM_TABLES:
        raise HTTPException(403, "核验结果、快照及提交记录由平台专用流程维护，智能体无权写入。")
    if context.conversation.conversation_type == "initialization":
        allowed = (table_name == DRAFT_TABLE and operation == "create") or (
            table_name == SECTION_TABLE and operation in {"create", "update"}
        )
        if not allowed:
            raise HTTPException(403, "初始化智能体只能创建草稿或写入资料分区，正式数据须由用户确认提交。")
    supplied = set(values) | set(fixed_values) | set(bound_values)
    protected = SYSTEM_FIELDS.get(table_name, frozenset())
    # A configured initial envelope is allowed, but model arguments cannot set
    # its status, payload or verdict. The executor always supplies these values.
    if table_name == DRAFT_TABLE and operation == "create":
        defaults = {"status": "building", "payload": {}, "validation_issues": []}
        supplied -= {key for key, value in defaults.items() if key not in values and key not in bound_values and fixed_values.get(key) == value}
    if supplied & protected:
        raise HTTPException(403, "智能体不能设置核验状态、核验问题或系统维护字段。")
