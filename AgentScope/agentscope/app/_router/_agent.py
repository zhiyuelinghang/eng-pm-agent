# -*- coding: utf-8 -*-
"""Agent router — CRUD endpoints for agent configurations."""
from datetime import datetime
import ipaddress
import json
import logging
import os
import socket
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError

from ...agent import ContextConfig, ReActConfig
from ..._utils._common import _flatten_json_schema
from ..access import ResourceKind
from ..deps import (
    get_current_user_id,
    get_mcp_registry_manager,
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
    MemoryInfrastructureResponse,
    MemorySettingsResponse,
    ResetMemorySettingsRequest,
    UpdateMemorySettingsRequest,
    ListWeKnoraKnowledgeBasesResponse,
    ListWeKnoraKnowledgeResponse,
    TestWeKnoraConnectionRequest,
    TestWeKnoraConnectionResponse,
    UpdateWeKnoraConnectionRequest,
    WeKnoraApiKeyResponse,
    WeKnoraConnectionResponse,
    WeKnoraKnowledgeBaseItem,
    WeKnoraKnowledgeItem,
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
    ChatModelConfig,
    MemorySettingsData,
    PlatformMCPVersionBinding,
    PlatformSettingsData,
    PlatformSettingsRecord,
    StorageBase,
    WeKnoraConnectionConfig,
)
from ..mcp_registry import (
    MCPPackageRecord,
    MCPRegistryManager,
    PROJECT_INITIALIZATION_VALIDATION_CAPABILITY,
)
from ...credential import CredentialFactory


logger = logging.getLogger(__name__)

agent_router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    responses={404: {"description": "Not found"}},
)


def _memory_infrastructure_response() -> MemoryInfrastructureResponse:
    """Return non-secret memory infrastructure details for the settings UI."""

    try:
        from utils import config as memory_config

        provider = str(memory_config.EMBEDDING_PROVIDER)
        model = str(memory_config.EMBEDDING_MODEL)
        dimensions = int(memory_config.EMBEDDING_DIMS)
        collection = str(memory_config.MEM0_COLLECTION)
    except (AttributeError, ImportError, TypeError, ValueError):
        provider = os.getenv("EMBEDDING_PROVIDER", "local")
        model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
        dimensions = int(os.getenv("EMBEDDING_DIMS", "1024"))
        collection = os.getenv("MEM0_COLLECTION", "dobby_memories")
    return MemoryInfrastructureResponse(
        embedding_provider=provider,
        embedding_model=model,
        embedding_dimensions=dimensions,
        mem0_collection=collection,
    )


def _memory_settings_response(
    settings: PlatformSettingsRecord,
) -> MemorySettingsResponse:
    return MemorySettingsResponse(
        settings=settings.data.memory_settings,
        revision=settings.data.memory_settings_revision,
        updated_at=settings.updated_at,
        infrastructure=_memory_infrastructure_response(),
    )


def _check_memory_settings_revision(
    expected_revision: int | None,
    current_revision: int,
) -> None:
    if expected_revision is not None and expected_revision != current_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "记忆配置已被其他操作更新，请刷新页面后重新修改。"
            ),
        )


def _validate_weknora_endpoint(base_url: str) -> str:
    """Validate a user-managed endpoint before the backend calls it."""
    normalised = base_url.strip().rstrip("/")
    parsed = urlsplit(normalised)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 服务地址必须是完整的 HTTP(S) URL。",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 服务地址不能包含用户信息、查询参数或片段。",
        )
    return normalised


def _validate_weknora_probe_target(base_url: str) -> None:
    """Resolve a configured host and reject unsafe special-use targets."""
    parsed = urlsplit(base_url)
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="无法解析 WeKnora 服务地址，请检查域名。",
        ) from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="WeKnora 服务地址不能指向本机或保留网络。",
            )


def _weknora_response(
    config: WeKnoraConnectionConfig | None,
) -> WeKnoraConnectionResponse:
    if config is None:
        return WeKnoraConnectionResponse()
    return WeKnoraConnectionResponse(
        base_url=config.base_url,
        api_prefix=config.api_prefix,
        auth_header=config.auth_header,
        api_key_configured=bool(config.api_key.get_secret_value()),
    )


