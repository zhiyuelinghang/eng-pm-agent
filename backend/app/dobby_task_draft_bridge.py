"""Convert a Dobby-orchestrated Task Assistant result into a private draft."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agentscope_client import AgentScopeReply
from .api_common import audit
from .models import AgentConversation, ChatTaskDraft, User


_TASK_DRAFT_TAG = re.compile(
    r"<task-draft>\s*(.*?)\s*</task-draft>",
    flags=re.DOTALL | re.IGNORECASE,
)
_ACTIVE_DRAFT_STATUSES = (
    "generating",
    "ready",
    "publishing",
    "failed",
    "cancelled",
)


def _tagged_flow(reply: AgentScopeReply) -> dict[str, Any] | None:
    texts = [reply.content]
    for message in reply.raw_messages:
        if not isinstance(message, dict):
            continue
        texts.extend(
            str(block.get("text") or "")
            for block in message.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
    for text in reversed(texts):
        matched = _TASK_DRAFT_TAG.search(text)
        if matched is None:
            continue
        try:
            payload = json.loads(matched.group(1))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("title") and isinstance(
            payload.get("steps"),
            list,
        ):
            return payload
    return None


def _request_id(conversation_id: int, reply: AgentScopeReply) -> str:
    source = f"{conversation_id}:{reply.message_id or reply.content}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    return f"dobby-task-{digest}"


def _display_content(content: str) -> str:
    cleaned = _TASK_DRAFT_TAG.sub("", content).strip()
    return cleaned or "任务助手已生成待确认草稿，请核对后再发布。"


def materialize_dobby_task_draft(
    db: Session,
    conversation: AgentConversation,
    reply: AgentScopeReply,
    *,
    user_request: str = "",
) -> tuple[int, str] | None:
    """Persist a tagged worker result without publishing any formal task."""

    if conversation.conversation_type != "general" or reply.status != "completed":
        return None
    flow = _tagged_flow(reply)
    if flow is None:
        return None
    user = db.get(User, conversation.user_id)
    if user is None:
        return None

    client_request_id = _request_id(conversation.id, reply)
    existing = db.scalar(
        select(ChatTaskDraft).where(
            ChatTaskDraft.requested_by_user_id == user.id,
            ChatTaskDraft.client_request_id == client_request_id,
        ),
    )
    if existing is not None:
        return existing.id, _display_content(reply.content)
    active = db.scalar(
        select(ChatTaskDraft)
        .where(
            ChatTaskDraft.project_id == conversation.project_id,
            ChatTaskDraft.requested_by_user_id == user.id,
            ChatTaskDraft.status.in_(_ACTIVE_DRAFT_STATUSES),
        )
        .order_by(ChatTaskDraft.updated_at.desc(), ChatTaskDraft.id.desc())
        .limit(1),
    )
    if active is not None:
        return active.id, _display_content(reply.content)

    # Import lazily because chat_api imports the conversation router during
    # application startup. These helpers enforce the same project channel,
    # payload normalization, private outbox, and confirmation contract as an
    # explicit @任务助手 request.
    from .chat_api import (  # noqa: PLC0415
        _queue_private_task_draft_publish,
        _task_draft_payload,
        ensure_project_chat_channel,
    )

    channel = ensure_project_chat_channel(db, conversation.project_id, user)
    request_text = user_request.strip()[:4000] or "请核对 Dobby 生成的任务草稿"
    draft = ChatTaskDraft(
        project_id=conversation.project_id,
        channel_id=channel.id,
        requested_by_user_id=user.id,
        client_request_id=client_request_id,
        generation_id=client_request_id,
        request_text=request_text,
        context_json=[
            {
                "source": "dobby_orchestration",
                "conversation_id": conversation.id,
                "agentscope_message_id": reply.message_id,
            },
        ],
        status="ready",
        draft_payload=_task_draft_payload(flow, request_text),
        publish_result={},
        published_task_ids=[],
    )
    db.add(draft)
    db.flush()
    _queue_private_task_draft_publish(db, draft)
    audit(
        db,
        user,
        "生成任务草稿",
        "Dobby 调用任务助手生成私有待确认草稿，未发布",
        conversation.project_id,
        "chat_task_draft",
        draft.id,
    )
    return draft.id, _display_content(reply.content)


__all__ = ["materialize_dobby_task_draft"]
