# -*- coding: utf-8 -*-
"""Persistence models for platform-wide AgentScope settings."""

from pydantic import BaseModel, Field

from ._base import _RecordBase


class PlatformMCPVersionBinding(BaseModel):
    """Exact immutable MCP package version bound to a platform capability."""

    package_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)


class PlatformSettingsData(BaseModel):
    """Settings shared by the whole engineering-management platform."""

    global_main_agent_id: str | None = Field(
        default=None,
        description=(
            "The single agent used by ordinary platform conversations. "
            "This is a platform-wide pointer, not a per-agent declaration."
        ),
    )
    project_initializer_agent_id: str | None = Field(
        default=None,
        description=(
            "The hidden built-in agent used by project-initialization "
            "conversations. It may build initialization drafts but cannot "
            "write formal project data directly."
        ),
    )
    project_initializer_validation_mcp: PlatformMCPVersionBinding | None = Field(
        default=None,
        description=(
            "The exact managed MCP package version used by the required "
            "project-initialization validation step."
        ),
    )


class PlatformSettingsRecord(_RecordBase):
    """The single platform-settings record in one global config namespace."""

    user_id: str
    data: PlatformSettingsData = Field(default_factory=PlatformSettingsData)
