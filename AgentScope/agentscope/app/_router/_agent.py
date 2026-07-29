# -*- coding: utf-8 -*-
"""Agent router — CRUD endpoints for agent configurations."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from ...agent import ContextConfig, ReActConfig
from ..._utils._common import _flatten_json_schema
from ..access import ResourceKind
from ..deps import (
    get_current_user_id,
    get_resource_access_service,
    get_session_service,
    get_storage,
)
from ._schema import (
    AgentSchemaResponse,
    AgentSchemaV2Response,
    ListAgentsResponse,
    CreateAgentRequest,
    CreateAgentResponse,
    PlatformAgentCatalogItem,
    PlatformAgentCatalogResponse,
    PlatformSettingsResponse,
    UpdatePlatformSettingsRequest,
    UpdateAgentRequest,
)
from .._service import (
    AgentView,
    ResourceAccessService,
    SessionService,
    build_credential_model_catalog,
    normalize_credential_model_parameters,
)
from ..storage import (
    AgentData,
    AgentModelPolicy,
    AgentRecord,
    PlatformSettingsData,
    PlatformSettingsRecord,
    StorageBase,
)
from ...credential import CredentialFactory

agent_router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    responses={404: {"description": "Not found"}},
)


def _normalise_platform_agent_data(data: AgentData) -> AgentData:
    """Apply invariants implied by an agent's platform role."""
    platform_config = data.platform_config
    updates = {}
    if platform_config.role == "global_main" and data.call_config.scope != "all":
        updates["call_config"] = data.call_config.model_copy(
            update={"scope": "all"},
        )
    if platform_config.role == "system_internal" and platform_config.published:
        updates["platform_config"] = platform_config.model_copy(
            update={"published": False},
        )
    return data.model_copy(update=updates) if updates else data


async def _demote_other_global_main_agents(
    storage: StorageBase,
    global_config_id: str,
    selected_agent_id: str,
) -> None:
    """Keep exactly one global-main agent in the platform configuration."""
    for record in await storage.list_agents(global_config_id):
        if (
            record.id == selected_agent_id
            or record.data.platform_config.role != "global_main"
        ):
            continue
        demoted_config = record.data.platform_config.model_copy(
            update={"role": "business"},
        )
        demoted_call_config = record.data.call_config.model_copy(
            update={"scope": "selected"},
        )
        demoted = record.model_copy(
            update={
                "data": record.data.model_copy(
                    update={
                        "platform_config": demoted_config,
                        "call_config": demoted_call_config,
                    },
                ),
                "updated_at": datetime.now(),
            },
        )
        await storage.upsert_agent(global_config_id, demoted)


async def _synchronise_global_main_agent_roles(
    storage: StorageBase,
    global_config_id: str,
    selected_agent_id: str | None,
) -> None:
    """Mirror the authoritative pointer into legacy per-agent role fields.

    The pointer in :class:`PlatformSettingsData` is authoritative. Keeping the
    old role field synchronized preserves wire compatibility with older
    clients while ensuring there is never more than one derived
    ``global_main`` role.
    """
    for record in await storage.list_agents(global_config_id):
        current_role = record.data.platform_config.role
        desired_role = (
            "global_main"
            if record.id == selected_agent_id
            else ("business" if current_role == "global_main" else current_role)
        )
        if record.id == selected_agent_id:
            desired_scope = "all"
        elif current_role == "global_main":
            # A former main must not retain its platform-wide privilege.
            # Keep any explicit IDs so the admin can reuse the old whitelist.
            desired_scope = "selected"
        else:
            desired_scope = record.data.call_config.scope
        if (
            desired_role == current_role
            and desired_scope == record.data.call_config.scope
        ):
            continue
        platform_config = record.data.platform_config.model_copy(
            update={"role": desired_role},
        )
        call_config = record.data.call_config.model_copy(
            update={"scope": desired_scope},
        )
        updated = record.model_copy(
            update={
                "data": record.data.model_copy(
                    update={
                        "platform_config": platform_config,
                        "call_config": call_config,
                    },
                ),
                "updated_at": datetime.now(),
            },
        )
        await storage.upsert_agent(global_config_id, updated)


