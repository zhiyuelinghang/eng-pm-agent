"""任务引擎自动化动作执行器。

任务引擎负责计划、节点顺序、任务实例和审计；本模块只负责解释宿主 ``scope``
中的节点动作并调用平台能力。动作以任务 id 与节点序号作为幂等键，因此宿主重启或
重复扫描不会重复发消息。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from task_engine.domain.models import StepState, TaskInstance
from task_engine.engine import TaskEngine

from .models import (
    ChatChannel,
    ChatChannelMember,
    ChatMessage,
    ChatMessageMention,
    ChatMessageMentionReceipt,
    ChatRealtimeOutbox,
    Project,
    ProjectMember,
    User,
)
from .task_engine_gateway import TASK_MESSAGE_AGENT_ID, TASK_MESSAGE_AGENT_NAME


@dataclass(slots=True)
class ActionExecutionResult:
    task_id: str
    action_type: str
    ok: bool
    detail: str
    message_id: int | None = None


def _realtime_channel(channel: ChatChannel) -> str:
    return f"chat:project_{channel.project_id}:channel_{channel.id}"


def _realtime_user_channel(project_id: int, user_id: int) -> str:
    return f"chat:project_{project_id}:user_{user_id}"


def _ensure_channel_member(
    db: Session,
    channel: ChatChannel,
    user_id: int,
    *,
    role: str = "member",
) -> ChatChannelMember:
    membership = db.scalar(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel.id,
            ChatChannelMember.user_id == user_id,
        ),
    )
    if membership is None:
        membership = ChatChannelMember(
            channel_id=channel.id,
            user_id=user_id,
            member_role=role,
        )
        db.add(membership)
    else:
        membership.left_at = None
        if role == "owner":
            membership.member_role = "owner"
    return membership


def _project_channel(
    db: Session,
    project_id: int,
    channel_id: int | None,
    creator_user_id: int | None,
) -> ChatChannel:
    if channel_id:
        channel = db.get(ChatChannel, channel_id)
        if (
            channel is None
            or channel.project_id != project_id
            or channel.archived_at is not None
        ):
            raise ValueError("自动化任务的目标群聊不存在或已归档")
        return channel

    channel = db.scalar(
        select(ChatChannel).where(
            ChatChannel.project_id == project_id,
            ChatChannel.channel_type == "project",
            ChatChannel.archived_at.is_(None),
        ),
    )
    if channel is not None:
        return channel

    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("自动化任务所属项目不存在")
    owner_id = creator_user_id or db.scalar(
        select(ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.id.asc())
        .limit(1),
    )
    if owner_id is None:
        raise ValueError("项目没有成员，无法创建项目群聊")
    channel = ChatChannel(
        project_id=project_id,
        created_by_user_id=owner_id,
        title=f"{project.name}项目群",
        summary="项目成员共享的实时协同群聊",
        channel_type="project",
    )
    db.add(channel)
    db.flush()
    return channel


def _sync_project_channel_members(
    db: Session,
    channel: ChatChannel,
    *,
    additional_user_id: int | None = None,
) -> None:
    if channel.channel_type != "project":
        return
    user_ids = set(
        db.scalars(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == channel.project_id,
            ),
        ).all(),
    )
    if channel.created_by_user_id:
        user_ids.add(channel.created_by_user_id)
    if additional_user_id:
        # 管理员可访问项目但不一定存在于 ProjectMember，自动动作仍需能 @ 发起人。
        user_ids.add(additional_user_id)
    for user_id in user_ids:
        _ensure_channel_member(
            db,
            channel,
            user_id,
            role="owner" if user_id == channel.created_by_user_id else "member",
        )
    db.flush()


def _active_channel_users(db: Session, channel: ChatChannel) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
            .where(
                ChatChannelMember.channel_id == channel.id,
                ChatChannelMember.left_at.is_(None),
            )
            .order_by(User.real_name.asc(), User.id.asc()),
        ).all(),
    )


def _selected_users(
    db: Session,
    channel: ChatChannel,
    user_ids: list[int],
) -> list[User]:
    requested = list(dict.fromkeys(int(item) for item in user_ids))
    active = {user.id: user for user in _active_channel_users(db, channel)}
    if any(user_id not in active for user_id in requested):
        raise ValueError("自动化任务指定的接收人不在目标群聊中")
    return [active[user_id] for user_id in requested]


def _message_view(
    row: ChatMessage,
    mentions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": row.id,
        "channel_id": row.channel_id,
        "sender_type": row.sender_type,
        "sender_user_id": row.sender_user_id,
        "sender_agent_id": row.sender_agent_id,
        "sender": None,
        "message_type": row.message_type,
        "content": row.content,
        "client_message_id": row.client_message_id,
        "reply_to_id": row.reply_to_id,
        "task_ids": row.task_ids or [],
        "metadata": row.metadata_json or {},
        "mentions": mentions,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "edited_at": row.edited_at.isoformat() if row.edited_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _deliver_project_chat_message(
    db: Session,
    task: TaskInstance,
    action: dict[str, Any],
    step_seq: int,
) -> ChatMessage:
    project_id = int(task.scope.get("project_id") or 0)
    if not project_id:
        raise ValueError("自动化任务缺少项目上下文")
    client_message_id = f"automation:{task.id}:{step_seq}"[:64]
    existing = db.scalar(
        select(ChatMessage).where(
            ChatMessage.client_message_id == client_message_id,
        ),
    )
    if existing is not None:
        return existing

    channel = _project_channel(
        db,
        project_id,
        int(action["channel_id"]) if action.get("channel_id") else None,
        int(action["created_by_user_id"])
        if action.get("created_by_user_id")
        else None,
    )
    _sync_project_channel_members(
        db,
        channel,
        additional_user_id=(
            int(action["created_by_user_id"])
            if action.get("created_by_user_id")
            else None
        ),
    )

    mention_mode = str(action.get("mention_mode") or "none")
    if mention_mode == "all":
        mentioned_users = _active_channel_users(db, channel)
    elif mention_mode == "users":
        mentioned_users = _selected_users(
            db,
            channel,
            list(action.get("mentioned_user_ids") or []),
        )
        if not mentioned_users:
            raise ValueError("指定成员消息至少需要一位接收人")
    elif mention_mode == "none":
        mentioned_users = []
    else:
        raise ValueError(f"不支持的群聊提及方式：{mention_mode}")

    content = str(action.get("content") or "").strip()
    if not content:
        raise ValueError("群聊消息内容不能为空")
    if mention_mode == "all" and "@全体成员" not in content:
        content = f"@全体成员 {content}"
    if mention_mode == "users":
        prefix = " ".join(f"@{user.real_name}" for user in mentioned_users)
        if not all(f"@{user.real_name}" in content for user in mentioned_users):
            content = f"{prefix} {content}"

    row = ChatMessage(
        channel_id=channel.id,
        sender_type="agent",
        sender_agent_id=TASK_MESSAGE_AGENT_ID,
        message_type="task_event",
        content=content,
        client_message_id=client_message_id,
        task_ids=[task.id],
        metadata_json={
            "mention_all": mention_mode == "all",
            "automation": True,
            "agent_name": TASK_MESSAGE_AGENT_NAME,
            "task_engine_task_id": task.id,
            "task_engine_flow_id": task.flow_id,
            "task_engine_step_seq": step_seq,
        },
    )
    db.add(row)
    db.flush()

    mention_views: list[dict[str, Any]] = []
    if mention_mode == "all":
        mention_views.append(
            {
                "target_type": "all",
                "target_user_id": None,
                "target_agent_id": None,
                "display_name": "全体成员",
            },
        )
    else:
        for mentioned_user in mentioned_users:
            db.add(
                ChatMessageMention(
                    message_id=row.id,
                    target_type="user",
                    target_user_id=mentioned_user.id,
                    display_name=mentioned_user.real_name,
                ),
            )
            mention_views.append(
                {
                    "target_type": "user",
                    "target_user_id": mentioned_user.id,
                    "target_agent_id": None,
                    "display_name": mentioned_user.real_name,
                },
            )

    for mentioned_user in mentioned_users:
        db.add(
            ChatMessageMentionReceipt(
                message_id=row.id,
                user_id=mentioned_user.id,
            ),
        )
    db.flush()

    channel.last_message_at = datetime.now(UTC)
    channel.summary = content[:160]
    message_data = _message_view(row, mention_views)
    db.add(
        ChatRealtimeOutbox(
            method="publish",
            payload={
                "channel": _realtime_channel(channel),
                "data": {
                    "type": "chat.message.created",
                    "project_id": project_id,
                    "channel_id": channel.id,
                    "message": message_data,
                },
            },
            partition=0,
        ),
    )
    for mentioned_user in mentioned_users:
        db.add(
            ChatRealtimeOutbox(
                method="publish",
                payload={
                    "channel": _realtime_user_channel(
                        project_id,
                        mentioned_user.id,
                    ),
                    "data": {
                        "type": "chat.mention.created",
                        "project_id": project_id,
                        "channel_id": channel.id,
                        "message": message_data,
                    },
                },
                partition=0,
            ),
        )
    db.commit()
    db.refresh(row)
    return row


def current_task_action(
    task: TaskInstance,
) -> tuple[int, dict[str, Any]] | None:
    """返回当前节点的宿主动作；兼容早期整条自动化任务结构。"""
    current = task.current_step
    if current is None:
        return None
    step_actions = (task.scope or {}).get("step_actions") or {}
    if isinstance(step_actions, dict):
        action = step_actions.get(str(current.seq))
        if isinstance(action, dict) and action.get("type"):
            return current.seq, action

    legacy_action = (task.scope or {}).get("action")
    if (
        task.scope.get("execution_kind") == "automation"
        and isinstance(legacy_action, dict)
        and legacy_action.get("type")
    ):
        return current.seq, legacy_action
    return None


def execute_automation_task(
    db: Session,
    task_engine: TaskEngine,
    task: TaskInstance,
) -> ActionExecutionResult:
    """幂等执行当前自动节点，并把执行结果写回引擎状态机。"""
    current_action = current_task_action(task)
    if current_action is None:
        return ActionExecutionResult(task.id, "", False, "当前不是自动节点")
    step_seq, action = current_action
    action_type = str(action.get("type") or "")

    try:
        if action_type == "project_chat_message":
            message = _deliver_project_chat_message(db, task, action, step_seq)
            detail = f"群聊消息 {message.id} 已发送"
        else:
            raise ValueError(f"不支持的自动化动作：{action_type}")

        refreshed = task_engine.get_task(task.id) or task
        current = refreshed.current_step
        if current and current.state is StepState.BLOCKED:
            refreshed = task_engine.unblock_step(
                refreshed.id,
                current.seq,
                actor="system",
                note="自动化动作重试成功",
            )
            current = refreshed.current_step
        if current and current.state is StepState.ACTIVE:
            refreshed = task_engine.complete_step(
                refreshed.id,
                current.seq,
                actor="system",
                comment=detail,
            )
        if str(refreshed.state) == "review" and refreshed.confirmer is None:
            task_engine.accept(
                refreshed.id,
                actor="system",
                note="自动化动作已执行",
            )
        return ActionExecutionResult(
            task.id,
            action_type,
            True,
            detail,
            message.id if action_type == "project_chat_message" else None,
        )
    except Exception as exc:
        db.rollback()
        refreshed = task_engine.get_task(task.id) or task
        current = refreshed.current_step
        if current and current.state is StepState.ACTIVE:
            task_engine.block_step(
                refreshed.id,
                current.seq,
                actor="system",
                reason=str(exc)[:300],
            )
        return ActionExecutionResult(
            task.id,
            action_type,
            False,
            str(exc)[:300],
        )


def execute_pending_automation_tasks(
    db: Session,
    task_engine: TaskEngine,
    *,
    limit: int = 100,
) -> list[ActionExecutionResult]:
    tasks = task_engine.list_tasks(open_only=True, limit=limit)
    results: list[ActionExecutionResult] = []
    for task in tasks:
        results.extend(execute_ready_automation_chain(db, task_engine, task))
    return results


def execute_ready_automation_chain(
    db: Session,
    task_engine: TaskEngine,
    task: TaskInstance,
    *,
    max_steps: int = 100,
) -> list[ActionExecutionResult]:
    """连续执行当前已就绪的自动节点，遇到人工节点或失败即停止。"""
    results: list[ActionExecutionResult] = []
    current = task
    for _ in range(max_steps):
        if current_task_action(current) is None:
            break
        result = execute_automation_task(db, task_engine, current)
        results.append(result)
        if not result.ok:
            break
        refreshed = task_engine.get_task(current.id)
        if refreshed is None:
            break
        current = refreshed
    return results
