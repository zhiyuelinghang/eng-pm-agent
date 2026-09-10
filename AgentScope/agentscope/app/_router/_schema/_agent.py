# -*- coding: utf-8 -*-
"""Request / response schemas for the agent router."""
from datetime import datetime
from typing import Literal
import warnings

from pydantic import BaseModel, ConfigDict, Field

from ....agent import ContextConfig, ReActConfig
from ...storage import (
    AgentCallConfig,
    AgentMCPConfig,
    AgentSkillConfig,
    AgentModelPolicy,
    InviteConfig,
    MemorySettingsData,
    ChatModelConfig,
    PlatformAgentConfig,
    PlatformMCPVersionBinding,
    SessionKnowledgeConfig,
)
from ..._service import AgentView


class CreateAgentRequest(BaseModel):
    """Request body for creating a new agent."""

    name: str = Field(description="Display name of the agent.")
    system_prompt: str = Field(
        default="You're a helpful assistant.",
        description="Base system prompt fed to the agent.",
    )
    context_config: ContextConfig = Field(
        default_factory=ContextConfig,
        description="Context-window management configuration.",
    )
    react_config: ReActConfig = Field(
        default_factory=ReActConfig,
        description="ReAct loop configuration.",
    )
    model_policy: AgentModelPolicy = Field(
        default_factory=AgentModelPolicy,
        description=(
            "Agent-specific model selection. Defaults to following the "
            "current conversation."
        ),
    )
    platform_config: PlatformAgentConfig = Field(
        default_factory=PlatformAgentConfig,
        description="Engineering-platform role and publication settings.",
    )
    invite_config: InviteConfig = Field(
        default_factory=InviteConfig,
        description=(
            "Invite-pool settings for this agent. See "
            ":class:`InviteConfig` — enforces the "
            "``invitable ⇒ non-empty description`` invariant."
        ),
    )
    call_config: AgentCallConfig = Field(
        default_factory=AgentCallConfig,
        description="Controls which existing agents this agent may invite.",
    )
    mcp_config: AgentMCPConfig = Field(
        default_factory=AgentMCPConfig,
        description="Managed MCP packages assigned to this agent.",
    )
    skill_config: AgentSkillConfig = Field(
        default_factory=AgentSkillConfig,
        description="Managed skill packages assigned to this agent.",
    )


class CreateAgentResponse(BaseModel):
    """Response body after creating an agent."""

    agent_id: str = Field(description="Server-assigned agent identifier.")


class UpdateAgentRequest(BaseModel):
    """Request body for partially updating an agent.

    Omit any field to keep its current value.
    """

    name: str | None = Field(default=None, description="New display name.")
    system_prompt: str | None = Field(
        default=None,
        description="New system prompt.",
    )
    context_config: ContextConfig | None = Field(
        default=None,
        description="New context configuration.",
    )
    react_config: ReActConfig | None = Field(
        default=None,
        description="New ReAct loop configuration.",
    )
    model_policy: AgentModelPolicy | None = Field(
        default=None,
        description=(
            "New agent model policy. Omit to retain the existing policy."
        ),
    )
    platform_config: PlatformAgentConfig | None = Field(
        default=None,
        description=(
            "Engineering-platform capability and publication settings. "
            "Only explicitly supplied fields are changed; omitted fields "
            "retain their current values."
        ),
    )
    invite_config: InviteConfig | None = Field(
        default=None,
        description=(
            "New invite-pool settings. Pass the full :class:`InviteConfig` "
            "object to update; omit to leave both invitable-related "
            "fields unchanged."
        ),
    )
    call_config: AgentCallConfig | None = Field(
        default=None,
        description=(
            "New agent-call scope and selected-agent whitelist. Pass the "
            "complete object to update; omit to keep the existing settings."
        ),
    )
    mcp_config: AgentMCPConfig | None = Field(
        default=None,
        description=(
            "Complete managed-MCP assignment for this agent. Omit to keep "
            "the existing assignment."
        ),
    )
    skill_config: AgentSkillConfig | None = Field(
        default=None,
        description=(
            "Complete managed-skill assignment for this agent. Omit to keep "
            "the existing assignment."
        ),
    )


class ListAgentsResponse(BaseModel):
    """Response body for listing agents."""

    agents: list[AgentView] = Field(description="Agent records.")
    total: int = Field(description="Total number of agents.")


class PlatformAgentCatalogItem(BaseModel):
    """Safe, runtime-ready agent metadata consumed by the main platform."""

    id: str
    name: str
    description: str
    category: str
    role: str
    enabled: bool
    published: bool
    invitable: bool
    allow_global_main_call: bool
    project_knowledge_enabled: bool
    model_ready: bool
    sort_order: int
    permission_mode: str
    knowledge_config: SessionKnowledgeConfig | None = None
    initialization_role: str | None = None


