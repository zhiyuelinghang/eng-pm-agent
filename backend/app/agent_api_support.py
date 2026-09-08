from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agentscope_client import (
    AgentScopeClient,
    AgentScopeGatewayError,
    AgentScopeReply,
)
from .api_common import project_for_user_or_403, serialize
from .config import get_settings
from .db import SessionLocal
from .engineering_document_catalog import (
    _catalogue_access_is_open,
    local_catalogue_knowledge_base_ids,
    readable_external_ids,
)
from .initialization_attachment_store import (
    InitializationAttachmentParseError,
    initialization_attachment_manifest,
    initialization_attachment_summary,
)
from .models import (
    AgentConversation,
    EngineeringDocumentNode,
    EngineeringDocumentSyncState,
    EngineeringKnowledgeConversation,
    EngineeringKnowledgeMessage,
    Project,
    ProjectInitializationFile,
    ProjectSettings,
    User,
)


@lru_cache(maxsize=1)
def _agentscope_client() -> AgentScopeClient:
    return AgentScopeClient(get_settings())


def _project_weknora_agent_id(db: Session, project_id: int) -> str:
    settings = db.get(ProjectSettings, project_id)
    agent_id = (settings.weknora_agent_id or "").strip() if settings else ""
    if not agent_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "当前项目尚未绑定 WeKnora 机器人，请先在智能体管理平台的"
                "“工程知识库 > 项目分配”中完成绑定。"
            ),
        )
    return agent_id


def _raise_agentscope_http_error(exc: AgentScopeGatewayError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _engineering_document_catalogue_state(
    db: Session,
    project_id: int,
    agent_id: str,
) -> EngineeringDocumentSyncState | None:
    """Read local synchronization state without contacting WeKnora."""

    state_row = db.get(EngineeringDocumentSyncState, project_id)
    if state_row is not None and state_row.weknora_agent_id == agent_id:
        return state_row
    return None


def _ready_project_weknora_agent_id(db: Session, project_id: int) -> str:
    agent_id = _project_weknora_agent_id(db, project_id)
    state_row = _engineering_document_catalogue_state(
        db,
        project_id,
        agent_id,
    )
    if state_row is None or state_row.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=(
                "工程资料目录尚未初始化，请先在智能体管理端完成目录同步。"
            ),
        )
    return agent_id


def _public_agent_catalog_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        key: item.get(key)
        for key in (
            "id",
            "name",
            "description",
            "category",
            "role",
            "agent_level",
            "enabled",
            "published",
            "invitable",
            "allow_global_main_call",
            "project_knowledge_enabled",
            "model_ready",
            "sort_order",
            "permission_mode",
            "knowledge_config",
            "initialization_role",
        )
    }


