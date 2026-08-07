# -*- coding: utf-8 -*-
"""Authenticated management proxy for Dobby database interactions."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..access import ResourceKind
from ..database_interactions import (
    DatabaseInteractionGatewayError,
    DatabaseInteractionManager,
)
from ..deps import (
    get_current_user_id,
    get_database_interaction_manager,
    get_resource_access_service,
)
from .._service import ResourceAccessService


database_interaction_router = APIRouter(
    prefix="/database-interactions",
    tags=["database-interactions"],
)


class AssignmentRequest(BaseModel):
    interaction_ids: list[int] = Field(default_factory=list)


class TableContextBindingRequest(BaseModel):
    field: str = Field(min_length=1, max_length=128)
    source: Literal[
        "project_id",
        "conversation_id",
        "user_id",
        "actor_agent_id",
    ]
    mode: Literal["scope", "value"] = "scope"


class TableInteractionRequest(BaseModel):
    key: str
    display_name: str
    description: str = ""
    table_policy_id: int
    table_operation: Literal["read", "create", "update", "delete"]
    join_rules: list["TableJoinRequest"] = Field(
        default_factory=list,
        max_length=8,
    )
    context_bindings: list[TableContextBindingRequest] = Field(
        default_factory=list,
        max_length=12,
    )
    allowed_conversation_types: list[
        Literal["general", "business", "initialization"]
    ] = Field(
        default_factory=lambda: [
            "general",
            "business",
            "initialization",
        ],
        min_length=1,
    )
    access_mode: Literal["agent", "workflow"] = "agent"
    requires_confirmation: bool = False
    enabled: bool = True
    sort_order: int = 0


class TableJoinRequest(BaseModel):
    alias: str = Field(min_length=2, max_length=32)
    source_alias: str = Field(default="main", min_length=2, max_length=32)
    source_field: str = Field(min_length=1, max_length=128)
    target_policy_id: int
    target_field: str = Field(min_length=1, max_length=128)
    join_type: Literal["left", "inner"] = "left"
    readable_fields: list[str] = Field(default_factory=list)
    filterable_fields: list[str] = Field(default_factory=list)


def _raise_gateway_error(exc: DatabaseInteractionGatewayError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@database_interaction_router.get("/")
async def list_interactions(
    agent_id: str,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> list[dict[str, Any]]:
    agent = await access.resolve_agent(user_id, agent_id)
    try:
        return await manager.list_catalog(
            agent_id,
            agent.data.tool_config.allowed_tool_names,
        )
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)


@database_interaction_router.put("/assignments/{agent_id}")
async def update_assignments(
    agent_id: str,
    payload: AssignmentRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> list[dict[str, Any]]:
    await access.resolve_for_edit(user_id, ResourceKind.AGENT, agent_id)
    try:
        return await manager.update_assignments(agent_id, payload.interaction_ids)
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)


@database_interaction_router.get("/tables")
async def list_tables(
    _user_id: str = Depends(get_current_user_id),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> list[dict[str, Any]]:
    try:
        return await manager.list_tables()
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)


@database_interaction_router.get("/policies")
async def list_policies(
    _user_id: str = Depends(get_current_user_id),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> list[dict[str, Any]]:
    try:
        return await manager.list_policies()
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)


@database_interaction_router.post(
    "/interactions",
    status_code=status.HTTP_201_CREATED,
)
async def create_interaction(
    payload: TableInteractionRequest,
    _user_id: str = Depends(get_current_user_id),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> dict[str, Any]:
    try:
        return await manager.create_interaction(payload.model_dump())
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)


@database_interaction_router.put("/interactions/{interaction_id}/table")
async def update_table_interaction(
    interaction_id: int,
    payload: TableInteractionRequest,
    _user_id: str = Depends(get_current_user_id),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> dict[str, Any]:
    try:
        return await manager.update_interaction(
            interaction_id,
            payload.model_dump(),
        )
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)


@database_interaction_router.delete(
    "/interactions/{interaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_interaction(
    interaction_id: int,
    _user_id: str = Depends(get_current_user_id),
    manager: DatabaseInteractionManager = Depends(
        get_database_interaction_manager,
    ),
) -> Response:
    try:
        await manager.delete_interaction(interaction_id)
    except DatabaseInteractionGatewayError as exc:
        _raise_gateway_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
