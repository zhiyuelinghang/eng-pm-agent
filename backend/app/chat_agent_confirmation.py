"""Resume group agent consent using the original requester's bound session."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .api_common import get_current_user
from .db import get_db
from .agentscope_client import AgentScopeGatewayError
from .models import AgentConversation, ChatMessage, User
from .schemas import AgentConversationConfirmInput


router = APIRouter()


@router.post("/chat/messages/{message_id}/agent/confirm")
def confirm_chat_agent_tool(
    message_id: int, payload: AgentConversationConfirmInput,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from . import chat_api as chat
    from .chat_agent_runtime import _agent_reply_runtime_metadata, _persist_chat_agent_reply

    row = db.get(ChatMessage, message_id)
    if row is None or row.deleted_at is not None or row.sender_type != "agent":
        raise HTTPException(status_code=404, detail="智能体运行不存在")
    channel = chat.chat_channel_for_user_or_403(db, row.channel_id, user)
    source = db.get(ChatMessage, row.reply_to_id)
    if source is None or source.sender_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有本次请求的发起人可以确认操作")
    metadata = dict(row.metadata_json or {})
    if metadata.get("runtime_status") != "awaiting_permission":
        raise HTTPException(status_code=409, detail="本次运行已结束或不在等待确认")
    conversation = db.get(AgentConversation, metadata.get("platform_conversation_id"))
    if (conversation is None or conversation.user_id != user.id
        or conversation.project_id != channel.project_id
        or conversation.agent_id != row.sender_agent_id
        or conversation.agentscope_session_id != metadata.get("agentscope_session_id")):
        raise HTTPException(status_code=403, detail="确认操作与当前会话不匹配")
    # A later mention may have changed ChatAgentThread. Never use that mutable
    # thread's session to resume this older request.
    thread = SimpleNamespace(agent_id=conversation.agent_id, agent_name=conversation.agent_name,
                             agentscope_session_id=conversation.agentscope_session_id)
    try:
        reply = chat._agentscope_client().confirm_tool_call(
            agent_id=conversation.agent_id, session_id=conversation.agentscope_session_id,
            reply_id=payload.reply_id, tool_call=payload.tool_call,
            confirmed=payload.confirmed, rules=None, wait_for_collaboration=True,
        )
    except AgentScopeGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    db.expire_all()
    chat.chat_channel_for_user_or_403(db, row.channel_id, user)
    if (row.metadata_json or {}).get("runtime_status") == "interrupted":
        return chat.ok(chat.chat_message_view(db, row))
    conversation.status = reply.status
    previous_trace = metadata.get("runtime_trace") or {}
    stages = [dict(stage) for stage in previous_trace.get("stages", [])]
    if reply.status not in {"running", "awaiting_permission", "awaiting_external_result"}:
        for stage in stages:
            if not stage.get("finished_at"):
                stage.update(status=reply.status, finished_at=datetime.now(UTC).isoformat())
    result = _persist_chat_agent_reply(
        db, channel, source, thread,
        content=reply.content or "确认结果已处理。",
        metadata=_agent_reply_runtime_metadata(source, thread, reply, stages=stages,
            turn_started_at=previous_trace.get("turn_started_at")),
    )
    db.commit()
    return chat.ok(chat.chat_message_view(db, result), "人工确认结果已处理")
