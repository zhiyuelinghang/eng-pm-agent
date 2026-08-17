# -*- coding: utf-8 -*-
"""Management APIs for reviewing and correcting personal long-term memory."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .._auth import AgentScopePrincipal
from .._session_access import require_management_audit_access
from ..deps import get_current_principal, get_current_user_id, get_storage
from ..memory import build_business_memory_target, get_memory_runtime
from ..storage import SessionSource, StorageBase


MemoryScopeType = Literal["user", "user_project"]


class ManagedMemoryItem(BaseModel):
    """One editable v2 business-user memory."""

    id: str
    content: str
    scope_type: MemoryScopeType
    platform_user_id: str
    project_id: str | None = None
    memory_type: str
    importance: float
    source: str
    source_agent_id: str | None = None
    source_session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryManagementProject(BaseModel):
    project_id: str
    project_name: str
    memory_count: int = 0


class MemoryManagementUser(BaseModel):
    user_id: str
    username: str
    display_name: str
    memory_count: int = 0
    user_memory_count: int = 0
    projects: list[MemoryManagementProject] = Field(default_factory=list)


class MemoryManagementResponse(BaseModel):
    users: list[MemoryManagementUser] = Field(default_factory=list)
    memories: list[ManagedMemoryItem] = Field(default_factory=list)
    total: int = 0


class UpdateMemoryScopeRequest(BaseModel):
    scope_type: MemoryScopeType
    project_id: str | None = None


memory_management_router = APIRouter(
    prefix="/memory-management",
    tags=["memory-management"],
)


def _memory_database() -> tuple[str, str]:
    from utils import config as memory_config

    return memory_config.DATABASE_URL, memory_config.MEM0_COLLECTION


def _memory_uuid(memory_id: str) -> UUID:
    try:
        return UUID(memory_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("memory_not_found") from exc


def _list_business_memories() -> list[dict[str, Any]]:
    """Read v2 payloads without instantiating the BGE embedding model."""

    import psycopg
    from psycopg import sql

    database_url, collection = _memory_database()
    tenant_id = get_memory_runtime().tenant_id
    with psycopg.Connection.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
    ) as connection:
        rows = connection.execute(
            sql.SQL(
                """SELECT id, payload
                   FROM {}
                   WHERE payload->>'scope_version' = '2'
                     AND payload->>'identity_type' = 'business_user'
                     AND payload->>'tenant_id' = %s
                   ORDER BY COALESCE(
                       payload->>'updated_at',
                       payload->>'created_at',
                       ''
                   ) DESC
                   LIMIT 10000""",
            ).format(sql.Identifier(collection)),
            (tenant_id,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for memory_id, raw_payload in rows:
        payload = dict(raw_payload or {})
        scope_type = str(payload.get("scope_type") or "")
        platform_user_id = str(payload.get("platform_user_id") or "")
        if scope_type not in {"user", "user_project"} or not platform_user_id:
            continue
        result.append({
            "id": str(memory_id),
            "payload": payload,
        })
    return result


def _to_item(record: dict[str, Any]) -> ManagedMemoryItem:
    payload = record["payload"]
    return ManagedMemoryItem(
        id=record["id"],
        content=str(payload.get("data") or ""),
        scope_type=str(payload["scope_type"]),
        platform_user_id=str(payload["platform_user_id"]),
        project_id=(str(payload["project_id"]) if payload.get("project_id") else None),
        memory_type=str(payload.get("memory_type") or "fact"),
        importance=float(payload.get("importance") or 0.5),
        source=str(payload.get("source") or "memory"),
        source_agent_id=(
            str(payload["source_agent_id"])
            if payload.get("source_agent_id")
            else None
        ),
        source_session_id=(
            str(payload["source_session_id"])
            if payload.get("source_session_id")
            else None
        ),
        created_at=(str(payload["created_at"]) if payload.get("created_at") else None),
        updated_at=(str(payload["updated_at"]) if payload.get("updated_at") else None),
    )


async def _identity_catalog(
    storage: StorageBase,
    storage_user_id: str,
) -> tuple[dict[str, dict[str, str]], dict[tuple[str, str], str]]:
    users: dict[str, dict[str, str]] = {}
    projects: dict[tuple[str, str], str] = {}
    for session in await storage.list_all_sessions(storage_user_id):
        context = session.config.platform_context
        if (
            session.source != SessionSource.PLATFORM
            or context is None
            or context.session_role != "primary"
        ):
            continue
        users[context.user_id] = {
            "username": context.username,
            "display_name": context.display_name,
        }
        projects[(context.user_id, context.project_id)] = context.project_name
    return users, projects


def _find_memory(memory_id: str) -> dict[str, Any]:
    import psycopg
    from psycopg import sql

    database_url, collection = _memory_database()
    with psycopg.Connection.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
    ) as connection:
        row = connection.execute(
            sql.SQL("SELECT payload FROM {} WHERE id = %s").format(
                sql.Identifier(collection),
            ),
            (_memory_uuid(memory_id),),
        ).fetchone()
    if not row:
        raise ValueError("memory_not_found")
    metadata = dict(row[0] or {})
    if (
        str(metadata.get("scope_version") or "") != "2"
        or metadata.get("identity_type") != "business_user"
        or metadata.get("scope_type") not in {"user", "user_project"}
        or metadata.get("tenant_id") != get_memory_runtime().tenant_id
    ):
        raise PermissionError("memory_not_managed")
    return {
        "item": {
            "id": memory_id,
            "memory": str(metadata.get("data") or ""),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
        },
        "metadata": metadata,
    }


def _update_memory_metadata(memory_id: str, metadata: dict[str, Any]) -> None:
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

    database_url, collection = _memory_database()
    with psycopg.Connection.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
    ) as connection:
        row = connection.execute(
            sql.SQL(
                """UPDATE {}
                   SET payload = payload || %s
                   WHERE id = %s
                   RETURNING id""",
            ).format(sql.Identifier(collection)),
            (Jsonb(metadata), _memory_uuid(memory_id)),
        ).fetchone()
    if not row:
        raise ValueError("memory_not_found")


def _delete_memory_record(memory_id: str) -> None:
    import psycopg
    from psycopg import sql

    database_url, collection = _memory_database()
    with psycopg.Connection.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
    ) as connection:
        row = connection.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s RETURNING id").format(
                sql.Identifier(collection),
            ),
            (_memory_uuid(memory_id),),
        ).fetchone()
    if not row:
        raise ValueError("memory_not_found")


async def _log_management_action(
    *,
    action: str,
    principal: AgentScopePrincipal,
    memory_id: str,
    metadata: dict[str, Any],
    details: dict[str, Any],
) -> None:
    """Persist an admin mutation when the optional audit table is available."""

    def _write() -> None:
        import psycopg
        from psycopg.types.json import Jsonb
        from utils import config as memory_config

        with psycopg.Connection.connect(
            memory_config.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
        ) as connection:
            connection.execute(
                """INSERT INTO memory.memory_audit_log
                   (tenant_id, project_id, platform_user_id, agent_id,
                    action, memory_id, details)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(metadata.get("tenant_id") or "projectcopilot"),
                    metadata.get("project_id"),
                    metadata.get("platform_user_id"),
                    f"management:{principal.subject}",
                    action,
                    memory_id,
                    Jsonb(details),
                ),
            )

    try:
        await asyncio.to_thread(_write)
    except Exception:
        # Memory mutation is authoritative; an unavailable auxiliary audit
        # table must not make a successful correction appear to have failed.
        return


