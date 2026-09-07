"""普通群设置、成员管理及群文件目录。"""
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, PositiveInt, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_common import audit, get_current_user, ok, project_for_user_or_403
from .chat_api import (
    _ensure_active_channel_member, _project_member_user_ids,
    chat_channel_for_user_or_403, chat_channel_view, chat_realtime_user_channel, chat_realtime_channel,
)
from .db import get_db
from .chat_membership_policy import chat_auto_sync
from .engineering_document_catalog import readable_external_ids
from .models import ChatChannel, ChatChannelMember, ChatRealtimeOutbox, EngineeringDocumentNode, User
from .schemas import ChatPrivateChannelInput
from .workspace_models import ChatKnowledgeFolder

router = APIRouter(prefix="/api", tags=["chat-management"])


class ChatMembersInput(BaseModel):
    user_ids: list[PositiveInt] = Field(min_length=1, max_length=1000)


class ChatOwnerInput(BaseModel):
    user_id: PositiveInt


class ChatMembershipSettingsInput(BaseModel):
    user_ids: list[PositiveInt] = Field(min_length=1, max_length=1000)
    auto_sync: bool = False
    owner_user_id: PositiveInt


class ChatSettingsInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: Any) -> Any:
        return ChatPrivateChannelInput.normalize_title(value)


def _managed_channel(db: Session, channel_id: int, user: User, *, allow_all: bool = False) -> ChatChannel:
    channel = chat_channel_for_user_or_403(db, channel_id, user)
    if chat_auto_sync(channel) and not allow_all:
        raise HTTPException(409, "ALL 群成员由项目名单同步，不支持普通群设置")
    # Serialize settings writes and ownership transfers before checking authority.
    channel = db.scalar(select(ChatChannel).where(ChatChannel.id == channel_id)
                        .with_for_update().execution_options(populate_existing=True))
    owner = db.scalar(select(ChatChannelMember).where(
        ChatChannelMember.channel_id == channel_id, ChatChannelMember.user_id == user.id,
        ChatChannelMember.left_at.is_(None), ChatChannelMember.member_role == "owner",
    ).execution_options(populate_existing=True))
    if owner is None:
        raise HTTPException(403, "仅群主可以管理群聊")
    return channel


def _publish_settings_change(db: Session, channel: ChatChannel) -> None:
    user_ids = db.scalars(select(ChatChannelMember.user_id).where(
        ChatChannelMember.channel_id == channel.id, ChatChannelMember.left_at.is_(None),
    )).all()
    for user_id in user_ids:
        db.add(ChatRealtimeOutbox(method="publish", partition=0, payload={
            "channel": chat_realtime_user_channel(channel.project_id, user_id),
            "data": {"type": "chat.channel.updated", "project_id": channel.project_id, "channel_id": channel.id},
        }))
    channel.updated_at = datetime.now(UTC)


def _retire_member_access(db: Session, channel: ChatChannel, previous_ids: set[int]) -> None:
    old_channel = chat_realtime_channel(channel)
    channel.membership_revision = (channel.membership_revision or 0) + 1
    # New publications use a new channel name; previously issued tokens cannot
    # subscribe to messages after a membership removal.
    for user_id in previous_ids:
        db.add(ChatRealtimeOutbox(method="unsubscribe", partition=0, payload={
            "channel": old_channel, "user": str(user_id),
        }))
        db.add(ChatRealtimeOutbox(method="publish", partition=0, payload={
            "channel": chat_realtime_user_channel(channel.project_id, user_id),
            "data": {"type": "chat.channel.updated", "project_id": channel.project_id, "channel_id": channel.id},
        }))


