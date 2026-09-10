# -*- coding: utf-8 -*-
"""Persistence models for platform-wide AgentScope settings."""

import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ._base import _RecordBase
from ._session import ChatModelConfig


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

DEFAULT_MEMORY_SCOPE_PROMPT = """你是长期记忆作用域路由器。你只负责判断待处理内容应进入哪一种个人长期记忆空间，不负责回答用户。

当前项目上下文：
{project_context}

待处理内容：
{content}

请将内容拆分到以下两类：

1. user：明确、稳定且与具体项目无关的个人信息，例如长期身份、跨项目通用偏好、沟通习惯、长期禁忌。只有能合理应用于该用户其他项目的信息才能进入此类。
2. user_project：只在当前项目成立的信息，例如项目职责、项目约定、技术决策、当前目标、项目内偏好；任何无法确定是否跨项目稳定的内容也必须进入此类。

规则：
- 不得因为一句普通表达就推断出永久个人偏好。
- 出现“这个项目、当前项目、在这里、本项目”等项目语境时，优先归入 user_project。
- 出现“以后所有项目、我一直、我通常、无论什么项目”等明确跨项目语义时，才可以归入 user。
- 同一段内容同时包含两类信息时，应拆成两个最小且语义完整的片段。
- content 必须直接摘取待处理内容中的原文，不得改写或虚构，不要添加解释。
- 如果无法确定，归入 user_project。
- user 中的每一项必须给出待处理内容里的原文证据，stable 必须为 true，confidence 必须不低于 0.9；达不到时放入 user_project。

严格输出 JSON：
{{
  "user": [
    {{
      "content": "用户级内容片段",
      "evidence": "待处理内容中能证明它跨项目稳定的原文",
      "stable": true,
      "confidence": 0.95
    }}
  ],
  "user_project": ["用户＋项目级内容片段"]
}}

只输出 JSON，不要其他文字。"""


class MemorySettingsData(BaseModel):
    """The six user decisions for platform memory and background learning."""

    model_config = ConfigDict(extra="forbid")

    learning_enabled: bool = False
    learning_model_config: ChatModelConfig | None = None
    learning_interactions_enabled: bool = True
    learning_business_events_enabled: bool = True
    group_learning_enabled: bool = True
    compression_model_config: ChatModelConfig | None = None

    @model_validator(mode="after")
    def _validate_learning(self) -> "MemorySettingsData":
        if self.learning_enabled:
            if self.learning_model_config is None:
                raise ValueError("启用后台学习前，请先选择学习模型。")
            if not any((self.learning_interactions_enabled,
                        self.learning_business_events_enabled,
                        self.group_learning_enabled)):
                raise ValueError("启用后台学习时，至少选择一种学习来源。")
        return self


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
    task_assistant_agent_id: str | None = Field(
        default=None,
        description=(
            "The hidden built-in agent assigned to the fixed platform "
            "responsibility named Task Assistant. The engineering platform "
            "never exposes the selected agent's own display name."
        ),
    )
    knowledge_assistant_agent_id: str | None = Field(
        default=None,
        description="The agent assigned to the platform's Knowledge Assistant responsibility.",
    )
    project_initializer_validation_mcp: PlatformMCPVersionBinding | None = Field(
        default=None,
        description=(
            "The exact managed MCP package version used by the required "
            "project-initialization validation step."
        ),
    )
    weknora_connection: WeKnoraConnectionConfig | None = Field(
        default=None,
        description=(
            "The independently managed WeKnora tenant connection. The API "
            "key is persisted server-side and never exposed by API responses."
        ),
    )
    memory_settings: MemorySettingsData = Field(
        default_factory=MemorySettingsData,
        description="Platform-wide Dobby memory policy.",
    )
    memory_settings_revision: int = Field(default=1, ge=1)


class PlatformSettingsRecord(_RecordBase):
    """The single platform-settings record in one global config namespace."""

    user_id: str
    data: PlatformSettingsData = Field(default_factory=PlatformSettingsData)
