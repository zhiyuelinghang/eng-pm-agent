# -*- coding: utf-8 -*-
"""Persistence models for the built-in permission reviewer."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._base import _RecordBase


class PermissionReviewerConfigData(BaseModel):
    """Per-user model binding and policy for the system reviewer."""

    model_config = ConfigDict(extra="forbid")

    credential_id: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence_threshold: float = Field(default=0.85, ge=0.5, le=1)
    max_auto_risk: Literal["low", "medium"] = "low"
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @field_validator("credential_id", "model")
    @classmethod
    def _nonblank_binding(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("审核凭证和模型不能为空白。")
        return value

    @model_validator(mode="after")
    def _validate_bindings(self) -> "PermissionReviewerConfigData":
        if bool(self.credential_id) != bool(self.model):
            raise ValueError("审核凭证和模型必须一起配置。")
        return self


class PermissionReviewerConfigRecord(_RecordBase):
    """The single permission-reviewer configuration owned by one user."""

    user_id: str
    data: PermissionReviewerConfigData = Field(
        default_factory=PermissionReviewerConfigData,
    )


class PermissionReviewAuditRecord(_RecordBase):
    """One persisted decision made by the built-in permission reviewer."""

    user_id: str
    agent_id: str
    session_id: str
    tool_name: str
    action: Literal["allow_once", "deny", "human_required"]
    risk: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    source: str
    model: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
