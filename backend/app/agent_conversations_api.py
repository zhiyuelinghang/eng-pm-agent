from __future__ import annotations

import asyncio
import hashlib
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agentscope_client import (
    AgentScopeGatewayError,
    AgentScopeReply,
)
from .agentscope_stream_completion import AgentScopeCompletionRelay
from .agent_api_support import (
    _turn_platform_context,
    INITIALIZATION_FILE_MAX_BYTES,
    INITIALIZATION_FILE_SUFFIXES,
    _agent_conversation_or_404,
    _adopt_initial_conversation_title,
    _agentscope_client,
    _agentscope_platform_messages,
    _annotate_collaboration_event,
    _build_agent_project_context,
    _catalog_agent_for_conversation,
    _finalize_agent_reply,
    _finalize_agent_reply_after_disconnect,
    _initialization_attachment_manifest_context,
    _initialization_file_refs,
    _initialization_files_for_message,
    _mark_agent_turn_running,
    _platform_session_context,
    _project_agentscope_user_message,
    _public_agent_catalog_item,
    _public_initialization_file,
    _public_task_assistant_catalog_item,
    _raise_agentscope_http_error,
    _record_agent_turn_error,
    _sse_frame,
    _upsert_collaboration_member,
)
from .api_common import (
    audit,
    get_current_user,
    ok,
    project_for_user_or_403,
    serialize,
)
from .config import get_settings
from .db import get_db
from .initialization_attachment_store import (
    store_failed_initialization_attachment,
    store_parsed_initialization_attachment,
)
from .models import AgentConversation, EngineeringKnowledgeConversation, Project, ProjectInitializationFile, User
from .schemas import (
    AgentConversationConfirmInput,
    AgentConversationInput,
    AgentConversationMessageInput,
)
from .system_attachment_parser import (
    SystemAttachmentParserError,
    parse_uploaded_attachment,
)
from .runtime_observability import RuntimeStageTracker, runtime_stage_event
from .knowledge_agent_support import knowledge_entry_prompt
from .agent_image_attachments import image_attachment_refs, image_blocks_for_turn


router = APIRouter(prefix="/api", tags=["agent-conversations"])