class PlatformAgentCatalogResponse(BaseModel):
    """Agents exposed to the engineering platform by their global purpose."""

    global_main: PlatformAgentCatalogItem | None = None
    project_initializer: PlatformAgentCatalogItem | None = None
    task_assistant: PlatformAgentCatalogItem | None = None
    knowledge_assistant: PlatformAgentCatalogItem | None = None
    initialization_workers: list[PlatformAgentCatalogItem] = Field(
        default_factory=list,
    )
    business_agents: list[PlatformAgentCatalogItem] = Field(
        default_factory=list,
    )
    total: int


class PlatformSettingsResponse(BaseModel):
    """Platform-wide settings managed independently from agent records."""

    global_main_agent_id: str | None = Field(
        default=None,
        description="The single agent used for ordinary platform chat.",
    )
    project_initializer_agent_id: str | None = Field(
        default=None,
        description="The hidden agent used for project initialization.",
    )
    task_assistant_agent_id: str | None = Field(
        default=None,
        description="The hidden agent assigned to the Task Assistant role.",
    )
    knowledge_assistant_agent_id: str | None = None
    project_initializer_validation_mcp: PlatformMCPVersionBinding | None = Field(
        default=None,
        description=(
            "The exact MCP package version used for required project "
            "initialization validation."
        ),
    )


class MemoryInfrastructureResponse(BaseModel):
    """Read-only memory infrastructure that is unsafe to hot-edit."""

    storage_backend: str = "PostgreSQL/pgvector"
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    mem0_collection: str
    record_table: str = "memory.memory_records"
    write_mode: str = "direct_transaction"
    change_notice: str = (
        "修改嵌入模型或维度需要重建全部记忆向量，不能作为普通在线配置生效。"
    )


class MemorySettingsResponse(BaseModel):
    """Versioned platform-wide Dobby memory policy."""

    settings: MemorySettingsData
    revision: int = Field(ge=1)
    updated_at: datetime
    infrastructure: MemoryInfrastructureResponse


class UpdateMemorySettingsData(MemorySettingsData):
    """A replacement request must explicitly include every public setting."""

    learning_enabled: bool = Field(...)
    learning_model_config: ChatModelConfig | None = Field(...)
    learning_interactions_enabled: bool = Field(...)
    learning_business_events_enabled: bool = Field(...)
    group_learning_enabled: bool = Field(...)
    compression_model_config: ChatModelConfig | None = Field(...)


class UpdateMemorySettingsRequest(BaseModel):
    """Replace the six settings using a mandatory revision check."""

    model_config = ConfigDict(extra="forbid")

    settings: UpdateMemorySettingsData
    expected_revision: int = Field(ge=1)


class WeKnoraConnectionResponse(BaseModel):
    """Secret-free view of the saved WeKnora connection."""

    base_url: str = ""
    api_prefix: str = "/api/v1"
    auth_header: str = "X-API-Key"
    api_key_configured: bool = False


class WeKnoraApiKeyResponse(BaseModel):
    """Saved WeKnora API key returned only on an explicit reveal request."""

    api_key: str


class UpdateWeKnoraConnectionRequest(BaseModel):
    """Create or update the independently managed WeKnora connection."""

    base_url: str = Field(min_length=1, max_length=2048)
    api_prefix: str = Field(default="/api/v1", min_length=1, max_length=256)
    auth_header: str = Field(default="X-API-Key", min_length=1, max_length=256)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)


class TestWeKnoraConnectionRequest(UpdateWeKnoraConnectionRequest):
    """Candidate connection to probe without necessarily saving it."""


class TestWeKnoraConnectionResponse(BaseModel):
    """Result returned after validating the tenant and optional agent."""

    success: bool
    knowledge_base_count: int = 0
    message: str


class WeKnoraKnowledgeBaseItem(BaseModel):
    """Knowledge-base metadata returned by the configured WeKnora tenant."""

    id: str
    name: str
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None


class ListWeKnoraKnowledgeBasesResponse(BaseModel):
    """Remote WeKnora knowledge bases available to engineering documents."""

    knowledge_bases: list[WeKnoraKnowledgeBaseItem] = Field(
        default_factory=list,
    )
    total: int


class WeKnoraKnowledgeItem(BaseModel):
    """One remote file, URL, or manual knowledge item."""

    id: str
    knowledge_base_id: str | None = None
    type: str = ""
    title: str = ""
    description: str = ""
    file_name: str = ""
    folder_path: str = ""
    file_type: str = ""
    file_size: int | None = None
    source: str = ""
    channel: str = ""
    parse_status: str = ""
    enable_status: str = ""
    created_at: str | None = None
    processed_at: str | None = None


