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
from .agent_api_support import _agent_reply_extra_data
from .chat_agent_sessions import create_group_agent_session
from .models import ChatAgentThread, ChatChannel, ChatMessage, ChatMessageMention, Project, User
from .runtime_observability import RuntimeStageTracker
from .schemas import TaskInput
from .task_draft_adapter import normalize_task_flow


router = _legacy.router
logger = _legacy.logger
get_db = _legacy.get_db
get_current_user = _legacy.get_current_user
ok = _legacy.ok
chat_channel_for_user_or_403 = _legacy.chat_channel_for_user_or_403
chat_message_view = _legacy.chat_message_view
_configured_task_assistant = _legacy._configured_task_assistant
_task_assistant_platform_context = _legacy._task_assistant_platform_context
_chat_agent_platform_context = _legacy._chat_agent_platform_context
_chat_message_actor_name = _legacy._chat_message_actor_name
_group_chat_agent_content = _legacy._group_chat_agent_content
_public_task_assistant_catalog_item = _legacy._public_task_assistant_catalog_item
_queue_chat_message_publish = _legacy._queue_chat_message_publish
_CHAT_AGENT_LOCKS = _legacy._CHAT_AGENT_LOCKS
_CHAT_AGENT_TASKS = _legacy._CHAT_AGENT_TASKS
_CHAT_TASK_DRAFT_PUBLISH_LOCKS = _legacy._CHAT_TASK_DRAFT_PUBLISH_LOCKS
_CHAT_TASK_DRAFT_TASKS = _legacy._CHAT_TASK_DRAFT_TASKS
PROJECT_CHAT_TASK_ASSISTANT_ID = _legacy.PROJECT_CHAT_TASK_ASSISTANT_ID


def _agent_run_for_source(
    db: Session,
    source_message_id: int,
    agent_id: str,
) -> ChatMessage | None:
    return db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.reply_to_id == source_message_id,
            ChatMessage.message_type == "agent",
            ChatMessage.sender_agent_id == agent_id,
            ChatMessage.deleted_at.is_(None),
        )
        .order_by(ChatMessage.id.desc())
        .limit(1),
    )


def _create_agent_run_placeholder(
    db: Session,
    channel: ChatChannel,
    source: ChatMessage,
    agent: dict[str, Any],
) -> ChatMessage:
    """Create the durable queued state before background execution starts."""

    now = datetime.now(UTC).isoformat()
    agent_id = str(agent["id"])
    agent_name = str(agent.get("name") or agent_id)
    row = ChatMessage(
        channel_id=channel.id,
        sender_type="agent",
        sender_agent_id=agent_id,
        message_type="agent",
        content=f"@{agent_name} 已接收请求，正在排队处理…",
        reply_to_id=source.id,
        metadata_json={
            "agent_name": agent_name,
            "source_message_id": source.id,
            "requester_user_id": source.sender_user_id,
            "runtime_status": "queued",
            "status": "running",
            "agentscope_messages": [
                {
                    "id": f"group-agent-run-{source.id}-{agent_id}",
                    "name": agent_name,
                    "role": "assistant",
                    "content": [],
                    "created_at": now,
                },
            ],
            "runtime_trace": {
                "model_names": [],
                "tasks_context": None,
                "team_update_count": 0,
                "collaborations": [],
                "subagent_hitl": [],
                "stages": [
                    {
                        "stage_id": "accepted",
                        "label": "请求已受理",
                        "status": "completed",
                        "started_at": now,
                        "finished_at": now,
                        "duration_ms": 0,
                    },
                ],
                "turn_started_at": now,
                "turn_finished_at": None,
            },
        },
    )
    db.add(row)
    db.flush()
    return row


def _update_agent_run_progress(
    db: Session,
    channel: ChatChannel,
    row: ChatMessage,
    *,
    content: str,
    status_name: str,
    stages: list[dict[str, object]],
    finished: bool = False,
) -> None:
    now = datetime.now(UTC).isoformat()
    metadata = dict(row.metadata_json or {})
    runtime_trace = dict(metadata.get("runtime_trace") or {})
    runtime_trace.update(
        {
            "stages": stages,
            "turn_started_at": runtime_trace.get("turn_started_at") or now,
            "turn_finished_at": now if finished else None,
        },
    )
    row.content = content
    row.metadata_json = {
        **metadata,
        "runtime_status": status_name,
        "status": status_name,
        "runtime_trace": runtime_trace,
    }
    row.edited_at = datetime.now(UTC)
    channel.last_message_at = datetime.now(UTC)
    channel.summary = content[:160]
    _queue_chat_message_publish(db, channel, row)
    db.flush()

def _task_assistant_ids(agents: list[dict[str, Any]]) -> list[str]:
    """Return the dedicated task assistant ids from a validated mention list."""

    return [
        str(agent["id"])
        for agent in agents
        if agent.get("id")
        and agent.get("role") == "system_internal"
        and agent.get("name") == "任务助手"
    ]


