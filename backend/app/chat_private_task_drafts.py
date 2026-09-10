from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import chat_api as _legacy
from .agentscope_client import AgentScopeGatewayError
from .chat_agent_runtime import _task_draft_payload
from .models import AgentConversation, ChatChannel, ChatMessage, ChatTaskDraft, Project, User
from .schemas import ChatTaskDraftCreateInput, HomeTaskDraftCreateInput, TaskInput


router = _legacy.router
logger = _legacy.logger
get_db = _legacy.get_db
get_current_user = _legacy.get_current_user
ok = _legacy.ok
project_for_user_or_403 = _legacy.project_for_user_or_403
ensure_project_chat_channel = _legacy.ensure_project_chat_channel
chat_channel_for_user_or_403 = _legacy.chat_channel_for_user_or_403
chat_message_view = _legacy.chat_message_view
chat_task_draft_view = _legacy.chat_task_draft_view
_configured_task_assistant = _legacy._configured_task_assistant
_chat_message_actor_name = _legacy._chat_message_actor_name
_message_text = _legacy._message_text
_tagged_content = _legacy._tagged_content
_queue_chat_message_publish = _legacy._queue_chat_message_publish
_queue_private_task_draft_publish = _legacy._queue_private_task_draft_publish
_PRIVATE_CHAT_TASK_DRAFT_LOCKS = _legacy._PRIVATE_CHAT_TASK_DRAFT_LOCKS
_PRIVATE_CHAT_TASK_DRAFT_TASKS = _legacy._PRIVATE_CHAT_TASK_DRAFT_TASKS
_PRIVATE_TASK_AGENT_RUNS = _legacy._PRIVATE_TASK_AGENT_RUNS
_PRIVATE_TASK_DRAFT_ACTIVE_STATUSES = _legacy._PRIVATE_TASK_DRAFT_ACTIVE_STATUSES

def _private_task_context_snapshot(
    db: Session,
    channel: ChatChannel,
) -> list[dict[str, Any]]:
    rows = list(
        reversed(
            db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel_id == channel.id,
                    ChatMessage.deleted_at.is_(None),
                    ChatMessage.message_type != "task_draft",
                )
                .order_by(ChatMessage.id.desc())
                .limit(20),
            ).all(),
        ),
    )
    return [
        {
            "message_id": row.id,
            "actor": _chat_message_actor_name(db, row),
            "content": " ".join((row.content or "").split())[:800],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
        if (row.content or "").strip()
    ]


async def _home_agent_task_context_snapshot(
    *,
    session_id: str,
    agent_id: str,
    agent_name: str,
    user_name: str,
) -> list[dict[str, Any]]:
    """Read a bounded, user-visible snapshot from one homepage conversation."""
    if not session_id:
        return []
    try:
        client = _legacy._agentscope_client()
        payload = await asyncio.to_thread(
            client.list_messages,
            session_id,
            agent_id,
            limit=40,
        )
    except AgentScopeGatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"无法读取当前 Dobby 对话：{exc}",
        ) from exc
    result: list[dict[str, Any]] = []
    for row in list(payload.get("messages") or [])[-20:]:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        metadata = row.get("metadata")
        display_content = (
            metadata.get("platform_display_content")
            if role == "user" and isinstance(metadata, dict)
            else None
        )
        content = (
            display_content
            if isinstance(display_content, str)
            else _message_text(row)
        )
        if role == "user" and not isinstance(display_content, str):
            content = _tagged_content(content, "user-request") or content
        normalized = " ".join(content.split())[:800]
        if not normalized:
            continue
        result.append(
            {
                "message_id": str(row.get("id") or ""),
                "actor": user_name if role == "user" else agent_name,
                "content": normalized,
                "created_at": row.get("created_at"),
                "source": "home_agent",
            },
        )
    return result