def _public_task_assistant_catalog_item(
    item: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project the assigned agent through the fixed Task Assistant identity."""
    public = _public_agent_catalog_item(item)
    if public is None:
        return None
    public.update(
        {
            "name": "任务助手",
            "description": "分析群聊内容，整理任务草稿",
            "category": "任务协同",
            "role": "system_internal",
            # This dedicated projection is mentionable even though the
            # underlying system agent remains hidden from the business list.
            "published": True,
            "invitable": False,
        },
    )
    return public


def _catalog_agent_for_conversation(
    catalog: dict[str, Any],
    conversation: AgentConversation,
    *, db: Session | None = None,
) -> dict[str, Any]:
    """Resolve a conversation against the latest publication catalogue."""
    if db is not None and conversation.conversation_type == 'business':
        from .knowledge_agent_support import linked_knowledge_conversation, require_knowledge_agent
        if linked_knowledge_conversation(db, conversation) is not None:
            return require_knowledge_agent(catalog, conversation.agent_id)
    if conversation.conversation_type == "general":
        selected = catalog.get("global_main")
        if selected is None or selected.get("id") != conversation.agent_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "平台全局主智能体已停用或发生切换，请刷新页面后开始"
                    "新的主智能体会话"
                ),
            )
    elif conversation.conversation_type == "initialization":
        selected = catalog.get("project_initializer")
        if selected is None or selected.get("id") != conversation.agent_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "项目初始化智能体已停用或发生切换，请刷新工程配置页"
                    "后重新开始初始化会话"
                ),
            )
    else:
        selected = next(
            (
                item
                for item in catalog.get("business_agents", [])
                if item.get("id") == conversation.agent_id
            ),
            None,
        )
        if selected is None:
            raise HTTPException(
                status_code=409,
                detail="该业务智能体已停用或取消发布，请刷新业务工具页面",
            )
    if not selected.get("model_ready"):
        raise HTTPException(
            status_code=409,
            detail=f"智能体「{selected.get('name')}」尚未配置固定模型",
        )
    return selected


def _platform_session_context(
    user: User,
    project: Project,
    conversation: AgentConversation,
    db: Session | None = None,
    *,
    knowledge_query_enabled: bool | None = None,
) -> dict[str, Any]:
    """Build the grouping snapshot stored with the AgentScope session."""
    if knowledge_query_enabled is False or (
        knowledge_query_enabled is None and conversation.conversation_type == "general"
    ):
        return {
            "user_id": str(user.id), "username": user.username,
            "display_name": user.real_name, "project_id": str(project.id),
            "project_name": project.name, "conversation_id": str(conversation.id),
            "conversation_title": conversation.title,
            "conversation_type": conversation.conversation_type,
            "agent_name": conversation.agent_name, "weknora_query_enabled": False,
            "session_role": "primary", "auto_allowed_tool_names": [],
        }
    project_settings = db.get(ProjectSettings, project.id) if db else None
    weknora_agent_id = (
        (project_settings.weknora_agent_id or "").strip() or None
        if project_settings is not None
        else None
    )
    query_enabled = (
        conversation.conversation_type != "general"
        if knowledge_query_enabled is None
        else knowledge_query_enabled
    )
    catalogue_state = (
        _engineering_document_catalogue_state(
            db,
            project.id,
            weknora_agent_id,
        )
        if db is not None and weknora_agent_id
        else None
    )
    knowledge_base_ids: list[str] = []
    knowledge_ids: list[str] = []
    user_role = str(getattr(user, "role", "user"))
    knowledge_access_mode = (
        str(getattr(catalogue_state, "access_mode", "project"))
        if catalogue_state is not None and user_role != "admin"
        else "project"
    )
    if (
        db is not None
        and query_enabled
        and catalogue_state is not None
        and getattr(catalogue_state, "status", "") == "ready"
    ):
        if not _catalogue_access_is_open(db, project.id, user):
            knowledge_access_mode = "restricted"
        knowledge_base_ids = local_catalogue_knowledge_base_ids(db, project.id)
        readable_ids = readable_external_ids(
            db,
            project.id,
            user,
            knowledge_base_ids,
        )
        knowledge_ids = sorted(readable_ids)
        if readable_ids:
            # Always use a document allowlist, even when project-wide access is
            # open. This prevents a robot shared by several catalogue scopes
            # from reaching files outside this project selection.
            knowledge_base_ids = sorted(
                {
                    str(value)
                    for value in db.scalars(
                        select(EngineeringDocumentNode.knowledge_base_id).where(
                            EngineeringDocumentNode.project_id == project.id,
                            EngineeringDocumentNode.node_type == "file",
                            EngineeringDocumentNode.external_id.in_(readable_ids),
                        ),
                    ).all()
                    if value
                },
            )
        else:
            knowledge_base_ids = []
    return {
        "user_id": str(user.id),
        "username": user.username,
        "display_name": user.real_name,
        "project_id": str(project.id),
        "project_name": project.name,
        "conversation_id": str(conversation.id),
        "conversation_title": conversation.title,
        "conversation_type": conversation.conversation_type,
        "agent_name": conversation.agent_name,
        "weknora_agent_id": weknora_agent_id,
        "weknora_catalogue_ready": bool(
            catalogue_state is not None
            and getattr(catalogue_state, "status", "") == "ready"
        ),
        "weknora_query_enabled": bool(query_enabled),
        "weknora_access_mode": knowledge_access_mode,
        "weknora_knowledge_base_ids": knowledge_base_ids,
        "weknora_knowledge_ids": knowledge_ids,
        "session_role": "primary",
        "auto_allowed_tool_names": [],
    }


def _agent_conversation_or_404(
    db: Session,
    conversation_id: int,
    user: User,
) -> AgentConversation:
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="智能体会话不存在")
    if conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该智能体会话")
    project_for_user_or_403(db, conversation.project_id, user)
    return conversation


def _engineering_knowledge_conversation_or_404(
    db: Session,
    project_id: int,
    conversation_id: int,
    user: User,
) -> EngineeringKnowledgeConversation:
    conversation = db.get(EngineeringKnowledgeConversation, conversation_id)
    if (
        conversation is None
        or conversation.project_id != project_id
        or conversation.user_id != user.id
    ):
        raise HTTPException(status_code=404, detail="知识库对话不存在")
    project_for_user_or_403(db, project_id, user)
    return conversation


def _engineering_knowledge_conversation_view(
    conversation: EngineeringKnowledgeConversation,
) -> dict[str, Any]:
    return serialize(conversation)


def _engineering_knowledge_message_view(
    message: EngineeringKnowledgeMessage,
    allowed_knowledge_ids: set[str] | None = None,
) -> dict[str, Any]:
    result = serialize(message)
    if allowed_knowledge_ids is None or message.role != "assistant":
        return result
    references = result.get("references")
    if not isinstance(references, list):
        return result
    authorized_references: list[dict[str, Any]] = []
    contains_unauthorized_reference = False
    for reference in references:
        if not isinstance(reference, dict):
            contains_unauthorized_reference = True
            continue
        knowledge_id = str(reference.get("knowledge_id") or "").strip()
        if not knowledge_id or knowledge_id not in allowed_knowledge_ids:
            contains_unauthorized_reference = True
            continue
        authorized_references.append(reference)
    if contains_unauthorized_reference:
        result["content"] = "该历史回答包含当前无权访问的资料，内容已隐藏。"
        result["references"] = []
        result["failed"] = True
    else:
        result["references"] = authorized_references
    return result


def _restricted_engineering_knowledge_ids(
    db: Session,
    project_id: int,
    user: User,
) -> set[str] | None:
    state_row = db.get(EngineeringDocumentSyncState, project_id)
    if _catalogue_access_is_open(db, project_id, user):
        return None
    return readable_external_ids(db, project_id, user)


def _reset_unsafe_engineering_knowledge_session(
    db: Session,
    project_id: int,
    user: User,
    request_body: dict[str, Any],
) -> dict[str, Any]:
    """Discard a remote session whose stored answer crossed today's ACL."""

    allowed_knowledge_ids = _restricted_engineering_knowledge_ids(
        db,
        project_id,
        user,
    )
    session_id = str(request_body.get("session_id") or "").strip()
    if allowed_knowledge_ids is None or not session_id:
        return request_body
    conversation = db.scalar(
        select(EngineeringKnowledgeConversation).where(
            EngineeringKnowledgeConversation.project_id == project_id,
            EngineeringKnowledgeConversation.user_id == user.id,
            EngineeringKnowledgeConversation.weknora_session_id == session_id,
        ),
    )
    if conversation is None:
        return request_body
    references = db.scalars(
        select(EngineeringKnowledgeMessage.references).where(
            EngineeringKnowledgeMessage.conversation_id == conversation.id,
            EngineeringKnowledgeMessage.role == "assistant",
        ),
    ).all()
    for reference_group in references:
        if not isinstance(reference_group, list):
            continue
        for reference in reference_group:
            knowledge_id = (
                str(reference.get("knowledge_id") or "").strip()
                if isinstance(reference, dict)
                else ""
            )
            if not knowledge_id or knowledge_id not in allowed_knowledge_ids:
                return {**request_body, "session_id": None}
    return request_body


INITIALIZATION_FILE_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".xls",
    ".xlsx",
    ".docx",
    ".pptx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}
INITIALIZATION_FILE_MAX_BYTES = 30 * 1024 * 1024


def _public_initialization_file(
    row: ProjectInitializationFile,
    db: Session | None = None,
) -> dict[str, Any]:
    result = {
        "id": row.id,
        "project_id": row.project_id,
        "conversation_id": row.conversation_id,
        "uploaded_by_user_id": row.uploaded_by_user_id,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if db is not None:
        result["attachment_preprocessing"] = (
            initialization_attachment_summary(db, row)
        )
    return result


def _initialization_files_for_message(
    db: Session,
    conversation: AgentConversation,
    file_ids: list[int],
) -> list[ProjectInitializationFile]:
    unique_ids = list(dict.fromkeys(file_ids))
    if not unique_ids:
        return []
    if conversation.conversation_type != "initialization":
        raise HTTPException(
            status_code=422,
            detail="只有项目初始化会话可以携带初始化附件",
        )
    rows = db.scalars(
        select(ProjectInitializationFile).where(
            ProjectInitializationFile.id.in_(unique_ids),
            ProjectInitializationFile.project_id == conversation.project_id,
            ProjectInitializationFile.conversation_id == conversation.id,
        ),
    ).all()
    by_id = {row.id: row for row in rows}
    if any(file_id not in by_id for file_id in unique_ids):
        raise HTTPException(
            status_code=422,
            detail="初始化附件不存在或不属于当前会话",
        )
    return [by_id[file_id] for file_id in unique_ids]


def _initialization_attachment_manifest_context(
    db: Session,
    files: list[ProjectInitializationFile],
) -> str:
    """Inject only bounded parsed-data references into the leader context."""
    if not files:
        return ""
    try:
        manifest = initialization_attachment_manifest(db, files)
    except InitializationAttachmentParseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return (
        "\n<parsed-attachment-manifest>\n"
        + json.dumps(manifest, ensure_ascii=False)
        + "\n</parsed-attachment-manifest>"
    )


def _initialization_file_refs(
    files: list[ProjectInitializationFile],
) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "name": item.file_name,
            "size": item.file_size,
            "content_type": item.content_type,
        }
        for item in files
    ]


