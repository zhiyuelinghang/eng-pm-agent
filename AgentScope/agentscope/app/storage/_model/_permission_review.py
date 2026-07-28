# -*- coding: utf-8 -*-
"""Persistence models for the built-in permission reviewer."""
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ._base import _RecordBase


class PermissionReviewerConfigData(BaseModel):
    """Per-user model binding and policy for the system reviewer."""

    enabled: bool = False
    credential_id: str | None = None
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    fallback_credential_id: str | None = None
    fallback_model: str | None = None
    fallback_parameters: dict[str, Any] = Field(default_factory=dict)
    confidence_threshold: float = Field(default=0.85, ge=0.5, le=1)
    max_auto_risk: Literal["low", "medium"] = "low"
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def _validate_bindings(self) -> "PermissionReviewerConfigData":
        if self.enabled and (not self.credential_id or not self.model):
            raise ValueError(
                "An enabled permission reviewer requires a credential "
                "and model.",
            )
        fallback_values = (
            self.fallback_credential_id,
            self.fallback_model,
        )
        if any(fallback_values) and not all(fallback_values):
            raise ValueError(
                "Fallback credential and fallback model must be configured "
                "together.",
            )
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