async def _load_platform_settings(
    storage: StorageBase,
    global_config_id: str,
) -> PlatformSettingsRecord:
    """Load settings and migrate the former per-agent main role once."""
    existing = await storage.get_platform_settings(global_config_id)
    if existing is not None:
        await _synchronise_global_main_agent_roles(
            storage,
            global_config_id,
            existing.data.global_main_agent_id,
        )
        return existing

    records = await storage.list_agents(global_config_id)
    legacy_candidates = sorted(
        (
            record
            for record in records
            if record.data.platform_config.role == "global_main"
        ),
        key=lambda record: (
            not record.data.platform_config.enabled,
            record.data.platform_config.sort_order,
            record.data.name,
            record.id,
        ),
    )
    selected_id = legacy_candidates[0].id if legacy_candidates else None
    data = PlatformSettingsData(global_main_agent_id=selected_id)
    try:
        settings = await storage.upsert_platform_settings(
            global_config_id,
            data,
        )
    except NotImplementedError:
        settings = PlatformSettingsRecord(
            user_id=global_config_id,
            data=data,
        )
    await _synchronise_global_main_agent_roles(
        storage,
        global_config_id,
        selected_id,
    )
    return settings


def _catalog_item(agent: AgentView) -> PlatformAgentCatalogItem:
    config = agent.data.platform_config
    description = (
        (config.description or "").strip()
        or (agent.data.invite_config.invite_description or "").strip()
        or "暂无业务说明"
    )
    permission_mode = config.permission_mode
    return PlatformAgentCatalogItem(
        id=agent.id,
        name=agent.data.name,
        description=description,
        category=config.category.strip() or "通用",
        role=config.role,
        enabled=config.enabled,
        published=config.published,
        invitable=bool(agent.data.invite_config.invitable),
        model_ready=(
            agent.data.model_policy.mode == "fixed"
            and agent.data.model_policy.chat_model_config is not None
        ),
        sort_order=config.sort_order,
        permission_mode=getattr(permission_mode, "value", permission_mode),
        knowledge_config=config.knowledge_config,
    )