class ListWeKnoraKnowledgeResponse(BaseModel):
    """A page of knowledge items in one remote WeKnora knowledge base."""

    knowledge: list[WeKnoraKnowledgeItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class WeKnoraFolderItem(BaseModel):
    """One node in WeKnora's documented folder tree."""

    path: str
    name: str
    document_count: int = 0
    total_count: int = 0
    children: list["WeKnoraFolderItem"] = Field(default_factory=list)


class WeKnoraFolderTreeResponse(BaseModel):
    """The complete folder hierarchy for one remote knowledge base."""

    root_document_count: int = 0
    total_document_count: int = 0
    folders: list[WeKnoraFolderItem] = Field(default_factory=list)


class CreateWeKnoraFolderRequest(BaseModel):
    """Create one persistent WeKnora folder through a hidden marker file."""

    folder_path: str = Field(min_length=1, max_length=4096)


class UpdateWeKnoraFolderRequest(BaseModel):
    """Rename or move a real WeKnora folder by its current path."""

    source_path: str = Field(min_length=1, max_length=4096)
    target_path: str = Field(min_length=1, max_length=4096)


class MoveWeKnoraKnowledgeRequest(BaseModel):
    """Move existing knowledge items without reparsing them."""

    knowledge_ids: list[str] = Field(min_length=1, max_length=200)
    folder_path: str = Field(default="", max_length=4096)


class SearchWeKnoraKnowledgeRequest(BaseModel):
    """Run the documented WeKnora hybrid search for one knowledge base."""

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    vector_threshold: float = Field(default=0.5, ge=0, le=1)
    keyword_threshold: float = Field(default=0.3, ge=0, le=1)


class WeKnoraSearchReference(BaseModel):
    """One cited search result enriched with its source-file metadata."""

    chunk_id: str = ""
    knowledge_id: str = ""
    knowledge_base_id: str = ""
    title: str = ""
    filename: str = ""
    folder_path: str = ""
    content: str = ""
    score: float | None = None
    chunk_index: int | None = None
    start_at: int | None = None
    end_at: int | None = None
    match_type: str = ""
    chunk_type: str = ""
    knowledge_channel: str = ""
    file_type: str = ""
    file_size: int | None = None
    source: str = ""
    knowledge_type: str = ""
    parse_status: str = ""
    download_url: str = ""
    preview_url: str = ""


class SearchWeKnoraKnowledgeResponse(BaseModel):
    """Hybrid-search results ready for AgentScope and frontend citation UI."""

    query: str
    total: int
    references: list[WeKnoraSearchReference] = Field(default_factory=list)


class CreateWeKnoraUrlKnowledgeRequest(BaseModel):
    """Create one WeKnora knowledge item from a remote URL."""

    url: str = Field(min_length=1, max_length=4096)
    title: str = Field(default="", max_length=512)
    enable_multimodel: bool = True


class WeKnoraKnowledgeMutationResponse(BaseModel):
    """Result of a WeKnora upload or URL-ingestion request."""

    knowledge_id: str
    file_name: str = ""
    title: str = ""
    parse_status: str = ""
    message: str


class AskWeKnoraAgentRequest(BaseModel):
    """Call the configured WeKnora agent and aggregate its SSE response."""

    query: str = Field(min_length=1, max_length=4000)
    weknora_agent_id: str = Field(min_length=1, max_length=128)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=50)
    knowledge_ids: list[str] = Field(default_factory=list, max_length=200)
    session_id: str | None = Field(default=None, max_length=128)


class AskWeKnoraAgentResponse(BaseModel):
    """Aggregated answer and citations from the documented agent-chat API."""

    session_id: str
    answer: str
    references: list[dict] = Field(default_factory=list)
    session_title: str = ""


class CreateWeKnoraAgentSessionRequest(BaseModel):
    """Create a WeKnora conversation for one project-bound robot."""

    weknora_agent_id: str = Field(min_length=1, max_length=128)


class WeKnoraAgentSessionResponse(BaseModel):
    """Identifier of a WeKnora conversation prepared for a long answer."""

    session_id: str


class StopWeKnoraAgentSessionRequest(BaseModel):
    """Stop the active assistant generation in a WeKnora conversation."""

    weknora_agent_id: str = Field(min_length=1, max_length=128)


class StopWeKnoraAgentSessionResponse(BaseModel):
    """Result returned after forwarding a stop request to WeKnora."""

    session_id: str
    message_id: str | None = None
    stopped: bool
    message: str


class WeKnoraCatalogueSyncState(BaseModel):
    """Engineering platform's local WeKnora metadata mirror state."""

    status: Literal[
        "uninitialized",
        "pending",
        "syncing",
        "ready",
        "error",
    ] = "uninitialized"
    access_mode: Literal["project", "restricted"] = "project"
    revision: int = 0
    knowledge_base_ids: list[str] = Field(default_factory=list)
    last_started_at: str | None = None
    last_completed_at: str | None = None
    last_error: str | None = None


