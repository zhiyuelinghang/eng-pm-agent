# -*- coding: utf-8 -*-
"""Read-only management audit of engineering-platform conversations."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .._auth import AgentScopePrincipal
from .._session_access import require_management_audit_access
from ..deps import (
    get_current_principal,
    get_current_user_id,
    get_message_bus,
    get_storage,
)
from ..message_bus import MessageBus, MessageBusKeys
from ..storage import SessionSource, StorageBase


class PlatformAuditConversation(BaseModel):
    """One platform conversation shown at the third navigation level."""

    session_id: str
    conversation_id: str
    title: str
    conversation_type: str
    agent_id: str
    agent_name: str
    is_running: bool
    created_at: datetime
    updated_at: datetime


class PlatformAuditProject(BaseModel):
    """One project and its platform conversations."""

    project_id: str
    project_name: str
    conversations: list[PlatformAuditConversation] = Field(
        default_factory=list,
    )


class PlatformAuditUser(BaseModel):
    """One engineering-platform user and their projects."""

    user_id: str
    username: str
    display_name: str
    projects: list[PlatformAuditProject] = Field(default_factory=list)


class PlatformAuditTreeResponse(BaseModel):
    """Complete three-level audit navigation tree."""

    users: list[PlatformAuditUser] = Field(default_factory=list)
    total_conversations: int = 0


class PlatformAuditMessagesResponse(BaseModel):
    """Complete read-only transcript for one selected conversation."""

    session_id: str
    messages: list[Any]
    is_running: bool


platform_audit_router = APIRouter(
    prefix="/platform-audit",
    tags=["platform-audit"],
)


def _project_message(message: Any) -> dict[str, Any]:
    """Replace platform-injected user context with its display-only text."""
    payload = message.model_dump(mode="json")
    metadata = payload.get("metadata") or {}
    display_content = metadata.get("platform_display_content")
    if payload.get("role") == "user" and isinstance(display_content, str):
        first_text = next(
            (
                block
                for block in payload.get("content") or []
                if block.get("type") == "text"
            ),
            None,
        )
        payload["content"] = [
            {
                "type": "text",
                "id": (
                    first_text.get("id")
                    if isinstance(first_text, dict)
                    else f"{payload['id']}-platform"
                ),
                "text": display_content,
            },
        ]
    return payload


@platform_audit_router.get(
    "/tree",
    response_model=PlatformAuditTreeResponse,
    summary="List platform users, projects and conversations for audit",
)
async def list_platform_audit_tree(
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    message_bus: MessageBus = Depends(get_message_bus),
) -> PlatformAuditTreeResponse:
    """Build the complete navigation hierarchy without loading messages."""
    require_management_audit_access(principal)
    sessions = [
        session
        for session in await storage.list_all_sessions(user_id)
        if session.source == SessionSource.PLATFORM
        and session.config.platform_context is not None
        and session.config.platform_context.session_role == "primary"
    ]

    users: dict[str, PlatformAuditUser] = {}
    projects: dict[tuple[str, str], PlatformAuditProject] = {}
    for session in sessions:
        context = session.config.platform_context
        assert context is not None
        user = users.get(context.user_id)
        if user is None:
            user = PlatformAuditUser(
                user_id=context.user_id,
                username=context.username,
                display_name=context.display_name,
            )
            users[context.user_id] = user

        project_key = (context.user_id, context.project_id)
        project = projects.get(project_key)
        if project is None:
            project = PlatformAuditProject(
                project_id=context.project_id,
                project_name=context.project_name,
            )
            projects[project_key] = project
            user.projects.append(project)

        project.conversations.append(
            PlatformAuditConversation(
                session_id=session.id,
                conversation_id=context.conversation_id,
                title=context.conversation_title,
                conversation_type=context.conversation_type,
                agent_id=session.agent_id,
                agent_name=context.agent_name,
                is_running=await message_bus.is_locked(
                    MessageBusKeys.session_lock(session.id),
                ),
                created_at=session.created_at,
                updated_at=session.updated_at,
            ),
        )

    for user in users.values():
        for project in user.projects:
            project.conversations.sort(
                key=lambda item: item.updated_at,
                reverse=True,
            )
        user.projects.sort(
            key=lambda item: item.conversations[0].updated_at,
            reverse=True,
        )

    ordered_users = sorted(
        users.values(),
        key=lambda item: item.projects[0].conversations[0].updated_at,
        reverse=True,
    )
    return PlatformAuditTreeResponse(
        users=ordered_users,
        total_conversations=len(sessions),
    )


@platform_audit_router.get(
    "/sessions/{session_id}/messages",
    response_model=PlatformAuditMessagesResponse,
    summary="Read the complete platform conversation transcript",
)
async def get_platform_audit_messages(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    message_bus: MessageBus = Depends(get_message_bus),
) -> PlatformAuditMessagesResponse:
    """Return all persisted messages for the selected platform session."""
    require_management_audit_access(principal)
    session = await storage.get_session(user_id, "", session_id)
    if (
        session is None
        or session.source != SessionSource.PLATFORM
        or session.config.platform_context is None
        or session.config.platform_context.session_role != "primary"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该平台交互会话。",
        )

    messages, has_more = await storage.list_messages(
        user_id,
        session_id,
        limit=200,
    )
    while has_more and messages:
        older, has_more = await storage.list_messages(
            user_id,
            session_id,
            limit=200,
            before=messages[0].id,
        )
        messages = [*older, *messages]

    return PlatformAuditMessagesResponse(
        session_id=session_id,
        messages=[_project_message(message) for message in messages],
        is_running=await message_bus.is_locked(
            MessageBusKeys.session_lock(session_id),
        ),
    )