def _build_agent_project_context(
    db: Session,
    project: Project,
    user: User,
    *,
    knowledge_query_enabled: bool | None = None,
) -> str:
    """Build the immutable authorization boundary for one agent turn.

    Live project facts deliberately do not belong in this envelope.  The
    global controller receives only the caller/project identity here and
    obtains WBS, risk, task, member, or other business data through the
    database interactions assigned in AgentScope management.  Besides
    keeping that configuration authoritative, this prevents every ordinary
    greeting from carrying a duplicated project snapshot in conversation
    history.
    """
    del db  # Kept in the signature for the existing platform call sites.
    if knowledge_query_enabled is True:
        knowledge_context = (
            "\n工程资料：用户本轮已明确点名 @资料助手。必须调用 "
            "weknora_query_project_knowledge，并仅依据该工具返回的授权资料"
            "组织回答；不得补写未检索到的资料内容，也不得使用旧的本地附件表"
            "推断工程资料。"
        )
    elif knowledge_query_enabled is False:
        knowledge_context = (
            "\n工程资料：用户本轮没有点名 @资料助手，不得调用资料查询工具，"
            "也不得声称已查询项目知识库。"
        )
    else:
        knowledge_context = ""
    return (
        "<platform-context>\n"
        "以下内容由工程管理平台后端按当前登录状态生成，仅用于限定本轮身份、"
        "项目和权限边界；业务事实必须按需调用管理中心已分配的工具读取，不得"
        "根据未查询的数据自行补写。\n"
        f"当前登录用户ID：{user.id}；账号显示名：{user.real_name}；系统角色：{user.role}\n"
        "账号显示名仅为平台资料标签，可以与用户自报姓名或希望的称呼不同；称呼偏好不改变此处的登录身份与权限。\n"
        f"当前项目：{project.name}（项目ID {project.id}）\n"
        + knowledge_context
        + "\n</platform-context>"
    )