class WeKnoraProjectBindingItem(BaseModel):
    """One existing engineering project and its assigned WeKnora robot."""

    project_id: int
    project_name: str
    weknora_agent_id: str | None = None
    updated_at: str | None = None
    catalogue_sync: WeKnoraCatalogueSyncState = Field(
        default_factory=WeKnoraCatalogueSyncState,
    )


class ListWeKnoraProjectBindingsResponse(BaseModel):
    """Projects loaded from the engineering platform's authoritative DB."""

    projects: list[WeKnoraProjectBindingItem] = Field(default_factory=list)
    total: int


class UpdateWeKnoraProjectBindingRequest(BaseModel):
    """Assign or clear a WeKnora robot for one existing project."""

    weknora_agent_id: str | None = Field(default=None, max_length=128)


class WeKnoraCatalogueSelectionRequest(BaseModel):
    """Knowledge bases explicitly selected for one project catalogue."""

    knowledge_base_ids: list[str] = Field(min_length=1, max_length=50)


class WeKnoraCatalogueDiffItem(BaseModel):
    """One source/local catalogue difference."""

    node_key: str
    node_type: str
    knowledge_base_id: str
    name: str
    folder_path: str
    changed_fields: list[str] = Field(default_factory=list)


class WeKnoraCatalogueDiffResponse(BaseModel):
    """Read-only comparison result returned by the engineering platform."""

    project_id: int
    project_name: str
    matches: bool
    remote_node_count: int
    local_node_count: int
    added_count: int
    changed_count: int
    removed_count: int
    added: list[WeKnoraCatalogueDiffItem] = Field(default_factory=list)
    changed: list[WeKnoraCatalogueDiffItem] = Field(default_factory=list)
    removed: list[WeKnoraCatalogueDiffItem] = Field(default_factory=list)
    truncated: bool = False


class UpdatePlatformSettingsRequest(BaseModel):
    """Update one or more platform-wide agent assignments."""

    global_main_agent_id: str | None = Field(
        default=None,
        min_length=1,
        description="ID of an enabled agent with a fixed chat model.",
    )
    project_initializer_agent_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "ID of an enabled agent with a fixed chat model to use for "
            "project-initialization conversations."
        ),
    )
    task_assistant_agent_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "ID of an enabled agent with a fixed chat model to use for the "
            "platform Task Assistant responsibility."
        ),
    )
    knowledge_assistant_agent_id: str | None = Field(default=None, min_length=1)
    project_initializer_validation_mcp: PlatformMCPVersionBinding | None = Field(
        default=None,
        description=(
            "Exact managed MCP version used by project initialization "
            "validation."
        ),
    )


class AgentSchemaResponse(BaseModel):
    """**Deprecated.** JSON Schema fragments used by the frontend to
    render the agent create / edit forms.

    Superseded by :class:`AgentSchemaV2Response`, which returns the full
    :class:`AgentData` JSON Schema in a single ``schema`` field so newly
    added agent fields (like the ``invite_config`` sub-model) reach the
    frontend automatically without the router having to know about them.

    The frontend previously split :class:`AgentData` into three
    hand-picked sections (``identity``, ``context_config``,
    ``react_config``) here, which required a router edit every time a
    new user-editable field landed on :class:`AgentData`. Kept for
    backwards compatibility with pre-v2 API consumers.
    """

    identity: dict = Field(
        description=(
            "Schema for the agent's identity fields (``name``, "
            "``system_prompt``)."
        ),
    )
    context_config: dict = Field(
        description="Schema for ``ContextConfig``.",
    )
    react_config: dict = Field(
        description="Schema for ``ReActConfig``.",
    )


# The ``schema`` field name below is intentional — the wire contract for
# ``GET /agent/schema/v2`` is ``{"schema": ...}`` so the response is
# self-documenting. Pydantic v2's :meth:`BaseModel.schema` is a
# deprecated legacy classmethod (superseded by ``model_json_schema``);
# a like-named instance field triggers a cosmetic "shadows an attribute
# in parent BaseModel" warning that is irrelevant here because we never
# call the legacy classmethod. Suppress it locally instead of adding an
# alias that would obscure the wire contract at every call site.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r'Field name "schema" in "AgentSchemaV2Response"',
    )

    class AgentSchemaV2Response(BaseModel):
        """Response for ``GET /agent/schema/v2``.

        Wraps the full :class:`AgentData` JSON Schema in a single
        ``schema`` field so the frontend can render every user-editable
        property without the router having to enumerate them.
        """

        schema: dict = Field(
            description=(
                "Full :class:`AgentData` JSON Schema. All user-editable "
                "fields appear as top-level entries in ``properties`` — "
                "the frontend derives its section grouping from this "
                "single schema."
            ),
        )