@router.put("/chat/channels/{channel_id}/members")
def save_chat_membership(channel_id: int, payload: ChatMembershipSettingsInput,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = _managed_channel(db, channel_id, user, allow_all=True)
    selected = set(payload.user_ids)
    project_ids = _project_member_user_ids(db, channel.project_id) | {user.id}
    if not selected.issubset(project_ids):
        raise HTTPException(422, "只能选择当前项目的成员，请刷新成员名单")
    if user.id not in selected:
        raise HTTPException(422, "当前群主必须保留在群内")
    if payload.owner_user_id not in selected:
        raise HTTPException(422, "新群主必须是已勾选的群成员")
    if payload.auto_sync and selected != project_ids:
        raise HTTPException(422, "全选项目成员后才能开启自动同步，请刷新成员名单")
    previous = db.scalars(select(ChatChannelMember).where(
        ChatChannelMember.channel_id == channel.id, ChatChannelMember.left_at.is_(None),
    )).all()
    previous_ids = {member.user_id for member in previous}
    previous_owner_ids = {member.user_id for member in previous if member.member_role == "owner"}
    if payload.owner_user_id != user.id and payload.owner_user_id not in previous_ids:
        raise HTTPException(422, "请先保存新增成员，再转让群主")
    channel.auto_sync_members = payload.auto_sync
    for member in previous:
        if member.user_id not in selected:
            member.left_at = datetime.now(UTC)
        member.member_role = "member"
    for user_id in selected:
        member = _ensure_active_channel_member(db, channel, user_id)
        member.member_role = "owner" if user_id == payload.owner_user_id else "member"
    db.flush()
    if previous_ids - selected:
        _retire_member_access(db, channel, previous_ids)
    _publish_settings_change(db, channel)
    audit(db, user, "更新群成员", f"群聊 {channel.id}：新增 {len(selected - previous_ids)} 人，移除 {len(previous_ids - selected)} 人，自动同步 {'开启' if payload.auto_sync else '关闭'}", channel.project_id, "chat_channel", channel.id)
    if previous_owner_ids != {payload.owner_user_id}:
        audit(db, user, "转让群主", f"将群聊 {channel.id} 的群主转让给用户 {payload.owner_user_id}", channel.project_id, "chat_channel", channel.id)
    db.commit()
    return ok(chat_channel_view(db, channel), "成员设置已保存")


class ChatTitleCheckInput(ChatSettingsInput):
    exclude_channel_id: PositiveInt | None = None


@router.post("/projects/{project_id}/chat/check-title")
def check_chat_title(project_id: int, payload: ChatTitleCheckInput,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    if payload.exclude_channel_id is not None:
        channel = _managed_channel(db, payload.exclude_channel_id, user, allow_all=True)
        if channel.project_id != project_id:
            raise HTTPException(422, "群聊不属于当前项目")
    statement = select(ChatChannel.id).where(
        ChatChannel.project_id == project_id, ChatChannel.archived_at.is_(None),
        func.lower(func.trim(ChatChannel.title)) == payload.title.lower(),
    )
    if payload.exclude_channel_id is not None:
        statement = statement.where(ChatChannel.id != payload.exclude_channel_id)
    return ok({"available": db.scalar(statement) is None})


@router.post("/chat/channels/{channel_id}/members")
def add_chat_members(channel_id: int, payload: ChatMembersInput,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = _managed_channel(db, channel_id, user)
    selected = set(payload.user_ids)
    if not selected.issubset(_project_member_user_ids(db, channel.project_id)):
        raise HTTPException(422, "只能添加当前项目的成员")
    for user_id in selected:
        member = _ensure_active_channel_member(db, channel, user_id)
        # Rejoining must not restore a historical ownership role.
        if member.user_id != user.id:
            member.member_role = "member"
    db.flush()
    _publish_settings_change(db, channel)
    audit(db, user, "添加群成员", f"向群聊 {channel.id} 添加 {len(selected)} 位项目成员", channel.project_id, "chat_channel", channel.id)
    db.commit()
    return ok(chat_channel_view(db, channel), "群成员已添加")


@router.post("/chat/channels/{channel_id}/owner")
def transfer_chat_owner(channel_id: int, payload: ChatOwnerInput,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = _managed_channel(db, channel_id, user, allow_all=True)
    if payload.user_id == user.id:
        raise HTTPException(422, "请选择其他群成员")
    target = db.scalar(select(ChatChannelMember).where(
        ChatChannelMember.channel_id == channel_id, ChatChannelMember.user_id == payload.user_id,
        ChatChannelMember.left_at.is_(None),
    ))
    if target is None or payload.user_id not in _project_member_user_ids(db, channel.project_id):
        raise HTTPException(422, "新群主必须是当前群内的项目成员")
    for member in db.scalars(select(ChatChannelMember).where(
        ChatChannelMember.channel_id == channel_id, ChatChannelMember.member_role == "owner",
    )).all():
        member.member_role = "member"
    target.member_role = "owner"
    db.flush()
    _publish_settings_change(db, channel)
    audit(db, user, "转让群主", f"将群聊 {channel.id} 的群主转让给用户 {payload.user_id}", channel.project_id, "chat_channel", channel.id)
    db.commit()
    return ok(chat_channel_view(db, channel), "群主已转让")


@router.delete("/chat/channels/{channel_id}/members/{member_user_id}")
def remove_chat_member(channel_id: int, member_user_id: int,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = _managed_channel(db, channel_id, user)
    member = db.scalar(select(ChatChannelMember).where(
        ChatChannelMember.channel_id == channel_id, ChatChannelMember.user_id == member_user_id,
        ChatChannelMember.left_at.is_(None),
    ))
    if member is None:
        raise HTTPException(404, "该成员已不在群内")
    if member.member_role == "owner" or member_user_id == user.id:
        raise HTTPException(422, "不能移除群主，请先转让群主")
    member.left_at = datetime.now(UTC)
    member.member_role = "member"
    db.flush()
    _retire_member_access(db, channel, {member_user_id} | set(db.scalars(select(ChatChannelMember.user_id).where(
        ChatChannelMember.channel_id == channel.id, ChatChannelMember.left_at.is_(None),
    )).all()))
    _publish_settings_change(db, channel)
    audit(db, user, "移除群成员", f"从群聊 {channel.id} 移除用户 {member_user_id}", channel.project_id, "chat_channel", channel.id)
    db.commit()
    return ok(chat_channel_view(db, channel), "群成员已移除")


@router.patch("/chat/channels/{channel_id}/settings")
def update_chat_settings(channel_id: int, payload: ChatSettingsInput,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = _managed_channel(db, channel_id, user, allow_all=True)
    duplicate = db.scalar(select(ChatChannel.id).where(
        ChatChannel.project_id == channel.project_id, ChatChannel.id != channel_id,
        ChatChannel.archived_at.is_(None), func.lower(func.trim(ChatChannel.title)) == payload.title.lower(),
    ))
    if duplicate:
        raise HTTPException(409, "当前项目已存在同名群聊")
    channel.title = payload.title
    _publish_settings_change(db, channel)
    audit(db, user, "修改群名称", f"将群聊 {channel.id} 重命名为「{payload.title}」", channel.project_id, "chat_channel", channel.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "当前项目已存在同名群聊") from exc
    return ok(chat_channel_view(db, channel), "群名称已保存")


@router.get("/chat/channels/{channel_id}/files")
def list_chat_files(channel_id: int, before_id: int | None = Query(default=None, ge=1),
                    limit: int = Query(default=50, ge=1, le=100),
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    channel = chat_channel_for_user_or_403(db, channel_id, user)
    binding = db.get(ChatKnowledgeFolder, channel_id)
    if binding is None:
        return ok({"items": [], "next_cursor": None})
    readable = readable_external_ids(db, channel.project_id, user, [binding.knowledge_base_id])
    statement = select(EngineeringDocumentNode).where(
        EngineeringDocumentNode.project_id == channel.project_id,
        EngineeringDocumentNode.knowledge_base_id == binding.knowledge_base_id,
        EngineeringDocumentNode.node_type == "file",
        EngineeringDocumentNode.external_id.in_(readable),
        (EngineeringDocumentNode.folder_path == binding.folder_path)
        | EngineeringDocumentNode.folder_path.startswith(binding.folder_path + "/", autoescape=True),
    )
    if before_id is not None:
        statement = statement.where(EngineeringDocumentNode.id < before_id)
    rows = db.scalars(statement.order_by(EngineeringDocumentNode.id.desc()).limit(limit + 1)).all()
    return ok({
        "items": [{"id": row.id, "knowledge_id": row.external_id, "file_name": row.name,
                   "file_size": row.file_size, "parse_status": row.parse_status,
                   "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    })
