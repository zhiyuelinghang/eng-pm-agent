# -*- coding: utf-8 -*-
"""Persistence models for platform-wide AgentScope settings."""

from pydantic import BaseModel, Field

from ._base import _RecordBase


class PlatformSettingsData(BaseModel):
    """Settings shared by the whole engineering-management platform."""

    global_main_agent_id: str | None = Field(
        default=None,
        description=(
            "The single agent used by ordinary platform conversations. "
            "This is a platform-wide pointer, not a per-agent declaration."
        ),
    )


class PlatformSettingsRecord(_RecordBase):
    """The single platform-settings record in one global config namespace."""

    user_id: str
    data: PlatformSettingsData = Field(default_factory=PlatformSettingsData)
