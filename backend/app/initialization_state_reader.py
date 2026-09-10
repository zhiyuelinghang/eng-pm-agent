"""Bounded, permission-filtered reads of the project's confirmed baseline."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DatabaseInteraction, DatabaseInteractionTablePolicy
from .project_initialization import build_initialization_state


class InitializationStateReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section: Literal[
        "overview", "project", "personnel", "wbs", "risks", "quality_requirements",
    ] = "overview"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=20)
    fields: list[str] | None = Field(default=None, min_length=1, max_length=50)


def initialization_state_input_schema() -> dict[str, Any]:
    schema = InitializationStateReadInput.model_json_schema()
    schema["description"] = (
        "默认返回正式数据分区概况；读取实际记录时指定 section，"
        "按 offset/limit 分页（每页最多 20 条），可用 fields 缩小字段。"
        "项目与账号由当前会话绑定，不能指定其他项目。"
    )
    return schema


_SECTION_TABLES = {
    "project": "projects",
    "personnel": "project_personnel_assignments",
    "wbs": "project_wbs_items",
    "risks": "project_risks",
    "quality_requirements": "project_wbs_quality_requirements",
}


def _policy_fields(
    policies: dict[str, DatabaseInteractionTablePolicy],
    table: str,
    context: Any,
) -> set[str]:
    policy = policies.get(table)
    if (
        policy is None
        or not policy.enabled
        or "read" not in (policy.allowed_operations or [])
        or (policy.minimum_role == "admin" and not context.is_admin)
        or (policy.scope_type == "global_admin" and not context.is_admin)
    ):
        return set()
    return set(policy.readable_fields or [])


def read_initialization_state(
    db: Session,
    context: Any,
    interaction: DatabaseInteraction,
    policy: DatabaseInteractionTablePolicy,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Read confirmed data across sessions without bypassing table permissions."""
    if (
        context.conversation.conversation_type != "initialization"
        or "initialization" not in (interaction.allowed_conversation_types or [])
    ):
        raise HTTPException(status_code=403, detail="当前会话类型不能读取初始化正式数据")
    if (
        not policy.enabled
        or "read" not in (policy.allowed_operations or [])
        or interaction.table_operation != "read"
    ):
        raise HTTPException(status_code=409, detail="数据表白名单已不再允许读取")
    if (
        policy.minimum_role == "admin" or policy.scope_type == "global_admin"
    ) and not context.is_admin:
        raise HTTPException(status_code=403, detail="该数据库交互仅允许管理员使用")
    try:
        request = InitializationStateReadInput.model_validate(arguments)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "正式数据读取参数无效", "errors": exc.errors(include_input=False)},
        ) from exc
    if request.section == "overview" and request.fields is not None:
        raise HTTPException(status_code=422, detail="概况不接受 fields，请先指定业务分区")

    policies = {
        row.table_name: row
        for row in db.scalars(select(DatabaseInteractionTablePolicy)).all()
    }
    allowed = {
        section: _policy_fields(policies, table, context)
        for section, table in _SECTION_TABLES.items()
    }
    # Personnel is a project-bound join.  Each contributing table retains its
    # own field and role restrictions, including the ban on account secrets.
    member_fields = _policy_fields(policies, "project_members", context)
    position_fields = _policy_fields(policies, "project_positions", context)
    user_fields = _policy_fields(policies, "users", context)
    if not all((member_fields, position_fields, user_fields)):
        allowed["personnel"] = set()
    elif allowed["personnel"]:
        allowed["personnel"] |= position_fields & {"position_name"}
        allowed["personnel"] |= user_fields & {"username", "real_name"}
        if "user_id" in member_fields and "id" in user_fields:
            allowed["personnel"].add("user_id")

    if request.section != "overview" and not allowed[request.section]:
        raise HTTPException(status_code=403, detail="该分区未获正式数据读取权限")
    if request.fields is not None and not set(request.fields) <= allowed[request.section]:
        raise HTTPException(status_code=403, detail="请求包含未获准读取的字段")

    state = build_initialization_state(db, context.project)
    if request.section == "overview":
        sections: dict[str, Any] = {}
        for section, fields in allowed.items():
            if not fields:
                sections[section] = {"readable": False}
                continue
            value = state[section]
            if section == "project":
                present = [
                    name for name, value in value.items()
                    if name in fields and name not in {"id", "name", "updated_at"}
                    and value is not None and value != ""
                ]
                sections[section] = {
                    "readable": True, "count": int(bool(present)),
                    "populated_fields": present,
                }
            else:
                sections[section] = {"readable": True, "count": len(value)}
        return {
            "project_id": context.project.id,
            "source": "confirmed_project_data",
            "has_existing_data": any(item.get("count", 0) for item in sections.values()),
            "sections": sections,
        }

    section = request.section
    rows = [state[section]] if section == "project" else state[section]
    fields = set(request.fields) if request.fields else allowed[section]
    page = rows[request.offset:request.offset + request.limit]
    next_offset = request.offset + len(page)
    return {
        "project_id": context.project.id,
        "source": "confirmed_project_data",
        "section": section,
        "items": [{key: value for key, value in row.items() if key in fields} for row in page],
        "page": {
            "offset": request.offset, "limit": request.limit,
            "total": len(rows), "returned": len(page),
            "has_more": next_offset < len(rows),
            "next_offset": next_offset if next_offset < len(rows) else None,
        },
    }
