"""Internal management and runtime API for database interactions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .agent_context_gateway import (
    ok,
    require_service_token,
    resolve_tool_context,
)
from .database_interactions import (
    TableInteractionInput,
    TablePolicyInput,
    create_table_interaction,
    create_table_policy,
    delete_agent_assignments,
    delete_interaction,
    delete_table_policy,
    execute_table_interaction,
    list_database_tables,
    list_interaction_catalog,
    list_runtime_interactions,
    list_table_policies,
    resolve_assigned_interaction,
    update_agent_assignments,
    update_interaction,
    update_table_policy,
)
from .db import get_db


router = APIRouter(
    prefix="/api/internal/database-interactions",
    tags=["internal-database-interactions"],
    dependencies=[Depends(require_service_token)],
)


class AgentCatalogRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    legacy_allowed_names: list[str] | None = None


class RuntimeCatalogRequest(AgentCatalogRequest):
    agentscope_session_id: str = Field(min_length=1, max_length=128)


class AssignmentRequest(BaseModel):
    interaction_ids: list[int] = Field(default_factory=list)


class ExecuteInteractionRequest(BaseModel):
    agentscope_session_id: str = Field(min_length=1, max_length=128)
    actor_agent_id: str = Field(min_length=1, max_length=128)
    platform_agent_id: str | None = Field(default=None, max_length=128)
    interaction_key: str = Field(min_length=3, max_length=128)
    access_mode: Literal["agent", "workflow"] = "agent"
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/catalog")
def get_catalog(
    payload: AgentCatalogRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        list_interaction_catalog(
            db,
            payload.agent_id,
            payload.legacy_allowed_names,
        ),
    )


@router.post("/runtime")
def get_runtime_catalog(
    payload: RuntimeCatalogRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = resolve_tool_context(db, payload.agentscope_session_id)
    return ok(
        list_runtime_interactions(
            db,
            context,
            payload.agent_id,
            payload.legacy_allowed_names,
        ),
    )


@router.put("/assignments/{agent_id}")
def put_assignments(
    agent_id: str,
    payload: AssignmentRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        update_agent_assignments(db, agent_id, payload.interaction_ids),
        "数据库交互分配已保存",
    )


@router.delete(
    "/assignments/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_agent_assignments(
    agent_id: str,
    db: Session = Depends(get_db),
) -> Response:
    delete_agent_assignments(db, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tables")
def get_tables() -> dict[str, Any]:
    return ok(list_database_tables())


@router.get("/policies")
def get_policies(db: Session = Depends(get_db)) -> dict[str, Any]:
    return ok(list_table_policies(db))


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def post_policy(
    payload: TablePolicyInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(create_table_policy(db, payload), "数据表白名单已创建")


@router.put("/policies/{policy_id}")
def put_policy(
    policy_id: int,
    payload: TablePolicyInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(update_table_policy(db, policy_id, payload), "数据表白名单已更新")


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_policy(
    policy_id: int,
    db: Session = Depends(get_db),
) -> Response:
    delete_table_policy(db, policy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/interactions", status_code=status.HTTP_201_CREATED)
def post_interaction(
    payload: TableInteractionInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(create_table_interaction(db, payload), "数据库交互已创建")


@router.put("/interactions/{interaction_id}/table")
def put_table_interaction(
    interaction_id: int,
    payload: TableInteractionInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(update_interaction(db, interaction_id, payload), "数据库交互已更新")


@router.delete(
    "/interactions/{interaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_interaction(
    interaction_id: int,
    db: Session = Depends(get_db),
) -> Response:
    delete_interaction(db, interaction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/execute")
def execute_interaction(
    payload: ExecuteInteractionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = resolve_tool_context(db, payload.agentscope_session_id)
    if (
        payload.platform_agent_id is not None
        and payload.platform_agent_id != context.conversation.agent_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="数据库交互与当前平台会话不匹配",
        )
    interaction, policy = resolve_assigned_interaction(
        db,
        payload.actor_agent_id,
        payload.interaction_key,
        access_mode=payload.access_mode,
    )
    if interaction.execution_kind != "table" or policy is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该数据库交互尚未完成结构化规则迁移",
        )
    data, message = execute_table_interaction(
        db,
        context,
        interaction,
        policy,
        payload.arguments,
        actor_agent_id=payload.actor_agent_id,
    )
    return ok(data, message)