def _require_weknora_connection(
    settings: PlatformSettingsRecord,
) -> WeKnoraConnectionConfig:
    connection = settings.data.weknora_connection
    if connection is None or not connection.api_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先保存 WeKnora 服务地址和 API Key。",
        )
    return connection


def _build_weknora_config(
    body: UpdateWeKnoraConnectionRequest,
    existing: WeKnoraConnectionConfig | None,
) -> WeKnoraConnectionConfig:
    base_url = _validate_weknora_endpoint(body.base_url)
    api_key = body.api_key or (
        existing.api_key.get_secret_value() if existing is not None else ""
    )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="首次配置 WeKnora 时必须填写 API Key。",
        )
    try:
        return WeKnoraConnectionConfig(
            base_url=base_url,
            api_prefix=body.api_prefix,
            auth_header=body.auth_header,
            api_key=api_key,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors()[0]["msg"],
        ) from exc


async def _request_weknora_json(
    config: WeKnoraConnectionConfig,
    path: str,
    *,
    params: dict[str, int | str] | None = None,
) -> dict:
    """Call one WeKnora JSON endpoint through the management backend."""
    _validate_weknora_probe_target(config.base_url)
    url = f"{config.base_url}{config.api_prefix}{path}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                url,
                headers={
                    config.auth_header: config.api_key.get_secret_value(),
                    "Accept": "application/json",
                },
                params=params,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="连接 WeKnora 超时，请检查服务地址和网络。",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法连接 WeKnora，请检查服务地址和网络。",
        ) from exc
    if response.status_code in {301, 302, 303, 307, 308}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回了重定向，请直接填写最终服务地址。",
        )
    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 拒绝鉴权，请检查 API Key 和鉴权请求头。",
        )
    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WeKnora 中不存在所请求的知识库或资料。",
        )
    if not 200 <= response.status_code < 300:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WeKnora 返回 HTTP {response.status_code}，请检查配置。",
        )
    if len(response.content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 知识库列表响应过大，已拒绝处理。",
        )
    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回的不是有效 JSON。",
        ) from exc
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回了失败或无效的响应。",
        )
    return payload