@router.get("/agents/catalog")
def get_agent_catalog(
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Expose AgentScope's safe publication catalogue to the platform UI."""
    from .knowledge_agent_support import public_knowledge_assistant
    try:
        catalog = _agentscope_client().get_catalog()
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    business_agents = [
        _public_agent_catalog_item(item)
        for item in catalog.get("business_agents", [])
    ]
    initialization_workers = [
        _public_agent_catalog_item(item)
        for item in catalog.get("initialization_workers", [])
    ]
    return ok(
        {
            "global_main": _public_agent_catalog_item(
                catalog.get("global_main"),
            ),
            "project_initializer": _public_agent_catalog_item(
                catalog.get("project_initializer"),
            ),
            "task_assistant": _public_task_assistant_catalog_item(
                catalog.get("task_assistant"),
            ),
            "knowledge_assistant": public_knowledge_assistant(catalog.get("knowledge_assistant")),
            "initialization_workers": initialization_workers,
            "business_agents": business_agents,
            "total": len(business_agents),
        },
    )


@router.get("/projects/{project_id}/agent-conversations")
def list_agent_conversations(
    project_id: int,
    conversation_type: str | None = Query(
        default=None,
        pattern="^(general|business|initialization)$",
    ),
    agent_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    statement = select(AgentConversation).where(
        AgentConversation.project_id == project_id,
        AgentConversation.user_id == user.id,
        AgentConversation.conversation_type.in_(("general", "business", "initialization")),
        ~select(EngineeringKnowledgeConversation.id).where(
            EngineeringKnowledgeConversation.agent_conversation_id == AgentConversation.id,
        ).exists(),
    )
    if conversation_type:
        statement = statement.where(
            AgentConversation.conversation_type == conversation_type,
        )
    if conversation_type == "general" and not agent_id:
        try:
            selected_agent = _agentscope_client().get_catalog().get(
                "global_main",
            )
        except AgentScopeGatewayError as exc:
            _raise_agentscope_http_error(exc)
        if selected_agent is None:
            return ok([])
        statement = statement.where(
            AgentConversation.agent_id == str(selected_agent["id"]),
        )
    if agent_id:
        statement = statement.where(AgentConversation.agent_id == agent_id)
    statement = statement.order_by(AgentConversation.updated_at.desc(), AgentConversation.id.desc())
    rows = db.scalars(statement).all()
    return ok([serialize(row) for row in rows])


@router.post("/projects/{project_id}/agent-conversations")
def create_agent_conversation(
    project_id: int,
    payload: AgentConversationInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        if payload.conversation_type == "general":
            selected_agent = catalog.get("global_main")
            if selected_agent is None:
                raise HTTPException(
                    status_code=409,
                    detail="AgentScope 尚未配置已启用的全局主智能体",
                )
        elif payload.conversation_type == "initialization":
            if user.role != "admin":
                raise HTTPException(status_code=403, detail="请由管理人员在初始化页面使用项目初始化助手")
            selected_agent = catalog.get("project_initializer")
            if selected_agent is None:
                raise HTTPException(
                    status_code=409,
                    detail="AgentScope 尚未配置已启用的项目初始化智能体",
                )
        else:
            if not payload.agent_id:
                raise HTTPException(
                    status_code=422,
                    detail="业务智能体会话必须提供 agent_id",
                )
            selected_agent = next(
                (
                    item
                    for item in catalog.get("business_agents", [])
                    if item.get("id") == payload.agent_id
                ),
                None,
            )
            if selected_agent is None:
                raise HTTPException(
                    status_code=404,
                    detail="该业务智能体未发布、已停用或不存在",
                )

        row = AgentConversation(
            project_id=project.id,
            user_id=user.id,
            agent_id=str(selected_agent["id"]),
            agent_name=str(selected_agent["name"]),
            conversation_type=payload.conversation_type,
            title=payload.title
            or (
                f"{selected_agent['name']} · {project.name}"
                if payload.conversation_type == "business"
                else (
                    f"{project.name} · 项目初始化"
                    if payload.conversation_type == "initialization"
                    else f"{project.name} · 智能协同"
                )
            ),
            status="creating",
        )
        db.add(row)
        db.flush()
        row.agentscope_session_id = client.create_session(
            agent=selected_agent,
            workspace_id=(
                f"platform-u{user.id}-p{project.id}-conversation-{row.id}"
            ),
            name=row.title,
            platform_context=_platform_session_context(user, project, row, db),
        )
        row.status = "active"
        audit(
            db,
            user,
            "创建智能体会话",
            f"创建「{row.agent_name}」平台会话",
            project.id,
            "agent_conversation",
            row.id,
        )
        db.commit()
        db.refresh(row)
        return ok(serialize(row), "智能体会话已创建")
    except AgentScopeGatewayError as exc:
        db.rollback()
        _raise_agentscope_http_error(exc)


@router.delete("/agent-conversations/{conversation_id}")
def delete_agent_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a user-owned chat and its AgentScope runtime session."""
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if conversation.conversation_type == "initialization":
        raise HTTPException(
            status_code=409,
            detail="项目初始化会话属于项目初始化流程，不能在聊天记录中删除",
        )

    if conversation.agentscope_session_id:
        try:
            _agentscope_client().delete_session(
                conversation.agentscope_session_id,
                conversation.agent_id,
            )
        except AgentScopeGatewayError as exc:
            _raise_agentscope_http_error(exc)

    deleted_id = conversation.id
    project_id = conversation.project_id
    audit(
        db,
        user,
        "删除智能体会话",
        f"删除「{conversation.title}」平台会话及聊天记录",
        project_id,
        "agent_conversation",
        deleted_id,
    )
    db.delete(conversation)
    db.commit()
    return ok({"id": deleted_id}, "智能体会话已删除")


@router.get(
    "/projects/{project_id}/agent-conversations/{conversation_id}"
    "/initialization-files",
)
def list_project_initialization_files(
    project_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if (
        conversation.project_id != project_id
        or conversation.conversation_type != "initialization"
    ):
        raise HTTPException(status_code=404, detail="项目初始化会话不存在")
    rows = db.scalars(
        select(ProjectInitializationFile)
        .where(
            ProjectInitializationFile.project_id == project_id,
            ProjectInitializationFile.conversation_id == conversation_id,
        )
        .order_by(ProjectInitializationFile.created_at),
    ).all()
    return ok([_public_initialization_file(row, db) for row in rows])


@router.post(
    "/projects/{project_id}/agent-conversations/{conversation_id}"
    "/initialization-files",
)
def upload_project_initialization_file(
    project_id: int,
    conversation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if (
        conversation.project_id != project_id
        or conversation.conversation_type != "initialization"
    ):
        raise HTTPException(status_code=404, detail="项目初始化会话不存在")
    safe_name = Path(file.filename or "attachment").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in INITIALIZATION_FILE_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化附件仅支持 TXT、Markdown、CSV、XLS/XLSX、"
                "DOCX、PPTX、PDF 和常见图片"
            ),
        )
    content = file.file.read(INITIALIZATION_FILE_MAX_BYTES + 1)
    if len(content) > INITIALIZATION_FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="单个初始化附件不能超过 30MB")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(ProjectInitializationFile).where(
            ProjectInitializationFile.conversation_id == conversation.id,
            ProjectInitializationFile.file_name == safe_name,
            ProjectInitializationFile.file_hash == digest,
        ),
    )
    if duplicate is not None:
        return ok(
            _public_initialization_file(duplicate, db),
            "相同初始化附件已存在",
        )

    settings = get_settings()
    folder = (
        settings.upload_dir
        / "project-initialization"
        / str(project_id)
        / str(conversation_id)
    )
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (
        f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    )
    target.write_bytes(content)
    row = ProjectInitializationFile(
        project_id=project_id,
        conversation_id=conversation.id,
        uploaded_by_user_id=user.id,
        file_name=safe_name,
        storage_path=str(target),
        content_type=file.content_type,
        file_size=len(content),
        file_hash=digest,
    )
    db.add(row)
    db.flush()
    try:
        parsed = parse_uploaded_attachment(
            content,
            file_name=safe_name,
            media_type=file.content_type,
        )
        store_parsed_initialization_attachment(db, row, parsed)
        response_message = "初始化附件已上传并完成解析"
    except SystemAttachmentParserError as exc:
        store_failed_initialization_attachment(db, row, str(exc))
        response_message = "初始化附件已上传，但解析失败"
    audit(
        db,
        user,
        "上传项目初始化附件",
        f"上传初始化附件「{safe_name}」",
        project_id,
        "project_initialization_file",
        row.id,
    )
    db.commit()
    db.refresh(row)
    return ok(_public_initialization_file(row, db), response_message)


@router.delete("/project-initialization-files/{file_id}")
def delete_project_initialization_file(
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.get(ProjectInitializationFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="初始化附件不存在")
    conversation = _agent_conversation_or_404(
        db,
        row.conversation_id,
        user,
    )
    if conversation.conversation_type != "initialization":
        raise HTTPException(status_code=404, detail="初始化附件不存在")
    path = Path(row.storage_path)
    db.delete(row)
    audit(
        db,
        user,
        "删除项目初始化附件",
        f"删除初始化附件「{row.file_name}」",
        row.project_id,
        "project_initialization_file",
        row.id,
    )
    db.commit()
    with suppress(OSError):
        path.unlink()
    return ok({}, "初始化附件已删除")


@router.get("/agent-conversations/{conversation_id}/messages")
def list_agent_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(
            status_code=409,
            detail="智能体会话尚未完成初始化",
        )
    client = _agentscope_client()
    try:
        live_status = client.session_status(
            conversation.agentscope_session_id,
            conversation.agent_id,
        )
        history = client.list_all_messages(
            conversation.agentscope_session_id,
            conversation.agent_id,
        )
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        conversation.updated_at = datetime.now(UTC)
        db.commit()
        _raise_agentscope_http_error(exc)

    messages = _agentscope_platform_messages(
        conversation.id,
        list(history.get("messages") or []),
        live_status,
        conversation.agentscope_session_id,
    )
    first_user_message = next(
        (item for item in messages if item["role"] == "user"),
        None,
    )
    if first_user_message:
        _adopt_initial_conversation_title(
            conversation,
            str(first_user_message.get("content") or ""),
        )
    latest_assistant = next(
        (item for item in reversed(messages) if item["role"] == "assistant"),
        None,
    )
    if live_status not in {"idle", "active", "completed"}:
        conversation.status = live_status
    elif latest_assistant:
        conversation.status = str(
            (latest_assistant.get("extra_data") or {}).get("status")
            or "completed",
        )
    else:
        conversation.status = "active"
    conversation.last_error = None
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    return ok(messages)


@router.post("/agent-conversations/{conversation_id}/messages")
def create_agent_conversation_message(
    conversation_id: int,
    payload: AgentConversationMessageInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    project = project_for_user_or_403(db, conversation.project_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(
            status_code=409,
            detail="智能体会话尚未完成初始化",
        )
    _adopt_initial_conversation_title(conversation, payload.content)
    platform_context, knowledge_query_enabled = _turn_platform_context(
        db,
        user,
        project,
        conversation,
        payload.content,
    )

    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        selected_agent = _catalog_agent_for_conversation(
            catalog,
            conversation,
            db=db,
        )
        client.sync_session(
            agent=selected_agent,
            session_id=conversation.agentscope_session_id,
            platform_context=platform_context,
            name=conversation.title,
        )
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        db.commit()
        _raise_agentscope_http_error(exc)

    initialization_files = _initialization_files_for_message(
        db,
        conversation,
        payload.initialization_file_ids,
    )
    image_blocks, native_image_ids = image_blocks_for_turn(payload.image_attachments,
        initialization_files, upload_dir=get_settings().upload_dir)
    attachment_manifest = _initialization_attachment_manifest_context(
        db,
        initialization_files,
        native_image_ids=native_image_ids,
    )
    injected_content = (
        _build_agent_project_context(
            db,
            project,
            user,
            knowledge_query_enabled=knowledge_query_enabled,
        )
        + knowledge_entry_prompt(db, conversation)
        + attachment_manifest
        + "\n<user-request>\n"
        + payload.content
        + "\n</user-request>"
    )
    user_message_id = uuid4().hex
    user_message_metadata = {
        "source": "engineering_platform",
        "platform_user_id": user.id,
        "platform_username": user.username,
        "platform_user_display_name": user.real_name,
        "project_id": project.id,
        "platform_project_name": project.name,
        "conversation_id": conversation.id,
        "platform_display_content": payload.content,
        "platform_image_attachments": image_attachment_refs(image_blocks),
        "platform_initialization_files": _initialization_file_refs(
            initialization_files,
        ),
    }
    user_message = _project_agentscope_user_message(
        conversation.id,
        {
            "id": user_message_id,
            "name": user.real_name,
            "role": "user",
            "content": [{"type": "text", "text": injected_content}, *image_blocks],
            "metadata": user_message_metadata,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    conversation.status = "running"
    conversation.last_error = None
    conversation.updated_at = datetime.now(UTC)
    audit(
        db,
        user,
        "调用智能体",
        f"调用「{conversation.agent_name}」处理平台消息",
        project.id,
        "agent_conversation",
        conversation.id,
    )
    db.commit()
    try:
        reply = client.chat(
            agent_id=conversation.agent_id,
            session_id=conversation.agentscope_session_id,
            content=injected_content,
            sender_name=user.real_name,
            metadata=user_message_metadata,
            user_message_id=user_message_id,
            content_blocks=image_blocks,
        )
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        conversation.updated_at = datetime.now(UTC)
        db.commit()
        _raise_agentscope_http_error(exc)

    assistant = _finalize_agent_reply(
        conversation.id,
        reply,
        {
            "turn_started_at": user_message["created_at"],
            "platform_user_request": payload.content,
        },
    )
    if assistant is None:
        raise HTTPException(status_code=409, detail="平台智能体会话已被删除")
    db.expire_all()
    db.refresh(conversation)
    return ok(
        {
            "conversation": serialize(conversation),
            "user_message": user_message,
            "message": assistant,
            "runtime_status": reply.status,
        },
        (
            "智能体处理完成"
            if reply.status == "completed"
            else "智能体等待进一步处理"
        ),
    )


@router.post("/agent-conversations/{conversation_id}/messages/stream")
def stream_agent_conversation_message(
    conversation_id: int,
    payload: AgentConversationMessageInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Relay one authorized AgentScope turn as structured SSE events."""
    stage_tracker = RuntimeStageTracker()
    total_stage = stage_tracker.start("total", "总耗时")
    authorization_stage = stage_tracker.start(
        "platform_authorization",
        "平台鉴权与项目边界",
    )
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    project = project_for_user_or_403(db, conversation.project_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(
            status_code=409,
            detail="智能体会话尚未完成初始化",
        )
    stage_tracker.finish(authorization_stage)
    context_stage = stage_tracker.start("context_build", "上下文与权限白名单")
    _adopt_initial_conversation_title(conversation, payload.content)
    platform_context, knowledge_query_enabled = _turn_platform_context(
        db,
        user,
        project,
        conversation,
        payload.content,
    )
    stage_tracker.finish(context_stage)

    client = _agentscope_client()
    try:
        catalog_stage = stage_tracker.start("agent_catalog", "智能体目录读取")
        catalog = client.get_catalog()
        selected_agent = _catalog_agent_for_conversation(
            catalog,
            conversation,
            db=db,
        )
        stage_tracker.finish(catalog_stage)
        sync_stage = stage_tracker.start("session_sync", "AgentScope 会话同步")
        client.sync_session(
            agent=selected_agent,
            session_id=conversation.agentscope_session_id,
            platform_context=platform_context,
            name=conversation.title,
        )
        stage_tracker.finish(sync_stage)
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        db.commit()
        _raise_agentscope_http_error(exc)

    payload_stage = stage_tracker.start("request_payload", "请求与附件上下文装配")
    initialization_files = _initialization_files_for_message(
        db,
        conversation,
        payload.initialization_file_ids,
    )
    image_blocks, native_image_ids = image_blocks_for_turn(payload.image_attachments,
        initialization_files, upload_dir=get_settings().upload_dir)
    attachment_manifest = _initialization_attachment_manifest_context(
        db,
        initialization_files,
        native_image_ids=native_image_ids,
    )
    injected_content = (
        _build_agent_project_context(
            db,
            project,
            user,
            knowledge_query_enabled=knowledge_query_enabled,
        )
        + knowledge_entry_prompt(db, conversation)
        + attachment_manifest
        + "\n<user-request>\n"
        + payload.content
        + "\n</user-request>"
    )
    stage_tracker.finish(payload_stage)
    user_message_id = uuid4().hex
    agent_id = conversation.agent_id
    session_id = conversation.agentscope_session_id
    sender_name = user.real_name
    metadata = {
        "source": "engineering_platform",
        "platform_user_id": user.id,
        "platform_username": user.username,
        "platform_user_display_name": user.real_name,
        "project_id": project.id,
        "platform_project_name": project.name,
        "conversation_id": conversation.id,
        "platform_display_content": payload.content,
        "platform_image_attachments": image_attachment_refs(image_blocks),
        "platform_initialization_files": _initialization_file_refs(
            initialization_files,
        ),
    }
    user_message = _project_agentscope_user_message(
        conversation.id,
        {
            "id": user_message_id,
            "name": sender_name,
            "role": "user",
            "content": [{"type": "text", "text": injected_content}, *image_blocks],
            "metadata": metadata,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    conversation.status = "running"
    conversation.last_error = None
    conversation.updated_at = datetime.now(UTC)
    audit(
        db,
        user,
        "调用智能体",
        f"调用「{conversation.agent_name}」处理平台消息",
        project.id,
        "agent_conversation",
        conversation.id,
    )
    db.commit()
    accepted_payload = {
        "conversation_id": conversation.id,
        "user_message": user_message,
        "runtime_status": "running",
    }

    async def relay() -> Any:
        chat_task: asyncio.Task[AgentScopeReply] | None = None
        event_task: asyncio.Task[dict[str, Any]] | None = None
        completion_relay = AgentScopeCompletionRelay(
            client=client,
            user_message_id=user_message_id,
        )
        trace_summary: dict[str, Any] = {
            "model_names": [],
            "tasks_context": None,
            "team_update_count": 0,
            "collaborations": [],
            "subagent_hitl": [],
            "turn_started_at": user_message["created_at"],
            "platform_user_request": payload.content,
            "turn_finished_at": None,
            "stages": stage_tracker.snapshot(),
        }
        execution_stage = stage_tracker.start(
            "agent_execution",
            "智能体持续执行",
        )
        dispatch_stage = stage_tracker.start(
            "agentscope_dispatch",
            "AgentScope 装配与首个事件",
        )
        first_output_stage = stage_tracker.start(
            "model_first_output",
            "模型首个可见输出",
        )
        try:
            # Start the turn immediately and acknowledge the browser before
            # opening the observability stream. AgentScope keeps a replay log
            # for the active run, so events emitted during this brief overlap
            # are delivered when the stream subscribes; the user no longer
            # waits for a second connection before the model can start.
            chat_task = asyncio.create_task(
                asyncio.to_thread(
                    client.chat,
                    agent_id=agent_id,
                    session_id=session_id,
                    content=injected_content,
                    sender_name=sender_name,
                    metadata=metadata,
                    user_message_id=user_message_id,
                    content_blocks=image_blocks,
                    completion=completion_relay.completion,
                ),
            )
            yield _sse_frame("accepted", accepted_payload)
            for stage in stage_tracker.snapshot():
                yield _sse_frame(
                    "agent_event",
                    {
                        "type": "CUSTOM",
                        "name": "runtime_stage_updated",
                        "created_at": datetime.now(UTC).isoformat(),
                        "value": stage,
                    },
                )

            async with client.event_stream(session_id, agent_id) as events:
                event_task = asyncio.create_task(anext(events))

                while True:
                    waiting: set[asyncio.Task[Any]] = {chat_task}
                    if event_task is not None:
                        waiting.add(event_task)
                    completed, _ = await asyncio.wait(
                        waiting,
                        timeout=15.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not completed:
                        # Keep browsers and reverse proxies from treating a
                        # quiet but still-running agent turn as a dead
                        # connection. SSE comments are ignored by the client.
                        yield ": dobby-agent-heartbeat\n\n"
                        continue

                    if event_task is not None and event_task in completed:
                        try:
                            runtime_event = event_task.result()
                        except StopAsyncIteration:
                            event_task = None
                        else:
                            event_type = str(runtime_event.get("type") or "")
                            if dispatch_stage.finished_at is None:
                                stage_tracker.finish(dispatch_stage)
                                yield _sse_frame(
                                    "agent_event",
                                    runtime_stage_event(dispatch_stage),
                                )
                            if (
                                first_output_stage.finished_at is None
                                and event_type
                                in {
                                    "TEXT_BLOCK_DELTA",
                                    "THINKING_BLOCK_DELTA",
                                    "TOOL_CALL_START",
                                    "REQUIRE_USER_CONFIRM",
                                }
                            ):
                                stage_tracker.finish(first_output_stage)
                                yield _sse_frame(
                                    "agent_event",
                                    runtime_stage_event(first_output_stage),
                                )
                            if event_type == "REPLY_END":
                                # AgentScope publishes the correlated durable
                                # completion immediately after this event. Hold
                                # REPLY_END for that brief interval so team
                                # state can be annotated without another HTTP
                                # status probe.
                                completion_relay.hold_reply_end(runtime_event)
                                event_task = asyncio.create_task(anext(events))
                                continue
                            if completion_relay.handles(runtime_event):
                                reply_end = completion_relay.consume(
                                    runtime_event,
                                )
                                if reply_end is not None:
                                    yield _sse_frame(
                                        "agent_event",
                                        reply_end,
                                    )
                                event_task = asyncio.create_task(anext(events))
                                continue
                            if event_type == "MODEL_CALL_START":
                                model_name = str(
                                    runtime_event.get("model_name") or "",
                                )
                                if (
                                    model_name
                                    and model_name
                                    not in trace_summary["model_names"]
                                ):
                                    trace_summary["model_names"].append(
                                        model_name,
                                    )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "state_updated"
                            ):
                                value = runtime_event.get("value") or {}
                                trace_summary["tasks_context"] = value.get(
                                    "tasks_context",
                                )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "team_updated"
                            ):
                                trace_summary["team_update_count"] += 1
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "collaboration_member_updated"
                            ):
                                value = runtime_event.get("value") or {}
                                if isinstance(value, dict):
                                    _upsert_collaboration_member(
                                        trace_summary,
                                        value,
                                    )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_require_user_confirm"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary["subagent_hitl"]
                                    if (
                                        str(
                                            entry.get(
                                                "worker_session_id",
                                            )
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                                trace_summary["subagent_hitl"].append(value)
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_user_confirm_result"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary["subagent_hitl"]
                                    if (
                                        str(
                                            entry.get(
                                                "worker_session_id",
                                            )
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                            yield _sse_frame("agent_event", runtime_event)
                            event_task = asyncio.create_task(anext(events))

                    if chat_task in completed:
                        pending_reply_end = (
                            completion_relay.flush_reply_end()
                        )
                        if pending_reply_end is not None:
                            yield _sse_frame(
                                "agent_event",
                                pending_reply_end,
                            )
                        reply = chat_task.result()
                        break

                if event_task is not None and not event_task.done():
                    event_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await event_task

            if dispatch_stage.finished_at is None:
                stage_tracker.finish(dispatch_stage, status="completed")
            if first_output_stage.finished_at is None:
                stage_tracker.finish(first_output_stage, status="no_visible_output")
            stage_tracker.finish(execution_stage)
            stage_tracker.finish(total_stage)
            trace_summary["stages"] = stage_tracker.snapshot()
            for stage in (dispatch_stage, first_output_stage, execution_stage, total_stage):
                yield _sse_frame(
                    "agent_event",
                    runtime_stage_event(stage),
                )
            persisted = await asyncio.to_thread(
                _finalize_agent_reply,
                conversation_id,
                reply,
                trace_summary,
            )
            if persisted is None:
                raise AgentScopeGatewayError(
                    "平台会话已被删除，无法保存智能体回复。",
                    status_code=409,
                )
            yield _sse_frame(
                "done",
                {
                    "message": persisted,
                    "runtime_status": reply.status,
                },
            )
        except asyncio.CancelledError:
            if chat_task is not None:
                asyncio.create_task(
                    _finalize_agent_reply_after_disconnect(
                        chat_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
            raise
        except Exception as exc:  # noqa: BLE001
            for stage in (
                dispatch_stage,
                first_output_stage,
                execution_stage,
                total_stage,
            ):
                if stage.finished_at is None:
                    stage_tracker.finish(stage, status="error")
            trace_summary["stages"] = stage_tracker.snapshot()
            if event_task is not None and not event_task.done():
                event_task.cancel()
            if chat_task is not None and not chat_task.done():
                asyncio.create_task(
                    _finalize_agent_reply_after_disconnect(
                        chat_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
            else:
                await asyncio.to_thread(
                    _record_agent_turn_error,
                    conversation_id,
                    str(exc),
                )
            status_code = (
                exc.status_code
                if isinstance(exc, AgentScopeGatewayError)
                else 500
            )
            yield _sse_frame(
                "error",
                {
                    "detail": str(exc),
                    "status_code": status_code,
                },
            )

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent-conversations/{conversation_id}/interrupt")
def interrupt_agent_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(status_code=409, detail="智能体会话尚未完成初始化")
    try:
        result = _agentscope_client().interrupt(
            agent_id=conversation.agent_id,
            session_id=conversation.agentscope_session_id,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    conversation.status = "interrupting"
    db.commit()
    return ok(result, "已请求停止智能体")


@router.post("/agent-conversations/{conversation_id}/confirm")
def confirm_agent_conversation_tool(
    conversation_id: int,
    payload: AgentConversationConfirmInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(status_code=409, detail="智能体会话尚未完成初始化")
    try:
        client = _agentscope_client()
        catalog = client.get_catalog()
        _catalog_agent_for_conversation(catalog, conversation, db=db)
        reply = client.confirm_tool_call(
            agent_id=conversation.agent_id,
            session_id=conversation.agentscope_session_id,
            reply_id=payload.reply_id,
            tool_call=payload.tool_call,
            confirmed=payload.confirmed,
            rules=payload.rules,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    if reply.projected:
        return ok(
            {
                "message": None,
                "runtime_status": reply.status,
            },
            reply.content,
        )
    persisted = _finalize_agent_reply(conversation.id, reply)
    if persisted is None:
        raise HTTPException(status_code=409, detail="平台智能体会话已被删除")
    return ok(
        {
            "message": persisted,
            "runtime_status": reply.status,
        },
        "人工确认结果已处理",
    )


@router.post("/agent-conversations/{conversation_id}/confirm/stream")
def stream_agent_conversation_tool_confirmation(
    conversation_id: int,
    payload: AgentConversationConfirmInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Submit a HITL decision and relay the resumed AgentScope turn."""
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(status_code=409, detail="智能体会话尚未完成初始化")

    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        _catalog_agent_for_conversation(catalog, conversation, db=db)
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)

    agent_id = conversation.agent_id
    session_id = conversation.agentscope_session_id

    accepted_payload = {
        "conversation_id": conversation.id,
        "runtime_status": "running",
        "message": (
            f"已允许「{payload.tool_call.get('name', '工具')}」，"
            "智能体正在继续执行。"
            if payload.confirmed
            else f"已拒绝「{payload.tool_call.get('name', '工具')}」，"
            "智能体正在处理确认结果。"
        ),
    }

    async def relay() -> Any:
        confirm_task: asyncio.Task[AgentScopeReply] | None = None
        event_task: asyncio.Task[dict[str, Any]] | None = None
        reply_handed_off = False
        trace_summary: dict[str, Any] = {
            "model_names": [],
            "tasks_context": None,
            "team_update_count": 0,
            "collaborations": [],
            "subagent_hitl": [],
        }
        try:
            async with client.event_stream(session_id, agent_id) as events:
                submission = await asyncio.to_thread(
                    client.submit_tool_confirmation,
                    agent_id=agent_id,
                    session_id=session_id,
                    reply_id=payload.reply_id,
                    tool_call=payload.tool_call,
                    confirmed=payload.confirmed,
                    rules=payload.rules,
                )
                await asyncio.to_thread(
                    _mark_agent_turn_running,
                    conversation_id,
                )
                confirm_task = asyncio.create_task(
                    asyncio.to_thread(
                        client.wait_for_tool_confirmation,
                        agent_id=agent_id,
                        session_id=session_id,
                        reply_id=payload.reply_id,
                        tool_call=payload.tool_call,
                        submission=submission,
                    ),
                )
                event_task = asyncio.create_task(anext(events))
                # Do not acknowledge until AgentScope has validated that this
                # exact tool call is still waiting and accepted the decision.
                yield _sse_frame("accepted", accepted_payload)

                while True:
                    waiting: set[asyncio.Task[Any]] = {confirm_task}
                    if event_task is not None:
                        waiting.add(event_task)
                    completed, _ = await asyncio.wait(
                        waiting,
                        timeout=15.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not completed:
                        yield ": dobby-agent-heartbeat\n\n"
                        continue

                    if event_task is not None and event_task in completed:
                        try:
                            runtime_event = event_task.result()
                        except StopAsyncIteration:
                            event_task = None
                        else:
                            runtime_event = (
                                await _annotate_collaboration_event(
                                    client,
                                    session_id=session_id,
                                    agent_id=agent_id,
                                    runtime_event=runtime_event,
                                )
                            )
                            event_type = str(runtime_event.get("type") or "")
                            if event_type == "MODEL_CALL_START":
                                model_name = str(
                                    runtime_event.get("model_name") or "",
                                )
                                if (
                                    model_name
                                    and model_name
                                    not in trace_summary["model_names"]
                                ):
                                    trace_summary["model_names"].append(
                                        model_name,
                                    )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "state_updated"
                            ):
                                value = runtime_event.get("value") or {}
                                trace_summary["tasks_context"] = value.get(
                                    "tasks_context",
                                )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "team_updated"
                            ):
                                trace_summary["team_update_count"] += 1
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "collaboration_member_updated"
                            ):
                                value = runtime_event.get("value") or {}
                                if isinstance(value, dict):
                                    _upsert_collaboration_member(
                                        trace_summary,
                                        value,
                                    )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_require_user_confirm"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary[
                                        "subagent_hitl"
                                    ]
                                    if (
                                        str(
                                            entry.get("worker_session_id")
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                                trace_summary["subagent_hitl"].append(value)
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_user_confirm_result"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary[
                                        "subagent_hitl"
                                    ]
                                    if (
                                        str(
                                            entry.get("worker_session_id")
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                            yield _sse_frame("agent_event", runtime_event)
                            event_task = asyncio.create_task(anext(events))

                    if confirm_task in completed:
                        reply = confirm_task.result()
                        break

                if event_task is not None and not event_task.done():
                    event_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await event_task

            if reply.projected:
                reply_handed_off = True
                yield _sse_frame(
                    "done",
                    {
                        "message": None,
                        "runtime_status": reply.status,
                    },
                )
                return

            persisted = await asyncio.to_thread(
                _finalize_agent_reply,
                conversation_id,
                reply,
                trace_summary,
            )
            if persisted is None:
                raise AgentScopeGatewayError(
                    "平台会话已被删除，无法保存智能体回复。",
                    status_code=409,
                )
            reply_handed_off = True
            yield _sse_frame(
                "done",
                {
                    "message": persisted,
                    "runtime_status": reply.status,
                },
            )
        except asyncio.CancelledError:
            if confirm_task is not None:
                asyncio.create_task(
                    _finalize_agent_reply_after_disconnect(
                        confirm_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
                reply_handed_off = True
            raise
        except Exception as exc:  # noqa: BLE001
            if event_task is not None and not event_task.done():
                event_task.cancel()
            if confirm_task is not None and not confirm_task.done():
                asyncio.create_task(
                    _finalize_agent_reply_after_disconnect(
                        confirm_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
                reply_handed_off = True
            elif confirm_task is not None:
                await asyncio.to_thread(
                    _record_agent_turn_error,
                    conversation_id,
                    str(exc),
                )
                reply_handed_off = True
            status_code = (
                exc.status_code
                if isinstance(exc, AgentScopeGatewayError)
                else 500
            )
            yield _sse_frame(
                "error",
                {
                    "detail": str(exc),
                    "status_code": status_code,
                },
            )
        finally:
            if event_task is not None and not event_task.done():
                event_task.cancel()
                with suppress(asyncio.CancelledError):
                    await event_task
            if confirm_task is not None and not reply_handed_off:
                asyncio.create_task(
                    _finalize_agent_reply_after_disconnect(
                        confirm_task,
                        conversation_id,
                        trace_summary,
                    ),
                )

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