def _private_task_draft_requirement(
    db: Session,
    draft: ChatTaskDraft,
) -> str:
    project = db.get(Project, draft.project_id)
    channel = db.get(ChatChannel, draft.channel_id)
    from_home_agent = any(
        item.get("source") in {"home_agent", "home_agent_reference"}
        for item in (draft.context_json or [])
        if isinstance(item, dict)
    )
    request_text = draft.request_text.strip()[:3000]
    prefix = (
        "请根据当前对话上下文生成一份待用户确认的结构化任务草稿。"
        "本步骤只生成草稿，不执行、不登记、不发布，也不要输出解释性长文。\n"
        f"当前项目：{project.name if project else draft.project_id}\n"
        "当前会话："
        + (
            "首页 Dobby 对话"
            if from_home_agent
            else (channel.title if channel else str(draft.channel_id))
        )
        + "\n"
        "规则：用户未明确指定其他群聊时，群聊消息默认发到当前项目群；"
        "缺少的信息保留为空，不要编造。\n"
        f"本轮请求：{request_text}\n"
        "近期对话（较早到较晚）：\n"
    )
    remaining = max(0, 3950 - len(prefix))
    selected_lines: list[str] = []
    for item in reversed(draft.context_json or []):
        if item.get("source") == "home_agent_reference":
            continue
        line = (
            f"[{item.get('message_id')}] {item.get('actor') or '项目成员'}："
            f"{item.get('content') or ''}"
        )
        if len(line) > remaining and selected_lines:
            break
        selected_lines.append(line[:remaining])
        remaining -= min(len(line), remaining)
        if remaining <= 0:
            break
    selected_lines.reverse()
    return (prefix + ("\n".join(selected_lines) or "- 暂无")).strip()[:4000]


def _private_task_draft_for_user_or_403(
    db: Session,
    draft_id: int,
    user: User,
) -> tuple[ChatTaskDraft, ChatChannel]:
    draft = db.get(ChatTaskDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="任务草稿不存在")
    if draft.requested_by_user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="只有发起本次生成的用户可以查看和处理该草稿",
        )
    channel = chat_channel_for_user_or_403(db, draft.channel_id, user)
    return draft, channel


def _set_private_task_draft_state(
    db: Session,
    draft: ChatTaskDraft,
    *,
    status_name: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
    publish_result: dict[str, Any] | None = None,
) -> None:
    draft.status = status_name
    draft.error = error
    if payload is not None:
        draft.draft_payload = payload
    if publish_result is not None:
        draft.publish_result = publish_result
    terminal = {'ready': 'completed', 'failed': 'failed', 'cancelled': 'cancelled'}.get(status_name)
    runtime = _PRIVATE_TASK_AGENT_RUNS.get(draft.id)
    if terminal and runtime:
        run = db.scalar(select(AgentConversation).where(AgentConversation.agentscope_session_id == runtime[1]))
        if run is not None:
            run.status = terminal
    db.flush()
    _queue_private_task_draft_publish(db, draft)


