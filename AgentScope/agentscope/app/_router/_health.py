# -*- coding: utf-8 -*-
"""The health router."""

from fastapi import APIRouter, Depends, Request, Response, status

from ._schema import ComponentStatus, HealthResponse
from ..deps import get_current_user_id

health_router = APIRouter(tags=["health"])

_EAGER_COMPONENTS = ("storage", "message_bus", "workspace_manager")
_LIFESPAN_COMPONENTS = (
    "background_task_manager",
    "chat_run_registry",
    "scheduler_manager",
    "resource_access_service",
    "permission_review_service",
    "chat_service",
    "session_service",
)


@health_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Report service readiness",
)
async def get_health(
    request: Request,
    response: Response,
    _: str = Depends(get_current_user_id),
) -> HealthResponse:
    """Inspect attached runtime components without performing external I/O."""
    state = request.app.state
    components: dict[str, ComponentStatus] = {
        name: "ok" if getattr(state, name, None) is not None else "not_ready"
        for name in _EAGER_COMPONENTS + _LIFESPAN_COMPONENTS
    }

    components["mcp_registry"] = (
        "ok"
        if getattr(state, "mcp_registry_manager", None) is not None
        else "disabled"
    )

    if getattr(state, "knowledge_base_manager", None) is None:
        components["knowledge_base"] = "disabled"
    elif getattr(state, "knowledge_base_service", None) is not None:
        components["knowledge_base"] = "ok"
    else:
        components["knowledge_base"] = "not_ready"

    ready = all(value != "not_ready" for value in components.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if ready else "not_ready",
        version=request.app.version,
        components=components,
    )
