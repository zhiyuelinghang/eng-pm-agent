"""Validated contracts for declarative database interactions."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
