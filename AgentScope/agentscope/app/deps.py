# -*- coding: utf-8 -*-
"""Shared FastAPI dependencies for the agentscope app."""
from fastapi import Depends, Header, HTTPException, Request, status

from ._auth import (
    AgentScopeAuthConfig,
    AgentScopePrincipal,
    authenticate_bearer_token,
)
from .workspace_manager import WorkspaceManagerBase
from ._manager import (
    BackgroundTaskManager,
    ChatRunRegistry,
    SchedulerManager,
)
from ._service import (
    ChatService,
    KnowledgeBaseService,
    PermissionReviewService,
    ResourceAccessService,
    SessionService,
)
from ._types import (
    AgentMiddlewareFactory,
    AgentToolCatalogFactory,
    AgentToolFactory,
)
from .message_bus import MessageBus
from .mcp_registry import MCPRegistryManager
from .database_interactions import DatabaseInteractionManager
from .rag.blob_store import BlobStoreBase
from .rag.knowledge_base_manager import KnowledgeBaseManagerBase
from .storage import StorageBase
from ..rag import ParserBase


def _service_request_allowed(request: Request) -> bool:
    """Limit the engineering-platform token to runtime gateway endpoints."""
    path = request.url.path.rstrip("/") or "/"
    if request.method == "GET" and path == "/agent/platform/catalog":
        return True
    if (
        request.method == "POST"
        and path == "/agent/platform/weknora/agent-query"
    ):
        # The endpoint body requires a non-empty ``weknora_agent_id`` and
        # validates the robot's own knowledge-base scope before querying.
        return True
    if request.method == "POST" and (
        path == "/agent/platform/weknora/sessions"
        or (
            path.startswith("/agent/platform/weknora/sessions/")
            and path.endswith("/stop")
        )
    ):
        # Session creation and cancellation carry the project robot ID in the
        # validated request body and never expose the saved WeKnora API key.
        return True
    if (
        path == "/agent/platform/weknora/knowledge-bases"
        or path.startswith("/agent/platform/weknora/knowledge-bases/")
        or path.startswith("/agent/platform/weknora/knowledge/")
    ):
        # Management calls may omit the robot scope. Platform-service calls
        # must always carry it, so one project can never see another robot's
        # knowledge bases through the shared service credential.
        return bool(request.query_params.get("weknora_agent_id", "").strip())
    if (
        request.method == "POST"
        and path
        == "/mcp-registry/platform/project-initialization-validation"
    ):
        return True
    return path == "/chat" or any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in ("/sessions", "/workspace")
    )


async def get_current_principal(
    request: Request,
    authorization: str | None = Header(
        default=None,
        description="Bearer management token or platform service token.",
    ),
    x_user_id: str | None = Header(
        default=None,
        description=(
            "Legacy identity header, accepted only when the embedding "
            "application has not enabled authentication."
        ),
    ),
) -> AgentScopePrincipal:
    """Authenticate the management WebUI or engineering-platform service.

    When the embedding application does not supply an
    :class:`AgentScopeAuthConfig`, the historical ``X-User-ID`` behavior is
    retained for upstream compatibility. The local engineering deployment
    always enables the new authentication mode.
    """
    config: AgentScopeAuthConfig | None = getattr(
        request.app.state,
        "auth_config",
        None,
    )
    if config is None:
        if not x_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-User-ID header is required.",
            )
        return AgentScopePrincipal(kind="legacy", subject=x_user_id)

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录 AgentScope 管理页面。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = authenticate_bearer_token(config, token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证无效或已过期，请重新登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if principal.kind == "service" and not _service_request_allowed(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="平台服务凭证无权访问 AgentScope 管理接口。",
        )
    request.state.agentscope_principal = principal
    return principal


async def get_current_user_id(
    request: Request,
    principal: AgentScopePrincipal = Depends(get_current_principal),
) -> str:
    """Return the storage scope for the authenticated caller.

    In authenticated deployments every management account and the engineering
    platform service map to the same global configuration namespace. The
    principal only grants access; it never owns AgentScope settings.
    """
    config: AgentScopeAuthConfig | None = getattr(
        request.app.state,
        "auth_config",
        None,
    )
    if config is None:
        return principal.subject
    return config.global_config_id


async def get_storage(request: Request) -> StorageBase:
    """Return the application-wide storage backend.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `StorageBase`: The storage instance stored in ``app.state``.
    """
    return request.app.state.storage


async def get_message_bus(request: Request) -> MessageBus:
    """Return the application-wide message bus.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `MessageBus`: The message bus instance stored in ``app.state``.
    """
    return request.app.state.message_bus


async def get_chat_service(request: Request) -> ChatService:
    """Return the application-wide chat service.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `ChatService`: The chat service instance stored in ``app.state``.
    """
    return request.app.state.chat_service


async def get_resource_access_service(
    request: Request,
) -> ResourceAccessService:
    """Return the application-wide resource access service.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `ResourceAccessService`:
            The access service stored in ``app.state`` — the single
            entry point routers should use to resolve
            credential / agent / knowledge base records.
    """
    return request.app.state.resource_access_service


async def get_permission_review_service(
    request: Request,
) -> PermissionReviewService:
    """Return the application-wide built-in permission review service."""
    return request.app.state.permission_review_service


async def get_session_service(request: Request) -> SessionService:
    """Return the application-wide session service.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `SessionService`: The session service instance stored in
        ``app.state``.
    """
    return request.app.state.session_service


async def get_chat_run_registry(request: Request) -> ChatRunRegistry:
    """Return the per-process chat-run registry.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `ChatRunRegistry`: The registry stored in ``app.state``.
    """
    return request.app.state.chat_run_registry


async def get_scheduler_manager(request: Request) -> SchedulerManager:
    """Return the application-wide scheduler manager.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `SchedulerManager`: The scheduler manager stored in ``app.state``.
    """
    return request.app.state.scheduler_manager


async def get_background_task_manager(
    request: Request,
) -> BackgroundTaskManager:
    """Return the application-wide background task manager.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `BackgroundTaskManager`: The background task manager stored in
        ``app.state``.
    """
    return request.app.state.background_task_manager


async def get_workspace_manager(request: Request) -> WorkspaceManagerBase:
    """Return the application-wide workspace manager.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `WorkspaceManagerBase`: The workspace manager stored in ``app.state``.
    """
    return request.app.state.workspace_manager


async def get_mcp_registry_manager(request: Request) -> MCPRegistryManager:
    """Return the configured platform-level MCP package registry."""
    manager: MCPRegistryManager | None = getattr(
        request.app.state,
        "mcp_registry_manager",
        None,
    )
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Managed MCP package registry is not configured.",
        )
    return manager


