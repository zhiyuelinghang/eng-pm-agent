# -*- coding: utf-8 -*-
"""The agent storage class."""
from typing import Literal, Self

from pydantic import ConfigDict, Field, BaseModel, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from ...._utils._common import _generate_id
from ._base import _RecordBase
from ._session import (
    ChatModelConfig,
    SessionKnowledgeConfig,
)
from ....permission import PermissionMode
from ....agent import ContextConfig, ReActConfig


class InviteConfig(BaseModel):
    """Consent to invitations from non-main agents and collaboration metadata."""

    invitable: bool = Field(
        default=False,
        description=(
            "Whether other non-main agents can select and invite this agent. "
            "The caller must also include it in its explicit collaboration "
            "list. Independent from allow_global_main_call."
        ),
        title="Invitable",
    )

    invite_description: str | None = Field(
        default=None,
        description=(
            "Free-text blurb shown to a leader LLM in the ``AgentInvite`` "
            "tool description — used by the leader to decide whether to "
            "borrow this agent. Falls back to the platform description or "
            "agent name when empty."
        ),
        title="Invite Description",
        json_schema_extra={"format": "textarea"},
    )

class AgentCallConfig(BaseModel):
    """Controls which existing agents this agent may invite.

    Platform main access is derived from the authoritative main-agent pointer.
    Other agents can only use an explicitly selected list.
    """

    scope: Literal["selected", "none"] = Field(
        default="none",
        description=(
            "Agent-call scope. ``selected`` allows only ``allowed_agent_ids``; "
            "``none`` disables outgoing delegation. Main-agent access is "
            "fixed by platform settings."
        ),
        title="Call Scope",
    )

    allowed_agent_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Agent ids allowed when ``scope`` is ``selected``. The list is "
            "preserved while another scope is active so a user can switch "
            "back without rebuilding the selection."
        ),
        title="Allowed Agents",
    )

    @field_validator("allowed_agent_ids")
    @classmethod
    def _normalise_allowed_agent_ids(cls, values: list[str]) -> list[str]:
        """Trim, de-duplicate, and discard empty ids while preserving order."""
        return list(
            dict.fromkeys(
                value.strip() for value in values if value.strip()
            ),
        )

    def allows(self, agent_id: str) -> bool:
        """Return whether ``agent_id`` is inside this configured scope."""
        if self.scope == "selected":
            return agent_id in self.allowed_agent_ids
        return False