def _task_draft_for_source(
    db: Session,
    source_message_id: int,
    agent_id: str | None = None,
) -> ChatMessage | None:
    statement = select(ChatMessage).where(
        ChatMessage.reply_to_id == source_message_id,
        ChatMessage.message_type == "task_draft",
        ChatMessage.deleted_at.is_(None),
    )
    if agent_id:
        statement = statement.where(ChatMessage.sender_agent_id == agent_id)
    return db.scalar(statement.order_by(ChatMessage.id.desc()).limit(1))


def _create_task_draft_placeholder(
    db: Session,
    channel: ChatChannel,
    source: ChatMessage,
    agent: dict[str, Any],
) -> ChatMessage:
    agent_id = str(agent["id"])
    draft = ChatMessage(
        channel_id=channel.id,
        sender_type="agent",
        sender_agent_id=agent_id,
        message_type="task_draft",
        content="正在根据当前会话生成任务草稿…",
        reply_to_id=source.id,
        metadata_json={
            "agent_name": "任务助手",
            "source_message_id": source.id,
            "requested_by_user_id": source.sender_user_id,
            "draft_status": "generating",
            "runtime_status": "running",
            "requires_confirmation": True,
            "generation_id": f"chat-task-draft-{source.id}",
        },
    )
    db.add(draft)
    db.flush()
    return draft


def _set_task_draft_state(
    db: Session,
    draft: ChatMessage,
    channel: ChatChannel,
    *,
    status_name: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> ChatMessage:
    runtime_status = {
        "generating": "running",
        "ready": "awaiting_permission",
        "publishing": "running",
        "published": "completed",
        "dismissed": "interrupted",
        "cancelled": "interrupted",
        "failed": "error",
    }.get(status_name, status_name)
    draft.content = content
    draft.metadata_json = {
        **(draft.metadata_json or {}),
        **(metadata or {}),
        "draft_status": status_name,
        "runtime_status": runtime_status,
        "requires_confirmation": status_name == "ready",
        "failed": status_name == "failed",
    }
    draft.edited_at = datetime.now(UTC)
    db.flush()
    channel.last_message_at = datetime.now(UTC)
    channel.summary = content[:160]
    _queue_chat_message_publish(db, channel, draft)
    return draft


def _task_assistant_requirement(
    db: Session,
    project: Project,
    channel: ChatChannel,
    source: ChatMessage,
    agent_name: str,
) -> str:
    recent_rows = list(
        reversed(
            db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel_id == channel.id,
                    ChatMessage.id <= source.id,
                    ChatMessage.deleted_at.is_(None),
                    ChatMessage.message_type != "task_draft",
                )
                .order_by(ChatMessage.id.desc())
                .limit(20),
            ).all(),
        ),
    )
    history_lines: list[str] = []
    history_size = 0
    for row in recent_rows:
        content = " ".join((row.content or "").split())[:800]
        line = f"[{row.id}] {_chat_message_actor_name(db, row)}：{content}"
        if history_size + len(line) > 8000:
            break
        history_lines.append(line)
        history_size += len(line)

    marked_request = source.content.strip()
    mention_token = f"@{agent_name}"
    if mention_token in marked_request:
        marked_request = marked_request.replace(mention_token, "", 1).strip()
    return (
        "请根据下面的当前群聊上下文生成一份待用户确认的任务草稿。"
        "本步骤只做结构化生成，不执行、不登记、不发布任务。\n"
        f"当前项目：{project.name}\n"
        f"当前会话：{channel.title}（ref={channel.id}，类型={channel.channel_type}）\n"
        "规则：只有用户明确说出其他群聊名称时才选择其他群聊；"
        "只说‘群里’‘群聊’或未说明目标时，选择项目群。\n"
        "近期对话（较早到较晚）：\n"
        + ("\n".join(history_lines) or "- 暂无")
        + "\n本轮明确请求：\n"
        + (marked_request or source.content.strip())
    )


