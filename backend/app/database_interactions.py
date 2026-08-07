"""Declarative database-interaction catalogue and guarded executor.

This module is the single authority for database capabilities exposed to
agents.  It intentionally accepts structured filters and values only; raw SQL,
SQL fragments, arbitrary table names and arbitrary column names never cross
the API boundary.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    and_,
    delete,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Base
from .models import (
    DatabaseInteraction,
    DatabaseInteractionAgentAssignment,
    DatabaseInteractionTablePolicy,
    OperationLog,
    ProjectInitializationDraft,
)
from .initialization_draft_queries import compose_initialization_draft_payload
from .project_initialization import (
    PersonnelDraft,
    ProjectDetailsDraft,
    QualityRequirementDraft,
    RiskDraftItem,
    WbsDraft,
    validate_initialization_payload,
)


TableOperation = Literal["read", "create", "update", "delete"]
JoinType = Literal["left", "inner"]
ScopeType = Literal["project", "user", "global_admin"]
MinimumRole = Literal["member", "admin"]
ConversationType = Literal["general", "business", "initialization"]
InteractionAccessMode = Literal["agent", "workflow"]
ContextBindingSource = Literal[
    "project_id",
    "conversation_id",
    "user_id",
    "actor_agent_id",
]
ContextBindingMode = Literal["scope", "value"]

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_CONTROL_TABLES = frozenset(
    {
        "database_interaction_table_policies",
        "database_interactions",
        "database_interaction_agent_assignments",
        "platform_schema_versions",
    },
)
_SENSITIVE_FIELD_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "identity_card",
    "storage_path",
)
_SYSTEM_MANAGED_FIELDS = frozenset({"created_at", "updated_at"})
_DECLARATIVE_CATALOG_VERSION = 17
_MAX_BATCH_RECORD_IDS = 12
_MAX_JSON_PAGE_ITEMS = 20
_MAX_TEXT_PAGE_CHARS = 6000

_INITIALIZATION_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "project": ProjectDetailsDraft,
    "personnel": PersonnelDraft,
    "wbs": WbsDraft,
    "risks": RiskDraftItem,
    "quality_requirements": QualityRequirementDraft,
}
_INITIALIZATION_ARRAY_SECTIONS = frozenset(
    {"personnel", "wbs", "risks", "quality_requirements"},
)
_INITIALIZATION_SECTION_MAX_ITEMS = {
    "personnel": 2000,
    "wbs": 10000,
    "risks": 5000,
    "quality_requirements": 10000,
}
_INITIALIZATION_SECTION_ADAPTERS = {
    "project": TypeAdapter(ProjectDetailsDraft),
    "personnel": TypeAdapter(list[PersonnelDraft]),
    "wbs": TypeAdapter(list[WbsDraft]),
    "risks": TypeAdapter(list[RiskDraftItem]),
    "quality_requirements": TypeAdapter(list[QualityRequirementDraft]),
}

_OBSOLETE_INITIALIZATION_TABLES = {
    "project_initialization_normalizations",
    "project_initialization_artifacts",
    "project_initialization_draft_workflows",
    "project_initialization_runs",
    "project_initialization_run_steps",
    "project_initialization_parsed_chunks",
}
_DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "database_interaction_defaults.json"
)


class TablePolicyInput(BaseModel):
    table_name: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=20000)
    allowed_operations: list[TableOperation] = Field(min_length=1)
    readable_fields: list[str] = Field(default_factory=list)
    writable_fields: list[str] = Field(default_factory=list)
    filterable_fields: list[str] = Field(default_factory=list)
    scope_type: ScopeType = "project"
    scope_field: str | None = Field(default=None, max_length=128)
    minimum_role: MinimumRole = "member"
    enabled: bool = True

    @field_validator(
        "allowed_operations",
        "readable_fields",
        "writable_fields",
        "filterable_fields",
    )
    @classmethod
    def _unique_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class TableInteractionInput(BaseModel):
    key: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=20000)
    table_policy_id: int
    table_operation: TableOperation
    join_rules: list["TableJoinInput"] = Field(
        default_factory=list,
        max_length=8,
    )
    context_bindings: list["TableContextBindingInput"] = Field(
        default_factory=list,
        max_length=12,
    )
    allowed_conversation_types: list[ConversationType] = Field(
        default_factory=lambda: ["general", "business", "initialization"],
        min_length=1,
    )
    access_mode: InteractionAccessMode = "agent"
    requires_confirmation: bool = False
    enabled: bool = True
    sort_order: int = 0

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        if not _KEY_PATTERN.fullmatch(value):
            raise ValueError("技术标识仅允许小写字母、数字和下划线，并以字母开头")
        return value

    @field_validator("allowed_conversation_types")
    @classmethod
    def _unique_conversation_types(
        cls,
        values: list[ConversationType],
    ) -> list[ConversationType]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def _unique_context_bindings(self) -> "TableInteractionInput":
        fields = [item.field for item in self.context_bindings]
        if len(fields) != len(set(fields)):
            raise ValueError("同一字段不能重复配置上下文绑定")
        return self


class TableJoinInput(BaseModel):
    """One explicit foreign-key join attached to a read interaction."""

    alias: str = Field(min_length=2, max_length=32)
    source_alias: str = Field(default="main", min_length=2, max_length=32)
    source_field: str = Field(min_length=1, max_length=128)
    target_policy_id: int
    target_field: str = Field(min_length=1, max_length=128)
    join_type: JoinType = "left"
    readable_fields: list[str] = Field(default_factory=list)
    filterable_fields: list[str] = Field(default_factory=list)

    @field_validator("alias")
    @classmethod
    def _valid_alias(cls, value: str) -> str:
        if value == "main" or not _ALIAS_PATTERN.fullmatch(value):
            raise ValueError("关联别名仅允许小写字母、数字和下划线，且不能使用 main")
        return value

    @field_validator("source_alias")
    @classmethod
    def _valid_source_alias(cls, value: str) -> str:
        if value != "main" and not _ALIAS_PATTERN.fullmatch(value):
            raise ValueError("来源别名格式不正确")
        return value

    @field_validator("readable_fields", "filterable_fields")
    @classmethod
    def _unique_join_fields(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def _has_purpose(self) -> "TableJoinInput":
        if not self.readable_fields and not self.filterable_fields:
            raise ValueError("关联表至少选择一个返回字段或筛选字段")
        return self


class TableContextBindingInput(BaseModel):
    """Bind one table field to trusted platform context at runtime."""

    field: str = Field(min_length=1, max_length=128)
    source: ContextBindingSource
    mode: ContextBindingMode = "scope"


class DeclarativeJoinSeed(BaseModel):
    alias: str
    source_alias: str = "main"
    source_field: str
    target_table_name: str
    target_field: str
    join_type: JoinType = "left"
    readable_fields: list[str] = Field(default_factory=list)
    filterable_fields: list[str] = Field(default_factory=list)


class DeclarativePolicySeed(TablePolicyInput):
    """Policy seed plus an explicit one-version upgrade instruction."""

    upgrade_existing: bool = False


class DeclarativeInteractionSeed(BaseModel):
    """One editable table interaction imported during the legacy migration."""

    key: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=20000)
    table_name: str = Field(min_length=1, max_length=128)
    table_operation: TableOperation
    join_rules: list[DeclarativeJoinSeed] = Field(default_factory=list)
    context_bindings: list[TableContextBindingInput] = Field(
        default_factory=list,
    )
    fixed_values: dict[str, Any] = Field(default_factory=dict)
    runtime_policy: dict[str, Any] = Field(default_factory=dict)
    allowed_conversation_types: list[ConversationType] = Field(
        default_factory=lambda: ["general", "business", "initialization"],
        min_length=1,
    )
    access_mode: InteractionAccessMode = "agent"
    requires_confirmation: bool = False
    default_assigned: bool = False
    sort_order: int = 0
    legacy_keys: list[str] = Field(default_factory=list)
    upgrade_existing: bool = False

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        if not _KEY_PATTERN.fullmatch(value):
            raise ValueError("技术标识仅允许小写字母、数字和下划线，并以字母开头")
        return value


class DeclarativeCatalog(BaseModel):
    version: int = 1
    policies: list[DeclarativePolicySeed]
    interactions: list[DeclarativeInteractionSeed]


def _is_sensitive_field(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE_FIELD_PARTS)


def _business_table(table_name: str) -> Table:
    if table_name in _CONTROL_TABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="数据库交互模块自身的控制表不能作为业务交互目标",
        )
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"数据表 {table_name!r} 不存在",
        )
    return table


def _column_json_schema(column: Any) -> dict[str, Any]:
    column_type = column.type
    if isinstance(column_type, Boolean):
        type_name: str = "boolean"
    elif isinstance(column_type, Integer):
        type_name = "integer"
    elif isinstance(column_type, (Float, Numeric)):
        type_name = "number"
    elif isinstance(column_type, JSON):
        return {}
    else:
        type_name = "string"

    result: dict[str, Any] = {"type": type_name}
    if isinstance(column_type, DateTime):
        result["format"] = "date-time"
    elif isinstance(column_type, Date):
        result["format"] = "date"
    if isinstance(column_type, String) and column_type.length:
        result["maxLength"] = column_type.length
    if column.nullable:
        result["type"] = [type_name, "null"]
    return result


def _public_column(column: Any) -> dict[str, Any]:
    foreign_keys = sorted(str(key.target_fullname) for key in column.foreign_keys)
    return {
        "name": column.name,
        "type": str(column.type),
        "nullable": bool(column.nullable),
        "primary_key": bool(column.primary_key),
        "foreign_keys": foreign_keys,
        "sensitive": _is_sensitive_field(column.name),
        "system_managed": column.name in _SYSTEM_MANAGED_FIELDS,
    }


def list_database_tables() -> list[dict[str, Any]]:
    """Return SQLAlchemy-known business tables and safe column metadata."""
    result: list[dict[str, Any]] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        if table_name in _CONTROL_TABLES:
            continue
        columns = [_public_column(column) for column in table.columns]
        safe_columns = [item for item in columns if not item["sensitive"]]
        column_names = {item["name"] for item in safe_columns}
        if "project_id" in column_names:
            scope_type = "project"
            scope_field = "project_id"
        elif table_name == "users" and "id" in column_names:
            scope_type = "user"
            scope_field = "id"
        else:
            scope_type = "global_admin"
            scope_field = None
        result.append(
            {
                "name": table_name,
                "columns": safe_columns,
                "recommended_scope_type": scope_type,
                "recommended_scope_field": scope_field,
            },
        )
    return result


def _validate_policy_input(payload: TablePolicyInput) -> Table:
    table = _business_table(payload.table_name)
    columns = {column.name: column for column in table.columns}
    safe_columns = {
        name for name in columns if not _is_sensitive_field(name)
    }
    selected_fields = set(payload.readable_fields)
    selected_fields.update(payload.writable_fields)
    selected_fields.update(payload.filterable_fields)
    unknown = sorted(selected_fields - safe_columns)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"字段不存在或属于敏感字段：{'、'.join(unknown)}",
        )
    if "read" in payload.allowed_operations and not payload.readable_fields:
        raise HTTPException(status_code=422, detail="允许查询时至少选择一个可读字段")
    if set(payload.allowed_operations) & {"create", "update"} and not payload.writable_fields:
        raise HTTPException(status_code=422, detail="允许新增或修改时至少选择一个可写字段")

    primary_keys = [column for column in table.primary_key.columns]
    if set(payload.allowed_operations) & {"update", "delete"} and len(primary_keys) != 1:
        raise HTTPException(
            status_code=422,
            detail="通用修改和删除仅支持具有单一主键的数据表",
        )
    if payload.scope_type in {"project", "user"}:
        if not payload.scope_field or payload.scope_field not in columns:
            raise HTTPException(status_code=422, detail="行级范围字段不存在")
    elif payload.scope_field:
        raise HTTPException(status_code=422, detail="全局管理员范围不应设置范围字段")
    if (
        set(payload.allowed_operations) & {"create", "update", "delete"}
        and payload.scope_type == "global_admin"
        and payload.minimum_role != "admin"
    ):
        raise HTTPException(
            status_code=422,
            detail="无行级范围的写操作必须限制为管理员",
        )
    if "project_id" in columns and (
        payload.scope_type != "project" or payload.scope_field != "project_id"
    ):
        raise HTTPException(
            status_code=422,
            detail="包含 project_id 的业务表必须按当前项目隔离",
        )
    forbidden_writes = set(_SYSTEM_MANAGED_FIELDS & set(columns))
    if payload.scope_field:
        forbidden_writes.add(payload.scope_field)
    invalid_writes = sorted(set(payload.writable_fields) & forbidden_writes)
    if invalid_writes:
        raise HTTPException(
            status_code=422,
            detail=f"范围字段或审计时间由系统维护，不能设为可写：{'、'.join(invalid_writes)}",
        )
    return table


def _validate_join_rules(
    db: Session,
    primary_policy: DatabaseInteractionTablePolicy,
    operation: str,
    rules: list[TableJoinInput] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate an ordered, acyclic chain of real foreign-key joins."""
    parsed = [
        rule if isinstance(rule, TableJoinInput) else TableJoinInput.model_validate(rule)
        for rule in rules
    ]
    if parsed and operation != "read":
        raise HTTPException(
            status_code=422,
            detail="多表关联仅用于查询；新增、修改和删除只能作用于主表",
        )

    aliases: dict[str, tuple[DatabaseInteractionTablePolicy, Table]] = {
        "main": (primary_policy, _business_table(primary_policy.table_name)),
    }
    normalized: list[dict[str, Any]] = []
    for index, rule in enumerate(parsed, start=1):
        if rule.alias in aliases:
            raise HTTPException(status_code=422, detail=f"关联别名重复：{rule.alias}")
        source = aliases.get(rule.source_alias)
        if source is None:
            raise HTTPException(
                status_code=422,
                detail=f"第 {index} 个关联引用了尚未建立的来源别名：{rule.source_alias}",
            )
        source_policy, source_table = source
        target_policy = db.get(
            DatabaseInteractionTablePolicy,
            rule.target_policy_id,
        )
        if target_policy is None:
            raise HTTPException(status_code=422, detail="关联表白名单不存在")
        if "read" not in (target_policy.allowed_operations or []):
            raise HTTPException(
                status_code=422,
                detail=f"关联表「{target_policy.display_name}」未开放查询权限",
            )
        target_table = _business_table(target_policy.table_name)
        if rule.source_field not in source_table.c:
            raise HTTPException(
                status_code=422,
                detail=f"来源字段不存在：{rule.source_alias}.{rule.source_field}",
            )
        if rule.target_field not in target_table.c:
            raise HTTPException(
                status_code=422,
                detail=f"目标字段不存在：{rule.alias}.{rule.target_field}",
            )
        if _is_sensitive_field(rule.source_field) or _is_sensitive_field(rule.target_field):
            raise HTTPException(status_code=422, detail="敏感字段不能作为通用关联条件")

        unknown_readable = sorted(
            set(rule.readable_fields) - set(target_policy.readable_fields or []),
        )
        if unknown_readable:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"关联表「{target_policy.display_name}」字段不可读："
                    f"{'、'.join(unknown_readable)}"
                ),
            )
        unknown_filterable = sorted(
            set(rule.filterable_fields) - set(target_policy.filterable_fields or []),
        )
        if unknown_filterable:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"关联表「{target_policy.display_name}」字段不可筛选："
                    f"{'、'.join(unknown_filterable)}"
                ),
            )

        source_column = source_table.c[rule.source_field]
        target_column = target_table.c[rule.target_field]
        source_target = f"{target_table.name}.{rule.target_field}"
        target_source = f"{source_table.name}.{rule.source_field}"
        source_foreign_keys = {
            foreign_key.target_fullname
            for foreign_key in source_column.foreign_keys
        }
        target_foreign_keys = {
            foreign_key.target_fullname
            for foreign_key in target_column.foreign_keys
        }
        if (
            source_target not in source_foreign_keys
            and target_source not in target_foreign_keys
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "只能使用数据库中真实存在的外键关系："
                    f"{source_policy.table_name}.{rule.source_field} → "
                    f"{target_policy.table_name}.{rule.target_field}"
                ),
            )

        aliases[rule.alias] = (target_policy, target_table)
        normalized.append(rule.model_dump())
    return normalized


