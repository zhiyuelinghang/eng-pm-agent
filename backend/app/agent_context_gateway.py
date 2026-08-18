"""Session-bound context and attachment transport for AgentScope.

This router deliberately exposes no business-operation dispatcher. Database
operations are resolved through the editable database-interaction catalogue.
Platform workflows such as project initialization are not exposed here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import (
    AgentConversation,
    Project,
    ProjectMember,
    ProjectSettings,
    User,
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


def ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


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
    row.weknora_agent_id = (
        (payload.weknora_agent_id or "").strip() or None
    )
    db.commit()
    db.refresh(row)
    return ok(
        {
            "project_id": project.id,
            "project_name": project.name,
            "weknora_agent_id": row.weknora_agent_id,
            "updated_at": (
                row.updated_at.isoformat() if row.updated_at is not None else None
            ),
        },
        "项目知识库机器人绑定已保存",
    )