def _weknora_list_payload(payload: dict) -> tuple[list[dict], dict]:
    """Extract either the documented array or paginated list shape."""
    data = payload.get("data", [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], {}
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return (
            [item for item in data["list"] if isinstance(item, dict)],
            data,
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="WeKnora 列表响应结构无效。",
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


async def _fetch_weknora_knowledge_bases(
    config: WeKnoraConnectionConfig,
) -> list[WeKnoraKnowledgeBaseItem]:
    payload = await _request_weknora_json(config, "/knowledge-bases")
    raw_items, _ = _weknora_list_payload(payload)
    result: list[WeKnoraKnowledgeBaseItem] = []
    for item in raw_items:
        item_id = _text(item.get("id"))
        if not item_id:
            continue
        result.append(
            WeKnoraKnowledgeBaseItem(
                id=item_id,
                name=_text(item.get("name")) or item_id,
                description=_text(item.get("description")),
                created_at=_text(item.get("created_at")) or None,
                updated_at=_text(item.get("updated_at")) or None,
            ),
        )
    return result


async def _fetch_weknora_knowledge(
    config: WeKnoraConnectionConfig,
    knowledge_base_id: str,
    *,
    page: int,
    page_size: int,
) -> tuple[list[WeKnoraKnowledgeItem], int]:
    encoded_id = quote(knowledge_base_id, safe="")
    payload = await _request_weknora_json(
        config,
        f"/knowledge-bases/{encoded_id}/knowledge",
        params={"page": page, "page_size": page_size},
    )
    raw_items, metadata = _weknora_list_payload(payload)
    result: list[WeKnoraKnowledgeItem] = []
    for item in raw_items:
        item_id = _text(item.get("id"))
        if not item_id:
            continue
        file_size = item.get("file_size")
        try:
            normalised_file_size = (
                int(file_size) if file_size is not None else None
            )
        except (TypeError, ValueError):
            normalised_file_size = None
        result.append(
            WeKnoraKnowledgeItem(
                id=item_id,
                knowledge_base_id=(
                    _text(item.get("knowledge_base_id"))
                    or knowledge_base_id
                ),
                type=_text(item.get("type")),
                title=_text(item.get("title")),
                description=_text(item.get("description")),
                file_name=_text(item.get("file_name")),
                file_type=_text(item.get("file_type")),
                file_size=normalised_file_size,
                source=_text(item.get("source")),
                channel=_text(item.get("channel")),
                parse_status=_text(item.get("parse_status")),
                enable_status=_text(item.get("enable_status")),
                created_at=_text(item.get("created_at")) or None,
                processed_at=_text(item.get("processed_at")) or None,
            ),
        )
    raw_total = metadata.get("total", len(result))
    try:
        total = max(int(raw_total), len(result))
    except (TypeError, ValueError):
        total = len(result)
    return result, total


async def _probe_weknora(config: WeKnoraConnectionConfig) -> int:
    return len(await _fetch_weknora_knowledge_bases(config))


def _is_initialization_validation_package(record: MCPPackageRecord) -> bool:
    """Whether one package version satisfies the platform validation slot."""
    return (
        PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
        in record.manifest.platform_capabilities
        and len(record.tools) == 1
    )


async def _migrate_initialization_validation_binding(
    settings: PlatformSettingsRecord,
    *,
    storage: StorageBase,
    user_id: str,
    manager: MCPRegistryManager,
) -> PlatformSettingsRecord:
    """Bind the sole legacy validator package once, without naming it."""
    if settings.data.project_initializer_validation_mcp is not None:
        return settings
    candidates = [
        record
        for record in await manager.list_records()
        if _is_initialization_validation_package(record)
    ]
    if len(candidates) != 1:
        return settings
    record = candidates[0]
    data = settings.data.model_copy(
        update={
            "project_initializer_validation_mcp": PlatformMCPVersionBinding(
                package_id=record.id,
                version=record.manifest.version,
            ),
        },
    )
    return await storage.upsert_platform_settings(user_id, data)


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


async def _synchronise_project_initializer_role(
    storage: StorageBase,
    global_config_id: str,
    selected_agent_id: str | None,
) -> None:
    """Keep the selected initializer hidden with an explicit allowlist."""
    if selected_agent_id is None:
        return
    record = await storage.get_agent(global_config_id, selected_agent_id)
    if record is None:
        return
    platform_config = record.data.platform_config
    call_config = record.data.call_config
    if (
        platform_config.role == "system_internal"
        and not platform_config.published
        and call_config.scope == "selected"
    ):
        return
    updated = record.model_copy(
        update={
            "data": record.data.model_copy(
                update={
                    "platform_config": platform_config.model_copy(
                        update={
                            "role": "system_internal",
                            "published": False,
                        },
                    ),
                    "call_config": call_config.model_copy(
                        update={"scope": "selected"},
                    ),
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
        await _synchronise_project_initializer_role(
            storage,
            global_config_id,
            existing.data.project_initializer_agent_id,
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
    await _synchronise_project_initializer_role(
        storage,
        global_config_id,
        data.project_initializer_agent_id,
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
        initialization_role=config.initialization_role,
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
    # Dobby owns compression as one platform-wide policy. Keep only the
    # genuinely agent-specific context option in the agent editor.
    for memory_owned_field in (
        "trigger_ratio",
        "reserve_ratio",
        "compression_prompt",
        "summary_template",
        "summary_schema",
    ):
        context_schema.get("properties", {}).pop(memory_owned_field, None)

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
    # Compression is configured once from the dedicated Memory Settings
    # page. The agent editor retains only tool_result_limit.
    context_config = schema.get("properties", {}).get("context_config", {})
    for memory_owned_field in (
        "trigger_ratio",
        "reserve_ratio",
        "compression_prompt",
        "summary_template",
        "summary_schema",
    ):
        context_config.get("properties", {}).pop(memory_owned_field, None)
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
    initializer_id = settings.data.project_initializer_agent_id
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
    initializer_item = next(
        (
            item
            for item in items
            if item.id == initializer_id
            and item.id != selected_id
            and item.enabled
        ),
        None,
    )
    if initializer_item is not None:
        initializer_item = initializer_item.model_copy(
            update={"role": "system_internal", "published": False},
        )
    business_agents = sorted(
        (
            item
            for item in items
            if item.id != selected_id
            and item.id != initializer_id
            and item.role == "business"
            and item.enabled
            and item.published
        ),
        key=lambda item: (item.sort_order, item.name, item.id),
    )
    initialization_workers = sorted(
        (
            item
            for item in items
            if item.id != initializer_id
            and item.role == "system_internal"
            and item.enabled
            and item.initialization_role in {
                "project",
                "personnel",
                "wbs",
                "risks",
                "quality_requirements",
                "validator",
            }
        ),
        key=lambda item: (item.sort_order, item.name, item.id),
    )
    return PlatformAgentCatalogResponse(
        global_main=selected_item,
        project_initializer=initializer_item,
        initialization_workers=initialization_workers,
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
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> PlatformSettingsResponse:
    """Return the global settings shared by the whole platform."""
    settings = await _load_platform_settings(storage, user_id)
    settings = await _migrate_initialization_validation_binding(
        settings,
        storage=storage,
        user_id=user_id,
        manager=manager,
    )
    return PlatformSettingsResponse(
        global_main_agent_id=settings.data.global_main_agent_id,
        project_initializer_agent_id=(
            settings.data.project_initializer_agent_id
        ),
        project_initializer_validation_mcp=(
            settings.data.project_initializer_validation_mcp
        ),
        engineering_document_agent_id=(
            settings.data.engineering_document_agent_id
        ),
    )


async def _validate_memory_model_config(
    user_id: str,
    config: ChatModelConfig | None,
    access: ResourceAccessService,
) -> ChatModelConfig | None:
    """Validate and normalize the optional global memory model."""

    if config is None:
        return None

    record = await access.resolve_credential(user_id, config.credential_id)
    credential = CredentialFactory.from_dict(record.data)
    credential_type = getattr(credential, "type", None)
    if config.type != credential_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="记忆处理模型与所选凭证类型不匹配。",
        )

    candidate = next(
        (
            model
            for model in build_credential_model_catalog(credential)
            if model.name == config.model and model.enabled
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="所选记忆处理模型在该凭证中不存在或已被停用。",
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

    normalized = config.model_copy(update={"parameters": parameters})
    try:
        from ..memory import build_memory_model_runtime_config

        build_memory_model_runtime_config(
            normalized,
            credential,
            context_size=candidate.context_size,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return normalized


@agent_router.get(
    "/platform/memory-settings",
    response_model=MemorySettingsResponse,
    summary="Get platform-wide Dobby memory settings",
)
async def get_memory_settings(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> MemorySettingsResponse:
    """Return the active versioned memory policy and safe infrastructure."""

    settings = await _load_platform_settings(storage, user_id)
    return _memory_settings_response(settings)


@agent_router.put(
    "/platform/memory-settings",
    response_model=MemorySettingsResponse,
    summary="Update platform-wide Dobby memory settings",
)
async def update_memory_settings(
    body: UpdateMemorySettingsRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> MemorySettingsResponse:
    """Atomically replace memory policy while preserving other settings."""

    current = await _load_platform_settings(storage, user_id)
    _check_memory_settings_revision(
        body.expected_revision,
        current.data.memory_settings_revision,
    )
    memory_model_config = await _validate_memory_model_config(
        user_id,
        body.settings.memory_model_config,
        access,
    )
    normalized_settings = body.settings.model_copy(
        update={"memory_model_config": memory_model_config},
    )
    updated_data = current.data.model_copy(
        update={
            "memory_settings": normalized_settings,
            "memory_settings_revision": (
                current.data.memory_settings_revision + 1
            ),
        },
    )
    updated = await storage.upsert_platform_settings(user_id, updated_data)
    return _memory_settings_response(updated)


@agent_router.post(
    "/platform/memory-settings/reset",
    response_model=MemorySettingsResponse,
    summary="Restore reference-branch Dobby memory defaults",
)
async def reset_memory_settings(
    body: ResetMemorySettingsRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> MemorySettingsResponse:
    """Restore the integrated Dobby memory defaults."""

    current = await _load_platform_settings(storage, user_id)
    _check_memory_settings_revision(
        body.expected_revision,
        current.data.memory_settings_revision,
    )
    updated_data = current.data.model_copy(
        update={
            "memory_settings": MemorySettingsData(),
            "memory_settings_revision": (
                current.data.memory_settings_revision + 1
            ),
        },
    )
    updated = await storage.upsert_platform_settings(user_id, updated_data)
    return _memory_settings_response(updated)


@agent_router.get(
    "/platform/weknora-connection",
    response_model=WeKnoraConnectionResponse,
    summary="Get the independently managed WeKnora connection",
)
async def get_weknora_connection(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraConnectionResponse:
    settings = await _load_platform_settings(storage, user_id)
    return _weknora_response(settings.data.weknora_connection)


@agent_router.get(
    "/platform/weknora-connection/api-key",
    response_model=WeKnoraApiKeyResponse,
    summary="Reveal the saved WeKnora API key on explicit admin request",
)
async def reveal_weknora_api_key(
    response: Response,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraApiKeyResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return WeKnoraApiKeyResponse(
        api_key=connection.api_key.get_secret_value(),
    )


@agent_router.put(
    "/platform/weknora-connection",
    response_model=WeKnoraConnectionResponse,
    summary="Save the independently managed WeKnora connection",
)
async def update_weknora_connection(
    body: UpdateWeKnoraConnectionRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraConnectionResponse:
    current = await _load_platform_settings(storage, user_id)
    connection = _build_weknora_config(
        body,
        current.data.weknora_connection,
    )
    updated_data = current.data.model_copy(
        update={"weknora_connection": connection},
    )
    settings = await storage.upsert_platform_settings(user_id, updated_data)
    return _weknora_response(settings.data.weknora_connection)


@agent_router.post(
    "/platform/weknora-connection/test",
    response_model=TestWeKnoraConnectionResponse,
    summary="Test a WeKnora connection by listing knowledge bases",
)
async def test_weknora_connection(
    body: TestWeKnoraConnectionRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> TestWeKnoraConnectionResponse:
    current = await _load_platform_settings(storage, user_id)
    connection = _build_weknora_config(
        body,
        current.data.weknora_connection,
    )
    knowledge_base_count = await _probe_weknora(connection)
    return TestWeKnoraConnectionResponse(
        success=True,
        knowledge_base_count=knowledge_base_count,
        message=f"连接成功，读取到 {knowledge_base_count} 个知识库。",
    )


@agent_router.get(
    "/platform/weknora/knowledge-bases",
    response_model=ListWeKnoraKnowledgeBasesResponse,
    summary="List knowledge bases from the configured WeKnora tenant",
)
async def list_weknora_knowledge_bases(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> ListWeKnoraKnowledgeBasesResponse:
    settings = await _load_platform_settings(storage, user_id)
    knowledge_bases = await _fetch_weknora_knowledge_bases(
        _require_weknora_connection(settings),
    )
    return ListWeKnoraKnowledgeBasesResponse(
        knowledge_bases=knowledge_bases,
        total=len(knowledge_bases),
    )


@agent_router.get(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge",
    response_model=ListWeKnoraKnowledgeResponse,
    summary="List engineering content from one WeKnora knowledge base",
)
async def list_weknora_knowledge(
    knowledge_base_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> ListWeKnoraKnowledgeResponse:
    settings = await _load_platform_settings(storage, user_id)
    knowledge, total = await _fetch_weknora_knowledge(
        _require_weknora_connection(settings),
        knowledge_base_id,
        page=page,
        page_size=page_size,
    )
    return ListWeKnoraKnowledgeResponse(
        knowledge=knowledge,
        total=total,
        page=page,
        page_size=page_size,
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
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> PlatformSettingsResponse:
    """Update global agent assignments without exposing per-account settings."""
    if not body.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one platform setting must be provided.",
        )
    current = await _load_platform_settings(storage, user_id)
    current = await _migrate_initialization_validation_binding(
        current,
        storage=storage,
        user_id=user_id,
        manager=manager,
    )
    global_main_agent_id = current.data.global_main_agent_id
    project_initializer_agent_id = (
        current.data.project_initializer_agent_id
    )
    validation_mcp = current.data.project_initializer_validation_mcp
    engineering_document_agent_id = (
        current.data.engineering_document_agent_id
    )
    previous_validation_mcp = validation_mcp

    async def validate_candidate(
        agent_id: str,
        purpose: str,
    ) -> AgentRecord:
        selected = await storage.get_agent(user_id, agent_id)
        if selected is None or selected.source != "user":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"The selected {purpose} agent does not exist.",
            )
        if not selected.data.platform_config.enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The {purpose} agent must be enabled.",
            )
        if (
            selected.data.model_policy.mode != "fixed"
            or selected.data.model_policy.chat_model_config is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The {purpose} agent must use a fixed chat model.",
            )
        return selected

    if "global_main_agent_id" in body.model_fields_set:
        if body.global_main_agent_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The platform main agent cannot be cleared.",
            )
        await validate_candidate(
            body.global_main_agent_id,
            "platform main",
        )
        global_main_agent_id = body.global_main_agent_id
    if "project_initializer_agent_id" in body.model_fields_set:
        if body.project_initializer_agent_id is not None:
            await validate_candidate(
                body.project_initializer_agent_id,
                "project initializer",
            )
        project_initializer_agent_id = body.project_initializer_agent_id
    if "project_initializer_validation_mcp" in body.model_fields_set:
        requested_binding = body.project_initializer_validation_mcp
        if requested_binding is not None:
            record = await manager.get_record(
                requested_binding.package_id,
                requested_binding.version,
            )
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="选择的核验 MCP 版本不存在，请刷新后重新选择。",
                )
            if not _is_initialization_validation_package(record):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "选择的 MCP 未声明项目初始化核验能力，或包含多个"
                        "核验入口。"
                    ),
                )
        validation_mcp = requested_binding
    if "engineering_document_agent_id" in body.model_fields_set:
        if body.engineering_document_agent_id is not None:
            await validate_candidate(
                body.engineering_document_agent_id,
                "engineering document manager",
            )
        engineering_document_agent_id = body.engineering_document_agent_id
    if (
        global_main_agent_id is not None
        and global_main_agent_id == project_initializer_agent_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The platform main agent and project initializer must be "
                "different agents."
            ),
        )
    if project_initializer_agent_id is not None and validation_mcp is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="项目初始化智能体必须配置一个核验 MCP 版本。",
        )
    if validation_mcp is not None:
        selected_validation_record = await manager.get_record(
            validation_mcp.package_id,
            validation_mcp.version,
        )
        if (
            selected_validation_record is None
            or not _is_initialization_validation_package(
                selected_validation_record,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="当前核验 MCP 配置已不可用，请重新选择版本。",
            )
    settings = await storage.upsert_platform_settings(
        user_id,
        current.data.model_copy(
            update={
                "global_main_agent_id": global_main_agent_id,
                "project_initializer_agent_id": project_initializer_agent_id,
                "project_initializer_validation_mcp": validation_mcp,
                "engineering_document_agent_id": (
                    engineering_document_agent_id
                ),
            },
        ),
    )
    if (
        previous_validation_mcp is not None
        and previous_validation_mcp != validation_mcp
    ):
        await manager.close_version_instances(
            previous_validation_mcp.package_id,
            previous_validation_mcp.version,
        )
    await _synchronise_global_main_agent_roles(
        storage,
        user_id,
        settings.data.global_main_agent_id,
    )
    await _synchronise_project_initializer_role(
        storage,
        user_id,
        settings.data.project_initializer_agent_id,
    )
    return PlatformSettingsResponse(
        global_main_agent_id=settings.data.global_main_agent_id,
        project_initializer_agent_id=(
            settings.data.project_initializer_agent_id
        ),
        project_initializer_validation_mcp=(
            settings.data.project_initializer_validation_mcp
        ),
        engineering_document_agent_id=(
            settings.data.engineering_document_agent_id
        ),
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
            mcp_config=body.mcp_config,
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
    request: Request = None,  # type: ignore[assignment]
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
    database_manager = (
        getattr(request.app.state, "database_interaction_manager", None)
        if request is not None
        else None
    )
    if database_manager is not None:
        try:
            await database_manager.delete_assignments(agent_id)
        except Exception as exc:  # pragma: no cover - remote cleanup fallback
            # The agent is already gone from authoritative AgentScope storage.
            # Orphaned external assignment rows are inert and can be retried;
            # do not turn a successful delete into a misleading client error.
            logger.warning(
                "Unable to clean database interaction assignments for %s: %s",
                agent_id,
                exc,
            )
