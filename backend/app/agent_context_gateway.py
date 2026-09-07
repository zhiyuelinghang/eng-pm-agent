"""Session-bound context and attachment transport for AgentScope.

This router deliberately exposes no business-operation dispatcher. Database
operations are resolved through the editable database-interaction catalogue.
Platform workflows such as project initialization are not exposed here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .engineering_document_catalog import (
    clear_document_catalogue,
    compare_document_catalogue,
    local_catalogue_knowledge_base_ids,
    mark_catalogue_pending,
    sync_document_catalogue_in_background,
    sync_state_view,
)
from .models import (
    AgentConversation,
    EngineeringDocumentSyncState,
    OperationLog,
    Project,
    ProjectMember,
    ProjectSettings,
    User,
)
from .wecom_notification_gateway import (
    WeComDeliveryError,
    safe_wecom_error,
    send_project_wecom_payload,
)


router = APIRouter(prefix="/api/internal/agent-tools", tags=["internal-agent-context"])


@dataclass(frozen=True)
class ToolContext:
    conversation: AgentConversation
    user: User
    project: Project
    membership: ProjectMember | None

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"

    @property
    def can_write(self) -> bool:
        return self.conversation.conversation_type == "general"

    @property
    def can_admin_write(self) -> bool:
        return self.can_write and self.is_admin

    @property
    def can_submit_initialization_draft(self) -> bool:
        """Initialization agents may write only assigned draft interactions."""
        return self.conversation.conversation_type == "initialization"


class ProjectWeKnoraBindingInput(BaseModel):
    """Trusted management request for one project's WeKnora robot."""

    weknora_agent_id: str | None = Field(default=None, max_length=128)


class ProjectCatalogueSelectionInput(BaseModel):
    """Knowledge bases explicitly selected for one project's local mirror."""

    knowledge_base_ids: list[str] = Field(min_length=1, max_length=50)


class WeComRelayInput(BaseModel):
    """A message body whose destination is resolved from the bound session."""

    payload: dict[str, Any]


def ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _selected_knowledge_base_ids(
    payload: ProjectCatalogueSelectionInput,
) -> tuple[str, ...]:
    selected = tuple(
        dict.fromkeys(
            item.strip()
            for item in payload.knowledge_base_ids
            if item.strip()
        ),
    )
    if not selected:
        raise HTTPException(status_code=422, detail="请至少选择一个需要同步的知识库")
    return selected


def require_service_token(
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().effective_agent_tool_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="平台内部能力网关尚未配置服务令牌",
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的平台内部能力网关凭证",
        )


def resolve_tool_context(db: Session, agentscope_session_id: str) -> ToolContext:
    """Resolve the authoritative account and project for one session."""
    conversation = db.scalar(
        select(AgentConversation).where(
            AgentConversation.agentscope_session_id == agentscope_session_id,
        ),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="该会话不属于工程管理平台")
    user = db.get(User, conversation.user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="平台账号不存在")
    project = db.get(Project, conversation.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="会话关联项目不存在")
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        ),
    )
    if user.role != "admin" and membership is None:
        raise HTTPException(status_code=403, detail="当前账号已无权访问该项目")
    return ToolContext(
        conversation=conversation,
        user=user,
        project=project,
        membership=membership,
    )