@memory_management_router.get(
    "/memories",
    response_model=MemoryManagementResponse,
    summary="List editable business-user long-term memories",
)
async def list_managed_memories(
    platform_user_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    scope_type: MemoryScopeType | None = Query(default=None),
    query: str = Query(default="", max_length=500),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    storage_user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
) -> MemoryManagementResponse:
    require_management_audit_access(principal)
    raw, catalog = await asyncio.gather(
        asyncio.to_thread(_list_business_memories),
        _identity_catalog(storage, storage_user_id),
    )
    known_users, known_projects = catalog

    user_counts: dict[str, int] = defaultdict(int)
    global_counts: dict[str, int] = defaultdict(int)
    project_counts: dict[tuple[str, str], int] = defaultdict(int)
    all_items: list[ManagedMemoryItem] = []
    for record in raw:
        item = _to_item(record)
        all_items.append(item)
        user_counts[item.platform_user_id] += 1
        if item.scope_type == "user":
            global_counts[item.platform_user_id] += 1
        elif item.project_id:
            project_counts[(item.platform_user_id, item.project_id)] += 1

    user_ids = set(known_users) | set(user_counts)
    users: list[MemoryManagementUser] = []
    for user_id in user_ids:
        known = known_users.get(user_id) or {}
        project_ids = {
            pid
            for uid, pid in set(known_projects) | set(project_counts)
            if uid == user_id
        }
        projects = [
            MemoryManagementProject(
                project_id=pid,
                project_name=known_projects.get((user_id, pid), pid),
                memory_count=project_counts.get((user_id, pid), 0),
            )
            for pid in project_ids
        ]
        projects.sort(key=lambda value: (-value.memory_count, value.project_name))
        users.append(MemoryManagementUser(
            user_id=user_id,
            username=known.get("username", user_id),
            display_name=known.get("display_name", user_id),
            memory_count=user_counts.get(user_id, 0),
            user_memory_count=global_counts.get(user_id, 0),
            projects=projects,
        ))
    users.sort(key=lambda value: (-value.memory_count, value.display_name))

    normalized_query = query.strip().casefold()
    filtered = [
        item
        for item in all_items
        if (platform_user_id is None or item.platform_user_id == platform_user_id)
        and (scope_type is None or item.scope_type == scope_type)
        and (
            project_id is None
            or (item.scope_type == "user_project" and item.project_id == project_id)
        )
        and (not normalized_query or normalized_query in item.content.casefold())
    ]
    filtered.sort(
        key=lambda item: item.updated_at or item.created_at or "",
        reverse=True,
    )
    return MemoryManagementResponse(
        users=users,
        memories=filtered[offset : offset + limit],
        total=len(filtered),
    )


