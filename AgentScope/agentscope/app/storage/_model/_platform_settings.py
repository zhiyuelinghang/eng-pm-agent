# -*- coding: utf-8 -*-
"""Persistence models for platform-wide AgentScope settings."""

import re
from typing import Literal

from pydantic import (
    BaseModel,
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

DEFAULT_COMPRESSION_SYSTEM_PROMPT = """你是 Dobby 对话压缩器。你的任务是将长对话历史压缩为结构化摘要。

**压缩规则**:
1. 保留所有活跃任务的状态（task_id, status, owner, description）
2. 保留关键决策和承诺（谁在什么时候决定了什么）
3. 保留用户偏好和约束（格式要求、风格偏好、禁止事项）
4. 普通闲聊和中间推理过程可以丢弃
5. 摘要应简洁但信息完整，中文书写

**输出格式** — 严格 JSON:
{
  "summary": "完整的对话摘要...",
  "tasks": {"task_id": {"status": "in_progress|done|blocked", "desc": "任务描述"}},
  "decisions": ["决定1", "决定2"],
  "context_to_preserve": "用户偏好和约束..."
}"""

DEFAULT_COMPRESSION_USER_PROMPT = """现有摘要:
{existing_summary}

活跃任务:
{existing_tasks}

新对话内容 (最近50轮):
{recent_messages}

请生成更新后的摘要。只输出 JSON，不要其他文字。"""

DEFAULT_COMPRESSION_INCREMENTAL_PROMPT = """你正在**更新**已有的对话摘要。无需重写整个摘要，只需整合新增内容。

## 旧摘要（请保留其中仍然有效的所有信息）
{existing_summary}

## 当前任务快照
{existing_tasks}

## 新增对话（最近50轮，整合进上述摘要）
{recent_messages}

## 更新规则
1. **保留**旧摘要中仍然有效的所有事项（任务、决策、偏好）
2. **新增**上面"新增对话"中出现的新任务、新决策、新约束
3. **更新**旧摘要中已经变化的任务状态（进行中→已完成、阻塞→解除等）
4. **删除**已经完成的、不再需要追踪的一次性闲聊内容
5. 如果新增对话无实质变化，摘要应与旧摘要基本一致

**输出格式** — 严格 JSON:
{{
  "summary": "完整的对话摘要...",
  "tasks": {{"task_id": {{"status": "in_progress|done|blocked", "desc": "任务描述"}}}},
  "decisions": ["决定1", "决定2"],
  "context_to_preserve": "用户偏好和约束..."
}}

只输出 JSON，不要其他文字。"""

DEFAULT_HISTORIAN_SYSTEM_PROMPT = """你是 Dobby 对话历史学家（Historian）。你的任务是将一段对话压缩为结构化分舱。

**输出格式** — 严格 JSON:
{
  "importance": 0.7,
  "episode_type": "task",
  "p1_verbose": "详细的事件描述...",
  "p2_standard": "标准摘要(50%长度)...",
  "p3_brief": "1-2句话简要概述",
  "p4_anchor": "关键词1,关键词2,关键词3",
  "facts": ["事实1", "事实2"],
  "events": ["事件1", "事件2"]
}

**episode_type**: conversation | task | decision | summary
**importance**: 0.9=关键决策/重大变更, 0.7=任务完成, 0.5=一般交互, 0.3=闲聊
**分层规则**: p1保留who/when/what/why, p2精简50%, p3一句话, p4仅关键词

只输出 JSON，不要其他文字。"""

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
    """Editable platform-wide policy for the Dobby memory subsystem.

    The active model still owns its real context window. Ratios below are
    applied to that window at runtime, so one global policy works for agents
    backed by models with different context sizes.
    """

    memory_model_config: ChatModelConfig | None = Field(
        default=None,
        description=(
            "Platform credential and model used by memory-only LLM work. "
            "None preserves the legacy runtime fallback."
        ),
    )

    recall_top_k: int = Field(default=5, ge=1, le=50)
    memory_profile_enabled: bool = True
    memory_semantic_search_enabled: bool = True
    memory_index_enabled: bool = True
    learning_enabled: bool = True
    group_learning_enabled: bool = True
    group_learning_scan_seconds: int = Field(default=300, ge=30, le=3600)
    group_learning_message_threshold: int = Field(default=20, ge=1, le=100)
    group_learning_idle_seconds: int = Field(default=600, ge=60, le=86400)
    group_learning_max_wait_seconds: int = Field(default=3600, ge=300, le=86400)
    group_learning_batch_size: int = Field(default=50, ge=1, le=100)
    group_learning_daily_limit: int = Field(default=100, ge=1, le=2000)
    learning_auto_consolidate: bool = True
    learning_model_config: ChatModelConfig | None = None
    learning_capture_corrections: bool = True
    learning_capture_failures: bool = True
    learning_capture_verified_tasks: bool = True
    learning_capture_patterns: bool = True
    learning_daily_job_limit: int = Field(default=30,ge=1,le=200)
    learning_cooldown_seconds: int = Field(default=60,ge=0,le=3600)
    learning_pattern_threshold: int = Field(default=3,ge=2,le=20)
    learning_timeout_seconds: int = Field(default=90,ge=10,le=180)
    learning_input_char_limit: int = Field(default=16000,ge=4000,le=60000)
    learning_review_days: int = Field(default=90,ge=7,le=365)
    learning_skill_limit: int = Field(default=3,ge=0,le=10)
    recall_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    recall_reinforce_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    fusion_weight_mem0: float = Field(default=0.20, ge=0.0, le=2.0)
    fusion_weight_kb: float = Field(default=0.35, ge=0.0, le=2.0)
    fusion_weight_timeline: float = Field(default=0.15, ge=0.0, le=2.0)
    fusion_weight_experience: float = Field(default=0.30, ge=0.0, le=2.0)
    fusion_weight_graphrag: float = Field(default=0.25, ge=0.0, le=2.0)
    fusion_mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    rrf_k: int = Field(default=60, ge=1, le=500)

    mem0_infer_enabled: bool = False
    mem0_infer_async: bool = True

    compression_trigger_ratio: float = Field(default=0.8, gt=0.0, le=0.9)
    compression_keep_messages: int = Field(default=20, ge=2, le=200)
    compression_mode: Literal["full", "incremental"] = "incremental"
    emergency_compression_ratio: float = Field(default=0.95, ge=0.9, le=1.0)
    compression_background: bool = True
    historian_trigger_ratio: float = Field(default=0.3, gt=0.0, lt=0.9)
    compression_max_consecutive: int = Field(default=3, ge=1, le=20)
    compression_quality_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    compression_min_rounds_between: int = Field(default=5, ge=0, le=100)

    token_budget_system_prompt: int = Field(default=5_000, ge=256, le=200_000)
    token_budget_skill_injection: int = Field(default=3_000, ge=0, le=200_000)
    token_budget_summary: int = Field(default=15_000, ge=256, le=200_000)
    token_budget_ltm_kb_timeline: int = Field(default=30_000, ge=256, le=200_000)
    token_budget_runtime: int = Field(default=2_000, ge=128, le=200_000)
    token_budget_recent_history: int = Field(default=10_000, ge=256, le=200_000)
    token_budget_output_reserve: int = Field(default=4_000, ge=256, le=200_000)

    dreamer_enabled: bool = True
    experience_event_driven_enabled: bool = True

    compression_system_prompt: str = Field(
        default=DEFAULT_COMPRESSION_SYSTEM_PROMPT,
        min_length=1,
        max_length=50_000,
    )
    compression_user_prompt: str = Field(
        default=DEFAULT_COMPRESSION_USER_PROMPT,
        min_length=1,
        max_length=50_000,
    )
    compression_incremental_prompt: str = Field(
        default=DEFAULT_COMPRESSION_INCREMENTAL_PROMPT,
        min_length=1,
        max_length=50_000,
    )
    historian_system_prompt: str = Field(
        default=DEFAULT_HISTORIAN_SYSTEM_PROMPT,
        min_length=1,
        max_length=50_000,
    )

    @model_validator(mode="after")
    def _validate_policy(self) -> "MemorySettingsData":
        if self.emergency_compression_ratio <= self.compression_trigger_ratio:
            raise ValueError("紧急压缩比例必须大于普通压缩触发比例。")
        required = {"existing_summary", "existing_tasks", "recent_messages"}
        for label, template in (
            ("压缩提示词", self.compression_user_prompt),
            ("增量压缩提示词", self.compression_incremental_prompt),
        ):
            missing = [name for name in required if "{" + name + "}" not in template]
            if missing:
                raise ValueError(f"{label}缺少占位符：{', '.join(sorted(missing))}")
            try:
                template.format(
                    existing_summary="summary",
                    existing_tasks="tasks",
                    recent_messages="messages",
                )
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"{label}格式无效：{exc}") from exc
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
