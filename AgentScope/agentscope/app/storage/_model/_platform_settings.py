# -*- coding: utf-8 -*-
"""Persistence models for platform-wide AgentScope settings."""

import re

from pydantic import BaseModel, Field, SecretStr, field_validator

from ._base import _RecordBase


class PlatformMCPVersionBinding(BaseModel):
    """Exact immutable MCP package version bound to a platform capability."""

    package_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)


class WeKnoraConnectionConfig(BaseModel):
    """Server-side connection details for one WeKnora tenant."""

    base_url: str = Field(
        min_length=1,
        max_length=2048,
        description="Absolute HTTP(S) URL of the WeKnora service.",
    )
    api_prefix: str = Field(
        default="/api/v1",
        min_length=1,
        max_length=256,
    )
    auth_header: str = Field(
        default="X-API-Key",
        min_length=1,
        max_length=256,
    )
    api_key: SecretStr = Field(min_length=1, max_length=4096)

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("api_prefix")
    @classmethod
    def _normalise_api_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character in value for character in "?#"):
            raise ValueError("API prefix must be a URL path without query data.")
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/") or "/"

    @field_validator("auth_header")
    @classmethod
    def _normalise_auth_header(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", value):
            raise ValueError("Authentication header must be a valid HTTP token.")
        return value


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
    engineering_document_agent_id: str | None = Field(
        default=None,
        description=(
            "The dedicated agent selected for engineering document "
            "management. This stores assignment intent only; runtime "
            "WeKnora retrieval is enabled separately."
        ),
    )
    weknora_connection: WeKnoraConnectionConfig | None = Field(
        default=None,
        description=(
            "The independently managed WeKnora tenant connection. The API "
            "key is persisted server-side and never exposed by API responses."
        ),
    )


class PlatformSettingsRecord(_RecordBase):
    """The single platform-settings record in one global config namespace."""

    user_id: str
    data: PlatformSettingsData = Field(default_factory=PlatformSettingsData)