@memory_management_router.patch(
    "/memories/{memory_id}/scope",
    response_model=ManagedMemoryItem,
    summary="Move one memory between user and user-project scopes",
)
async def update_managed_memory_scope(
    memory_id: str,
    body: UpdateMemoryScopeRequest,
    storage_user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
) -> ManagedMemoryItem:
    require_management_audit_access(principal)
    try:
        found = await asyncio.to_thread(_find_memory, memory_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该记忆。") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该记忆不属于可管理的业务用户记忆。") from exc

    metadata = found["metadata"]
    platform_user_id = str(metadata["platform_user_id"])
    target_project_id = body.project_id if body.scope_type == "user_project" else None
    if body.scope_type == "user_project" and not target_project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="调整为用户＋项目记忆时必须选择项目。",
        )
    if target_project_id:
        _, known_projects = await _identity_catalog(storage, storage_user_id)
        if (platform_user_id, target_project_id) not in known_projects:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="所选项目不属于该业务用户。",
            )

    target = build_business_memory_target(
        tenant_id=str(metadata.get("tenant_id") or get_memory_runtime().tenant_id),
        platform_user_id=platform_user_id,
        scope_type=body.scope_type,
        project_id=target_project_id,
    )
    old_scope = {
        "scope_type": metadata.get("scope_type"),
        "project_id": metadata.get("project_id"),
    }
    adjusted_at = datetime.now(timezone.utc).isoformat()
    update_metadata = {
        **target.as_dict(),
        "scope_adjusted_at": adjusted_at,
        "scope_adjusted_by": principal.subject,
        "updated_at": adjusted_at,
    }

    await asyncio.to_thread(_update_memory_metadata, memory_id, update_metadata)
    get_memory_runtime().invalidate_memory_caches()
    await _log_management_action(
        action="move_scope",
        principal=principal,
        memory_id=memory_id,
        metadata=update_metadata,
        details={"from": old_scope, "to": target.as_dict()},
    )
    refreshed = await asyncio.to_thread(_find_memory, memory_id)
    item = refreshed["item"]
    payload = {**refreshed["metadata"], "data": item.get("memory", "")}
    payload["created_at"] = item.get("created_at")
    payload["updated_at"] = item.get("updated_at")
    return _to_item({"id": memory_id, "payload": payload})


@memory_management_router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one managed long-term memory",
)
async def delete_managed_memory(
    memory_id: str,
    principal: AgentScopePrincipal = Depends(get_current_principal),
) -> None:
    require_management_audit_access(principal)
    try:
        found = await asyncio.to_thread(_find_memory, memory_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该记忆。") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该记忆不属于可管理的业务用户记忆。") from exc

    await asyncio.to_thread(_delete_memory_record, memory_id)
    get_memory_runtime().invalidate_memory_caches()
    await _log_management_action(
        action="delete",
        principal=principal,
        memory_id=memory_id,
        metadata=found["metadata"],
        details={"scope_type": found["metadata"].get("scope_type")},
    )


__all__ = ["memory_management_router"]