def _finish_private_task_draft(
    draft_id: int,
    *,
    status_name: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with _legacy.SessionLocal() as db:
        draft = db.get(ChatTaskDraft, draft_id)
        if draft is None:
            return
        if draft.status != "generating" and status_name in {
            "ready",
            "failed",
            "cancelled",
        }:
            return
        _set_private_task_draft_state(
            db,
            draft,
            status_name=status_name,
            payload=payload,
            error=error,
        )
        db.commit()


async def _generate_private_task_draft(draft_id: int) -> None:
    creation_pending = None
    session_id = None
    try:
        with _legacy.SessionLocal() as db:
            draft = db.get(ChatTaskDraft, draft_id)
            if draft is None or draft.status != "generating":
                return
            user = db.get(User, draft.requested_by_user_id)
            if user is None:
                return
            context_reference = next(
                (
                    item
                    for item in (draft.context_json or [])
                    if isinstance(item, dict)
                    and item.get("source") == "home_agent_reference"
                ),
                None,
            )
            if context_reference is not None:
                conversation_id = context_reference.get("conversation_id")
                conversation = (
                    db.get(AgentConversation, int(conversation_id))
                    if conversation_id
                    else None
                )
                if (
                    conversation is not None
                    and conversation.user_id == user.id
                    and conversation.project_id == draft.project_id
                    and conversation.conversation_type == "general"
                    and conversation.agentscope_session_id
                ):
                    snapshot = await _home_agent_task_context_snapshot(
                        session_id=conversation.agentscope_session_id,
                        agent_id=conversation.agent_id,
                        agent_name=conversation.agent_name,
                        user_name=user.real_name,
                    )
                    from .business_learning_policy import conversation_learning_policy, merge_learning_policies
                    actual_policy = conversation_learning_policy(conversation)
                    previous_policy = context_reference.get('learning_policy')
                    context_reference = {**context_reference,'learning_policy':merge_learning_policies(previous_policy,actual_policy)
                        if previous_policy is not None else actual_policy}
                    draft.context_json = [context_reference, *snapshot]
                    db.commit()
                    db.refresh(draft)
            requirement = _private_task_draft_requirement(db, draft)
            project = db.get(Project, draft.project_id)
            channel = db.get(ChatChannel, draft.channel_id)
            if project is None or channel is None:
                raise RuntimeError("任务草稿对应的项目或会话不存在")
            selected_agent = _configured_task_assistant()
            agent_id = str(selected_agent["id"])
            client = _legacy._agentscope_client()
            from .task_session_binding import create_bound_task_session
            creation_pending = asyncio.create_task(asyncio.to_thread(
                create_bound_task_session, client, agent=selected_agent,
                user_id=user.id, project_id=project.id, generation_id=draft.generation_id,
                source_channel_id=channel.id,
                session_factory=_legacy.SessionLocal,
            ))
            session_id = await asyncio.shield(creation_pending)
            _PRIVATE_TASK_AGENT_RUNS[draft_id] = (agent_id, session_id)
            draft.context_json = [
                *(draft.context_json or []),
                {
                    "source": "task_assistant_runtime",
                    "agent_id": agent_id,
                    "session_id": session_id,
                },
            ]
            db.commit()
            reply = await asyncio.to_thread(
                client.chat,
                agent_id=agent_id,
                session_id=session_id,
                content=(
                    requirement
                    + "\n必须调用 generate_task_flow，参数 generation_id="
                    + draft.generation_id
                    + "；只返回工具生成的草稿，不得发布任务。"
                ),
                sender_name=user.real_name,
                metadata={
                    "source": "private_task_draft",
                    "trigger": "explicit_agent_mention",
                    "platform_user_id": user.id,
                    "project_id": project.id,
                    "chat_channel_id": channel.id,
                    "task_draft_id": draft.id,
                    "generation_id": draft.generation_id,
                },
                user_message_id=uuid4().hex,
            )
            generated = _legacy._task_flow_from_agent_reply(reply)
            payload = _task_draft_payload(generated, draft.request_text)
            payload.update(
                {
                    "generated_by": agent_id,
                    "agentscope_session_id": session_id,
                    "agentscope_message_id": reply.message_id,
                },
            )

        _finish_private_task_draft(
            draft_id,
            status_name="ready",
            payload=payload,
        )
    except asyncio.CancelledError:
        if creation_pending is not None:
            try:
                session_id = await creation_pending
                _PRIVATE_TASK_AGENT_RUNS[draft_id] = (agent_id, session_id)
                await asyncio.to_thread(client.interrupt, agent_id=agent_id, session_id=session_id)
            except Exception:
                logger.exception('停止任务草稿会话失败：draft_id=%s', draft_id)
        _finish_private_task_draft(
            draft_id,
            status_name="cancelled",
        )
        raise
    except Exception as exc:
        detail = (
            str(exc.detail)
            if isinstance(exc, HTTPException)
            else str(exc)
        ).strip()
        detail = detail[:1200] or type(exc).__name__
        logger.exception("私有任务草稿生成失败：draft_id=%s", draft_id)
        _finish_private_task_draft(
            draft_id,
            status_name="failed",
            error=detail,
        )
    finally:
        _PRIVATE_TASK_AGENT_RUNS.pop(draft_id, None)


def _track_private_task_draft(
    task: asyncio.Task[Any],
    draft_id: int,
) -> None:
    _PRIVATE_CHAT_TASK_DRAFT_TASKS[draft_id] = task

    def discard(completed: asyncio.Task[Any]) -> None:
        if _PRIVATE_CHAT_TASK_DRAFT_TASKS.get(draft_id) is completed:
            _PRIVATE_CHAT_TASK_DRAFT_TASKS.pop(draft_id, None)
        if completed.cancelled():
            return
        try:
            error = completed.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.exception(
                "私有任务草稿后台任务异常",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(discard)


def _start_private_task_draft_generation(draft_id: int) -> None:
    task = asyncio.create_task(
        _generate_private_task_draft(draft_id),
        name=f"private-chat-task-draft-{draft_id}",
    )
    _track_private_task_draft(task, draft_id)


@router.post("/chat/channels/{channel_id}/task-drafts")
async def create_private_chat_task_draft(
    channel_id: int,
    payload: ChatTaskDraftCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await asyncio.to_thread(_configured_task_assistant)
    channel = chat_channel_for_user_or_403(db, channel_id, user)
    request_text = payload.requirement.replace("@任务助手", "", 1).strip()
    if len(request_text) < 4:
        raise HTTPException(status_code=422, detail="请说明需要布置的任务")

    existing = db.scalar(
        select(ChatTaskDraft).where(
            ChatTaskDraft.requested_by_user_id == user.id,
            ChatTaskDraft.client_request_id == payload.client_request_id,
        ),
    )
    if existing is not None:
        return ok(chat_task_draft_view(db, existing), "任务草稿已创建")

    active = db.scalar(
        select(ChatTaskDraft)
        .where(
            ChatTaskDraft.project_id == channel.project_id,
            ChatTaskDraft.requested_by_user_id == user.id,
            ChatTaskDraft.status.in_(_PRIVATE_TASK_DRAFT_ACTIVE_STATUSES),
        )
        .order_by(ChatTaskDraft.updated_at.desc(), ChatTaskDraft.id.desc())
        .limit(1),
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="已有一份未处理的任务草稿，请先继续或关闭该草稿",
        )

    draft = ChatTaskDraft(
        project_id=channel.project_id,
        channel_id=channel.id,
        requested_by_user_id=user.id,
        client_request_id=payload.client_request_id,
        generation_id=f"private-chat-task-{uuid4().hex}",
        request_text=request_text,
        context_json=_private_task_context_snapshot(db, channel),
        status="generating",
        draft_payload={},
        publish_result={},
        published_task_ids=[],
    )
    db.add(draft)
    db.flush()
    _queue_private_task_draft_publish(db, draft)
    db.commit()
    db.refresh(draft)
    _legacy._start_private_task_draft_generation(draft.id)
    return ok(chat_task_draft_view(db, draft), "任务助手正在生成待确认草稿")


@router.post("/projects/{project_id}/agent-task-drafts")
async def create_home_agent_task_draft(
    project_id: int,
    payload: HomeTaskDraftCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a private formal-task draft from a homepage Dobby context."""
    await asyncio.to_thread(_configured_task_assistant)
    project_for_user_or_403(db, project_id, user)
    conversation: AgentConversation | None = None
    if payload.conversation_id is not None:
        conversation = db.get(AgentConversation, payload.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Dobby 对话不存在")
        if conversation.user_id != user.id or conversation.project_id != project_id:
            raise HTTPException(status_code=403, detail="无权使用该 Dobby 对话")
        if conversation.conversation_type != "general":
            raise HTTPException(status_code=409, detail="仅首页 Dobby 对话支持此入口")
        if not conversation.agentscope_session_id:
            raise HTTPException(status_code=409, detail="Dobby 对话尚未完成初始化")

    request_text = payload.requirement.replace("@任务助手", "", 1).strip()
    if len(request_text) < 4:
        raise HTTPException(status_code=422, detail="请说明需要布置的任务")

    existing = db.scalar(
        select(ChatTaskDraft).where(
            ChatTaskDraft.requested_by_user_id == user.id,
            ChatTaskDraft.client_request_id == payload.client_request_id,
        ),
    )
    if existing is not None:
        return ok(chat_task_draft_view(db, existing), "任务草稿已创建")

    active = db.scalar(
        select(ChatTaskDraft)
        .where(
            ChatTaskDraft.project_id == project_id,
            ChatTaskDraft.requested_by_user_id == user.id,
            ChatTaskDraft.status.in_(_PRIVATE_TASK_DRAFT_ACTIVE_STATUSES),
        )
        .order_by(ChatTaskDraft.updated_at.desc(), ChatTaskDraft.id.desc())
        .limit(1),
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="已有一份未处理的任务草稿，请先继续或关闭该草稿",
        )

    channel = ensure_project_chat_channel(db, project_id, user)
    from .business_learning_policy import conversation_learning_policy
    context_snapshot = [
        {
            "source": "home_agent_reference",
            "conversation_id": conversation.id if conversation is not None else None,
            "learning_policy": conversation_learning_policy(conversation) if conversation is not None else
                {'allow_learning':True,'source_run_refs':[]},
        },
    ]
    draft = ChatTaskDraft(
        project_id=project_id,
        channel_id=channel.id,
        requested_by_user_id=user.id,
        client_request_id=payload.client_request_id,
        generation_id=f"home-agent-task-{uuid4().hex}",
        request_text=request_text,
        context_json=context_snapshot,
        status="generating",
        draft_payload={},
        publish_result={},
        published_task_ids=[],
    )
    db.add(draft)
    db.flush()
    _queue_private_task_draft_publish(db, draft)
    db.commit()
    db.refresh(draft)
    _legacy._start_private_task_draft_generation(draft.id)
    return ok(chat_task_draft_view(db, draft), "任务助手正在生成待确认草稿")


@router.get("/projects/{project_id}/chat/task-drafts")
def list_private_chat_task_drafts(
    project_id: int,
    active_only: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    statement = select(ChatTaskDraft).where(
        ChatTaskDraft.project_id == project_id,
        ChatTaskDraft.requested_by_user_id == user.id,
    )
    if active_only:
        statement = statement.where(
            ChatTaskDraft.status.in_(_PRIVATE_TASK_DRAFT_ACTIVE_STATUSES),
        )
    rows = db.scalars(
        statement.order_by(
            ChatTaskDraft.updated_at.desc(),
            ChatTaskDraft.id.desc(),
        ).limit(20),
    ).all()
    return ok([chat_task_draft_view(db, row) for row in rows])


@router.get("/chat/task-drafts/{draft_id}")
def get_private_chat_task_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft, _ = _private_task_draft_for_user_or_403(db, draft_id, user)
    return ok(chat_task_draft_view(db, draft))


@router.post("/chat/task-drafts/{draft_id}/publish")
def publish_private_chat_task_draft(
    draft_id: int,
    payload: TaskInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    with _PRIVATE_CHAT_TASK_DRAFT_LOCKS[draft_id]:
        draft, channel = _private_task_draft_for_user_or_403(
            db,
            draft_id,
            user,
        )
        if draft.status == "published":
            message = (
                db.get(ChatMessage, draft.published_message_id)
                if draft.published_message_id
                else None
            )
            return ok(
                {
                    "draft": chat_task_draft_view(db, draft),
                    "message": chat_message_view(db, message) if message else None,
                    "result": draft.publish_result or {},
                },
                "任务已经发布",
            )
        if draft.status != "ready":
            raise HTTPException(
                status_code=409,
                detail="任务草稿尚未生成完成或已被处理",
            )

        _set_private_task_draft_state(
            db,
            draft,
            status_name="publishing",
            payload=payload.model_dump(mode="json"),
        )
        db.commit()
        try:
            # Imported lazily to avoid the api.py -> chat_api.py cycle.
            from .api import create_task

            from .business_learning_sources import task_learning_origin
            reference = next((item for item in draft.context_json or [] if item.get('source')=='home_agent_reference'),None)
            # This object was persisted by the authenticated homepage entry, not provided by the publish payload.
            source_policy = (reference.get('learning_policy') or {'allow_learning':False,'source_run_refs':[]}) if reference else None
            with task_learning_origin(db, draft.channel_id, draft.generation_id, source_policy):
                created = create_task(draft.project_id, payload, db, user)
        except Exception:
            db.rollback()
            draft = db.get(ChatTaskDraft, draft_id)
            if draft is not None and draft.status == "publishing":
                _set_private_task_draft_state(
                    db,
                    draft,
                    status_name="ready",
                    payload=draft.draft_payload or {},
                    error="任务发布失败，请检查内容后重试",
                )
                db.commit()
            raise

        db.expire_all()
        draft = db.get(ChatTaskDraft, draft_id)
        channel = db.get(ChatChannel, draft.channel_id) if draft else None
        if draft is None or channel is None:
            raise HTTPException(status_code=409, detail="任务已创建，但草稿状态更新失败")
        result_data = created.get("data") or {}
        task_id = result_data.get("id") if isinstance(result_data, dict) else None
        linked_task_ids = [str(task_id)] if task_id else []
        event_message = ChatMessage(
            channel_id=channel.id,
            sender_type="system",
            message_type="task_event",
            content=f"{user.real_name} 已布置任务",
            task_ids=linked_task_ids,
            metadata_json={
                "event_type": "task_published",
                "task_title": payload.title,
                "requested_by_user_id": user.id,
                "requested_by_name": user.real_name,
                "run_mode": payload.run_mode,
                "action_type": payload.action_type,
                "publish_result": result_data,
            },
        )
        db.add(event_message)
        db.flush()
        channel.last_message_at = datetime.now(UTC)
        channel.summary = f"新任务：{payload.title}"[:160]
        _queue_chat_message_publish(db, channel, event_message)

        draft.published_task_ids = linked_task_ids
        draft.published_message_id = event_message.id
        _set_private_task_draft_state(
            db,
            draft,
            status_name="published",
            payload=payload.model_dump(mode="json"),
            publish_result=result_data,
        )
        db.commit()
        return ok(
            {
                "draft": chat_task_draft_view(db, draft),
                "message": chat_message_view(db, event_message),
                "result": result_data,
            },
            str(created.get("message") or "任务已发布"),
        )


@router.post("/chat/task-drafts/{draft_id}/dismiss")
def dismiss_private_chat_task_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft, _ = _private_task_draft_for_user_or_403(db, draft_id, user)
    if draft.status == "published":
        raise HTTPException(status_code=409, detail="已发布的任务草稿不能关闭")
    if draft.status == "generating":
        raise HTTPException(status_code=409, detail="请先停止任务助手当前的任务分析")
    if draft.status != "dismissed":
        _set_private_task_draft_state(
            db,
            draft,
            status_name="dismissed",
        )
        db.commit()
    return ok(chat_task_draft_view(db, draft), "任务草稿已关闭")


@router.post("/chat/task-drafts/{draft_id}/retry")
async def retry_private_chat_task_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await asyncio.to_thread(_configured_task_assistant)
    draft, _ = _private_task_draft_for_user_or_403(db, draft_id, user)
    running = _PRIVATE_CHAT_TASK_DRAFT_TASKS.get(draft_id)
    if running is not None and not running.done():
        raise HTTPException(status_code=409, detail="任务助手正在分析任务需求")
    if draft.status in {"published", "publishing"}:
        raise HTTPException(status_code=409, detail="任务已经发布或正在发布")
    draft.generation_id = f"private-chat-task-{uuid4().hex}"
    draft.draft_payload = {}
    draft.publish_result = {}
    _set_private_task_draft_state(
        db,
        draft,
        status_name="generating",
    )
    db.commit()
    db.refresh(draft)
    _legacy._start_private_task_draft_generation(draft.id)
    return ok(chat_task_draft_view(db, draft), "任务助手正在重新生成草稿")


@router.post("/chat/task-drafts/{draft_id}/stop")
async def stop_private_chat_task_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft, _ = _private_task_draft_for_user_or_403(db, draft_id, user)
    if draft.status != "generating":
        return ok(chat_task_draft_view(db, draft), "任务助手当前没有正在进行的任务分析")
    task = _PRIVATE_CHAT_TASK_DRAFT_TASKS.get(draft_id)
    if task is not None and not task.done():
        active_run = _PRIVATE_TASK_AGENT_RUNS.get(draft_id)
        if active_run is not None:
            try:
                await asyncio.to_thread(
                    _legacy._agentscope_client().interrupt,
                    agent_id=active_run[0],
                    session_id=active_run[1],
                )
            except AgentScopeGatewayError as exc:
                logger.warning("停止任务助手 AgentScope 运行失败：%s", exc)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        _set_private_task_draft_state(
            db,
            draft,
            status_name="cancelled",
        )
        db.commit()
    db.expire_all()
    refreshed = db.get(ChatTaskDraft, draft_id)
    return ok(
        chat_task_draft_view(db, refreshed or draft),
        "任务助手已停止本次草稿生成",
    )