def _agent_reply_extra_data(
    reply: AgentScopeReply,
    trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project AgentScope-owned runtime data into the platform API shape."""
    runtime_messages = reply.raw_messages or (
        [reply.raw_message] if reply.raw_message else []
    )
    result: dict[str, Any] = {
        "status": reply.status,
        "agentscope_message": reply.raw_message,
        "agentscope_messages": runtime_messages,
    }
    resolved_trace = _resolved_runtime_trace(reply, trace_summary)
    if isinstance(resolved_trace, dict):
        result["runtime_trace"] = resolved_trace
    source = reply.raw_message or (
        reply.raw_messages[-1] if reply.raw_messages else {}
    )
    metadata = source.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("platform_task_draft_id"):
        result["task_draft_id"] = int(metadata["platform_task_draft_id"])
    return result


_ACTIVE_AGENT_REPLY_STATUSES = frozenset(
    {
        "creating",
        "running",
        "interrupting",
        "awaiting_permission",
        "awaiting_external_result",
    },
)


def _resolved_runtime_trace(
    reply: AgentScopeReply,
    trace_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge runtime metadata and attach one stable clock to the whole turn."""
    runtime_messages = reply.raw_messages or (
        [reply.raw_message] if reply.raw_message else []
    )
    persisted_traces: list[dict[str, Any]] = []
    for message in runtime_messages:
        metadata = message.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        candidate = metadata.get("platform_runtime_trace")
        if isinstance(candidate, dict):
            persisted_traces.append(candidate)

    if not trace_summary and not persisted_traces:
        resolved: dict[str, Any] = {}
    else:
        resolved = {}
        for persisted in persisted_traces:
            resolved.update(persisted)
        if trace_summary:
            resolved.update(trace_summary)
    # Used only while materializing a Dobby-orchestrated private task draft;
    # the ordinary message already stores this text, so do not duplicate it
    # inside runtime telemetry metadata.
    resolved.pop("platform_user_request", None)

    started_at = (
        (trace_summary or {}).get("turn_started_at")
        or next(
            (
                persisted.get("turn_started_at")
                for persisted in persisted_traces
                if persisted.get("turn_started_at")
            ),
            None,
        )
        or next(
            (
                message.get("created_at")
                for message in runtime_messages
                if message.get("created_at")
            ),
            None,
        )
    )
    if started_at:
        resolved["turn_started_at"] = str(started_at)

    if reply.status in _ACTIVE_AGENT_REPLY_STATUSES:
        resolved["turn_finished_at"] = None
    else:
        finished_at = next(
            (
                message.get("finished_at")
                for message in reversed(runtime_messages)
                if message.get("finished_at")
            ),
            None,
        )
        if started_at and finished_at:
            resolved["turn_finished_at"] = str(finished_at)

    return resolved or None


def _message_text(message: dict[str, Any]) -> str:
    return "\n".join(
        str(block.get("text") or "")
        for block in message.get("content", [])
        if isinstance(block, dict)
        and block.get("type") == "text"
        and block.get("text")
    )


def _tagged_content(text: str, tag: str) -> str | None:
    matched = re.search(
        rf"<{re.escape(tag)}>\s*(.*?)\s*</{re.escape(tag)}>",
        text,
        flags=re.DOTALL,
    )
    return matched.group(1).strip() if matched else None


def _conversation_title_from_content(content: str) -> str:
    """Use the first sentence the user actually wrote as the chat title."""
    request = re.search(
        r"(?:^|\n)用户请求[：:]\s*(.*)$",
        str(content or ""),
        flags=re.DOTALL,
    )
    source = request.group(1) if request else str(content or "")
    first_line = next(
        (line.strip() for line in source.splitlines() if line.strip()),
        "",
    )
    normalized = re.sub(r"\s+", " ", first_line).strip()
    if not normalized:
        return "新对话"
    sentence = re.match(r"^.*?[。！？!?]|^.*?\.(?=\s|$)", normalized)
    title = sentence.group(0) if sentence else normalized
    if len(title) > 300:
        return title[:299].rstrip() + "…"
    return title


def _adopt_initial_conversation_title(
    conversation: AgentConversation,
    content: str,
) -> None:
    default_suffix = {
        "general": " · 智能协同",
        "initialization": " · 项目初始化",
    }.get(conversation.conversation_type)
    if default_suffix and conversation.title.endswith(default_suffix):
        conversation.title = _conversation_title_from_content(content)


def _initialization_files_from_agentscope_message(
    message: dict[str, Any],
) -> list[dict[str, Any]]:
    metadata = message.get("metadata") or {}
    stored = (
        metadata.get("platform_initialization_files")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(stored, list):
        return []
    return [item for item in stored if isinstance(item, dict)]


def _project_agentscope_user_message(
    conversation_id: int,
    message: dict[str, Any],
) -> dict[str, Any]:
    metadata = message.get("metadata") or {}
    display_content = (
        metadata.get("platform_display_content")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(display_content, str):
        display_content = _tagged_content(
            _message_text(message),
            "user-request",
        )
    if display_content is None:
        display_content = _message_text(message)
    return {
        "id": str(message.get("id") or uuid4().hex),
        "conversation_id": conversation_id,
        "role": "user",
        "content": display_content,
        "extra_data": {
            "initialization_files": (
                _initialization_files_from_agentscope_message(message)
            ),
            "attachment_preprocessing": (
                metadata.get("attachment_preprocessing")
                if isinstance(metadata, dict)
                else None
            ),
        },
        "created_at": str(
            message.get("created_at") or datetime.now(UTC).isoformat(),
        ),
    }


def _project_agentscope_reply(
    conversation_id: int,
    reply: AgentScopeReply,
    trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = reply.raw_message or (
        reply.raw_messages[-1] if reply.raw_messages else {}
    )
    metadata = source.get("metadata")
    display_content = (
        metadata.get("platform_display_content")
        if isinstance(metadata, dict)
        else None
    )
    return {
        "id": str(source.get("id") or reply.message_id or uuid4().hex),
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": str(display_content or reply.content),
        "agentscope_message_id": (
            str(source.get("id"))
            if source.get("id") is not None
            else reply.message_id
        ),
        "extra_data": _agent_reply_extra_data(reply, trace_summary),
        "created_at": str(
            source.get("created_at") or datetime.now(UTC).isoformat(),
        ),
    }


def _finalize_agent_reply(
    conversation_id: int,
    reply: AgentScopeReply,
    trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Annotate the AgentScope source message and update conversation state."""
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, conversation_id)
        if conversation is None:
            return None
        if not conversation.agentscope_session_id:
            return None
        client = _agentscope_client()
        runtime_messages = reply.raw_messages or (
            [reply.raw_message] if reply.raw_message else []
        )
        final_message = next(
            (
                message
                for message in reversed(runtime_messages)
                if str(message.get("id") or "")
                == str(reply.message_id or "")
            ),
            reply.raw_message,
        )
        resolved_trace = _resolved_runtime_trace(reply, trace_summary)
        from .dobby_task_draft_bridge import (  # noqa: PLC0415
            materialize_dobby_task_draft,
        )

        task_draft = materialize_dobby_task_draft(
            db,
            conversation,
            reply,
            user_request=str(
                (trace_summary or {}).get("platform_user_request") or ""
            ),
        )
        if final_message and reply.message_id:
            collaboration_statuses = {
                str(message["id"]): str(
                    message["platform_collaboration_status"],
                )
                for message in runtime_messages
                if message.get("id")
                and message.get("platform_collaboration_status")
            }
            metadata_update: dict[str, Any] = {
                "platform_status": reply.status,
            }
            if collaboration_statuses:
                metadata_update["platform_collaboration_statuses"] = (
                    collaboration_statuses
                )
            if resolved_trace:
                metadata_update["platform_runtime_trace"] = resolved_trace
            if task_draft is not None:
                metadata_update.update(
                    {
                        "platform_task_draft_id": task_draft[0],
                        "platform_display_content": task_draft[1],
                    },
                )
            updated = client.update_message_metadata(
                conversation.agentscope_session_id,
                conversation.agent_id,
                str(reply.message_id),
                metadata_update,
            )
            final_message["metadata"] = updated.get(
                "metadata",
                {
                    **(final_message.get("metadata") or {}),
                    **metadata_update,
                },
            )
        conversation.status = reply.status
        conversation.last_error = None
        conversation.updated_at = datetime.now(UTC)
        db.commit()
        return _project_agentscope_reply(
            conversation.id,
            reply,
            resolved_trace,
        )


def _agentscope_assistant_groups(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group assistant replies belonging to each AgentScope user turn."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role == "user":
            if current:
                groups.append(current)
                current = []
        elif role == "assistant":
            current.append(message)
    if current:
        groups.append(current)
    return groups


def _agentscope_platform_messages(
    conversation_id: int,
    messages: list[dict[str, Any]],
    live_status: str,
) -> list[dict[str, Any]]:
    """Project one authorized AgentScope history without a local mirror."""
    result: list[dict[str, Any]] = []
    assistant_group: list[dict[str, Any]] = []

    def flush_assistants(*, latest: bool) -> None:
        if not assistant_group:
            return
        final_metadata = assistant_group[-1].get("metadata") or {}
        persisted_statuses = (
            final_metadata.get("platform_collaboration_statuses")
            if isinstance(final_metadata, dict)
            else None
        )
        if isinstance(persisted_statuses, dict):
            for grouped_message in assistant_group:
                grouped_message_id = str(grouped_message.get("id") or "")
                collaboration_status = persisted_statuses.get(
                    grouped_message_id,
                )
                if collaboration_status:
                    grouped_message["platform_collaboration_status"] = (
                        collaboration_status
                    )
        result.append(
            _project_agentscope_reply(
                conversation_id,
                _agentscope_reply_from_group(
                    list(assistant_group),
                    live_status if latest else "idle",
                ),
            ),
        )
        assistant_group.clear()

    for source in messages:
        role = str(source.get("role") or "")
        metadata = source.get("metadata") or {}
        message = dict(source)
        if isinstance(metadata, dict):
            collaboration_status = metadata.get(
                "platform_collaboration_status",
            )
            if collaboration_status:
                message["platform_collaboration_status"] = (
                    collaboration_status
                )
        if role == "user":
            flush_assistants(latest=False)
            result.append(
                _project_agentscope_user_message(
                    conversation_id,
                    message,
                ),
            )
        elif role == "assistant":
            assistant_group.append(message)
    flush_assistants(latest=True)
    return result


def _agentscope_reply_from_group(
    messages: list[dict[str, Any]],
    live_status: str,
) -> AgentScopeReply:
    """Project one AgentScope turn into the platform's durable reply shape."""
    last = messages[-1]
    metadata = last.get("metadata") or {}
    persisted_status = (
        metadata.get("platform_status")
        if isinstance(metadata, dict)
        else None
    )
    finished_reason = str(last.get("finished_reason") or "")
    if last.get("error") or finished_reason == "error":
        status_value = "error"
    elif finished_reason == "interrupted":
        status_value = "interrupted"
    elif persisted_status:
        status_value = str(persisted_status)
    elif live_status not in {"idle", "active", "completed"}:
        status_value = live_status
    elif last.get("finished_at") is not None:
        status_value = "completed"
    else:
        status_value = live_status
    content = AgentScopeClient._message_text(last)
    if not content:
        content = (
            "智能体执行已中断，未产生可显示的文本。"
            if status_value == "interrupted"
            else "智能体尚未产生可显示的文本。"
        )
    return AgentScopeReply(
        status=status_value,
        content=content,
        message_id=(
            str(last.get("id"))
            if last.get("id") is not None
            else None
        ),
        raw_message=last,
        raw_messages=messages,
    )


def _record_agent_turn_error(conversation_id: int, detail: str) -> None:
    """Persist a transport/runtime failure after an SSE response has begun."""
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, conversation_id)
        if conversation is None:
            return
        conversation.status = "error"
        conversation.last_error = detail
        conversation.updated_at = datetime.now(UTC)
        db.commit()


def _mark_agent_turn_running(conversation_id: int) -> None:
    """Persist that AgentScope accepted a resumed confirmation turn."""
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, conversation_id)
        if conversation is None:
            return
        conversation.status = "running"
        conversation.last_error = None
        conversation.updated_at = datetime.now(UTC)
        db.commit()


def _sse_frame(event: str, data: Any) -> str:
    """Serialize one named Server-Sent Event frame."""
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _upsert_collaboration_member(
    trace_summary: dict[str, Any],
    value: dict[str, Any],
) -> None:
    """Keep the newest durable progress projection for one team member."""
    worker_session_id = str(value.get("worker_session_id") or "")
    if not worker_session_id:
        return
    current = list(trace_summary.get("collaborations") or [])
    trace_summary["collaborations"] = [
        entry
        for entry in current
        if str(entry.get("worker_session_id") or "") != worker_session_id
    ]
    trace_summary["collaborations"].append(value)


async def _annotate_collaboration_event(
    client: AgentScopeClient,
    *,
    session_id: str,
    agent_id: str,
    runtime_event: dict[str, Any],
) -> dict[str, Any]:
    """Keep an interim leader reply open while team members still work."""
    if str(runtime_event.get("type") or "") != "REPLY_END":
        return runtime_event
    collaboration_pending = await asyncio.to_thread(
        client.session_team_work_pending,
        session_id,
        agent_id,
    )
    if not collaboration_pending:
        return runtime_event
    return {
        **runtime_event,
        "platform_collaboration_pending": True,
    }


async def _finalize_agent_reply_after_disconnect(
    chat_task: asyncio.Task[AgentScopeReply],
    conversation_id: int,
    trace_summary: dict[str, Any],
) -> None:
    """Finish source annotation when the browser closes an in-flight stream."""
    try:
        reply = await asyncio.shield(chat_task)
        if reply.projected:
            return
        await asyncio.to_thread(
            _finalize_agent_reply,
            conversation_id,
            reply,
            trace_summary,
        )
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(
            _record_agent_turn_error,
            conversation_id,
            str(exc),
        )


def _turn_platform_context(
    db: Session,
    user: User,
    project: Project,
    conversation: AgentConversation,
    content: str,
) -> tuple[dict[str, Any], bool | None]:
    """Build a fresh authorization envelope for one agent turn."""
    from .knowledge_agent_support import linked_knowledge_conversation
    knowledge_entry = linked_knowledge_conversation(db, conversation)
    if knowledge_entry is not None:
        knowledge_entry.updated_at = datetime.now(UTC)
        # Greetings must not enumerate documents or contact WeKnora. The tool
        # resolves a fresh scope only after the assistant chooses to query it.
        return _platform_session_context(user, project, conversation, db, knowledge_query_enabled=False), None
    if conversation.conversation_type != "general":
        return (
            _platform_session_context(user, project, conversation, db),
            None,
        )
    explicit_agents = list(
        dict.fromkeys(
            re.findall(r"(?:^|\s)@([^\s@，。！？；：,.!?;:]+)", content),
        ),
    )
    if len(explicit_agents) > 1:
        raise HTTPException(
            status_code=422,
            detail="每条消息最多只能明确提及一个智能体",
        )
    if explicit_agents == ["任务助手"]:
        raise HTTPException(
            status_code=409,
            detail="任务助手需要先生成私有草稿，请通过首页任务助手入口发起。",
        )
    if explicit_agents:
        raise HTTPException(
            status_code=409,
            detail=(
                f"明确 @{explicit_agents[0]} 必须直接进入目标智能体会话，"
                "不能经过 Dobby 路由。"
            ),
        )
    # Discovery does not need a project-document snapshot. A knowledge agent
    # resolves the current document allowlist only when its tool is called.
    platform_context = _platform_session_context(
        user,
        project,
        conversation,
        db,
        knowledge_query_enabled=False,
    )
    return platform_context, None
