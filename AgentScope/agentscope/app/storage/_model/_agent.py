# -*- coding: utf-8 -*-
"""The agent storage class."""
from typing import Literal, Self

from pydantic import Field, BaseModel, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from ...._utils._common import _generate_id
from ._base import _RecordBase
from ._session import ChatModelConfig
from ....agent import ContextConfig, ReActConfig


class InviteConfig(BaseModel):
    """User-editable invite settings for :class:`AgentData`.

    Kept in its own sub-model so the frontend's schema-driven form —
    which renders any nested-object property as its own fieldset —
    picks it up as a dedicated section without a per-field allowlist.
    Also keeps the cross-field ``invitable ⇒ non-empty description``
    invariant local to this model.
    """

    invitable: bool = Field(
        default=False,
        description=(
            "Whether this agent may be borrowed into another agent's team "
            "via the ``AgentInvite`` tool. Independent from "
            ":attr:`invite_description` so the user can preserve an "
            "authored blurb while temporarily disabling the toggle. "
            "``invitable=True`` requires a non-empty "
            ":attr:`invite_description` (enforced by validator)."
        ),
        title="Invitable",
    )

    invite_description: str | None = Field(
        default=None,
        description=(
            "Free-text blurb shown to a leader LLM in the ``AgentInvite`` "
            "tool description — used by the leader to decide whether to "
            "borrow this agent. Persisted across toggle off/on so the "
            "user's authored draft is not lost when :attr:`invitable` "
            "is temporarily disabled."
        ),
        title="Invite Description",
        json_schema_extra={"format": "textarea"},
    )

    @model_validator(mode="after")
    def _check_invitable_has_description(self) -> Self:
        """Reject ``invitable=True`` without a non-empty description.

        The blurb is what the leader LLM sees when it inspects the
        ``AgentInvite`` tool; without it, the LLM cannot make a sensible
        choice. Rejecting at the model boundary (rather than in the
        service layer) means PATCH / POST return HTTP 422 automatically.
        """
        if self.invitable and not (self.invite_description or "").strip():
            raise ValueError(
                "invite_description must be non-empty when invitable=True",
            )
        return self


class AgentCallConfig(BaseModel):
    """Controls which existing agents this agent may invite.

    ``scope='all'`` deliberately represents a dynamic set: every agent that
    is visible to the caller and currently marked invitable is eligible,
    including agents created after this configuration was saved.
    """

    scope: Literal["all", "selected", "none"] = Field(
        default="all",
        description=(
            "Agent-call scope. ``all`` allows every visible invitable agent, "
            "``selected`` allows only ``allowed_agent_ids``, and ``none`` "
            "disables AgentInvite for this agent."
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
        if self.scope == "all":
            return True
        if self.scope == "selected":
            return agent_id in self.allowed_agent_ids
        return False


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
