"""Read the actual scoped record before asking a user to approve a write."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database_interactions import (
    _binding_values, _business_table, _scope_clause, _serialize_value,
    _validate_foreign_key_values, _with_context_scope, _write_allowed,
)
from .models import DatabaseInteraction, DatabaseInteractionTablePolicy, OperationLog


def preview_table_interaction(
    db: Session, context: Any, interaction: DatabaseInteraction,
    policy: DatabaseInteractionTablePolicy, arguments: dict[str, Any],
    *, actor_agent_id: str,
) -> dict[str, Any]:
    operation = interaction.table_operation
    if operation not in {"create", "update", "delete"} or not interaction.requires_confirmation:
        raise HTTPException(status_code=409, detail="该交互不是需要确认的业务写操作")
    if operation not in (policy.allowed_operations or []):
        raise HTTPException(status_code=409, detail="数据表白名单已不再允许该操作")
    if not _write_allowed(interaction, context):
        raise HTTPException(status_code=403, detail="当前会话不允许修改业务数据")
    table = _business_table(policy.table_name)
    primary_keys = list(table.primary_key.columns)
    scope_values, bound_values = _binding_values(interaction, context, actor_agent_id)
    fixed_values = dict(interaction.fixed_values or {})
    scope = _with_context_scope(_scope_clause(table, policy, context), table, {
        **scope_values, **(fixed_values if operation != "create" else {}),
    })
    bound_fields = {item["field"] for item in (interaction.context_bindings or [])}
    writable = set(policy.writable_fields or []) - bound_fields - set(fixed_values)
    if operation != "create":
        writable -= {column.name for column in primary_keys}
    values = arguments.get("values") or {}
    if operation != "delete":
        if not isinstance(values, dict) or not values or set(values) - writable:
            raise HTTPException(status_code=422, detail="写入内容为空或包含不可写字段")
        _validate_foreign_key_values(db, context, table, {**fixed_values, **values}, scope_values)

    # Only whitelisted readable fields may be included in the human preview.
    readable = set(policy.readable_fields or [])
    before: dict[str, Any] = {}
    record_id = arguments.get("record_id")
    if operation != "create":
        if len(primary_keys) != 1 or record_id is None:
            raise HTTPException(status_code=422, detail="修改或删除必须提供记录主键")
        where = primary_keys[0] == record_id
        if scope is not None:
            where &= scope
        fields = readable | {primary_keys[0].name}
        record = db.execute(select(*(table.c[name] for name in sorted(fields))).where(where)).first()
        if record is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前访问范围")
        before = dict(record._mapping)
    after = {} if operation == "delete" else {**fixed_values, **values, **bound_values}
    if operation == "create":
        if policy.scope_type in {"project", "user"}:
            after[policy.scope_field] = getattr(context, policy.scope_type).id
        after.update(scope_values)
        after.update(bound_values)
    names = sorted(readable if operation == "delete" else after)
    changes = [{
        "field": name,
        "before": _serialize_value(before.get(name)) if name in readable else "（无读取权限）",
        "after": _serialize_value(after.get(name)),
    } for name in names if operation != "update" or before.get(name) != after.get(name)]
    object_name = next((str(before[name]) for name in ("title", "name", "filename")
                        if name in readable and before.get(name)), policy.display_name)
    label = {"create": "新增", "update": "修改", "delete": "删除"}[operation]
    preview = {
        "operation": operation, "operation_label": label,
        "target_name": object_name, "record_id": record_id,
        "project_name": context.project.name,
        "scope": "当前用户" if policy.scope_type == "user" else
                 "管理员全局范围" if policy.scope_type == "global" else "当前项目",
        "affected_count": 1, "changes": changes,
        "impact": f"{label} 1 条{policy.display_name}记录" +
                  ("，关联记录按数据表约束处理。" if operation == "delete" else "。"),
    }
    db.add(OperationLog(
        project_id=context.project.id, operator_id=context.user.id,
        action="agent_database_preview",
        detail=f"智能体 {actor_agent_id} 在平台会话 {context.conversation.id} 预览「{interaction.display_name}」",
        target_type=policy.table_name, target_id=record_id if isinstance(record_id, int) else None,
    ))
    db.commit()
    return preview