class AgentToolConfig(BaseModel):
    """Legacy direct-tool assignment retained for data compatibility.

    System/workspace tools are now fixed global capabilities and no longer use
    this allowlist. The persisted value remains readable only so the database-
    interaction migration can recover assignments created by older versions.
    """

    allowed_tool_names: list[str] | None = Field(
        default=None,
        description=(
            "Deprecated legacy assignment names. Fixed system tools ignore "
            "this value."
        ),
        title="Legacy Tool Assignments",
    )

    @field_validator("allowed_tool_names")
    @classmethod
    def _normalise_allowed_tool_names(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        """Trim and de-duplicate explicit tool names in stable order."""
        if values is None:
            return None
        return list(
            dict.fromkeys(
                value.strip() for value in values if value.strip()
            ),
        )

    def allows(self, tool_name: str) -> bool:
        """Fixed system tools are available to every agent."""
        del tool_name
        return True


class AgentMCPConfig(BaseModel):
    """Managed MCP packages assigned to an agent.

    Package artifacts live in the platform registry.  This model stores only
    stable package ids so every management and engineering-platform session
    of the agent resolves the same assignment while receiving its own runtime
    process instances.
    """

    allowed_mcp_ids: list[str] = Field(
        default_factory=list,
        description="Managed MCP package ids assigned to this agent.",
        title="Assigned MCP Packages",
    )

    @field_validator("allowed_mcp_ids")
    @classmethod
    def _normalise_allowed_mcp_ids(cls, values: list[str]) -> list[str]:
        """Trim and de-duplicate package ids while preserving order."""
        return list(
            dict.fromkeys(
                value.strip() for value in values if value.strip()
            ),
        )


class AgentSkillConfig(BaseModel):
    """Managed platform skills assigned to every session of an agent."""

    allowed_skill_ids: list[str] = Field(
        default_factory=list,
        description="Managed skill package ids assigned to this agent.",
        title="Assigned Skills",
    )

    @field_validator("allowed_skill_ids")
    @classmethod
    def _normalise_allowed_skill_ids(cls, values: list[str]) -> list[str]:
        """Trim and de-duplicate package ids while preserving order."""
        return list(
            dict.fromkeys(
                value.strip() for value in values if value.strip()
            ),
        )


class AgentModelPolicy(BaseModel):
    """Controls whether an agent follows its session or pins a model.

    ``chat_model_config`` is intentionally retained while ``mode`` is
    ``inherit_session`` so users can temporarily follow a conversation and
    later switch back to the previously selected fixed model without
    rebuilding its provider-specific parameters.
    """

    mode: Literal["inherit_session", "fixed"] = Field(
        default="inherit_session",
        description=(
            "Model selection policy. ``inherit_session`` uses the model "
            "selected by the current conversation; ``fixed`` always uses "
            "``chat_model_config``."
        ),
        title="Model Policy",
    )

    chat_model_config: ChatModelConfig | None = Field(
        default=None,
        description=(
            "Agent-specific model and parameters. Required when mode is "
            "``fixed`` and ignored while inheriting the session model."
        ),
        title="Fixed Chat Model",
    )

    @model_validator(mode="after")
    def _require_fixed_model(self) -> "AgentModelPolicy":
        if self.mode == "fixed" and self.chat_model_config is None:
            raise ValueError(
                "chat_model_config is required when model policy is fixed",
            )
        return self


class PlatformAgentConfig(BaseModel):
    """Controls how an agent is exposed to the engineering platform.

    The AgentScope Web UI remains the administration surface, while the
    engineering platform consumes this deliberately small publication
    contract.  Runtime prompts, credentials, and provider parameters never
    need to leak into the platform's business-agent catalogue.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["global_main", "business", "system_internal"] = Field(
        default="business",
        description=(
            "Platform role. ``business`` is published in the business-tool "
            "catalogue and ``system_internal`` stays hidden. "
            "``global_main`` is reserved for the "
            "platform-wide main-agent setting and must not be assigned "
            "directly."
        ),
        title="Platform Role",
    )

    enabled: bool = Field(
        default=True,
        description="Whether the engineering platform may run this agent.",
        title="Platform Enabled",
    )

    published: bool = Field(
        default=True,
        description=(
            "Whether this agent is published to the engineering platform. "
            "Only enabled, published business agents appear as business tools."
        ),
        title="Published",
    )

    allow_global_main_call: bool = Field(
        default=False,
        description=(
            "Whether the enabled agent is included in the platform main "
            "agent's dynamic collaboration catalogue. Other callers still "
            "use their own explicit collaboration lists."
        ),
        title="Allow Platform Main Agent Call",
    )

    initialization_role: SkipJsonSchema[
        Literal[
            "orchestrator",
            "project",
            "personnel",
            "wbs",
            "risks",
            "quality_requirements",
            "validator",
        ]
        | None
    ] = Field(
        default=None,
        description=(
            "Internal project-initialization team label used for catalogue "
            "grouping. Capabilities are granted only by explicit database "
            "interaction assignments. Hidden from the schema-driven "
            "management form and maintained by Dobby's provisioning command."
        ),
    )

    description: str | None = Field(
        default=None,
        description=(
            "Business-facing description shown in the platform catalogue. "
            "When omitted, the invite description is used as a fallback."
        ),
        title="Platform Description",
        json_schema_extra={"format": "textarea"},
    )

    category: str = Field(
        default="通用",
        description="Business-tool category shown in the platform.",
        title="Category",
    )

    sort_order: int = Field(
        default=100,
        ge=0,
        le=9999,
        description="Ascending display order in the business-tool catalogue.",
        title="Sort Order",
    )

    permission_mode: PermissionMode = Field(
        default=PermissionMode.AUTO,
        description=(
            "Permission mode used by management debug runs and supplied to "
            "sessions created by the engineering platform. Debug sessions "
            "read this setting at each run and cannot override it."
        ),
        title="Platform Permission Mode",
    )

    knowledge_config: SessionKnowledgeConfig | None = Field(
        default=None,
        description=(
            "Default knowledge bases and retrieval parameters attached to "
            "sessions created for this agent by the engineering platform."
        ),
        title="Platform Knowledge Configuration",
    )

class AgentData(BaseModel):
    """The agent data model."""

    id: SkipJsonSchema[str] = Field(
        description="Unique agent id",
        default_factory=_generate_id,
    )
    """The agent id.

    Server-assigned; never edited via the create / update form.
    Annotated with :class:`SkipJsonSchema` so it is dropped from
    ``AgentData.model_json_schema()`` (the frontend renders the form
    off that schema) while still being serialised in normal JSON
    dumps (so persisted records keep the id).
    """

    name: str = Field(
        description="The name of the agent.",
        title="Name",
    )

    system_prompt: str = Field(
        default="You're a helpful assistant.",
        description="The system prompt for the agent.",
        title="System Prompt",
        # Hint for schema-driven UI renderers; see ``ContextConfig`` for
        # the same pattern on long-form prompts.
        json_schema_extra={"format": "textarea"},
    )

    context_config: ContextConfig = Field(
        description="The context config for the agent.",
        title="Context Config",
    )

    react_config: ReActConfig = Field(
        description="The react config for the agent.",
        title="React Config",
    )

    model_policy: AgentModelPolicy = Field(
        default_factory=AgentModelPolicy,
        description=(
            "Controls whether this agent follows the current conversation's "
            "model or always uses its own model and request parameters."
        ),
        title="Model Configuration",
    )

    platform_config: PlatformAgentConfig = Field(
        default_factory=PlatformAgentConfig,
        description=(
            "Publication, role, permission, and knowledge defaults used by "
            "the engineering platform integration."
        ),
        title="Platform Integration",
    )

    invite_config: InviteConfig = Field(
        default_factory=InviteConfig,
        description="The invite config for the agent.",
        title="Invite Config",
    )

    call_config: AgentCallConfig = Field(
        default_factory=AgentCallConfig,
        description="Controls which existing agents this agent may invite.",
        title="Agent Call Config",
    )

    tool_config: SkipJsonSchema[AgentToolConfig] = Field(
        default_factory=AgentToolConfig,
        description=(
            "Deprecated direct-tool assignment retained only for migration "
            "of historical database-interaction selections."
        ),
    )

    mcp_config: SkipJsonSchema[AgentMCPConfig] = Field(
        default_factory=AgentMCPConfig,
        description=(
            "Managed MCP assignment maintained by the chat sidebar. Hidden "
            "from the schema-driven dialog to avoid duplicate editors."
        ),
    )

    skill_config: SkipJsonSchema[AgentSkillConfig] = Field(
        default_factory=AgentSkillConfig,
        description=(
            "Managed skill assignment maintained by the chat sidebar. "
            "Hidden from the schema-driven dialog to avoid duplicate editors."
        ),
    )


class AgentRecord(_RecordBase):
    """The agent ORM model."""

    user_id: str
    """The user id"""

    source: Literal["user", "team"] = "user"
    """How this agent was created.

    - ``"user"``: created directly by the user (default). Can have multiple
      sessions and is listed in the user's regular agent list.
    - ``"team"``: spawned as a team worker by another agent's
      ``create_team`` / ``team_add_member`` tool. Has exactly one session.
      Team membership itself is session-level and stored on
      :class:`SessionRecord.team_id`.
    """

    data: AgentData
    """The agent data"""