async def _validate_model_policy(
    user_id: str,
    policy: AgentModelPolicy,
    access: ResourceAccessService,
) -> AgentModelPolicy:
    """Validate and normalize an agent's fixed model configuration."""
    if policy.mode != "fixed" or policy.chat_model_config is None:
        return policy

    config = policy.chat_model_config
    record = await access.resolve_credential(
        user_id,
        config.credential_id,
    )
    credential = CredentialFactory.from_dict(record.data)
    credential_type = getattr(credential, "type", None)
    if config.type != credential_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Agent model provider type does not match the selected "
                "credential."
            ),
        )

    candidate = next(
        (
            model
            for model in build_credential_model_catalog(credential)
            if model.name == config.model
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Model {config.model!r} is not present in the selected "
                "credential."
            ),
        )

    try:
        parameters = normalize_credential_model_parameters(
            credential,
            config.model,
            config.parameters,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return policy.model_copy(
        update={
            "chat_model_config": config.model_copy(
                update={"parameters": parameters},
            ),
        },
    )


@agent_router.get(
    "/schema",
    response_model=AgentSchemaResponse,
    deprecated=True,
    summary="[Deprecated] Legacy sectioned schema — use /schema/v2",
)
async def get_agent_schema() -> AgentSchemaResponse:
    """Return the legacy sectioned JSON Schema fragments.

    .. deprecated::
        Superseded by :func:`get_agent_schema_v2`, which returns the
        full :class:`AgentData` schema in a single ``schema`` field.
        Kept for backwards compatibility with existing API consumers.
        New consumers should call ``GET /agent/schema/v2``.

    The frontend previously used three sections — identity, context
    config, and react config — so we return them as separate
    self-contained schemas rather than a single :class:`AgentData`
    schema with ``$ref`` s.

    Returns:
        `AgentSchemaResponse`:
            Schemas for the three form sections.
    """
    # Slice ``AgentData``'s schema down to the identity-relevant fields.
    # Going through ``AgentData.model_json_schema()`` (rather than building
    # a dict by hand) keeps Pydantic as the single source of truth for
    # defaults, titles, descriptions, and the ``format: textarea`` hint.
    agent_schema = AgentData.model_json_schema()
    identity_keys = ("name", "system_prompt")
    identity = {
        "type": "object",
        "title": "Identity",
        "properties": {
            k: v
            for k, v in agent_schema.get("properties", {}).items()
            if k in identity_keys
        },
        "required": [
            r for r in agent_schema.get("required", []) if r in identity_keys
        ],
    }

    context_schema = ContextConfig.model_json_schema()
    # ``summary_schema`` holds a Pydantic JSON Schema describing how the
    # compression model should structure its output. The end-user is not
    # expected to edit it from the form, so we hide it.
    context_schema.get("properties", {}).pop("summary_schema", None)

    return AgentSchemaResponse(
        identity=identity,
        context_config=context_schema,
        react_config=ReActConfig.model_json_schema(),
    )


@agent_router.get(
    "/schema/v2",
    response_model=AgentSchemaV2Response,
    summary="Full AgentData JSON Schema for the agent form",
)
async def get_agent_schema_v2() -> AgentSchemaV2Response:
    """Return the full :class:`AgentData` JSON Schema.

    Superset of the legacy sectioned endpoint. The response body is a
    single ``schema`` field carrying the whole Pydantic-generated
    schema of :class:`AgentData`, with two curated exclusions handled
    at the model layer (so no post-processing is needed here):

    - ``id``: server-assigned, marked :class:`SkipJsonSchema` on
      :attr:`AgentData.id`.
    - ``context_config.summary_schema``: internal structured-output
      spec for the compression model, dropped below since it is not
      user-editable and there is no equivalent hook on the Pydantic
      side.

    ``$ref`` inlining is delegated to
    :func:`~agentscope._utils._common._flatten_json_schema` so the
    frontend can render every property from the response body alone.

    The frontend derives its section grouping (identity / context /
    react / invite) directly from this schema — top-level scalar
    properties are the "identity" section, and top-level nested-object
    properties each become their own section. Adding a new
    user-editable field to :class:`AgentData` is thus enough to have it
    appear in the create / edit form without a router change.

    Returns:
        `AgentSchemaV2Response`:
            ``schema`` = the full :class:`AgentData` JSON Schema.
    """
    schema = _flatten_json_schema(AgentData.model_json_schema())
    # ``summary_schema`` is Pydantic's structured-output spec fed to the
    # compression model — internal, not user-editable. No pydantic-side
    # hook covers this deep nested field, so drop it after inlining.
    context_config = schema.get("properties", {}).get("context_config", {})
    context_config.get("properties", {}).pop("summary_schema", None)
    return AgentSchemaV2Response(schema=schema)


@agent_router.get(
    "/",
    response_model=ListAgentsResponse,
    summary="List all agents",
)
async def list_agents(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListAgentsResponse:
    """Return all agent records visible to the authenticated user.

    Includes the caller's own ``source == "user"`` agents plus any agents
    shared to them through :class:`ResourceAccessPolicyBase`. Each entry
    carries an ``editable`` flag indicating whether the caller may
    PATCH/DELETE it.

    Args:
        user_id (`str`):
            Injected authenticated user ID.
        access (`ResourceAccessService`):
            Injected resource access service.

    Returns:
        `ListAgentsResponse`:
            All visible agent records paired with per-viewer editability.
    """
    entries = await access.list_resource(user_id, ResourceKind.AGENT)
    return ListAgentsResponse(agents=entries, total=len(entries))


@agent_router.get(
    "/platform/catalog",
    response_model=PlatformAgentCatalogResponse,
    summary="Published agent catalogue for the engineering platform",
)
async def get_platform_agent_catalog(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    storage: StorageBase = Depends(get_storage),
) -> PlatformAgentCatalogResponse:
    """Return the configured global main agent and published business agents.

    The response intentionally excludes prompts, credentials, and provider
    parameters.  It is the stable contract consumed by the engineering
    platform's backend gateway.
    """
    settings = await _load_platform_settings(storage, user_id)
    selected_id = settings.data.global_main_agent_id
    entries = await access.list_resource(user_id, ResourceKind.AGENT)
    items = [_catalog_item(entry) for entry in entries]
    selected_item = next(
        (
            item
            for item in items
            if item.id == selected_id and item.enabled
        ),
        None,
    )
    if selected_item is not None:
        selected_item = selected_item.model_copy(
            update={"role": "global_main", "published": False},
        )
    business_agents = sorted(
        (
            item
            for item in items
            if item.id != selected_id
            and item.role == "business"
            and item.enabled
            and item.published
        ),
        key=lambda item: (item.sort_order, item.name, item.id),
    )
    return PlatformAgentCatalogResponse(
        global_main=selected_item,
        business_agents=business_agents,
        total=len(business_agents),
    )


@agent_router.get(
    "/platform/settings",
    response_model=PlatformSettingsResponse,
    summary="Get platform-wide AgentScope settings",
)
async def get_platform_settings(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> PlatformSettingsResponse:
    """Return the global settings shared by the whole platform."""
    settings = await _load_platform_settings(storage, user_id)
    return PlatformSettingsResponse(
        global_main_agent_id=settings.data.global_main_agent_id,
    )


@agent_router.put(
    "/platform/settings",
    response_model=PlatformSettingsResponse,
    summary="Update platform-wide AgentScope settings",
)
async def update_platform_settings(
    body: UpdatePlatformSettingsRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> PlatformSettingsResponse:
    """Select the only agent used for ordinary platform conversations."""
    selected = await storage.get_agent(
        user_id,
        body.global_main_agent_id,
    )
    if selected is None or selected.source != "user":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected platform main agent does not exist.",
        )
    if not selected.data.platform_config.enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The platform main agent must be enabled.",
        )
    if (
        selected.data.model_policy.mode != "fixed"
        or selected.data.model_policy.chat_model_config is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The platform main agent must use a fixed chat model.",
        )

    settings = await storage.upsert_platform_settings(
        user_id,
        PlatformSettingsData(
            global_main_agent_id=body.global_main_agent_id,
        ),
    )
    await _synchronise_global_main_agent_roles(
        storage,
        user_id,
        body.global_main_agent_id,
    )
    return PlatformSettingsResponse(
        global_main_agent_id=settings.data.global_main_agent_id,
    )


@agent_router.post(
    "/",
    response_model=CreateAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent",
)
async def create_agent(
    body: CreateAgentRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CreateAgentResponse:
    """Create and persist a new agent configuration.

    Args:
        body (`CreateAgentRequest`):
            Agent configuration to store.
        user_id (`str`):
            Injected authenticated user ID.
        storage (`StorageBase`):
            Injected storage backend.

    Returns:
        `CreateAgentResponse`:
            The server-assigned agent identifier.

    Raises:
        `HTTPException`: 422 if the request body passes
            :class:`CreateAgentRequest` validation but the resulting
            :class:`AgentData` fails its cross-field invariants (e.g.
            ``invite_config.invitable=True`` without a non-empty
            ``invite_description``). Symmetrical with
            :func:`update_agent`.
    """
    if body.platform_config.role == "global_main":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Configure the platform main agent in Platform Settings "
                "instead of assigning the role on an agent."
            ),
        )
    try:
        model_policy = await _validate_model_policy(
            user_id,
            body.model_policy,
            access,
        )
        data = AgentData(
            name=body.name,
            system_prompt=body.system_prompt,
            context_config=body.context_config,
            react_config=body.react_config,
            model_policy=model_policy,
            platform_config=body.platform_config,
            invite_config=body.invite_config,
            call_config=body.call_config,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    data = _normalise_platform_agent_data(data)
    record = AgentRecord(user_id=user_id, data=data)
    agent_id = await storage.upsert_agent(user_id, record)
    return CreateAgentResponse(agent_id=agent_id)


@agent_router.patch(
    "/{agent_id}",
    response_model=AgentView,
    summary="Update an agent",
)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> AgentView:
    """Partially update an existing agent configuration.

    Only the fields present in the request body are updated; all other fields
    keep their current values.

    Args:
        agent_id (`str`): The agent to update.
        body (`UpdateAgentRequest`): Fields to update.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service.

    Returns:
        `AgentView`: The full agent record after the update.

    Raises:
        `HTTPException`: 404 if the agent is not visible to the caller;
            403 if visible but only readable.
    """
    owner_id, existing = await access.resolve_for_edit(
        user_id,
        ResourceKind.AGENT,
        agent_id,
    )
    settings = await _load_platform_settings(storage, owner_id)
    selected_id = settings.data.global_main_agent_id
    is_selected_main = selected_id == agent_id
    if (
        body.platform_config is not None
        and body.platform_config.role == "global_main"
        and not is_selected_main
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Configure the platform main agent in Platform Settings "
                "instead of assigning the role on an agent."
            ),
        )

    updates = body.model_dump(exclude_none=True)
    # ``model_copy(update=...)`` skips validators; re-run
    # ``AgentData.model_validate`` on the merged shape so the
    # ``invite_config`` sub-model's ``invitable ⇒ non-empty description``
    # invariant enforced by ``@model_validator(mode="after")`` produces
    # an HTTP 422 instead of a stored-but-invalid record.
    try:
        updated_data = AgentData.model_validate(
            {**existing.data.model_dump(), **updates},
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    updated_data = updated_data.model_copy(
        update={
            "model_policy": await _validate_model_policy(
                user_id,
                updated_data.model_policy,
                access,
            ),
        },
    )
    updated_data = _normalise_platform_agent_data(updated_data)
    if is_selected_main:
        if not updated_data.platform_config.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Select another platform main agent before disabling "
                    "the current one."
                ),
            )
        if (
            updated_data.model_policy.mode != "fixed"
            or updated_data.model_policy.chat_model_config is None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The current platform main agent must keep a fixed "
                    "chat model. Select another main agent first."
                ),
            )
        updated_data = updated_data.model_copy(
            update={
                "platform_config": (
                    updated_data.platform_config.model_copy(
                        update={"role": "global_main"},
                    )
                ),
                "call_config": updated_data.call_config.model_copy(
                    update={"scope": "all"},
                ),
            },
        )
    elif updated_data.platform_config.role == "global_main":
        updated_data = updated_data.model_copy(
            update={
                "platform_config": (
                    updated_data.platform_config.model_copy(
                        update={"role": "business"},
                    )
                ),
            },
        )
    if agent_id in updated_data.call_config.allowed_agent_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An agent cannot include itself in allowed_agent_ids.",
        )
    updated_agent = existing.model_copy(
        update={"data": updated_data, "updated_at": datetime.now()},
    )
    await storage.upsert_agent(owner_id, updated_agent)
    # Only reachable via ``resolve_for_edit``, so the caller has edit
    # permission by construction.
    return AgentView.model_validate(
        {**updated_agent.model_dump(), "editable": True},
    )


@agent_router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(
    agent_id: str,
    user_id: str = Depends(get_current_user_id),
    session_service: SessionService = Depends(get_session_service),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> None:
    """Permanently delete an agent configuration.

    Cascades through every session owned by this agent (and, for team
    leaders, through every worker session) — cancelling any in-flight
    chat run, removing storage records, and purging bus state.

    Args:
        agent_id (`str`): The agent to delete.
        user_id (`str`): Injected authenticated user ID.
        session_service (`SessionService`): Injected session service.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor deletes the agent.

    Raises:
        `HTTPException`: 404 if the agent is not visible to the caller;
            403 if visible but only readable.
    """
    owner_id, _ = await access.resolve_for_edit(
        user_id,
        ResourceKind.AGENT,
        agent_id,
    )
    settings = await _load_platform_settings(storage, owner_id)
    if settings.data.global_main_agent_id == agent_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Select another platform main agent before deleting the "
                "current one."
            ),
        )
    deleted = await session_service.delete_agent(owner_id, agent_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found.",
        )
