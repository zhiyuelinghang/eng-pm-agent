"""群聊未读计数、已读回执和文件自动入库。"""
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .agent_api_support import _agentscope_client, _ready_project_weknora_agent_id
from .agentscope_client import AgentScopeGatewayError
from .api_common import audit, get_current_user, ok, project_for_user_or_403
from .chat_api import (_ensure_active_channel_member, _queue_chat_message_publish,
                       chat_channel_for_user_or_403, chat_message_view, ensure_project_chat_channel,
                       _sync_project_channel_members)
from .db import get_db
from .chat_membership_policy import auto_sync_condition
from .engineering_document_catalog import add_local_folder, add_pending_local_file, find_catalogue_node
from .models import ChatChannel, ChatChannelMember, ChatMessage, EngineeringDocumentNode, User
from .personnel_policy import DEFAULT_ENGINEERING_KNOWLEDGE_BASE_NAME
from .workspace_models import ChatKnowledgeFolder

router = APIRouter(prefix="/api", tags=["chat-workspace"])


@router.get("/projects/{project_id}/chat/unread")
def chat_unread_counts(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    ensure_project_chat_channel(db, project_id, user)
    for channel in db.scalars(select(ChatChannel).where(ChatChannel.project_id == project_id, auto_sync_condition(), ChatChannel.archived_at.is_(None))).all():
        _sync_project_channel_members(db, channel, user)
    db.commit()
    rows = db.execute(select(ChatChannel.id, func.count(ChatMessage.id)).join(
        ChatChannelMember, (ChatChannelMember.channel_id == ChatChannel.id) & (ChatChannelMember.user_id == user.id) & ChatChannelMember.left_at.is_(None),
    ).outerjoin(ChatMessage, (ChatMessage.channel_id == ChatChannel.id) & ChatMessage.deleted_at.is_(None)
        & (ChatMessage.id > func.coalesce(ChatChannelMember.last_read_message_id, 0))
        & or_(ChatMessage.sender_user_id.is_(None), ChatMessage.sender_user_id != user.id),
    ).where(ChatChannel.project_id == project_id, ChatChannel.archived_at.is_(None)).group_by(ChatChannel.id)).all()
    counts = {str(channel_id): count for channel_id, count in rows}
    return ok({"total": sum(counts.values()), "channels": counts})


class ChatReadInput(BaseModel):
    message_id: int = Field(ge=1)


@router.post("/chat/channels/{channel_id}/read")
def mark_chat_read(channel_id: int, payload: ChatReadInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = chat_channel_for_user_or_403(db, channel_id, user)
    message = db.get(ChatMessage, payload.message_id)
    if message is None or message.channel_id != channel_id:
        raise HTTPException(422, "已读消息不属于当前群聊")
    member = _ensure_active_channel_member(db, channel, user.id)
    db.flush()
    db.execute(update(ChatChannelMember).where(ChatChannelMember.id == member.id,
        func.coalesce(ChatChannelMember.last_read_message_id, 0) < payload.message_id,
    ).values(last_read_message_id=payload.message_id))
    db.commit()
    return ok({"message_id": payload.message_id})


def ensure_group_folder(db: Session, channel: ChatChannel, agent_id: str) -> ChatKnowledgeFolder:
    binding = db.get(ChatKnowledgeFolder, channel.id)
    if binding is None:
        roots = db.scalars(select(EngineeringDocumentNode).where(EngineeringDocumentNode.project_id == channel.project_id, EngineeringDocumentNode.node_type == "knowledge_base").order_by(EngineeringDocumentNode.id)).all()
        root = next((row for row in roots if row.name == DEFAULT_ENGINEERING_KNOWLEDGE_BASE_NAME), roots[0] if roots else None)
        if root is None:
            raise HTTPException(409, "当前工程尚未配置知识库，请联系工程管理员配置后再上传群文件")
        # 旧群名可能包含目录分隔符，使用全角字符保留名称含义。
        name = channel.title.strip().replace("/", "／").replace("\\", "＼")
        path = f"群聊/{name}"
        existing = find_catalogue_node(db, channel.project_id, knowledge_base_id=root.knowledge_base_id, node_type="folder", folder_path=path)
        if existing:
            raise HTTPException(409, "知识库已存在同名目录，请联系工程管理员处理后重试")
        binding = ChatKnowledgeFolder(channel_id=channel.id, project_id=channel.project_id, knowledge_base_id=root.knowledge_base_id, folder_path=path)
        db.add(binding)
        # 先保存权限绑定，远端超时或后续失败也不会将文件变成项目公开资料。
        db.commit()
    client = _agentscope_client()
    for path in ("群聊", binding.folder_path):
        if not find_catalogue_node(db, channel.project_id, knowledge_base_id=binding.knowledge_base_id, node_type="folder", folder_path=path):
            client.create_weknora_folder(agent_id, binding.knowledge_base_id, folder_path=path)
            add_local_folder(db, channel.project_id, binding.knowledge_base_id, path)
            db.commit()
    return binding


@router.post("/chat/channels/{channel_id}/files", status_code=201)
def upload_chat_file(channel_id: int, file: UploadFile = File(...), client_message_id: str = Form(default="", max_length=64),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = chat_channel_for_user_or_403(db, channel_id, user)
    # 管理员可管理资料，但发送文件仍需是群成员。
    client_id = client_message_id or str(uuid4())
    existing = db.scalar(select(ChatMessage).where(ChatMessage.channel_id == channel.id, ChatMessage.client_message_id == client_id))
    if existing:
        if existing.sender_user_id != user.id:
            raise HTTPException(409, "上传标识已被占用")
        return ok(chat_message_view(db, existing), "文件已入库")
    filename = Path((file.filename or "").replace("\\", "/")).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(422, "请选择需要上传的文件")
    content = file.file.read(50 * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(422, "不能上传空文件")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, "上传文件不能超过 50 MB")
    agent_id = _ready_project_weknora_agent_id(db, channel.project_id)
    try:
        binding = ensure_group_folder(db, channel, agent_id)
        result = _agentscope_client().upload_weknora_knowledge(agent_id, binding.knowledge_base_id, filename=filename,
            content=content, content_type=file.content_type or "application/octet-stream", folder_path=binding.folder_path, enable_multimodel=True)
    except AgentScopeGatewayError as exc:
        raise HTTPException(exc.status_code, f"群文件入库失败：{exc}") from exc
    node = add_pending_local_file(db, channel.project_id, binding.knowledge_base_id, binding.folder_path, result,
        fallback_name=filename, file_size=len(content), file_type=Path(filename).suffix.removeprefix("."))
    message = ChatMessage(channel_id=channel.id, sender_type="user", sender_user_id=user.id, message_type="text",
        content=f"上传文件：{filename}", client_message_id=client_id, task_ids=[], metadata_json={"attachments": [{
            "knowledge_id": node.external_id, "knowledge_base_id": binding.knowledge_base_id,
            "file_name": filename, "file_size": len(content), "folder_path": binding.folder_path, "parse_status": node.parse_status,
        }]})
    db.add(message)
    channel.last_message_at = datetime.now(UTC)
    db.flush()
    _queue_chat_message_publish(db, channel, message)
    audit(db, user, "群文件自动入库", f"将「{filename}」保存到「{channel.title}」目录", channel.project_id, "chat_message", message.id)
    db.commit()
    db.refresh(message)
    return ok(chat_message_view(db, message), "群文件已入库，正在解析")
