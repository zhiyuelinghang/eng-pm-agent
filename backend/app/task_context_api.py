from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .chat_membership_policy import chat_auto_sync
from .api_common import get_current_user, ok, project_for_user_or_403
from .db import get_db
from .models import (
    Attachment,
    ChatChannel,
    ChatChannelMember,
    ChatMessage,
    CollaborationMessage,
    CollaborationSession,
    RiskSource,
    User,
    WbsItem,
)
from .task_engine_gateway import get_engine


router = APIRouter(prefix="/api", tags=["task-context"])


def _contains_task(values: list[Any] | None, task_id: str) -> bool:
    return task_id in {str(value) for value in values or []}


def _action_channel_ids(scope: dict[str, Any]) -> set[int]:
    actions: list[dict[str, Any]] = []
    root_action = scope.get("action")
    if isinstance(root_action, dict):
        actions.append(root_action)
    step_actions = scope.get("step_actions")
    if isinstance(step_actions, dict):
        actions.extend(
            value for value in step_actions.values() if isinstance(value, dict)
        )
    return {
        int(action["channel_id"])
        for action in actions
        if action.get("channel_id")
    }


def _task_material_names(task: Any) -> set[str]:
    names: set[str] = set()
    for step in task.steps:
        if step.deliverable:
            names.add(str(step.deliverable).strip())
        for attachment in getattr(step, "attachments", ()) or ():
            value = str(attachment).strip()
            if value:
                names.add(value)
    return {name for name in names if name}


@router.get("/projects/{project_id}/tasks/{task_id}/context")
def task_context(
    project_id: int,
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    task = get_engine().get_task(task_id)
    if task is None or int((task.scope or {}).get("project_id") or 0) != project_id:
        raise HTTPException(status_code=404, detail="任务不存在或不属于当前项目")

    scope = task.scope or {}
    all_channels = list(
        db.scalars(
            select(ChatChannel).where(
                ChatChannel.project_id == project_id,
                ChatChannel.archived_at.is_(None),
            ),
        ).all(),
    )
    private_memberships = set(
        db.scalars(
            select(ChatChannelMember.channel_id).where(
                ChatChannelMember.user_id == user.id,
                ChatChannelMember.left_at.is_(None),
            ),
        ).all(),
    )
    channels = {
        channel.id: channel
        for channel in all_channels
        if chat_auto_sync(channel) or channel.id in private_memberships
    }
    chat_rows = list(
        db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.channel_id.in_(channels.keys()),
                ChatMessage.deleted_at.is_(None),
            )
            .order_by(ChatMessage.id.desc())
            .limit(1000),
        ).all(),
    ) if channels else []
    chat_messages = [
        {
            "id": row.id,
            "channel_id": row.channel_id,
            "channel_title": channels[row.channel_id].title,
            "content": row.content,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in chat_rows
        if _contains_task(row.task_ids, task_id)
    ]

    sessions = list(
        db.scalars(
            select(CollaborationSession)
            .where(CollaborationSession.project_id == project_id)
            .order_by(CollaborationSession.id.desc()),
        ).all(),
    )
    session_ids = [row.id for row in sessions]
    collaboration_rows = list(
        db.scalars(
            select(CollaborationMessage)
            .where(CollaborationMessage.session_id.in_(session_ids))
            .order_by(CollaborationMessage.id.desc()),
        ).all(),
    ) if session_ids else []
    messages_by_session: dict[int, CollaborationMessage] = {}
    for row in collaboration_rows:
        if _contains_task(row.generated_task_ids, task_id):
            messages_by_session.setdefault(row.session_id, row)
    collaboration_sessions = [
        {
            "id": row.id,
            "title": row.title,
            "message_id": messages_by_session.get(row.id).id
            if row.id in messages_by_session
            else None,
            "content": messages_by_session.get(row.id).content
            if row.id in messages_by_session
            else "",
        }
        for row in sessions
        if _contains_task(row.task_ids, task_id) or row.id in messages_by_session
    ]

    risk = None
    risk_id = scope.get("risk_source_id")
    if risk_id:
        row = db.get(RiskSource, int(risk_id))
        if row is not None and row.project_id == project_id:
            risk = {"id": str(row.id), "name": row.risk_part}

    wbs = None
    site_ref = getattr(getattr(task, "site", None), "ref", None)
    if site_ref:
        row = db.get(WbsItem, int(site_ref))
        if row is not None and row.project_id == project_id:
            wbs = {"id": str(row.id), "code": row.wbs_code, "name": row.name}

    material_names = _task_material_names(task)
    attachment_rows = list(
        db.scalars(
            select(Attachment)
            .where(Attachment.project_id == project_id)
            .order_by(Attachment.created_at.desc()),
        ).all(),
    )
    documents = [
        {"id": str(row.id), "file_name": row.file_name, "category": row.category}
        for row in attachment_rows
        if row.file_name in material_names
    ]

    related_channel_ids = _action_channel_ids(scope)
    source_channel_ids = {item["channel_id"] for item in chat_messages}
    related_channels = [
        {"id": channel.id, "title": channel.title}
        for channel in channels.values()
        if channel.id in related_channel_ids and channel.id not in source_channel_ids
    ]
    return ok(
        {
            "task_id": task_id,
            "risk": risk,
            "wbs": wbs,
            "chat_messages": chat_messages,
            "collaboration_sessions": collaboration_sessions,
            "documents": documents,
            "related_channels": related_channels,
        },
    )