@router.get("/context", dependencies=[Depends(require_service_token)])
def get_agent_tool_context(
    agentscope_session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = resolve_tool_context(db, agentscope_session_id)
    return ok(
        {
            "conversation_id": context.conversation.id,
            "conversation_type": context.conversation.conversation_type,
            "project_id": context.project.id,
            "user_id": context.user.id,
            "user_role": context.user.role,
            "agent_id": context.conversation.agent_id,
            "capabilities": {
                "read": True,
                "write": context.can_write,
                "admin_write": context.can_admin_write,
                "initialization_draft": (
                    context.can_submit_initialization_draft
                ),
            },
        },
    )


@router.get("/knowledge-scope", dependencies=[Depends(require_service_token)])
def get_agent_knowledge_scope(
    agentscope_session_id: str,
    actor_agent_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recompute document permissions at query time from the bound account."""
    from .agent_api_support import _platform_session_context

    context = resolve_tool_context(db, agentscope_session_id)
    envelope = _platform_session_context(
        context.user, context.project, context.conversation, db,
        knowledge_query_enabled=True,
    )
    scope = {
        key: value for key, value in envelope.items()
        if key.startswith("weknora_")
        or key in {"user_id", "project_id", "conversation_id"}
    }
    db.add(OperationLog(
        project_id=context.project.id, operator_id=context.user.id,
        action="agent_knowledge_authorization", target_type="agent_conversations",
        target_id=context.conversation.id,
        detail=json.dumps({"agent_id": actor_agent_id, "session_id": agentscope_session_id,
                           "scope": scope}, ensure_ascii=False),
    ))
    db.commit()
    return ok(scope)


@router.post(
    "/wecom/messages",
    dependencies=[Depends(require_service_token)],
)
def relay_wecom_message(
    payload: WeComRelayInput,
    agentscope_session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Relay an MCP message through the current session's project Webhook."""

    context = resolve_tool_context(db, agentscope_session_id)
    if not context.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前会话只能读取项目资料，不能发送企业微信消息",
        )
    try:
        result = send_project_wecom_payload(
            db,
            context.project.id,
            payload.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (httpx.HTTPError, WeComDeliveryError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"企业微信消息发送失败：{safe_wecom_error(exc)}",
        ) from exc

    db.add(
        OperationLog(
            project_id=context.project.id,
            operator_id=context.user.id,
            action="Dobby发送企业微信消息",
            detail=f"发送 {result['message_type']} 类型项目群消息",
            target_type="project_connector_config",
        ),
    )
    db.commit()
    return ok(result, "企业微信消息已发送")


@router.get(
    "/weknora-project-bindings",
    dependencies=[Depends(require_service_token)],
)
def list_weknora_project_bindings(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List every existing project and its persisted WeKnora robot binding."""

    rows = db.execute(
        select(Project, ProjectSettings)
        .outerjoin(ProjectSettings, ProjectSettings.project_id == Project.id)
        .order_by(Project.id),
    ).all()
    return ok(
        [
            {
                "project_id": project.id,
                "project_name": project.name,
                "weknora_agent_id": (
                    settings.weknora_agent_id if settings is not None else None
                ),
                "updated_at": (
                    settings.updated_at.isoformat()
                    if settings is not None and settings.updated_at is not None
                    else None
                ),
                "catalogue_sync": sync_state_view(
                    db.get(EngineeringDocumentSyncState, project.id),
                    knowledge_base_ids=local_catalogue_knowledge_base_ids(
                        db,
                        project.id,
                    ),
                ),
            }
            for project, settings in rows
        ],
    )


@router.put(
    "/weknora-project-bindings/{project_id}",
    dependencies=[Depends(require_service_token)],
)
def update_weknora_project_binding(
    project_id: int,
    payload: ProjectWeKnoraBindingInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist the robot selected by the AgentScope management platform."""

    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    row = db.get(ProjectSettings, project_id)
    if row is None:
        row = ProjectSettings(project_id=project_id)
        db.add(row)
    previous_agent_id = (row.weknora_agent_id or "").strip()
    next_agent_id = (
        (payload.weknora_agent_id or "").strip() or None
    )
    row.weknora_agent_id = next_agent_id
    if previous_agent_id != next_agent_id:
        clear_document_catalogue(db, project_id)
    db.commit()
    db.refresh(row)
    state_row = db.get(EngineeringDocumentSyncState, project_id)
    return ok(
        {
            "project_id": project.id,
            "project_name": project.name,
            "weknora_agent_id": row.weknora_agent_id,
            "updated_at": (
                row.updated_at.isoformat() if row.updated_at is not None else None
            ),
            "catalogue_sync": sync_state_view(
                state_row,
                knowledge_base_ids=local_catalogue_knowledge_base_ids(
                    db,
                    project.id,
                ),
            ),
        },
        "项目知识库机器人绑定已保存",
    )


def _project_binding_agent_id(db: Session, project_id: int) -> tuple[Project, str]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    settings = db.get(ProjectSettings, project_id)
    agent_id = (settings.weknora_agent_id or "").strip() if settings else ""
    if not agent_id:
        raise HTTPException(status_code=409, detail="项目尚未绑定 WeKnora 机器人")
    return project, agent_id


@router.post(
    "/weknora-project-bindings/{project_id}/catalogue-sync",
    dependencies=[Depends(require_service_token)],
)
def start_weknora_catalogue_sync(
    project_id: int,
    payload: ProjectCatalogueSelectionInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start an explicit initialization or resynchronization from management."""

    project, agent_id = _project_binding_agent_id(db, project_id)
    knowledge_base_ids = _selected_knowledge_base_ids(payload)
    state_row = mark_catalogue_pending(db, project_id, agent_id)
    db.commit()
    db.refresh(state_row)
    background_tasks.add_task(
        sync_document_catalogue_in_background,
        project_id,
        agent_id,
        knowledge_base_ids,
    )
    return ok(
        {
            "project_id": project.id,
            "project_name": project.name,
            "weknora_agent_id": agent_id,
            "updated_at": None,
            "catalogue_sync": sync_state_view(
                state_row,
                knowledge_base_ids=knowledge_base_ids,
            ),
        },
        "工程资料目录同步已由管理端启动",
    )


@router.post(
    "/weknora-project-bindings/{project_id}/catalogue-diff",
    dependencies=[Depends(require_service_token)],
)
def check_weknora_catalogue_diff(
    project_id: int,
    payload: ProjectCatalogueSelectionInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compare source and mirror only; never update the local catalogue."""

    project, agent_id = _project_binding_agent_id(db, project_id)
    result = compare_document_catalogue(
        db,
        project_id,
        agent_id,
        knowledge_base_ids=_selected_knowledge_base_ids(payload),
    )
    return ok(
        {
            "project_id": project.id,
            "project_name": project.name,
            **result,
        },
        "工程资料目录差异校验完成",
    )