def _validate_context_bindings(
    policy: DatabaseInteractionTablePolicy,
    operation: TableOperation,
    bindings: list[TableContextBindingInput] | list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Validate trusted context-to-column mappings for one interaction."""
    parsed = [
        item
        if isinstance(item, TableContextBindingInput)
        else TableContextBindingInput.model_validate(item)
        for item in bindings
    ]
    fields = [item.field for item in parsed]
    if len(fields) != len(set(fields)):
        raise HTTPException(status_code=422, detail="同一字段不能重复配置上下文绑定")
    table = _business_table(policy.table_name)
    for item in parsed:
        if item.field not in table.c or _is_sensitive_field(item.field):
            raise HTTPException(
                status_code=422,
                detail=f"上下文绑定字段不存在或属于敏感字段：{item.field}",
            )
        column = table.c[item.field]
        if item.source == "actor_agent_id":
            compatible = isinstance(column.type, (String, Text))
        else:
            compatible = isinstance(column.type, Integer)
        if not compatible:
            raise HTTPException(
                status_code=422,
                detail=f"上下文来源与字段类型不匹配：{item.field}",
            )
        if item.mode == "value" and operation not in {"create", "update"}:
            raise HTTPException(
                status_code=422,
                detail="自动写入绑定只能用于新增或修改交互",
            )
        if item.mode == "value" and (
            item.field in _SYSTEM_MANAGED_FIELDS or column.primary_key
        ):
            raise HTTPException(
                status_code=422,
                detail=f"主键或审计字段不能自动改写：{item.field}",
            )
    return [item.model_dump() for item in parsed]


def _required_create_fields(table: Table) -> set[str]:
    required: set[str] = set()
    for column in table.columns:
        auto_integer_key = (
            column.primary_key
            and isinstance(column.type, Integer)
            and not column.foreign_keys
        )
        if (
            not column.nullable
            and column.default is None
            and column.server_default is None
            and not auto_integer_key
        ):
            required.add(column.name)
    return required


def _policies_for_interaction(
    db: Session,
    interaction: DatabaseInteraction,
) -> dict[int, DatabaseInteractionTablePolicy]:
    policy_ids = {
        int(rule["target_policy_id"])
        for rule in (interaction.join_rules or [])
        if isinstance(rule, dict) and rule.get("target_policy_id") is not None
    }
    if interaction.table_policy_id is not None:
        policy_ids.add(interaction.table_policy_id)
    if not policy_ids:
        return {}
    return {
        policy.id: policy
        for policy in db.scalars(
            select(DatabaseInteractionTablePolicy).where(
                DatabaseInteractionTablePolicy.id.in_(policy_ids),
            ),
        ).all()
    }


def _policy_view(policy: DatabaseInteractionTablePolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "table_name": policy.table_name,
        "display_name": policy.display_name,
        "description": policy.description,
        "allowed_operations": list(policy.allowed_operations or []),
        "readable_fields": list(policy.readable_fields or []),
        "writable_fields": list(policy.writable_fields or []),
        "filterable_fields": list(policy.filterable_fields or []),
        "scope_type": policy.scope_type,
        "scope_field": policy.scope_field,
        "minimum_role": policy.minimum_role,
        "enabled": policy.enabled,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


def _interaction_view(
    interaction: DatabaseInteraction,
    *,
    policy: DatabaseInteractionTablePolicy | None = None,
    policies: dict[int, DatabaseInteractionTablePolicy] | None = None,
    assigned: bool | None = None,
) -> dict[str, Any]:
    policy_map = policies or ({policy.id: policy} if policy is not None else {})
    join_rules: list[dict[str, Any]] = []
    for raw_rule in interaction.join_rules or []:
        rule = dict(raw_rule)
        target_policy = policy_map.get(int(rule["target_policy_id"]))
        rule["policy"] = (
            _policy_view(target_policy) if target_policy is not None else None
        )
        join_rules.append(rule)
    result = {
        "id": interaction.id,
        "key": interaction.key,
        "display_name": interaction.display_name,
        "description": interaction.description,
        "table_policy_id": interaction.table_policy_id,
        "table_operation": interaction.table_operation,
        "join_rules": join_rules,
        "context_bindings": list(interaction.context_bindings or []),
        "runtime_policy": dict(interaction.runtime_policy or {}),
        "allowed_conversation_types": list(
            interaction.allowed_conversation_types or [],
        ),
        "access_mode": interaction.access_mode,
        "input_schema": interaction.input_schema or {},
        "read_only": interaction.read_only,
        "requires_confirmation": interaction.requires_confirmation,
        "enabled": interaction.enabled,
        "default_assigned": interaction.default_assigned,
        "sort_order": interaction.sort_order,
        "created_at": interaction.created_at,
        "updated_at": interaction.updated_at,
        "policy": _policy_view(policy) if policy is not None else None,
    }
    if assigned is not None:
        result["assigned"] = assigned
    return result


def list_table_policies(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DatabaseInteractionTablePolicy).order_by(
            DatabaseInteractionTablePolicy.display_name,
            DatabaseInteractionTablePolicy.id,
        ),
    ).all()
    return [_policy_view(row) for row in rows]


def create_table_policy(db: Session, payload: TablePolicyInput) -> dict[str, Any]:
    _validate_policy_input(payload)
    if db.scalar(
        select(DatabaseInteractionTablePolicy).where(
            DatabaseInteractionTablePolicy.table_name == payload.table_name,
        ),
    ) is not None:
        raise HTTPException(status_code=409, detail="该数据表已经配置白名单")
    row = DatabaseInteractionTablePolicy(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _policy_view(row)


def update_table_policy(
    db: Session,
    policy_id: int,
    payload: TablePolicyInput,
) -> dict[str, Any]:
    row = db.get(DatabaseInteractionTablePolicy, policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="数据表白名单不存在")
    if payload.table_name != row.table_name:
        raise HTTPException(status_code=422, detail="已创建的白名单不能更换数据库表")
    _validate_policy_input(payload)
    duplicate = db.scalar(
        select(DatabaseInteractionTablePolicy).where(
            DatabaseInteractionTablePolicy.table_name == payload.table_name,
            DatabaseInteractionTablePolicy.id != policy_id,
        ),
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="该数据表已经配置白名单")
    for name, value in payload.model_dump().items():
        setattr(row, name, value)
    # Rebuild every interaction that uses this policy as its main or joined
    # table. JSON joins are intentionally scanned in Python so this remains
    # portable across SQLite and PostgreSQL.
    for interaction in db.scalars(select(DatabaseInteraction)).all():
        relation_policy_ids = {
            int(rule["target_policy_id"])
            for rule in (interaction.join_rules or [])
            if isinstance(rule, dict) and rule.get("target_policy_id") is not None
        }
        if (
            interaction.table_policy_id != policy_id
            and policy_id not in relation_policy_ids
        ):
            continue
        if (
            interaction.table_policy_id == policy_id
            and interaction.table_operation not in payload.allowed_operations
        ):
            interaction.enabled = False
        else:
            main_policy = db.get(
                DatabaseInteractionTablePolicy,
                interaction.table_policy_id,
            )
            if main_policy is None:
                interaction.enabled = False
                continue
            interaction.input_schema = build_table_interaction_schema(
                db,
                main_policy,
                interaction.table_operation,
                interaction.join_rules or [],
                interaction.context_bindings or [],
            )
    db.commit()
    db.refresh(row)
    return _policy_view(row)


def delete_table_policy(db: Session, policy_id: int) -> None:
    row = db.get(DatabaseInteractionTablePolicy, policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="数据表白名单不存在")
    used = any(
        interaction.table_policy_id == policy_id
        or policy_id
        in {
            int(rule["target_policy_id"])
            for rule in (interaction.join_rules or [])
            if isinstance(rule, dict) and rule.get("target_policy_id") is not None
        }
        for interaction in db.scalars(select(DatabaseInteraction)).all()
    )
    if used:
        raise HTTPException(status_code=409, detail="请先删除引用该白名单的数据库交互")
    db.delete(row)
    db.commit()


def _read_field_catalog(
    db: Session,
    policy: DatabaseInteractionTablePolicy,
    join_rules: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return public read/filter field names for the main and joined tables."""
    table = _business_table(policy.table_name)
    columns = {column.name: column for column in table.columns}
    readable = {
        name: columns[name]
        for name in policy.readable_fields
    }
    filterable = {
        name: columns[name]
        for name in policy.filterable_fields
    }
    for rule in join_rules:
        target_policy = db.get(
            DatabaseInteractionTablePolicy,
            int(rule["target_policy_id"]),
        )
        if target_policy is None:
            continue
        target_table = _business_table(target_policy.table_name)
        for name in rule.get("readable_fields") or []:
            readable[f"{rule['alias']}.{name}"] = target_table.c[name]
        for name in rule.get("filterable_fields") or []:
            filterable[f"{rule['alias']}.{name}"] = target_table.c[name]
    return readable, filterable


def _initialization_section_payload_schema(section: str) -> dict[str, Any]:
    """Return the canonical schema for one complete specialist payload."""
    model = _INITIALIZATION_SECTION_MODELS.get(section)
    if model is None:
        raise HTTPException(status_code=422, detail="初始化草稿分区类型无效")
    item_schema = model.model_json_schema()
    if section == "project":
        item_schema["description"] = (
            "工程信息对象；字段名必须与此结构完全一致，禁止额外包裹。"
        )
        return item_schema
    return {
        "type": "array",
        "items": item_schema,
        "minItems": 0,
        "maxItems": _INITIALIZATION_SECTION_MAX_ITEMS[section],
        "description": (
            "该分区的完整标准记录数组；字段名必须与 items 完全一致，"
            "禁止嵌套 children 或额外包裹。"
        ),
    }


def _normalize_initialization_section_payload(
    section: str,
    payload: Any,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Validate and serialize one project-initialization payload batch."""
    adapter = _INITIALIZATION_SECTION_ADAPTERS.get(section)
    if adapter is None:
        raise HTTPException(status_code=422, detail="初始化草稿分区类型无效")
    if section in _INITIALIZATION_ARRAY_SECTIONS:
        max_items = _INITIALIZATION_SECTION_MAX_ITEMS[section]
        if not isinstance(payload, list) or len(payload) > max_items:
            raise HTTPException(
                status_code=422,
                detail=(
                    "数组型初始化分区必须写入不超过 "
                    f"{max_items} 条完整标准记录"
                ),
            )
    try:
        validated = adapter.validate_python(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "初始化草稿分区字段不符合标准结构",
                "errors": exc.errors(include_input=False),
            },
        ) from exc
    return adapter.dump_python(validated, mode="json")


def _validate_initialization_section_evidence(values: dict[str, Any]) -> None:
    """Require every specialist write to retain a usable evidence trail."""
    source_files = values.get("source_files")
    valid_source_files = (
        isinstance(source_files, dict)
        and bool(source_files)
    ) or (
        isinstance(source_files, list)
        and bool(source_files)
        and all(
            (isinstance(item, str) and bool(item.strip()))
            or (isinstance(item, dict) and bool(item))
            for item in source_files
        )
    )
    if not valid_source_files:
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化草稿分区必须记录非空 source_files，"
                "并保留 file_id、chunk_id 或来源文件名"
            ),
        )
    extraction_notes = values.get("extraction_notes")
    if not isinstance(extraction_notes, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in extraction_notes
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化草稿分区必须显式提交 extraction_notes 数组；"
                "没有真实疑点时使用空数组"
            ),
        )


def _initialization_section_from_policy(
    policy: DatabaseInteractionTablePolicy,
    fixed_values: dict[str, Any] | None,
) -> str | None:
    if policy.table_name != "project_initialization_draft_sections":
        return None
    section = (fixed_values or {}).get("section")
    return section if section in _INITIALIZATION_SECTION_MODELS else None


def _validate_initialization_draft_finalization(
    db: Session,
    draft_id: Any,
    values: dict[str, Any],
) -> None:
    """Keep the validator interaction from publishing malformed drafts."""
    allowed_fields = {"status", "validation_issues"}
    unknown_fields = sorted(set(values) - allowed_fields)
    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化核验只能写入状态和核验问题："
                f"{'、'.join(unknown_fields)}"
            ),
        )
    draft_status = values.get("status")
    if draft_status not in {"ready", "invalid"}:
        raise HTTPException(
            status_code=422,
            detail="初始化核验状态只能是 ready 或 invalid",
        )
    issues = values.get("validation_issues", [])
    if not isinstance(issues, list) or any(
        not isinstance(item, dict)
        or item.get("level") not in {"error", "warning"}
        or not isinstance(item.get("path"), str)
        or not item["path"].strip()
        or not isinstance(item.get("message"), str)
        or not item["message"].strip()
        for item in issues
    ):
        raise HTTPException(
            status_code=422,
            detail="核验问题必须是包含 level、path、message 的标准数组",
        )
    if draft_status == "invalid":
        return
    semantic_errors = [
        item for item in issues if item.get("level") == "error"
    ]
    if semantic_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "仍有错误级核验问题，草稿不能标记为 ready",
                "issues": semantic_errors,
            },
        )
    draft = db.get(ProjectInitializationDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    try:
        payload = compose_initialization_draft_payload(db, draft)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "初始化草稿仍包含非标准分区结构，不能标记为 ready",
                "errors": exc.errors(include_input=False),
            },
        ) from exc
    deterministic_errors = [
        item
        for item in validate_initialization_payload(payload)
        if item.get("level") == "error"
    ]
    if deterministic_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "初始化草稿仍有确定性错误，不能标记为 ready",
                "issues": deterministic_errors,
            },
        )


def build_table_interaction_schema(
    db: Session,
    policy: DatabaseInteractionTablePolicy,
    operation: str,
    join_rules: list[TableJoinInput] | list[dict[str, Any]] | None = None,
    context_bindings: (
        list[TableContextBindingInput] | list[dict[str, Any]] | None
    ) = None,
    fixed_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_joins = _validate_join_rules(
        db,
        policy,
        operation,
        list(join_rules or []),
    )
    normalized_bindings = _validate_context_bindings(
        policy,
        operation,  # type: ignore[arg-type]
        list(context_bindings or []),
    )
    table = _business_table(policy.table_name)
    columns = {column.name: column for column in table.columns}
    if operation == "read":
        readable, filterable = _read_field_catalog(
            db,
            policy,
            normalized_joins,
        )
        filter_properties = {
            name: _column_json_schema(column)
            for name, column in filterable.items()
        }
        properties: dict[str, Any] = {
            "keyword": {
                "type": ["string", "null"],
                "maxLength": 200,
                "description": "在允许筛选的文本字段中进行包含匹配。",
            },
            "filters": {
                "type": "object",
                "properties": filter_properties,
                "additionalProperties": False,
                "description": "按允许字段进行精确匹配筛选。",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string", "enum": list(readable)},
                "uniqueItems": True,
                "description": "需要返回的字段；不传时返回全部可读字段。",
            },
            "order_by": {
                "type": ["string", "null"],
                "enum": [*filterable, None],
            },
            "descending": {"type": "boolean", "default": False},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        }
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) == 1:
            properties["record_id"] = _column_json_schema(primary_keys[0])
            properties["record_ids"] = {
                "type": "array",
                "items": _column_json_schema(primary_keys[0]),
                "minItems": 1,
                "maxItems": _MAX_BATCH_RECORD_IDS,
                "uniqueItems": True,
                "description": (
                    "按一组主键批量读取记录；不能与 record_id 同时使用。"
                ),
            }
        json_fields = [
            name
            for name, column in readable.items()
            if isinstance(column.type, JSON)
        ]
        if json_fields:
            properties.update(
                {
                    "json_field": {
                        "type": "string",
                        "enum": json_fields,
                        "description": (
                            "对返回记录中的一个 JSON 数组字段进行分段读取；"
                            "该字段必须同时包含在 fields 中。"
                        ),
                    },
                    "json_offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "JSON 数组分段的起始位置。",
                    },
                    "json_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_JSON_PAGE_ITEMS,
                        "default": _MAX_JSON_PAGE_ITEMS,
                        "description": "本次最多返回的 JSON 数组元素数量。",
                    },
                },
            )
        text_fields = [
            name
            for name, column in readable.items()
            if isinstance(column.type, Text)
        ]
        if text_fields:
            properties.update(
                {
                    "text_field": {
                        "type": "string",
                        "enum": text_fields,
                        "description": (
                            "对返回记录中的一个长文本字段进行分段读取；"
                            "该字段必须同时包含在 fields 中。"
                        ),
                    },
                    "text_offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "长文本分段的起始字符位置。",
                    },
                    "text_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_TEXT_PAGE_CHARS,
                        "default": _MAX_TEXT_PAGE_CHARS,
                        "description": "本次最多返回的长文本字符数量。",
                    },
                },
            )
        return {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }

    primary_keys = {column.name for column in table.primary_key.columns}
    fixed_fields = set(fixed_values or {})
    invalid_fixed_fields = sorted(fixed_fields - set(policy.writable_fields or []))
    if invalid_fixed_fields:
        raise HTTPException(
            status_code=422,
            detail=f"固定写入字段不在白名单中：{'、'.join(invalid_fixed_fields)}",
        )
    bound_fields = {
        item["field"] for item in normalized_bindings
    } | fixed_fields
    exposed_writable_fields = [
        name
        for name in policy.writable_fields
        if name not in bound_fields
        and (operation == "create" or name not in primary_keys)
    ]
    writable = {
        name: _column_json_schema(columns[name])
        for name in exposed_writable_fields
    }
    initialization_section = _initialization_section_from_policy(
        policy,
        fixed_values,
    )
    if initialization_section and "payload" in writable:
        writable["payload"] = _initialization_section_payload_schema(
            initialization_section,
        )
    if initialization_section and "source_files" in writable:
        writable["source_files"] = {
            "anyOf": [
                {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "anyOf": [
                            {"type": "string", "minLength": 1},
                            {"type": "object", "minProperties": 1},
                        ],
                    },
                },
                {"type": "object", "minProperties": 1},
            ],
            "description": (
                "非空来源映射；至少保留 file_id、chunk_id 或来源文件名，"
                "不得只存在于邀请说明中。"
            ),
        }
    if initialization_section and "extraction_notes" in writable:
        writable["extraction_notes"] = {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "description": (
                "仅记录从原文实际发现的冲突、缺失或转换；"
                "没有疑点时传空数组，禁止写通用免责声明。"
            ),
        }
    if (
        policy.table_name == "project_initialization_drafts"
        and operation == "update"
    ):
        if "status" in writable:
            writable["status"] = {
                "type": "string",
                "enum": ["ready", "invalid"],
                "description": "存在 error 时为 invalid，否则为 ready。",
            }
        if "validation_issues" in writable:
            writable["validation_issues"] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["error", "warning"],
                        },
                        "path": {"type": "string", "minLength": 1},
                        "message": {"type": "string", "minLength": 1},
                    },
                    "required": ["level", "path", "message"],
                    "additionalProperties": False,
                },
                "description": (
                    "标准核验问题数组；每项只包含 level、path、message。"
                ),
            }
    values_schema: dict[str, Any] = {
        "type": "object",
        "properties": writable,
        "additionalProperties": False,
    }
    required_value_fields: list[str] = []
    if initialization_section:
        required_value_fields = [
            name
            for name in ("payload", "source_files", "extraction_notes")
            if name in writable
        ]
    elif (
        policy.table_name == "project_initialization_drafts"
        and operation == "update"
    ):
        required_value_fields = [
            name
            for name in ("status", "validation_issues")
            if name in writable
        ]
    if required_value_fields:
        values_schema["required"] = required_value_fields
    return_record_schema = {
        "type": "boolean",
        "default": False,
        "description": "成功后返回当前白名单允许读取的完整记录。",
    }
    if operation == "create":
        required = [
            name
            for name in exposed_writable_fields
            if not columns[name].nullable
            and columns[name].default is None
            and columns[name].server_default is None
        ]
        required = list(
            dict.fromkeys(
                [*values_schema.get("required", []), *required],
            ),
        )
        if required:
            values_schema["required"] = required
        return {
            "type": "object",
            "properties": {
                "values": values_schema,
                "return_record": return_record_schema,
            },
            "required": ["values"],
            "additionalProperties": False,
        }
    primary_key_columns = list(table.primary_key.columns)
    if len(primary_key_columns) != 1:
        raise HTTPException(status_code=422, detail="该数据表不支持通用修改或删除")
    properties: dict[str, Any] = {
        "record_id": _column_json_schema(primary_key_columns[0]),
        "return_record": return_record_schema,
    }
    required = ["record_id"]
    if operation == "update":
        properties["values"] = values_schema
        expected_fields = {
            name: _column_json_schema(columns[name])
            for name in policy.readable_fields
        }
        properties["expected"] = {
            "type": "object",
            "properties": expected_fields,
            "additionalProperties": False,
            "description": "可选的并发校验旧值；不一致时拒绝覆盖。",
        }
        required.append("values")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _load_declarative_catalog() -> DeclarativeCatalog:
    try:
        payload = json.loads(_DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取数据库交互默认配置") from exc
    catalog = DeclarativeCatalog.model_validate(payload)
    if catalog.version != _DECLARATIVE_CATALOG_VERSION:
        raise RuntimeError("数据库交互默认配置版本与迁移版本不一致")
    return catalog


def _seed_join_rules(
    seed: DeclarativeInteractionSeed,
    policies_by_table: dict[str, DatabaseInteractionTablePolicy],
) -> list[TableJoinInput]:
    rules: list[TableJoinInput] = []
    for item in seed.join_rules:
        target_policy = policies_by_table.get(item.target_table_name)
        if target_policy is None:
            raise RuntimeError(
                f"数据库交互 {seed.key} 引用了未知关联白名单："
                f"{item.target_table_name}",
            )
        rules.append(
            TableJoinInput(
                alias=item.alias,
                source_alias=item.source_alias,
                source_field=item.source_field,
                target_policy_id=target_policy.id,
                target_field=item.target_field,
                join_type=item.join_type,
                readable_fields=item.readable_fields,
                filterable_fields=item.filterable_fields,
            ),
        )
    return rules


def bootstrap_declarative_catalog(db: Session) -> int:
    """Convert code-bound tools and apply declared catalogue upgrades."""
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS platform_schema_versions ("
            "version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ),
    )
    legacy_rows = db.scalars(
        select(DatabaseInteraction).where(
            or_(
                DatabaseInteraction.execution_kind == "builtin",
                DatabaseInteraction.built_in.is_(True),
            ),
        ),
    ).all()
    migrated = db.execute(
        text(
            "SELECT 1 FROM platform_schema_versions "
            "WHERE version = :version LIMIT 1",
        ),
        {"version": _DECLARATIVE_CATALOG_VERSION},
    ).scalar_one_or_none()
    obsolete_initialization_row = db.execute(
        select(DatabaseInteraction.id)
        .outerjoin(
            DatabaseInteractionTablePolicy,
            DatabaseInteraction.table_policy_id
            == DatabaseInteractionTablePolicy.id,
        )
        .where(
            or_(
                DatabaseInteraction.key.like("initialization_records_%"),
                DatabaseInteractionTablePolicy.table_name.in_(
                    _OBSOLETE_INITIALIZATION_TABLES,
                ),
            ),
        )
        .limit(1),
    ).scalar_one_or_none()
    if (
        migrated is not None
        and not legacy_rows
        and obsolete_initialization_row is None
    ):
        return 0

    catalog = _load_declarative_catalog()
    declared_interaction_keys = {row.key for row in catalog.interactions}
    obsolete_policy_ids = list(
        db.scalars(
            select(DatabaseInteractionTablePolicy.id).where(
                DatabaseInteractionTablePolicy.table_name.in_(
                    _OBSOLETE_INITIALIZATION_TABLES,
                ),
            ),
        ).all(),
    )
    obsolete_interactions = db.scalars(
        select(DatabaseInteraction).where(
            or_(
                DatabaseInteraction.key.like("initialization_records_%"),
                DatabaseInteraction.table_policy_id.in_(obsolete_policy_ids),
            ),
        ),
    ).all()
    obsolete_interaction_ids = [
        row.id
        for row in obsolete_interactions
        if row.key not in declared_interaction_keys
    ]
    removed_obsolete_count = len(obsolete_interaction_ids)
    if obsolete_interaction_ids:
        db.execute(
            delete(DatabaseInteractionAgentAssignment).where(
                DatabaseInteractionAgentAssignment.interaction_id.in_(
                    obsolete_interaction_ids,
                ),
            ),
        )
        db.execute(
            delete(DatabaseInteraction).where(
                DatabaseInteraction.id.in_(obsolete_interaction_ids),
            ),
        )
    reusable_interaction_ids = [
        row.id
        for row in obsolete_interactions
        if row.key in declared_interaction_keys
    ]
    if reusable_interaction_ids:
        # These catalogue keys remain valid, but their former policies point
        # at the removed pipeline tables. Detach them before deleting those
        # policies; the declared catalogue below immediately rebinds them to
        # the current draft/section tables.
        db.execute(
            update(DatabaseInteraction)
            .where(DatabaseInteraction.id.in_(reusable_interaction_ids))
            .values(table_policy_id=None, join_rules=[]),
        )
    if obsolete_policy_ids:
        db.execute(
            delete(DatabaseInteractionTablePolicy).where(
                DatabaseInteractionTablePolicy.id.in_(obsolete_policy_ids),
            ),
        )
    if obsolete_interaction_ids or reusable_interaction_ids:
        db.flush()
    policies_by_table = {
        row.table_name: row
        for row in db.scalars(select(DatabaseInteractionTablePolicy)).all()
    }
    for payload in catalog.policies:
        policy_values = payload.model_dump(exclude={"upgrade_existing"})
        row = policies_by_table.get(payload.table_name)
        if row is not None:
            if migrated is None and payload.upgrade_existing:
                # The declarative catalogue decides which existing defaults
                # need a one-version structural upgrade. Later administrator
                # edits remain the database source of truth.
                _validate_policy_input(payload)
                for name, value in policy_values.items():
                    setattr(row, name, value)
            continue
        _validate_policy_input(payload)
        row = DatabaseInteractionTablePolicy(**policy_values)
        db.add(row)
        policies_by_table[payload.table_name] = row
    db.flush()

    legacy_ids = {row.id for row in legacy_rows}
    legacy_keys_by_id = {row.id: row.key for row in legacy_rows}
    assignments = (
        db.scalars(
            select(DatabaseInteractionAgentAssignment).where(
                DatabaseInteractionAgentAssignment.interaction_id.in_(legacy_ids),
            ),
        ).all()
        if legacy_ids
        else []
    )
    legacy_agents: dict[str, set[str]] = {}
    all_legacy_agents: set[str] = set()
    for assignment in assignments:
        all_legacy_agents.add(assignment.agent_id)
        if assignment.assigned:
            legacy_agents.setdefault(assignment.agent_id, set()).add(
                legacy_keys_by_id[assignment.interaction_id],
            )

    interactions_by_key = {
        row.key: row for row in db.scalars(select(DatabaseInteraction)).all()
    }
    migrated_rows: dict[str, DatabaseInteraction] = {}
    changed = removed_obsolete_count
    for seed in catalog.interactions:
        policy = policies_by_table.get(seed.table_name)
        if policy is None:
            raise RuntimeError(
                f"数据库交互默认配置引用了未知白名单：{seed.table_name}",
            )
        if seed.table_operation not in (policy.allowed_operations or []):
            raise RuntimeError(
                f"数据库交互 {seed.key} 使用了白名单未允许的操作",
            )
        seed_joins = _seed_join_rules(seed, policies_by_table)
        normalized_seed_joins = _validate_join_rules(
            db,
            policy,
            seed.table_operation,
            seed_joins,
        )
        normalized_seed_bindings = _validate_context_bindings(
            policy,
            seed.table_operation,
            seed.context_bindings,
        )
        row = interactions_by_key.get(seed.key)
        if row is None:
            row = DatabaseInteraction(
                key=seed.key,
                display_name=seed.display_name,
                description=seed.description,
                execution_kind="table",
                builtin_operation=None,
                table_policy_id=policy.id,
                table_operation=seed.table_operation,
                join_rules=normalized_seed_joins,
                context_bindings=normalized_seed_bindings,
                fixed_values=dict(seed.fixed_values),
                runtime_policy=dict(seed.runtime_policy),
                allowed_conversation_types=seed.allowed_conversation_types,
                access_mode=seed.access_mode,
                input_schema=build_table_interaction_schema(
                    db,
                    policy,
                    seed.table_operation,
                    normalized_seed_joins,
                    normalized_seed_bindings,
                    seed.fixed_values,
                ),
                read_only=seed.table_operation == "read",
                requires_confirmation=seed.requires_confirmation,
                enabled=True,
                built_in=False,
                default_assigned=seed.default_assigned,
                sort_order=seed.sort_order,
            )
            db.add(row)
            interactions_by_key[seed.key] = row
            changed += 1
        elif (
            row.id in legacy_ids
            or row.id in reusable_interaction_ids
            or (migrated is None and seed.upgrade_existing)
        ):
            # Preserve the stable catalogue identity while replacing either
            # a fixed Python handler or a binding to a removed pipeline table
            # with the current declarative table/operation definition. A
            # versioned upgrade can explicitly refresh one system-managed
            # interaction without overwriting later administrator edits on
            # ordinary interactions.
            row.display_name = seed.display_name
            row.description = seed.description
            row.execution_kind = "table"
            row.builtin_operation = None
            row.table_policy_id = policy.id
            row.table_operation = seed.table_operation
            row.join_rules = normalized_seed_joins
            row.context_bindings = normalized_seed_bindings
            row.fixed_values = dict(seed.fixed_values)
            row.runtime_policy = dict(seed.runtime_policy)
            row.allowed_conversation_types = seed.allowed_conversation_types
            row.access_mode = seed.access_mode
            row.input_schema = build_table_interaction_schema(
                db,
                policy,
                seed.table_operation,
                normalized_seed_joins,
                normalized_seed_bindings,
                seed.fixed_values,
            )
            row.read_only = seed.table_operation == "read"
            row.requires_confirmation = seed.requires_confirmation
            row.built_in = False
            row.default_assigned = seed.default_assigned
            row.sort_order = seed.sort_order
            changed += 1
        else:
            seed_rule_changed = False
            if not (row.join_rules or []) and normalized_seed_joins:
                row.join_rules = normalized_seed_joins
                seed_rule_changed = True
            if not (row.context_bindings or []) and normalized_seed_bindings:
                row.context_bindings = normalized_seed_bindings
                seed_rule_changed = True
            if dict(row.fixed_values or {}) != dict(seed.fixed_values):
                row.fixed_values = dict(seed.fixed_values)
                seed_rule_changed = True
            if dict(row.runtime_policy or {}) != dict(seed.runtime_policy):
                row.runtime_policy = dict(seed.runtime_policy)
                seed_rule_changed = True
            if row.default_assigned != seed.default_assigned:
                row.default_assigned = seed.default_assigned
                seed_rule_changed = True
            if not (row.allowed_conversation_types or []):
                row.allowed_conversation_types = seed.allowed_conversation_types
                seed_rule_changed = True
            if row.access_mode == "agent" and seed.access_mode == "workflow":
                row.access_mode = "workflow"
                seed_rule_changed = True
            if seed_rule_changed:
                row.input_schema = build_table_interaction_schema(
                    db,
                    policy,
                    row.table_operation,
                    row.join_rules or [],
                    row.context_bindings or [],
                    row.fixed_values or {},
                )
                changed += 1
        migrated_rows[seed.key] = row
    db.flush()

    # Preserve each existing agent's legacy choices. A split read capability
    # (for example the old generic project-list tool) maps to every explicit
    # declarative interaction that names it in ``legacy_keys``.
    existing_assignments = {
        (row.agent_id, row.interaction_id): row
        for row in db.scalars(
            select(DatabaseInteractionAgentAssignment).where(
                DatabaseInteractionAgentAssignment.agent_id.in_(all_legacy_agents),
            ),
        ).all()
    } if all_legacy_agents else {}
    for agent_id in all_legacy_agents:
        assigned_legacy_keys = legacy_agents.get(agent_id, set())
        for seed in catalog.interactions:
            row = migrated_rows[seed.key]
            desired = bool(assigned_legacy_keys & set(seed.legacy_keys))
            assignment = existing_assignments.get((agent_id, row.id))
            if assignment is None:
                db.add(
                    DatabaseInteractionAgentAssignment(
                        agent_id=agent_id,
                        interaction_id=row.id,
                        assigned=desired,
                    ),
                )
            else:
                assignment.assigned = desired

    migrated_ids = {row.id for row in migrated_rows.values()}
    for row in legacy_rows:
        if row.id not in migrated_ids:
            db.delete(row)
            changed += 1
    db.execute(
        text(
            "INSERT OR IGNORE INTO platform_schema_versions(version) "
            "VALUES (:version)",
        ),
        {"version": _DECLARATIVE_CATALOG_VERSION},
    )
    db.commit()
    return changed


def _validate_table_interaction(
    db: Session,
    payload: TableInteractionInput,
) -> tuple[
    DatabaseInteractionTablePolicy,
    list[dict[str, Any]],
    list[dict[str, str]],
]:
    policy = db.get(DatabaseInteractionTablePolicy, payload.table_policy_id)
    if policy is None:
        raise HTTPException(status_code=422, detail="所选数据表白名单不存在")
    if payload.table_operation not in (policy.allowed_operations or []):
        raise HTTPException(status_code=422, detail="所选白名单未允许该操作")
    if (
        payload.table_operation != "read"
        and payload.access_mode == "agent"
        and not payload.requires_confirmation
    ):
        raise HTTPException(status_code=422, detail="数据库写操作必须启用人工确认")
    joins = _validate_join_rules(
        db,
        policy,
        payload.table_operation,
        payload.join_rules,
    )
    bindings = _validate_context_bindings(
        policy,
        payload.table_operation,
        payload.context_bindings,
    )
    if payload.table_operation == "create":
        table = _business_table(policy.table_name)
        available = set(policy.writable_fields or [])
        available.update(item["field"] for item in bindings)
        if policy.scope_field:
            available.add(policy.scope_field)
        missing = sorted(_required_create_fields(table) - available)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=(
                    "新增交互缺少必填字段或可信上下文绑定："
                    f"{'、'.join(missing)}"
                ),
            )
    return policy, joins, bindings


def create_table_interaction(
    db: Session,
    payload: TableInteractionInput,
) -> dict[str, Any]:
    if db.scalar(select(DatabaseInteraction).where(DatabaseInteraction.key == payload.key)):
        raise HTTPException(status_code=409, detail="数据库交互技术标识已存在")
    policy, join_rules, context_bindings = _validate_table_interaction(db, payload)
    values = payload.model_dump(exclude={"join_rules", "context_bindings"})
    row = DatabaseInteraction(
        **values,
        join_rules=join_rules,
        context_bindings=context_bindings,
        execution_kind="table",
        input_schema=build_table_interaction_schema(
            db,
            policy,
            payload.table_operation,
            join_rules,
            context_bindings,
        ),
        read_only=payload.table_operation == "read",
        built_in=False,
        default_assigned=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _interaction_view(
        row,
        policy=policy,
        policies=_policies_for_interaction(db, row),
        assigned=False,
    )


def update_interaction(
    db: Session,
    interaction_id: int,
    payload: TableInteractionInput,
) -> dict[str, Any]:
    row = db.get(DatabaseInteraction, interaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="数据库交互不存在")
    if row.execution_kind != "table" or row.built_in:
        raise HTTPException(status_code=409, detail="旧版交互尚未完成数据迁移")
    if payload.key != row.key:
        raise HTTPException(status_code=422, detail="已创建的数据库交互不能修改技术标识")
    duplicate = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key == payload.key,
            DatabaseInteraction.id != interaction_id,
        ),
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="数据库交互技术标识已存在")
    policy, join_rules, context_bindings = _validate_table_interaction(db, payload)
    for name, value in payload.model_dump(
        exclude={"join_rules", "context_bindings"},
    ).items():
        setattr(row, name, value)
    row.join_rules = join_rules
    row.context_bindings = context_bindings
    row.input_schema = build_table_interaction_schema(
        db,
        policy,
        payload.table_operation,
        join_rules,
        context_bindings,
    )
    row.read_only = payload.table_operation == "read"
    db.commit()
    db.refresh(row)
    return _interaction_view(
        row,
        policy=policy,
        policies=_policies_for_interaction(db, row),
    )


def delete_interaction(db: Session, interaction_id: int) -> None:
    row = db.get(DatabaseInteraction, interaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="数据库交互不存在")
    if row.execution_kind != "table" or row.built_in:
        raise HTTPException(status_code=409, detail="旧版交互尚未完成数据迁移")
    db.delete(row)
    db.commit()


def _ensure_agent_assignments(
    db: Session,
    agent_id: str,
    legacy_allowed_names: list[str] | None,
    *,
    _retry_on_conflict: bool = True,
) -> dict[int, DatabaseInteractionAgentAssignment]:
    interactions = db.scalars(
        select(DatabaseInteraction).where(
            DatabaseInteraction.execution_kind == "table",
            DatabaseInteraction.built_in.is_(False),
        ),
    ).all()
    assignments = {
        row.interaction_id: row
        for row in db.scalars(
            select(DatabaseInteractionAgentAssignment).where(
                DatabaseInteractionAgentAssignment.agent_id == agent_id,
            ),
        ).all()
    }
    legacy_set = set(legacy_allowed_names or [])
    first_initialization = not assignments
    for interaction in interactions:
        if interaction.id in assignments:
            continue
        if first_initialization:
            assigned = (
                interaction.default_assigned
                if legacy_allowed_names is None
                else interaction.key in legacy_set
            )
        else:
            # Once an agent has an explicit database-interaction profile, new
            # capabilities must be opted into. A deployment must never widen
            # an existing agent's database access merely by adding a seed.
            assigned = False
        assignment = DatabaseInteractionAgentAssignment(
            agent_id=agent_id,
            interaction_id=interaction.id,
            assigned=assigned,
        )
        db.add(assignment)
        assignments[interaction.id] = assignment
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not _retry_on_conflict:
            raise
        # Concurrent runtime/catalog requests can initialize the same agent.
        # The unique key makes the winner authoritative; re-read it once.
        return _ensure_agent_assignments(
            db,
            agent_id,
            legacy_allowed_names,
            _retry_on_conflict=False,
        )
    return assignments


def list_interaction_catalog(
    db: Session,
    agent_id: str,
    legacy_allowed_names: list[str] | None,
) -> list[dict[str, Any]]:
    assignments = _ensure_agent_assignments(db, agent_id, legacy_allowed_names)
    policies = {
        row.id: row for row in db.scalars(select(DatabaseInteractionTablePolicy)).all()
    }
    interactions = db.scalars(
        select(DatabaseInteraction).where(
            DatabaseInteraction.execution_kind == "table",
            DatabaseInteraction.built_in.is_(False),
        ).order_by(
            DatabaseInteraction.sort_order,
            DatabaseInteraction.display_name,
            DatabaseInteraction.id,
        ),
    ).all()
    return [
        _interaction_view(
            row,
            policy=policies.get(row.table_policy_id),
            policies=policies,
            assigned=assignments[row.id].assigned,
        )
        for row in interactions
    ]


def update_agent_assignments(
    db: Session,
    agent_id: str,
    interaction_ids: list[int],
) -> list[dict[str, Any]]:
    interactions = db.scalars(
        select(DatabaseInteraction).where(
            DatabaseInteraction.execution_kind == "table",
            DatabaseInteraction.built_in.is_(False),
        ),
    ).all()
    valid_ids = {row.id for row in interactions}
    unknown = sorted(set(interaction_ids) - valid_ids)
    if unknown:
        raise HTTPException(status_code=422, detail=f"数据库交互不存在：{unknown}")
    assignments = _ensure_agent_assignments(db, agent_id, [])
    selected = set(interaction_ids)
    for interaction_id, assignment in assignments.items():
        assignment.assigned = interaction_id in selected
    db.commit()
    return list_interaction_catalog(db, agent_id, [])


def delete_agent_assignments(db: Session, agent_id: str) -> None:
    db.execute(
        delete(DatabaseInteractionAgentAssignment).where(
            DatabaseInteractionAgentAssignment.agent_id == agent_id,
        ),
    )
    db.commit()


def _conversation_allowed(interaction: DatabaseInteraction, context: Any) -> bool:
    allowed = set(interaction.allowed_conversation_types or [])
    return not allowed or context.conversation.conversation_type in allowed


def _write_allowed(interaction: DatabaseInteraction, context: Any) -> bool:
    if not _conversation_allowed(interaction, context):
        return False
    if context.can_write:
        return True
    return (
        context.conversation.conversation_type == "initialization"
        and context.can_submit_initialization_draft
        and "initialization" in set(interaction.allowed_conversation_types or [])
    )


def list_runtime_interactions(
    db: Session,
    context: Any,
    agent_id: str,
    legacy_allowed_names: list[str] | None,
) -> list[dict[str, Any]]:
    assignments = _ensure_agent_assignments(db, agent_id, legacy_allowed_names)
    policies = {
        row.id: row for row in db.scalars(select(DatabaseInteractionTablePolicy)).all()
    }
    interactions = db.scalars(
        select(DatabaseInteraction).where(
            DatabaseInteraction.execution_kind == "table",
            DatabaseInteraction.built_in.is_(False),
            DatabaseInteraction.enabled.is_(True),
        ),
    ).all()
    result: list[dict[str, Any]] = []
    for row in interactions:
        if row.access_mode != "agent" or not _conversation_allowed(row, context):
            continue
        assignment = assignments.get(row.id)
        if assignment is None or not assignment.assigned:
            continue
        policy = policies.get(row.table_policy_id)
        if row.execution_kind == "table":
            if policy is None or not policy.enabled:
                continue
            if policy.minimum_role == "admin" and not context.is_admin:
                continue
            if not row.read_only and not _write_allowed(row, context):
                continue
            relation_policies = [
                policies.get(int(rule["target_policy_id"]))
                for rule in (row.join_rules or [])
                if isinstance(rule, dict)
                and rule.get("target_policy_id") is not None
            ]
            if any(
                relation_policy is None or not relation_policy.enabled
                for relation_policy in relation_policies
            ):
                continue
            if any(
                relation_policy is not None
                and relation_policy.minimum_role == "admin"
                and not context.is_admin
                for relation_policy in relation_policies
            ):
                continue
        result.append(
            _interaction_view(
                row,
                policy=policy,
                policies=policies,
                assigned=True,
            ),
        )
    return result


def resolve_assigned_interaction(
    db: Session,
    agent_id: str,
    interaction_key: str,
    *,
    access_mode: InteractionAccessMode = "agent",
) -> tuple[DatabaseInteraction, DatabaseInteractionTablePolicy | None]:
    row = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key == interaction_key,
            DatabaseInteraction.execution_kind == "table",
            DatabaseInteraction.built_in.is_(False),
            DatabaseInteraction.enabled.is_(True),
        ),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="数据库交互不存在或已停用")
    if row.access_mode != access_mode:
        raise HTTPException(status_code=403, detail="该数据库交互不允许当前调用方式")
    assignment = db.scalar(
        select(DatabaseInteractionAgentAssignment).where(
            DatabaseInteractionAgentAssignment.agent_id == agent_id,
            DatabaseInteractionAgentAssignment.interaction_id == row.id,
            DatabaseInteractionAgentAssignment.assigned.is_(True),
        ),
    )
    if assignment is None:
        raise HTTPException(status_code=403, detail="该数据库交互未分配给当前智能体")
    policy = db.get(DatabaseInteractionTablePolicy, row.table_policy_id) if row.table_policy_id else None
    if row.execution_kind == "table" and (policy is None or not policy.enabled):
        raise HTTPException(status_code=409, detail="该数据库交互引用的数据表白名单已停用")
    for rule in row.join_rules or []:
        relation_policy = db.get(
            DatabaseInteractionTablePolicy,
            int(rule["target_policy_id"]),
        )
        if relation_policy is None or not relation_policy.enabled:
            raise HTTPException(
                status_code=409,
                detail="该数据库交互引用的关联表白名单已停用或删除",
            )
    return row, policy


def _scope_clause(table: Table, policy: DatabaseInteractionTablePolicy, context: Any) -> Any:
    if policy.minimum_role == "admin" and not context.is_admin:
        raise HTTPException(status_code=403, detail="该数据库交互仅允许管理员使用")
    if policy.scope_type == "project":
        return table.c[policy.scope_field] == context.project.id
    if policy.scope_type == "user":
        return table.c[policy.scope_field] == context.user.id
    if not context.is_admin:
        raise HTTPException(status_code=403, detail="全局数据交互仅允许管理员使用")
    return None


def _context_value(
    context: Any,
    actor_agent_id: str | None,
    source: ContextBindingSource,
) -> Any:
    if source == "project_id":
        return context.project.id
    if source == "conversation_id":
        return context.conversation.id
    if source == "user_id":
        return context.user.id
    if not actor_agent_id:
        raise HTTPException(status_code=422, detail="当前调用缺少智能体标识")
    return actor_agent_id


def _binding_values(
    interaction: DatabaseInteraction,
    context: Any,
    actor_agent_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    scope_values: dict[str, Any] = {}
    write_values: dict[str, Any] = {}
    for raw in interaction.context_bindings or []:
        binding = TableContextBindingInput.model_validate(raw)
        value = _context_value(context, actor_agent_id, binding.source)
        if binding.mode == "scope":
            scope_values[binding.field] = value
        else:
            write_values[binding.field] = value
    return scope_values, write_values


def _with_context_scope(
    clause: Any,
    table: Table,
    scope_values: dict[str, Any],
) -> Any:
    clauses = [table.c[name] == value for name, value in scope_values.items()]
    if clause is not None:
        clauses.insert(0, clause)
    if not clauses:
        return None
    return and_(*clauses)


def _validate_foreign_key_values(
    db: Session,
    context: Any,
    table: Table,
    values: dict[str, Any],
    scope_values: dict[str, Any],
) -> None:
    """Ensure every caller-supplied relation remains inside allowed scope."""
    for field, value in values.items():
        if value is None:
            continue
        column = table.c[field]
        for foreign_key in column.foreign_keys:
            target_column = foreign_key.column
            target_table = target_column.table
            target_policy = db.scalar(
                select(DatabaseInteractionTablePolicy).where(
                    DatabaseInteractionTablePolicy.table_name == target_table.name,
                    DatabaseInteractionTablePolicy.enabled.is_(True),
                ),
            )
            if target_policy is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"关联表尚未配置可用白名单：{target_table.name}",
                )
            clause = target_column == value
            target_scope = _scope_clause(target_table, target_policy, context)
            if target_scope is not None:
                clause = and_(clause, target_scope)
            for scope_field, scope_value in scope_values.items():
                if scope_field in target_table.c:
                    clause = and_(
                        clause,
                        target_table.c[scope_field] == scope_value,
                    )
            if db.execute(select(target_column).where(clause).limit(1)).first() is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"关联记录不存在或超出当前访问范围：{field}",
                )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _joined_read_source(
    db: Session,
    context: Any,
    policy: DatabaseInteractionTablePolicy,
    join_rules: list[dict[str, Any]],
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Build a scoped FROM clause and its public field-name mappings."""
    main_table = _business_table(policy.table_name)
    aliases: dict[str, Any] = {"main": main_table}
    from_clause: Any = main_table
    readable: dict[str, Any] = {
        name: main_table.c[name]
        for name in policy.readable_fields
    }
    filterable: dict[str, Any] = {
        name: main_table.c[name]
        for name in policy.filterable_fields
    }

    for rule in join_rules:
        target_policy = db.get(
            DatabaseInteractionTablePolicy,
            int(rule["target_policy_id"]),
        )
        if target_policy is None or not target_policy.enabled:
            raise HTTPException(status_code=409, detail="关联表白名单不可用")
        if target_policy.minimum_role == "admin" and not context.is_admin:
            raise HTTPException(status_code=403, detail="关联表仅允许管理员读取")
        target_table = _business_table(target_policy.table_name).alias(
            rule["alias"],
        )
        source_table = aliases[rule["source_alias"]]
        join_condition = (
            source_table.c[rule["source_field"]]
            == target_table.c[rule["target_field"]]
        )
        # A related project table remains isolated even if an administrator
        # accidentally configures a non-unique join key.
        if target_policy.scope_type == "project":
            join_condition = and_(
                join_condition,
                target_table.c[target_policy.scope_field]
                == context.project.id,
            )
        from_clause = from_clause.join(
            target_table,
            join_condition,
            isouter=rule["join_type"] == "left",
        )
        aliases[rule["alias"]] = target_table
        for name in rule.get("readable_fields") or []:
            readable[f"{rule['alias']}.{name}"] = target_table.c[name]
        for name in rule.get("filterable_fields") or []:
            filterable[f"{rule['alias']}.{name}"] = target_table.c[name]
    return from_clause, readable, filterable


def execute_table_interaction(
    db: Session,
    context: Any,
    interaction: DatabaseInteraction,
    policy: DatabaseInteractionTablePolicy,
    arguments: dict[str, Any],
    *,
    actor_agent_id: str | None = None,
) -> tuple[Any, str]:
    """Execute one table operation after re-validating every boundary."""
    operation = interaction.table_operation
    if operation not in (policy.allowed_operations or []):
        raise HTTPException(status_code=409, detail="数据表白名单已不再允许该操作")
    if not _conversation_allowed(interaction, context):
        raise HTTPException(status_code=403, detail="当前会话类型不能使用该数据库交互")
    table = _business_table(policy.table_name)
    columns = {column.name: column for column in table.columns}
    primary_keys = list(table.primary_key.columns)
    scope_values, bound_write_values = _binding_values(
        interaction,
        context,
        actor_agent_id,
    )
    fixed_values = dict(interaction.fixed_values or {})
    initialization_section = _initialization_section_from_policy(
        policy,
        fixed_values,
    )
    scoped_values = dict(scope_values)
    if operation != "create":
        scoped_values.update(fixed_values)
    scope_clause = _with_context_scope(
        _scope_clause(table, policy, context),
        table,
        scoped_values,
    )
    if operation != "read":
        if not _write_allowed(interaction, context):
            raise HTTPException(status_code=403, detail="当前会话不允许修改业务数据")
        if policy.minimum_role == "admin" and not context.is_admin:
            raise HTTPException(status_code=403, detail="该写操作需要管理员权限")

    try:
        if operation == "read":
            join_rules = _validate_join_rules(
                db,
                policy,
                operation,
                interaction.join_rules or [],
            )
            from_clause, readable_columns, filterable_columns = (
                _joined_read_source(db, context, policy, join_rules)
            )
            requested_fields = arguments.get("fields") or list(readable_columns)
            if not isinstance(requested_fields, list) or not requested_fields:
                raise HTTPException(status_code=422, detail="返回字段不能为空")
            unknown_fields = sorted(
                set(requested_fields) - set(readable_columns),
            )
            if unknown_fields:
                raise HTTPException(status_code=422, detail=f"字段不可读：{'、'.join(unknown_fields)}")
            json_field = arguments.get("json_field")
            json_offset = arguments.get("json_offset", 0)
            json_limit = arguments.get("json_limit", _MAX_JSON_PAGE_ITEMS)
            if json_field is None:
                if "json_offset" in arguments or "json_limit" in arguments:
                    raise HTTPException(
                        status_code=422,
                        detail="json_offset/json_limit 必须与 json_field 一起使用",
                    )
            else:
                if (
                    not isinstance(json_field, str)
                    or json_field not in requested_fields
                    or json_field not in readable_columns
                    or not isinstance(readable_columns[json_field].type, JSON)
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="json_field 必须是 fields 中允许读取的 JSON 字段",
                    )
                if (
                    not isinstance(json_offset, int)
                    or isinstance(json_offset, bool)
                    or json_offset < 0
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="JSON 分页位置必须是非负整数",
                    )
                if (
                    not isinstance(json_limit, int)
                    or isinstance(json_limit, bool)
                    or not 1 <= json_limit <= _MAX_JSON_PAGE_ITEMS
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "JSON 分页数量必须在 1 到 "
                            f"{_MAX_JSON_PAGE_ITEMS} 之间"
                        ),
                    )
            text_field = arguments.get("text_field")
            text_offset = arguments.get("text_offset", 0)
            text_limit = arguments.get("text_limit", _MAX_TEXT_PAGE_CHARS)
            if text_field is None:
                if "text_offset" in arguments or "text_limit" in arguments:
                    raise HTTPException(
                        status_code=422,
                        detail="text_offset/text_limit 必须与 text_field 一起使用",
                    )
            else:
                if (
                    not isinstance(text_field, str)
                    or text_field not in requested_fields
                    or text_field not in readable_columns
                    or not isinstance(readable_columns[text_field].type, Text)
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="text_field 必须是 fields 中允许读取的文本字段",
                    )
                if (
                    not isinstance(text_offset, int)
                    or isinstance(text_offset, bool)
                    or text_offset < 0
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="文本分页位置必须是非负整数",
                    )
                if (
                    not isinstance(text_limit, int)
                    or isinstance(text_limit, bool)
                    or not 1 <= text_limit <= _MAX_TEXT_PAGE_CHARS
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "文本分页字符数必须在 1 到 "
                            f"{_MAX_TEXT_PAGE_CHARS} 之间"
                        ),
                    )
            statement = select(
                *(
                    readable_columns[name].label(name)
                    for name in requested_fields
                ),
            ).select_from(from_clause)
            if scope_clause is not None:
                statement = statement.where(scope_clause)
            record_id = arguments.get("record_id")
            record_ids = arguments.get("record_ids")
            if record_id is not None and record_ids is not None:
                raise HTTPException(
                    status_code=422,
                    detail="record_id 与 record_ids 不能同时使用",
                )
            if record_id is not None:
                if len(primary_keys) != 1:
                    raise HTTPException(status_code=422, detail="该数据表不支持按单一主键读取")
                statement = statement.where(primary_keys[0] == record_id)
            if record_ids is not None:
                if len(primary_keys) != 1:
                    raise HTTPException(status_code=422, detail="该数据表不支持按主键批量读取")
                if (
                    not isinstance(record_ids, list)
                    or not 1 <= len(record_ids) <= _MAX_BATCH_RECORD_IDS
                    or any(item is None for item in record_ids)
                    or len({json.dumps(item, sort_keys=True) for item in record_ids})
                    != len(record_ids)
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "record_ids 必须包含 1 到 "
                            f"{_MAX_BATCH_RECORD_IDS} 个互不重复的主键"
                        ),
                    )
                statement = statement.where(primary_keys[0].in_(record_ids))
            filters = arguments.get("filters") or {}
            if not isinstance(filters, dict):
                raise HTTPException(status_code=422, detail="筛选条件必须是对象")
            unknown_filters = sorted(
                set(filters) - set(filterable_columns),
            )
            if unknown_filters:
                raise HTTPException(status_code=422, detail=f"字段不可筛选：{'、'.join(unknown_filters)}")
            for name, value in filters.items():
                statement = statement.where(filterable_columns[name] == value)
            keyword = arguments.get("keyword")
            if keyword is not None:
                if not isinstance(keyword, str):
                    raise HTTPException(status_code=422, detail="关键词必须是文本")
                keyword = keyword.strip()
                if not keyword or len(keyword) > 200:
                    raise HTTPException(
                        status_code=422,
                        detail="关键词长度必须在 1 到 200 个字符之间",
                    )
                searchable_fields = [
                    name
                    for name, column in filterable_columns.items()
                    if isinstance(column.type, (String, Text))
                ]
                if not searchable_fields:
                    raise HTTPException(
                        status_code=422,
                        detail="当前白名单没有允许关键词检索的文本字段",
                    )
                statement = statement.where(
                    or_(
                        *(
                            filterable_columns[name].contains(keyword)
                            for name in searchable_fields
                        ),
                    ),
                )
            order_by = arguments.get("order_by")
            if order_by is not None:
                if order_by not in filterable_columns:
                    raise HTTPException(status_code=422, detail="排序字段不在白名单中")
                ordering = (
                    filterable_columns[order_by].desc()
                    if arguments.get("descending")
                    else filterable_columns[order_by].asc()
                )
                statement = statement.order_by(ordering)
            elif record_ids is not None:
                statement = statement.order_by(primary_keys[0].asc())
            offset = arguments.get("offset", 0)
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise HTTPException(status_code=422, detail="分页位置必须是非负整数")
            limit = arguments.get("limit", 50)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
                raise HTTPException(status_code=422, detail="返回数量必须在 1 到 200 之间")
            rows = db.execute(statement.offset(offset).limit(limit)).all()
            data = [
                {name: _serialize_value(value) for name, value in row._mapping.items()}
                for row in rows
            ]
            if json_field is not None:
                for item in data:
                    json_value = item.get(json_field)
                    if json_value is None:
                        json_value = []
                    if not isinstance(json_value, list):
                        raise HTTPException(
                            status_code=422,
                            detail=f"JSON 字段 {json_field} 不是数组，不能分段读取",
                        )
                    total = len(json_value)
                    page = json_value[json_offset : json_offset + json_limit]
                    next_offset = json_offset + len(page)
                    item[json_field] = page
                    item["_json_page"] = {
                        "field": json_field,
                        "offset": json_offset,
                        "limit": json_limit,
                        "returned": len(page),
                        "total": total,
                        "has_more": next_offset < total,
                        "next_offset": next_offset if next_offset < total else None,
                    }
            if text_field is not None:
                for item in data:
                    text_value = item.get(text_field)
                    if text_value is None:
                        text_value = ""
                    if not isinstance(text_value, str):
                        raise HTTPException(
                            status_code=422,
                            detail=f"文本字段 {text_field} 不是字符串，不能分段读取",
                        )
                    total = len(text_value)
                    page = text_value[text_offset : text_offset + text_limit]
                    next_offset = text_offset + len(page)
                    item[text_field] = page
                    item["_text_page"] = {
                        "field": text_field,
                        "offset": text_offset,
                        "limit": text_limit,
                        "returned": len(page),
                        "total": total,
                        "has_more": next_offset < total,
                        "next_offset": next_offset if next_offset < total else None,
                    }
            return data, f"已读取 {len(data)} 条{policy.display_name}数据"

        primary_key_names = {column.name for column in primary_keys}
        bound_fields = {
            str(item.get("field"))
            for item in (interaction.context_bindings or [])
            if isinstance(item, dict) and item.get("field")
        }
        bound_fields.update(fixed_values)
        writable = set(policy.writable_fields) - bound_fields
        if operation != "create":
            writable.difference_update(primary_key_names)
        values = arguments.get("values") or {}
        if operation in {"create", "update"}:
            if not isinstance(values, dict) or not values:
                raise HTTPException(status_code=422, detail="写入内容不能为空")
            unknown_values = sorted(set(values) - writable)
            if unknown_values:
                raise HTTPException(status_code=422, detail=f"字段不可写：{'、'.join(unknown_values)}")
            if initialization_section and "payload" in values:
                values = dict(values)
                values["payload"] = _normalize_initialization_section_payload(
                    initialization_section,
                    values["payload"],
                )
                _validate_initialization_section_evidence(values)
            if (
                interaction.key
                == "dobby_create_project_initialization_draft"
            ):
                # A new draft is a workflow envelope; all business content is
                # owned by project_initialization_draft_sections.  Do not let
                # a model reintroduce obsolete payload keys or pre-finalize a
                # draft while creating it.
                values = {
                    **values,
                    "status": "building",
                    "payload": {},
                    "validation_issues": [],
                }
            validated_values = {**fixed_values, **values}
            _validate_foreign_key_values(
                db,
                context,
                table,
                validated_values,
                scope_values,
            )
        if operation == "create":
            write_values = {**fixed_values, **values}
            if policy.scope_type == "project":
                write_values[policy.scope_field] = context.project.id
            elif policy.scope_type == "user":
                write_values[policy.scope_field] = context.user.id
            write_values.update(scope_values)
            write_values.update(bound_write_values)
            result = db.execute(insert(table).values(**write_values))
            target_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
            action = "create"
        else:
            if len(primary_keys) != 1 or "record_id" not in arguments:
                raise HTTPException(status_code=422, detail="修改或删除必须提供记录主键")
            where = primary_keys[0] == arguments["record_id"]
            if scope_clause is not None:
                where = where & scope_clause
            exists = db.execute(select(primary_keys[0]).where(where)).first()
            if exists is None:
                raise HTTPException(status_code=404, detail="记录不存在或不属于当前访问范围")
            target_id = arguments["record_id"]
            if operation == "update":
                expected = arguments.get("expected") or {}
                if not isinstance(expected, dict):
                    raise HTTPException(
                        status_code=422,
                        detail="并发校验旧值必须是对象",
                    )
                unknown_expected = sorted(
                    set(expected) - set(policy.readable_fields or []),
                )
                if unknown_expected:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "并发校验字段不可读："
                            f"{'、'.join(unknown_expected)}"
                        ),
                    )
                if expected:
                    current = db.execute(
                        select(*(table.c[name] for name in expected)).where(where),
                    ).first()
                    if current is None or any(
                        current._mapping[name] != value
                        for name, value in expected.items()
                    ):
                        raise HTTPException(
                            status_code=409,
                            detail="记录已被其他任务修改，请重新读取",
                        )
                if (
                    interaction.key
                    == "dobby_finalize_project_initialization_draft"
                ):
                    _validate_initialization_draft_finalization(
                        db,
                        arguments["record_id"],
                        values,
                    )
                update_values = {
                    **fixed_values,
                    **values,
                    **bound_write_values,
                }
                db.execute(update(table).where(where).values(**update_values))
                action = "update"
            elif operation == "delete":
                db.execute(delete(table).where(where))
                action = "delete"
            else:
                raise HTTPException(status_code=422, detail="不支持的数据库操作")
        db.add(
            OperationLog(
                project_id=getattr(context.project, "id", None),
                operator_id=getattr(context.user, "id", None),
                action=f"agent_database_{action}",
                detail=f"智能体通过数据库交互「{interaction.display_name}」执行结构化操作",
                target_type=policy.table_name,
                target_id=target_id if isinstance(target_id, int) else None,
            ),
        )
        db.commit()
        payload: dict[str, Any] = {
            "record_id": target_id,
            "operation": operation,
        }
        if (
            initialization_section in _INITIALIZATION_ARRAY_SECTIONS
            and isinstance(values.get("payload"), list)
        ):
            payload["payload_length"] = len(values["payload"])
        if arguments.get("return_record") is True and operation != "delete":
            if len(primary_keys) == 1:
                record = db.execute(
                    select(
                        *(
                            table.c[name].label(name)
                            for name in policy.readable_fields
                        ),
                    ).where(primary_keys[0] == target_id),
                ).first()
                if record is not None:
                    payload["record"] = {
                        name: _serialize_value(value)
                        for name, value in record._mapping.items()
                    }
        return payload, f"已完成{policy.display_name}{operation}操作"
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="写入内容不符合数据表约束") from exc
