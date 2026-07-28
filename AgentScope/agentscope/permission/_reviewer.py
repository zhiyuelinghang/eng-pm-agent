# -*- coding: utf-8 -*-
"""Optional second-stage reviewer for permission prompts.

The normal :class:`PermissionEngine` remains the security boundary.  A
reviewer is only consulted after the engine returns ``ASK`` (or
``PASSTHROUGH``), and can therefore never override an explicit ``DENY``.
Applications may provide a model-backed implementation, while the core Agent
depends only on the small protocol defined here.
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PermissionReviewAction(str, Enum):
    """Possible outcomes from the built-in permission reviewer."""

    ALLOW_ONCE = "allow_once"
    DENY = "deny"
    HUMAN_REQUIRED = "human_required"


class PermissionReviewRisk(str, Enum):
    """Risk level assigned to one tool invocation by the reviewer."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionReviewRequest(BaseModel):
    """Minimal, isolated context supplied to the permission reviewer."""

    agent_name: str
    tool_name: str
    tool_description: str = ""
    tool_input: dict[str, Any] = Field(default_factory=dict)
    user_intent: str = ""
    permission_mode: str
    permission_reason: str | None = None
    working_directories: list[str] = Field(default_factory=list)
    bypass_immune: bool = False


class PermissionReviewResult(BaseModel):
    """Structured result returned by a permission reviewer."""

    action: PermissionReviewAction
    risk: PermissionReviewRisk
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    model: str | None = None
    source: str = "model"


class PermissionReviewerBase(ABC):
    """Application-provided reviewer invoked for unresolved permission asks."""

    @abstractmethod
    async def review(
        self,
        request: PermissionReviewRequest,
    ) -> PermissionReviewResult:
        """Review a single tool invocation.

        Implementations must fail closed: exceptions are caught by
        :class:`Agent` and leave the original human confirmation in place.
        """