def _task_draft_payload(
    generated: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    generated = normalize_task_flow(generated)
    steps = [
        dict(step)
        for step in (generated.get("steps") or [])
        if isinstance(step, dict)
    ]
    pure_single_message = (
        len(steps) == 1
        and steps[0].get("node_type") == "project_chat_message"
        and isinstance(steps[0].get("action"), dict)
    )
    action = steps[0].get("action") if pure_single_message else {}
    action = action if isinstance(action, dict) else {}
    return {
        "title": str(generated.get("title") or "").strip(),
        "task_type": str(generated.get("task_type") or "risk_alert"),
        "action_type": (
            "project_chat_message"
            if pure_single_message
            else "responsibility_task"
        ),
        "risk_level": str(generated.get("risk_level") or "medium"),
        "assignee_user_id": generated.get("assignee_user_id"),
        "confirmer_user_id": generated.get("confirmer_user_id"),
        "wbs_item_id": generated.get("wbs_item_id"),
        "risk_source_id": generated.get("risk_source_id"),
        "trigger_reason": str(
            generated.get("summary") or source_text,
        ).strip(),
        "required_materials": [
            str(step.get("material") or "").strip()
            for step in steps
            if str(step.get("material") or "").strip()
        ],
        "workflow_steps": steps,
        "run_mode": str(generated.get("run_mode") or "once"),
        "trigger_date": generated.get("trigger_date"),
        "trigger_time": str(generated.get("trigger_time") or "09:00"),
        "trigger_interval_value": int(
            generated.get("trigger_interval_value") or 1,
        ),
        "trigger_interval_unit": str(
            generated.get("trigger_interval_unit") or "week",
        ),
        "trigger_end_mode": generated.get("trigger_end_mode") or "never",
        "trigger_until_date": generated.get("trigger_until_date"),
        "trigger_max_fires": generated.get("trigger_max_fires"),
        "trigger_calendar_mode": generated.get("trigger_calendar_mode") or "weekdays",
        "trigger_weekdays": list(generated.get("trigger_weekdays") or []),
        "trigger_day_of_month": generated.get("trigger_day_of_month"),
        "cc": str(generated.get("cc") or ""),
        "target_channel_id": action.get("channel_id"),
        "mention_mode": str(action.get("mention_mode") or "none"),
        "mentioned_user_ids": list(action.get("mentioned_user_ids") or []),
        "message_content": str(action.get("content") or ""),
        "generated_by": generated.get("generated_by"),
        "generation_note": generated.get("generation_note"),
        "trigger_rule": generated.get("trigger_rule"),
    }


def _task_assistant_thread(
    db: Session,
    channel: ChatChannel,
    agent_id: str,
) -> ChatAgentThread:
    thread = db.scalar(
        select(ChatAgentThread).where(
            ChatAgentThread.channel_id == channel.id,
            ChatAgentThread.agent_id == agent_id,
        ),
    )
    if thread is None:
        thread = ChatAgentThread(
            channel_id=channel.id,
            agent_id=agent_id,
            agent_name="任务助手",
        )
        db.add(thread)
        db.flush()
    else:
        thread.agent_name = "任务助手"
    return thread


def _finish_task_draft(
    draft_message_id: int,
    *,
    status_name: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    with _legacy.SessionLocal() as db:
        draft = db.get(ChatMessage, draft_message_id)
        channel = db.get(ChatChannel, draft.channel_id) if draft else None
        if draft is None or channel is None:
            return
        _set_task_draft_state(
            db,
            draft,
            channel,
            status_name=status_name,
            content=content,
            metadata=metadata,
        )
        if draft.sender_agent_id:
            thread = _task_assistant_thread(
                db,
                channel,
                draft.sender_agent_id,
            )
            thread.status = (
                "awaiting_permission"
                if status_name == "ready"
                else draft.metadata_json.get("runtime_status", status_name)
            )
            thread.last_error = (
                str((metadata or {}).get("error") or "")[:4000]
                if status_name == "failed"
                else None
            )
        db.commit()


async def _generate_task_assistant_draft(
    source_message_id: int,
    agent_id: str,
    draft_message_id: int,
) -> None:
    try:
        with _legacy.SessionLocal() as db:
            source = db.get(ChatMessage, source_message_id)
            draft = db.get(ChatMessage, draft_message_id)
            channel = db.get(ChatChannel, source.channel_id) if source else None
            project = db.get(Project, channel.project_id) if channel else None
            user = db.get(User, source.sender_user_id) if source and source.sender_user_id else None
            if not all((source, draft, channel, project, user)):
                return
            if str((draft.metadata_json or {}).get("draft_status")) != "generating":
                return

            selected_agent = _configured_task_assistant()
            configured_agent_id = str(selected_agent["id"])
            if agent_id not in {configured_agent_id, PROJECT_CHAT_TASK_ASSISTANT_ID}:
                raise HTTPException(status_code=409, detail="任务助手配置已发生变化")
            thread = _task_assistant_thread(db, channel, configured_agent_id)
            thread.status = "running"
            thread.last_error = None
            thread.last_source_message_id = source.id
            db.commit()

            requirement = _task_assistant_requirement(
                db,
                project,
                channel,
                source,
                thread.agent_name,
            )
            generation_id = str(
                (draft.metadata_json or {}).get("generation_id")
                or f"chat-task-draft-{source.id}"
            )
            client = _legacy._agentscope_client()
            platform_context = _task_assistant_platform_context(
                user=user,
                project=project,
                conversation_id=f"chat-task-draft-{draft.id}",
                conversation_title=channel.title,
                channel_id=channel.id,
            )
            if not thread.agentscope_session_id:
                thread.status = "creating"
                db.commit()
                thread.agentscope_session_id = await asyncio.to_thread(
                    client.create_session,
                    agent=selected_agent,
                    workspace_id=(
                        f"platform-chat-p{project.id}-c{channel.id}-task-assistant"
                    ),
                    name=f"{channel.title} · 任务助手",
                    platform_context=platform_context,
                )
                db.commit()
            else:
                await asyncio.to_thread(
                    client.sync_session,
                    agent=selected_agent,
                    session_id=thread.agentscope_session_id,
                    platform_context=platform_context,
                )
            reply = await asyncio.to_thread(
                client.chat,
                agent_id=configured_agent_id,
                session_id=str(thread.agentscope_session_id),
                content=(
                    requirement
                    + "\n必须调用 generate_task_flow，参数 generation_id="
                    + generation_id
                    + "；只返回工具生成的草稿，不得发布任务。"
                ),
                sender_name=user.real_name,
                metadata={
                    "source": "project_group_chat_task_draft",
                    "trigger": "explicit_agent_mention",
                    "platform_user_id": user.id,
                    "project_id": project.id,
                    "chat_channel_id": channel.id,
                    "chat_message_id": source.id,
                    "generation_id": generation_id,
                },
                user_message_id=uuid4().hex,
            )
            generated = _legacy._task_flow_from_agent_reply(reply)
            draft_payload = _task_draft_payload(generated, source.content)
            draft_payload.update(
                {
                    "generated_by": configured_agent_id,
                    "agentscope_session_id": thread.agentscope_session_id,
                    "agentscope_message_id": reply.message_id,
                },
            )
            thread.status = reply.status
            db.commit()

        _finish_task_draft(
            draft_message_id,
            status_name="ready",
            content="任务草稿已生成，请确认内容后再发布。",
            metadata={
                "task_draft": draft_payload,
                "generated_at": datetime.now(UTC).isoformat(),
                "generated_by_agent_id": configured_agent_id,
                "agentscope_session_id": thread.agentscope_session_id,
                "agentscope_message_id": reply.message_id,
            },
        )
    except asyncio.CancelledError:
        _finish_task_draft(
            draft_message_id,
            status_name="cancelled",
            content="已停止生成任务草稿。",
        )
        raise
    except Exception as exc:
        detail = (
            str(exc.detail)
            if isinstance(exc, HTTPException)
            else str(exc)
        ).strip()
        detail = detail[:1200] or type(exc).__name__
        logger.exception(
            "群聊任务草稿生成失败：source_message_id=%s",
            source_message_id,
        )
        _finish_task_draft(
            draft_message_id,
            status_name="failed",
            content=f"任务草稿生成失败：{detail}",
            metadata={"error": detail, "error_code": "task_draft_generation_failed"},
        )


def _track_chat_agent_task(
    task: asyncio.Task[Any],
    *,
    draft_message_id: int | None = None,
) -> None:
    _CHAT_AGENT_TASKS.add(task)
    if draft_message_id is not None:
        _CHAT_TASK_DRAFT_TASKS[draft_message_id] = task

    def discard(completed: asyncio.Task[Any]) -> None:
        _CHAT_AGENT_TASKS.discard(completed)
        if (
            draft_message_id is not None
            and _CHAT_TASK_DRAFT_TASKS.get(draft_message_id) is completed
        ):
            _CHAT_TASK_DRAFT_TASKS.pop(draft_message_id, None)
        if completed.cancelled():
            return
        try:
            error = completed.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.exception(
                "群聊智能体后台任务异常",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(discard)


def _schedule_chat_agent_invocations(message: dict[str, Any]) -> None:
    metadata = message.get("metadata") or {}
    task_assistant_ids = {
        str(agent_id)
        for agent_id in (metadata.get("task_assistant_ids") or [])
    }
    draft_ids = {
        str(agent_id): int(draft_id)
        for agent_id, draft_id in (
            metadata.get("task_draft_message_ids") or {}
        ).items()
    }
    for mention in message.get("mentions") or []:
        if mention.get("target_type") != "agent":
            continue
        agent_id = str(mention.get("target_agent_id") or "")
        if not agent_id:
            continue
        if agent_id in task_assistant_ids and agent_id in draft_ids:
            draft_id = draft_ids[agent_id]
            if draft_id in _CHAT_TASK_DRAFT_TASKS:
                continue
            task = asyncio.create_task(
                _generate_task_assistant_draft(
                    int(message["id"]),
                    agent_id,
                    draft_id,
                ),
                name=f"chat-task-draft-{draft_id}",
            )
            _track_chat_agent_task(task, draft_message_id=draft_id)
            continue

        task = asyncio.create_task(
            asyncio.to_thread(
                _invoke_one_chat_agent,
                int(message["id"]),
                agent_id,
            ),
            name=f"chat-agent-{message['id']}-{agent_id}",
        )
        _track_chat_agent_task(task)


def _agent_reply_runtime_metadata(
    source: ChatMessage,
    thread: ChatAgentThread,
    reply: Any,
    *,
    stages: list[dict[str, object]] | None = None,
    turn_started_at: str | None = None,
) -> dict[str, Any]:
    raw_message = reply.raw_message if isinstance(reply.raw_message, dict) else {}
    tool_calls = [
        {
            "id": str(block.get("id") or ""),
            "name": str(block.get("name") or ""),
            "state": str(block.get("state") or ""),
        }
        for block in raw_message.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_call"
    ]
    trace_summary: dict[str, Any] = {"stages": stages or []}
    if turn_started_at:
        trace_summary["turn_started_at"] = turn_started_at
    if reply.status not in {
        "creating",
        "running",
        "interrupting",
        "awaiting_permission",
        "awaiting_external_result",
    }:
        trace_summary["turn_finished_at"] = datetime.now(UTC).isoformat()
    return {
        **_agent_reply_extra_data(reply, trace_summary),
        "agent_name": thread.agent_name,
        "source_message_id": source.id,
        "agentscope_session_id": thread.agentscope_session_id,
        "agentscope_message_id": reply.message_id,
        "runtime_status": reply.status,
        "requires_confirmation": reply.status
        in {"awaiting_permission", "awaiting_external_result"},
        "tool_calls": tool_calls,
    }


def _persist_chat_agent_reply(
    db: Session,
    channel: ChatChannel,
    source: ChatMessage,
    thread: ChatAgentThread,
    *,
    content: str,
    metadata: dict[str, Any],
    is_task_assistant: bool = False,
    failed: bool = False,
) -> ChatMessage:
    if is_task_assistant:
        existing_draft = _task_draft_for_source(
            db,
            source.id,
            thread.agent_id,
        )
        if existing_draft is not None:
            return _set_task_draft_state(
                db,
                existing_draft,
                channel,
                status_name="failed" if failed else "ready",
                content=content,
                metadata=metadata,
            )
    existing_run = _agent_run_for_source(db, source.id, thread.agent_id)
    if existing_run is not None and not is_task_assistant:
        db.refresh(existing_run)
        if (existing_run.metadata_json or {}).get("runtime_status") == "interrupted":
            return existing_run
        existing_run.content = content
        existing_run.metadata_json = {
            **(existing_run.metadata_json or {}),
            **metadata,
            "failed": failed,
        }
        existing_run.edited_at = datetime.now(UTC)
        channel.last_message_at = datetime.now(UTC)
        channel.summary = content[:160]
        _queue_chat_message_publish(db, channel, existing_run)
        db.flush()
        return existing_run
    row = ChatMessage(
        channel_id=channel.id,
        sender_type="agent",
        sender_agent_id=thread.agent_id,
        message_type=(
            "task_draft"
            if is_task_assistant and not failed
            else "agent"
        ),
        content=content,
        reply_to_id=source.id,
        metadata_json={**metadata, "failed": failed},
    )
    db.add(row)
    db.flush()
    channel.last_message_at = datetime.now(UTC)
    channel.summary = content[:160]
    _queue_chat_message_publish(db, channel, row)
    return row


def _invoke_one_chat_agent(message_id: int, agent_id: str) -> None:
    """Run one explicitly mentioned agent outside the request transaction."""

    with _legacy.SessionLocal() as lookup_db:
        source_channel_id = lookup_db.scalar(
            select(ChatMessage.channel_id).where(ChatMessage.id == message_id),
        )
    if source_channel_id is None:
        return
    with _CHAT_AGENT_LOCKS[(int(source_channel_id), agent_id)]:
        with _legacy.SessionLocal() as db:
            source = db.get(ChatMessage, message_id)
            if source is None or source.deleted_at is not None:
                return
            channel = db.get(ChatChannel, source.channel_id)
            user = db.get(User, source.sender_user_id) if source.sender_user_id else None
            project = db.get(Project, channel.project_id) if channel else None
            if channel is None or user is None or project is None:
                return

            tracker = RuntimeStageTracker()
            accepted_stage = tracker.start("accepted", "请求已受理")
            tracker.finish(accepted_stage)
            active_stage = tracker.start("authorization", "校验智能体授权")
            run_row = _agent_run_for_source(db, source.id, agent_id)
            if run_row is not None and (run_row.metadata_json or {}).get("runtime_status") == "interrupted":
                return
            reserved_task_assistant = agent_id in {
                str(value)
                for value in (source.metadata_json or {}).get(
                    "task_assistant_ids",
                    [],
                )
            }
            if run_row is None and not reserved_task_assistant:
                run_row = _create_agent_run_placeholder(
                    db,
                    channel,
                    source,
                    {"id": agent_id, "name": agent_id},
                )
            turn_started_at = str(
                (((run_row.metadata_json if run_row else {}) or {}).get(
                    "runtime_trace",
                ) or {}).get(
                    "turn_started_at",
                )
                or datetime.now(UTC).isoformat(),
            )
            if run_row is not None:
                _update_agent_run_progress(
                    db,
                    channel,
                    run_row,
                    content=f"@{agent_id} 正在校验调用授权…",
                    status_name="running",
                    stages=tracker.snapshot(),
                )
            db.commit()
            try:
                chat_channel_for_user_or_403(db, channel.id, user)
                client = _legacy._agentscope_client()
                thread = db.scalar(
                    select(ChatAgentThread).where(
                        ChatAgentThread.channel_id == channel.id,
                        ChatAgentThread.agent_id == agent_id,
                    ),
                )
                catalog = client.get_catalog()
                task_assistant = _public_task_assistant_catalog_item(
                    catalog.get("task_assistant"),
                )
                is_task_assistant = bool(
                    task_assistant
                    and str(task_assistant.get("id")) == agent_id
                )
                selected_agent = (
                    task_assistant
                    if is_task_assistant
                    else next(
                        (
                            item
                            for item in catalog.get("business_agents", [])
                            if str(item.get("id")) == agent_id
                        ),
                        None,
                    )
                )
                if selected_agent is None:
                    raise AgentScopeGatewayError(
                        "该智能体职责未分配、已停用或不存在。",
                        status_code=404,
                    )
                tracker.finish(active_stage)
                active_stage = tracker.start("session", "建立受控会话")
                if thread is None:
                    thread = ChatAgentThread(
                        channel_id=channel.id,
                        agent_id=agent_id,
                        agent_name=str(selected_agent.get("name") or agent_id),
                    )
                    db.add(thread)
                    db.flush()
                    db.commit()
                    db.refresh(thread)
                else:
                    thread.agent_name = str(selected_agent.get("name") or agent_id)

                conversation = create_group_agent_session(
                    db, client, user=user, project=project, channel=channel,
                    thread=thread, agent=selected_agent,
                )

                tracker.finish(active_stage)
                active_stage = tracker.start("execution", "智能体执行")
                run_row = _agent_run_for_source(db, source.id, agent_id)
                if run_row is not None:
                    if (run_row.metadata_json or {}).get("runtime_status") == "interrupted":
                        conversation.status = "interrupted"
                        db.commit()
                        return
                    run_row.metadata_json = {
                        **(run_row.metadata_json or {}),
                        "agentscope_session_id": thread.agentscope_session_id,
                        "platform_conversation_id": conversation.id,
                        "requester_user_id": user.id,
                    }
                    _update_agent_run_progress(
                        db,
                        channel,
                        run_row,
                        content=f"@{thread.agent_name} 正在处理请求…",
                        status_name="running",
                        stages=tracker.snapshot(),
                    )
                injected_content = _group_chat_agent_content(
                    db,
                    project,
                    channel,
                    source,
                    user,
                    selected_agent,
                )
                thread.status = "running"
                thread.last_error = None
                thread.last_source_message_id = source.id
                db.commit()
                reply = client.chat(
                    agent_id=agent_id,
                    session_id=str(thread.agentscope_session_id),
                    content=injected_content,
                    sender_name=user.real_name,
                    metadata={
                        "source": "project_group_chat",
                        "trigger": "explicit_agent_mention",
                        "platform_user_id": user.id,
                        "project_id": project.id,
                        "chat_channel_id": channel.id,
                        "chat_message_id": source.id,
                        "platform_display_content": source.content,
                    },
                    user_message_id=uuid4().hex,
                )
                tracker.finish(active_stage)
                active_stage = tracker.start("persist", "整理并保存结果")

                db.expire_all()
                source = db.get(ChatMessage, message_id)
                channel = db.get(ChatChannel, source.channel_id) if source else None
                thread = db.scalar(
                    select(ChatAgentThread).where(
                        ChatAgentThread.channel_id == source.channel_id,
                        ChatAgentThread.agent_id == agent_id,
                    ),
                ) if source else None
                if source is None or channel is None or thread is None:
                    return
                # A stop request may have arrived while the synchronous
                # gateway was returning. Never replace its terminal state.
                run_row = _agent_run_for_source(db, source.id, agent_id)
                if run_row is not None and (run_row.metadata_json or {}).get("runtime_status") == "interrupted":
                    return
                chat_channel_for_user_or_403(db, channel.id, user)
                tracker.finish(active_stage)
                conversation.status = reply.status
                thread.status = reply.status
                thread.last_error = None
                _persist_chat_agent_reply(
                    db,
                    channel,
                    source,
                    thread,
                    content=reply.content or "智能体已完成处理，但未返回文本内容。",
                    metadata=_agent_reply_runtime_metadata(
                        source,
                        thread,
                        reply,
                        stages=tracker.snapshot(),
                        turn_started_at=turn_started_at,
                    ),
                    is_task_assistant=is_task_assistant,
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                tracker.finish(active_stage, status="error")
                source = db.get(ChatMessage, message_id)
                channel = db.get(ChatChannel, source.channel_id) if source else None
                thread = db.scalar(
                    select(ChatAgentThread).where(
                        ChatAgentThread.channel_id == source.channel_id,
                        ChatAgentThread.agent_id == agent_id,
                    ),
                ) if source else None
                if source is None or channel is None:
                    return
                run_row = _agent_run_for_source(db, source.id, agent_id)
                if run_row is not None and (run_row.metadata_json or {}).get("runtime_status") == "interrupted":
                    return
                if thread is None:
                    thread = ChatAgentThread(
                        channel_id=channel.id,
                        agent_id=agent_id,
                        agent_name=agent_id,
                        status="error",
                    )
                    db.add(thread)
                    db.flush()
                thread.status = "error"
                thread.last_error = str(exc)[:4000]
                _persist_chat_agent_reply(
                    db,
                    channel,
                    source,
                    thread,
                    content=(
                        f"@{thread.agent_name} 暂时未能完成处理，请稍后重新提及。"
                    ),
                    metadata={
                        "agent_name": thread.agent_name,
                        "source_message_id": source.id,
                        "runtime_status": "error",
                        "status": "error",
                        "error_code": "agent_invocation_failed",
                        "runtime_trace": {
                            "stages": tracker.snapshot(),
                            "turn_started_at": turn_started_at,
                            "turn_finished_at": datetime.now(UTC).isoformat(),
                        },
                    },
                    failed=True,
                )
                db.commit()


@router.post("/chat/messages/{message_id}/agent/stop")
def stop_chat_agent_run(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.get(ChatMessage, message_id)
    if row is None or row.deleted_at is not None or row.sender_type != "agent":
        raise HTTPException(status_code=404, detail="智能体运行不存在")
    channel = chat_channel_for_user_or_403(db, row.channel_id, user)
    source = db.get(ChatMessage, row.reply_to_id)
    if source is None or source.sender_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有本次请求的发起人可以停止执行")
    metadata = dict(row.metadata_json or {})
    if metadata.get("runtime_status") not in {
        "queued", "running", "creating", "awaiting_permission", "awaiting_external_result",
    }:
        return ok(chat_message_view(db, row))
    session_id = metadata.get("agentscope_session_id")
    if session_id:
        try:
            _legacy._agentscope_client().interrupt(
                agent_id=row.sender_agent_id, session_id=str(session_id),
            )
        except AgentScopeGatewayError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    trace = dict(metadata.get("runtime_trace") or {})
    now = datetime.now(UTC)
    stages = []
    for previous in trace.get("stages") or []:
        stage = dict(previous)
        if not stage.get("finished_at"):
            stage.update({"status": "interrupted", "finished_at": now.isoformat()})
            try:
                started = datetime.fromisoformat(stage["started_at"])
                stage["duration_ms"] = max(0, (now - started).total_seconds() * 1000)
            except (KeyError, ValueError, TypeError):
                stage["duration_ms"] = 0
        stages.append(stage)
    _update_agent_run_progress(
        db, channel, row, content="本次智能体执行已停止。",
        status_name="interrupted", stages=stages, finished=True,
    )
    from .models import AgentConversation

    conversation_id = metadata.get("platform_conversation_id")
    conversation = db.get(AgentConversation, conversation_id) if conversation_id else None
    if conversation is not None and conversation.agentscope_session_id == session_id:
        conversation.status = "interrupted"
    thread = db.scalar(select(ChatAgentThread).where(
        ChatAgentThread.channel_id == row.channel_id,
        ChatAgentThread.agent_id == row.sender_agent_id,
    ))
    if thread is not None and thread.agentscope_session_id == session_id:
        thread.status = "interrupted"
    db.commit()
    return ok(chat_message_view(db, row), "本次执行已停止")


def invoke_mentioned_chat_agents(message_id: int) -> None:
    """Invoke only agents stored as explicit mentions on one message."""

    with _legacy.SessionLocal() as db:
        agent_ids = list(
            db.scalars(
                select(ChatMessageMention.target_agent_id).where(
                    ChatMessageMention.message_id == message_id,
                    ChatMessageMention.target_type == "agent",
                ),
            ).all(),
        )
    for agent_id in dict.fromkeys(item for item in agent_ids if item):
        _invoke_one_chat_agent(message_id, str(agent_id))


def _task_draft_for_user_or_403(
    db: Session,
    draft_message_id: int,
    user: User,
) -> tuple[ChatMessage, ChatMessage, ChatChannel]:
    draft = db.get(ChatMessage, draft_message_id)
    if (
        draft is None
        or draft.message_type != "task_draft"
        or draft.deleted_at is not None
    ):
        raise HTTPException(status_code=404, detail="任务草稿不存在")
    channel = chat_channel_for_user_or_403(db, draft.channel_id, user)
    source = db.get(ChatMessage, draft.reply_to_id) if draft.reply_to_id else None
    if source is None or source.channel_id != channel.id:
        raise HTTPException(status_code=409, detail="任务草稿缺少来源消息")
    requested_by = (draft.metadata_json or {}).get("requested_by_user_id")
    if requested_by is None:
        requested_by = source.sender_user_id
    if int(requested_by or 0) != user.id:
        raise HTTPException(
            status_code=403,
            detail="只有发起本次任务生成的用户可以处理该草稿",
        )
    return draft, source, channel


@router.post("/chat/messages/{draft_message_id}/task-draft/publish")
def publish_chat_task_draft(
    draft_message_id: int,
    payload: TaskInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    with _CHAT_TASK_DRAFT_PUBLISH_LOCKS[draft_message_id]:
        draft, _, channel = _task_draft_for_user_or_403(
            db,
            draft_message_id,
            user,
        )
        draft_status = str((draft.metadata_json or {}).get("draft_status") or "")
        if draft_status == "published":
            return ok(
                {
                    "message": chat_message_view(db, draft),
                    "result": (draft.metadata_json or {}).get("publish_result"),
                },
                "任务草稿已经发布",
            )
        if draft_status != "ready":
            raise HTTPException(
                status_code=409,
                detail="任务草稿尚未生成完成或已被处理",
            )

        # Import lazily to avoid the api.py -> chat_api.py module cycle.
        from .api import create_task

        created = create_task(channel.project_id, payload, db, user)
        db.expire_all()
        draft = db.get(ChatMessage, draft_message_id)
        channel = db.get(ChatChannel, draft.channel_id) if draft else None
        if draft is None or channel is None:
            raise HTTPException(status_code=409, detail="任务已发布，但草稿状态更新失败")
        result_data = created.get("data") or {}
        task_id = result_data.get("id") if isinstance(result_data, dict) else None
        if task_id:
            draft.task_ids = list(
                dict.fromkeys([*(draft.task_ids or []), str(task_id)]),
            )
        _set_task_draft_state(
            db,
            draft,
            channel,
            status_name="published",
            content=f"任务已发布：{payload.title}",
            metadata={
                "publish_result": result_data,
                "publish_message": created.get("message"),
                "published_by_user_id": user.id,
                "published_at": datetime.now(UTC).isoformat(),
            },
        )
        db.commit()
        return ok(
            {
                "message": chat_message_view(db, draft),
                "result": result_data,
            },
            str(created.get("message") or "任务已发布"),
        )


@router.post("/chat/messages/{draft_message_id}/task-draft/dismiss")
def dismiss_chat_task_draft(
    draft_message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft, _, channel = _task_draft_for_user_or_403(
        db,
        draft_message_id,
        user,
    )
    draft_status = str((draft.metadata_json or {}).get("draft_status") or "")
    if draft_status == "published":
        raise HTTPException(status_code=409, detail="已发布的任务不能取消")
    if draft_status == "generating":
        raise HTTPException(status_code=409, detail="请先停止任务助手当前的任务分析")
    if draft_status != "dismissed":
        _set_task_draft_state(
            db,
            draft,
            channel,
            status_name="dismissed",
            content="本次任务草稿未发布。",
            metadata={
                "dismissed_by_user_id": user.id,
                "dismissed_at": datetime.now(UTC).isoformat(),
            },
        )
        db.commit()
    return ok(chat_message_view(db, draft), "任务草稿已取消")


@router.post("/chat/messages/{draft_message_id}/task-draft/retry")
async def retry_chat_task_draft(
    draft_message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft, source, channel = _task_draft_for_user_or_403(
        db,
        draft_message_id,
        user,
    )
    if draft_message_id in _CHAT_TASK_DRAFT_TASKS:
        raise HTTPException(status_code=409, detail="任务助手正在分析任务需求")
    draft_status = str((draft.metadata_json or {}).get("draft_status") or "")
    if draft_status == "published":
        raise HTTPException(status_code=409, detail="任务已经发布")

    cleaned_metadata = dict(draft.metadata_json or {})
    for key in (
        "task_draft",
        "error",
        "error_code",
        "generated_at",
        "dismissed_at",
        "dismissed_by_user_id",
    ):
        cleaned_metadata.pop(key, None)
    cleaned_metadata["generation_id"] = (
        f"chat-task-draft-{source.id}-{uuid4().hex[:8]}"
    )
    draft.metadata_json = cleaned_metadata
    _set_task_draft_state(
        db,
        draft,
        channel,
        status_name="generating",
        content="任务助手正在重新生成草稿…",
    )
    db.commit()
    db.refresh(draft)

    agent_id = str(draft.sender_agent_id or "")
    task = asyncio.create_task(
        _generate_task_assistant_draft(source.id, agent_id, draft.id),
        name=f"chat-task-draft-{draft.id}",
    )
    _track_chat_agent_task(task, draft_message_id=draft.id)
    return ok(chat_message_view(db, draft), "任务草稿已重新开始生成")


@router.post("/chat/messages/{draft_message_id}/task-draft/stop")
async def stop_chat_task_draft(
    draft_message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft, _, channel = _task_draft_for_user_or_403(
        db,
        draft_message_id,
        user,
    )
    draft_status = str((draft.metadata_json or {}).get("draft_status") or "")
    if draft_status != "generating":
        return ok(chat_message_view(db, draft), "任务助手当前没有正在生成草稿")

    task = _CHAT_TASK_DRAFT_TASKS.get(draft_message_id)
    if task is not None and not task.done():
        thread = (
            db.scalar(
                select(ChatAgentThread).where(
                    ChatAgentThread.channel_id == channel.id,
                    ChatAgentThread.agent_id == draft.sender_agent_id,
                ),
            )
            if draft.sender_agent_id
            else None
        )
        if thread is not None and thread.agentscope_session_id:
            try:
                await asyncio.to_thread(
                    _legacy._agentscope_client().interrupt,
                    agent_id=thread.agent_id,
                    session_id=thread.agentscope_session_id,
                )
            except AgentScopeGatewayError as exc:
                logger.warning("停止群聊任务助手 AgentScope 运行失败：%s", exc)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        _set_task_draft_state(
            db,
            draft,
            channel,
            status_name="cancelled",
            content="已停止生成任务草稿。",
        )
        db.commit()
    db.expire_all()
    refreshed = db.get(ChatMessage, draft_message_id)
    return ok(
        chat_message_view(db, refreshed or draft),
        "任务助手已停止本次草稿生成",
    )