async def get_optional_mcp_registry_manager(
    request: Request,
) -> MCPRegistryManager | None:
    """Return the managed-package registry when the app configured one."""
    return getattr(request.app.state, "mcp_registry_manager", None)


async def get_database_interaction_manager(
    request: Request,
) -> DatabaseInteractionManager:
    """Return the configured Dobby database-interaction proxy."""
    manager: DatabaseInteractionManager | None = getattr(
        request.app.state,
        "database_interaction_manager",
        None,
    )
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库交互管理服务尚未配置。",
        )
    return manager


async def get_extra_agent_middlewares(
    request: Request,
) -> AgentMiddlewareFactory | None:
    """Return the caller-supplied agent middleware factory, if any.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `AgentMiddlewareFactory | None`: The factory passed to
        :func:`~agentscope.app.create_app`, or ``None`` if not configured.
    """
    return request.app.state.extra_agent_middlewares


async def get_extra_agent_tools(
    request: Request,
) -> AgentToolFactory | None:
    """Return the caller-supplied agent tool factory, if any.

    Args:
        request (`Request`): The incoming FastAPI request.

    Returns:
        `AgentToolFactory | None`: The factory passed to
        :func:`~agentscope.app.create_app`, or ``None`` if not configured.
    """
    return request.app.state.extra_agent_tools


async def get_extra_agent_tool_catalog(
    request: Request,
) -> AgentToolCatalogFactory | None:
    """Return assignable application-tool metadata, if configured."""
    return request.app.state.extra_agent_tool_catalog


async def get_knowledge_base_service(
    request: Request,
) -> KnowledgeBaseService:
    """Return the application-wide knowledge base service.

    Args:
        request (`Request`):
            The incoming FastAPI request.

    Returns:
        `KnowledgeBaseService`:
            The service stored in ``app.state``.

    Raises:
        `HTTPException`:
            ``503`` when the app was created without a
            ``knowledge_base_manager`` and therefore exposes no
            knowledge base endpoints.
    """
    service = getattr(request.app.state, "knowledge_base_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Knowledge base feature is disabled — pass a "
                "knowledge_base_manager to create_app() to enable it."
            ),
        )
    return service


async def get_knowledge_base_manager(
    request: Request,
) -> KnowledgeBaseManagerBase:
    """Return the application-wide knowledge base manager.

    Args:
        request (`Request`):
            The incoming FastAPI request.

    Returns:
        `KnowledgeBaseManagerBase`:
            The manager stored in ``app.state``.

    Raises:
        `HTTPException`:
            ``503`` when the app was created without a
            ``knowledge_base_manager``.
    """
    manager = getattr(request.app.state, "knowledge_base_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Knowledge base feature is disabled — pass a "
                "knowledge_base_manager to create_app() to enable it."
            ),
        )
    return manager


async def get_blob_store(request: Request) -> BlobStoreBase:
    """Return the application-wide blob store.

    Args:
        request (`Request`):
            The incoming FastAPI request.

    Returns:
        `BlobStoreBase`:
            The blob store instance stored in ``app.state``.

    Raises:
        `HTTPException`:
            ``503`` when no blob store is configured (e.g. the KB
            feature was disabled at app-creation time).
    """
    blob_store = getattr(request.app.state, "blob_store", None)
    if blob_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Blob store is not configured — pass a "
                "knowledge_base_manager (and optionally a blob_store) "
                "to create_app() to enable knowledge base features."
            ),
        )
    return blob_store


async def get_knowledge_parsers(
    request: Request,
) -> list[ParserBase] | dict[str, ParserBase]:
    """Return the parser registry configured on the app.

    Args:
        request (`Request`):
            The incoming FastAPI request.

    Returns:
        `list[ParserBase] | dict[str, ParserBase]`:
            The parser registry stored in ``app.state.knowledge_parsers``
            — the same value the index worker uses to dispatch uploads.

    Raises:
        `HTTPException`:
            ``503`` when the KB feature is disabled (no parsers
            configured).
    """
    parsers = getattr(request.app.state, "knowledge_parsers", None)
    if not parsers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Knowledge base feature is disabled — pass a "
                "knowledge_base_manager to create_app() to enable it."
            ),
        )
    return parsers
