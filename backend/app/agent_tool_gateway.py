"""Internal, session-bound tool gateway used by AgentScope agents.

The browser never calls this router.  Every request is authenticated with an
internal service token and is scoped by an AgentScope session ID.  The platform
database is the authority for the account, project and role behind that
session; callers cannot provide or override those identifiers.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import (
    AgentConversation,
    Attachment,
    AttachmentText,
    DailyReport,
    DocumentFolderItem,
    Notification,
    OperationLog,
    Project,
    ProjectChange,
    ProjectInformationRecord,
    ProjectMember,
    ProjectStatusSnapshot,
    QualityMetric,
    RiskSource,
    Task,
    TaskStatusHistory,
    User,
    WbsItem,
)


router = APIRouter(prefix="/api/internal/agent-tools", tags=["internal-agent-tools"])

ResourceName = Literal[
    "tasks",
    "wbs",
    "risks",
    "quality",
    "members",
    "information",
    "changes",
    "notifications",
    "documents",
    "daily_reports",
]
OperationName = Literal[
    "get_project_overview",
    "list_project_items",
    "search_documents",
    "create_task",
    "update_task",
    "create_risk",
    "update_wbs_progress",
    "dispose_information",
    "create_project_change",
    "update_document_category",
]


class ToolExecuteRequest(BaseModel):
    agentscope_session_id: str = Field(min_length=1, max_length=128)
    operation: OperationName
    arguments: dict[str, Any] = Field(default_factory=dict)


class ListItemsArgs(BaseModel):
    resource: ResourceName
    keyword: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=50, ge=1, le=100)


class SearchDocumentsArgs(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    task_type: Literal[
        "risk_alert",
        "material_missing",
        "daily_confirm",
        "draft_review",
        "fill_platform",
    ] = "risk_alert"
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    assignee_user_id: int | None = None
    confirmer_user_id: int | None = None
    due_at: str | None = Field(default=None, max_length=40)
    wbs_item_id: int | None = None
    risk_source_id: int | None = None
    trigger_reason: str | None = Field(default=None, max_length=2000)
    required_materials: list[str] = Field(default_factory=list, max_length=30)


class UpdateTaskArgs(BaseModel):
    task_id: int
    action: Literal["transition", "reassign", "add_note", "update_step"]
    status: str | None = Field(default=None, max_length=32)
    assignee_user_id: int | None = None
    step_index: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class CreateRiskArgs(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    level: Literal["low", "medium", "high", "critical"] = "medium"
    risk_type: str = Field(default="综合风险", min_length=1, max_length=100)
    planned_start: str | None = Field(default=None, max_length=32)
    planned_finish: str | None = Field(default=None, max_length=32)
    responsible_user_id: int | None = None
    confirmer_user_id: int | None = None
    material_requirements: list[str] = Field(default_factory=list, max_length=30)
    control_requirements: str | None = Field(default=None, max_length=4000)


class UpdateWbsArgs(BaseModel):
    wbs_item_id: int
    progress: int = Field(ge=0, le=100)
    status: Literal[
        "not_started",
        "in_progress",
        "delayed",
        "completed",
        "blocked",
    ] | None = None
    note: str | None = Field(default=None, max_length=1000)


class DisposeInformationArgs(BaseModel):
    record_id: int
    action: Literal["confirm", "deny", "revise"]
    content: str | None = Field(default=None, max_length=10000)


class CreateProjectChangeArgs(BaseModel):
    category: str = Field(default="工程内容变更", min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=10000)
    source_refs: list[str] = Field(default_factory=list, max_length=30)


class UpdateDocumentCategoryArgs(BaseModel):
    attachment_id: int
    category: str = Field(min_length=1, max_length=100)


@dataclass(frozen=True)
class ToolContext:
    conversation: AgentConversation
    user: User
    project: Project
    membership: ProjectMember | None

    @property
    def is_admin(self) -> bool:
        return self.user.role in {"admin", "superadmin"}

    @property
    def can_write(self) -> bool:
        return self.conversation.conversation_type == "general"

    @property
    def can_admin_write(self) -> bool:
        return self.can_write and self.is_admin


def _ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _require_service_token(
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().effective_agent_tool_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dobby 智能体工具网关尚未配置内部服务令牌",
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Dobby 智能体工具网关凭证",
        )


def resolve_tool_context(db: Session, agentscope_session_id: str) -> ToolContext:
    """Resolve the authoritative platform identity for an AgentScope session."""
    conversation = db.scalar(
        select(AgentConversation).where(
            AgentConversation.agentscope_session_id == agentscope_session_id,
        ),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="该会话不属于工程管理平台")

    user = db.get(User, conversation.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=403, detail="平台账号已停用或不存在")

    project = db.get(Project, conversation.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="会话关联项目不存在")

    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.status == "active",
        ),
    )
    if user.role not in {"admin", "superadmin"} and membership is None:
        raise HTTPException(status_code=403, detail="当前账号已无权访问该项目")

    return ToolContext(
        conversation=conversation,
        user=user,
        project=project,
        membership=membership,
    )


def _public_row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in fields:
        value = getattr(row, name)
        data[name] = value.isoformat() if isinstance(value, datetime) else value
    return data


def _parse_args(model: type[BaseModel], raw: dict[str, Any]) -> BaseModel:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False),
        ) from exc


def _require_write(context: ToolContext) -> None:
    if not context.can_write:
        raise HTTPException(
            status_code=403,
            detail="专项智能体只能读取项目数据，写操作仅允许平台全局主智能体执行",
        )


def _require_admin_write(context: ToolContext) -> None:
    _require_write(context)
    if not context.is_admin:
        raise HTTPException(
            status_code=403,
            detail="该操作需要当前平台账号具备管理员权限",
        )


def _project_entity(
    db: Session,
    model: type[Any],
    item_id: int,
    project_id: int,
    not_found: str,
) -> Any:
    row = db.get(model, item_id)
    if row is None or getattr(row, "project_id", None) != project_id:
        # Deliberately use the same response for missing and cross-project IDs.
        raise HTTPException(status_code=404, detail=not_found)
    return row


def _active_member(db: Session, project_id: int, user_id: int) -> ProjectMember:
    row = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.status == "active",
        ),
    )
    if row is None:
        raise HTTPException(status_code=422, detail=f"用户 {user_id} 不是当前项目的有效成员")
    return row


def _audit(
    db: Session,
    context: ToolContext,
    action: str,
    detail: str,
    target_type: str,
    target_id: int,
) -> None:
    db.add(
        OperationLog(
            project_id=context.project.id,
            operator_id=context.user.id,
            action=action,
            detail=(
                f"{detail}（Dobby 智能体会话 "
                f"{context.conversation.id} 自动执行）"
            ),
            target_type=target_type,
            target_id=target_id,
        ),
    )


def _overview(db: Session, context: ToolContext) -> dict[str, Any]:
    project_id = context.project.id

    def count(model: type[Any], *filters: Any) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.project_id == project_id, *filters),
            )
            or 0,
        )

    snapshot = db.get(ProjectStatusSnapshot, project_id)
    dashboard = (
        _public_row(
            snapshot,
            (
                "progress_rate",
                "progress_status",
                "planned_delta",
                "risk_warnings",
                "safety_issues",
                "quality_issues",
                "task_completion_rate",
                "main_risk",
                "main_safety",
                "main_quality",
                "overall",
            ),
        )
        if snapshot
        else None
    )
    return {
        "project": _public_row(
            context.project,
            ("id", "project_name", "owner_unit", "description", "status"),
        ),
        "current_user": {
            **_public_row(
                context.user,
                ("id", "real_name", "title", "org_name", "role", "status"),
            ),
            "project_member_role": (
                context.membership.member_role if context.membership else "platform_admin"
            ),
            "responsibilities": (
                context.membership.responsibilities if context.membership else []
            ),
        },
        "dashboard": dashboard,
        "counts": {
            "tasks": count(Task),
            "open_tasks": count(
                Task,
                Task.status.not_in(("completed", "cancelled")),
            ),
            "risks": count(RiskSource),
            "active_risks": count(RiskSource, RiskSource.status == "active"),
            "wbs_items": count(WbsItem),
            "documents": count(Attachment),
            "information_records": count(ProjectInformationRecord),
            "unread_notifications": count(
                Notification,
                Notification.is_read.is_(False),
            ),
        },
        "scope": {
            "conversation_type": context.conversation.conversation_type,
            "can_write": context.can_write,
            "can_admin_write": context.can_admin_write,
        },
    }


def _list_items(
    db: Session,
    context: ToolContext,
    args: ListItemsArgs,
) -> list[dict[str, Any]]:
    project_id = context.project.id
    keyword = (args.keyword or "").strip()

    if args.resource == "tasks":
        stmt = select(Task).where(Task.project_id == project_id)
        if args.status:
            stmt = stmt.where(Task.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    Task.title.contains(keyword),
                    Task.trigger_reason.contains(keyword),
                ),
            )
        rows = db.scalars(stmt.order_by(Task.updated_at.desc()).limit(args.limit)).all()
        fields = (
            "id", "title", "task_type", "risk_level", "status",
            "assignee_user_id", "confirmer_user_id", "due_at", "wbs_item_id",
            "risk_source_id", "trigger_reason", "required_materials",
            "workflow_steps", "created_at", "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "wbs":
        stmt = select(WbsItem).where(WbsItem.project_id == project_id)
        if args.status:
            stmt = stmt.where(WbsItem.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(WbsItem.code.contains(keyword), WbsItem.name.contains(keyword)),
            )
        rows = db.scalars(stmt.order_by(WbsItem.code).limit(args.limit)).all()
        fields = (
            "id", "parent_id", "code", "name", "level", "planned_start",
            "planned_finish", "progress", "status", "responsible_user_id",
            "raw_data", "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "risks":
        stmt = select(RiskSource).where(RiskSource.project_id == project_id)
        if args.status:
            stmt = stmt.where(RiskSource.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    RiskSource.name.contains(keyword),
                    RiskSource.risk_type.contains(keyword),
                    RiskSource.control_requirements.contains(keyword),
                ),
            )
        rows = db.scalars(stmt.order_by(RiskSource.updated_at.desc()).limit(args.limit)).all()
        fields = (
            "id", "name", "level", "risk_type", "planned_start",
            "planned_finish", "responsible_user_id", "confirmer_user_id",
            "material_requirements", "control_requirements", "status",
            "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "quality":
        stmt = select(QualityMetric).where(QualityMetric.project_id == project_id)
        if args.status:
            stmt = stmt.where(QualityMetric.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    QualityMetric.name.contains(keyword),
                    QualityMetric.requirement.contains(keyword),
                ),
            )
        rows = db.scalars(stmt.order_by(QualityMetric.updated_at.desc()).limit(args.limit)).all()
        fields = (
            "id", "wbs_item_id", "name", "requirement",
            "inspection_frequency", "required_materials", "owner_user_id",
            "status", "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "members":
        stmt = (
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
        )
        if args.status:
            stmt = stmt.where(ProjectMember.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    ProjectMember.display_name.contains(keyword),
                    User.real_name.contains(keyword),
                    User.title.contains(keyword),
                ),
            )
        rows = db.execute(stmt.order_by(ProjectMember.id).limit(args.limit)).all()
        return [
            {
                "user_id": user.id,
                "display_name": member.display_name or user.real_name,
                "title": user.title,
                "member_role": member.member_role,
                "responsibilities": member.responsibilities,
                "status": member.status,
            }
            for member, user in rows
        ]

    if args.resource == "information":
        stmt = select(ProjectInformationRecord).where(
            ProjectInformationRecord.project_id == project_id,
        )
        if args.status:
            stmt = stmt.where(ProjectInformationRecord.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    ProjectInformationRecord.source_name.contains(keyword),
                    ProjectInformationRecord.content.contains(keyword),
                ),
            )
        rows = db.scalars(
            stmt.order_by(
                ProjectInformationRecord.recorded_at.desc(),
                ProjectInformationRecord.id.desc(),
            ).limit(args.limit),
        ).all()
        fields = (
            "id", "source_type", "source_name", "author", "recorded_at",
            "status", "confidence", "content", "source_refs",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "changes":
        stmt = select(ProjectChange).where(ProjectChange.project_id == project_id)
        if args.status:
            stmt = stmt.where(ProjectChange.status == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    ProjectChange.title.contains(keyword),
                    ProjectChange.content.contains(keyword),
                ),
            )
        rows = db.scalars(
            stmt.order_by(ProjectChange.updated_at.desc()).limit(args.limit),
        ).all()
        fields = (
            "id", "category", "title", "content", "status", "source_refs",
            "created_at", "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "notifications":
        stmt = select(Notification).where(Notification.project_id == project_id)
        if args.status == "read":
            stmt = stmt.where(Notification.is_read.is_(True))
        elif args.status == "unread":
            stmt = stmt.where(Notification.is_read.is_(False))
        if keyword:
            stmt = stmt.where(
                or_(
                    Notification.title.contains(keyword),
                    Notification.content.contains(keyword),
                ),
            )
        rows = db.scalars(
            stmt.order_by(Notification.created_at.desc()).limit(args.limit),
        ).all()
        fields = (
            "id", "notification_type", "title", "content", "priority",
            "source_type", "source_id", "is_read", "created_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "documents":
        stmt = (
            select(Attachment, DocumentFolderItem.folder_id)
            .outerjoin(
                DocumentFolderItem,
                DocumentFolderItem.attachment_id == Attachment.id,
            )
            .where(Attachment.project_id == project_id)
        )
        if args.status:
            stmt = stmt.where(Attachment.category == args.status)
        if keyword:
            stmt = stmt.where(Attachment.file_name.contains(keyword))
        rows = db.execute(
            stmt.order_by(Attachment.created_at.desc()).limit(args.limit),
        ).all()
        fields = (
            "id", "file_name", "content_type", "file_size", "version",
            "category", "source_type", "source_id", "created_at", "updated_at",
        )
        return [
            {**_public_row(attachment, fields), "folder_id": folder_id}
            for attachment, folder_id in rows
        ]

    stmt = select(DailyReport).where(DailyReport.project_id == project_id)
    if args.status:
        stmt = stmt.where(DailyReport.status == args.status)
    if keyword:
        stmt = stmt.where(
            or_(
                DailyReport.file_name.contains(keyword),
                DailyReport.content.contains(keyword),
            ),
        )
    rows = db.scalars(
        stmt.order_by(DailyReport.updated_at.desc()).limit(args.limit),
    ).all()
    fields = (
        "id", "file_name", "report_date", "content", "matched_wbs_id",
        "confidence", "parse_status", "status", "created_at", "updated_at",
    )
    return [_public_row(row, fields) for row in rows]


def _search_documents(
    db: Session,
    context: ToolContext,
    args: SearchDocumentsArgs,
) -> list[dict[str, Any]]:
    keyword = args.keyword.strip()
    rows = db.execute(
        select(
            Attachment,
            AttachmentText.content,
            DocumentFolderItem.folder_id,
        )
        .outerjoin(
            AttachmentText,
            AttachmentText.attachment_id == Attachment.id,
        )
        .outerjoin(
            DocumentFolderItem,
            DocumentFolderItem.attachment_id == Attachment.id,
        )
        .where(
            Attachment.project_id == context.project.id,
            or_(
                Attachment.file_name.contains(keyword),
                AttachmentText.content.contains(keyword),
            ),
        )
        .order_by(Attachment.created_at.desc())
        .limit(args.limit),
    ).all()
    result: list[dict[str, Any]] = []
    for attachment, content, folder_id in rows:
        snippet = ""
        if content:
            index = content.lower().find(keyword.lower())
            if index >= 0:
                snippet = content[max(0, index - 80): index + len(keyword) + 160]
        result.append(
            {
                **_public_row(
                    attachment,
                    (
                        "id", "file_name", "content_type", "file_size",
                        "version", "category", "source_type", "source_id",
                        "created_at",
                    ),
                ),
                "folder_id": folder_id,
                "snippet": snippet,
            },
        )
    return result


def _create_task(
    db: Session,
    context: ToolContext,
    args: CreateTaskArgs,
) -> dict[str, Any]:
    _require_write(context)
    project_id = context.project.id
    for user_id in (args.assignee_user_id, args.confirmer_user_id):
        if user_id is not None:
            _active_member(db, project_id, user_id)
    if args.wbs_item_id is not None:
        _project_entity(db, WbsItem, args.wbs_item_id, project_id, "WBS 工序不存在")
    if args.risk_source_id is not None:
        _project_entity(
            db,
            RiskSource,
            args.risk_source_id,
            project_id,
            "风险源不存在",
        )
    task = Task(
        project_id=project_id,
        title=args.title.strip(),
        task_type=args.task_type,
        risk_level=args.risk_level,
        status="pending",
        assignee_user_id=args.assignee_user_id,
        confirmer_user_id=args.confirmer_user_id,
        due_at=args.due_at,
        wbs_item_id=args.wbs_item_id,
        risk_source_id=args.risk_source_id,
        trigger_reason=args.trigger_reason,
        required_materials=args.required_materials,
        workflow_steps=[],
    )
    db.add(task)
    db.flush()
    db.add(
        TaskStatusHistory(
            task_id=task.id,
            to_status="pending",
            changed_by=context.user.id,
            note="由 Dobby 全局总控创建",
        ),
    )
    _audit(
        db,
        context,
        "Dobby 创建任务",
        f"创建任务「{task.title}」",
        "task",
        task.id,
    )
    db.commit()
    db.refresh(task)
    return _public_row(
        task,
        (
            "id", "title", "task_type", "risk_level", "status",
            "assignee_user_id", "confirmer_user_id", "due_at", "wbs_item_id",
            "risk_source_id", "trigger_reason", "required_materials",
            "created_at", "updated_at",
        ),
    )


def _update_task(
    db: Session,
    context: ToolContext,
    args: UpdateTaskArgs,
) -> dict[str, Any]:
    _require_write(context)
    task = _project_entity(
        db,
        Task,
        args.task_id,
        context.project.id,
        "任务不存在",
    )
    detail: str
    if args.action == "transition":
        transitions = {
            "pending": {"processing", "cancelled"},
            "processing": {"need_more_info", "pending_confirm", "cancelled"},
            "need_more_info": {"processing", "cancelled"},
            "pending_confirm": {"processing", "completed", "cancelled"},
            "overdue": {"processing", "cancelled"},
            "completed": set(),
            "cancelled": set(),
        }
        if not args.status or args.status not in transitions.get(task.status, set()):
            raise HTTPException(
                status_code=409,
                detail=f"任务当前为 {task.status}，不能流转到 {args.status}",
            )
        previous = task.status
        task.status = args.status
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=previous,
                to_status=task.status,
                note=args.note,
                changed_by=context.user.id,
            ),
        )
        detail = f"任务「{task.title}」由 {previous} 变更为 {task.status}"
    elif args.action == "reassign":
        if args.assignee_user_id is None:
            raise HTTPException(status_code=422, detail="转交任务必须指定 assignee_user_id")
        _active_member(db, context.project.id, args.assignee_user_id)
        previous = task.assignee_user_id
        task.assignee_user_id = args.assignee_user_id
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=task.status,
                to_status=task.status,
                note=args.note or f"由用户 {previous} 转交给 {args.assignee_user_id}",
                changed_by=context.user.id,
            ),
        )
        detail = f"任务「{task.title}」转交给用户 {args.assignee_user_id}"
    elif args.action == "add_note":
        note = (args.note or "").strip()
        if not note:
            raise HTTPException(status_code=422, detail="处理说明不能为空")
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=task.status,
                to_status=task.status,
                note=note,
                changed_by=context.user.id,
            ),
        )
        detail = f"任务「{task.title}」新增处理说明"
    else:
        if args.step_index is None:
            raise HTTPException(status_code=422, detail="更新步骤必须指定 step_index")
        if args.status not in {"pending", "processing", "completed", "blocked"}:
            raise HTTPException(status_code=422, detail="不支持的任务步骤状态")
        steps = list(task.workflow_steps or [])
        if args.step_index >= len(steps):
            raise HTTPException(status_code=404, detail="任务步骤不存在")
        step = {
            **steps[args.step_index],
            "status": args.status,
            "note": args.note,
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_by": context.user.id,
        }
        steps[args.step_index] = step
        task.workflow_steps = steps
        detail = (
            f"任务「{task.title}」步骤"
            f"「{step.get('name', args.step_index + 1)}」更新为 {args.status}"
        )

    _audit(db, context, "Dobby 更新任务", detail, "task", task.id)
    db.commit()
    db.refresh(task)
    return _public_row(
        task,
        (
            "id", "title", "status", "assignee_user_id", "confirmer_user_id",
            "due_at", "workflow_steps", "updated_at",
        ),
    )


def _create_risk(
    db: Session,
    context: ToolContext,
    args: CreateRiskArgs,
) -> dict[str, Any]:
    _require_admin_write(context)
    for user_id in (args.responsible_user_id, args.confirmer_user_id):
        if user_id is not None:
            _active_member(db, context.project.id, user_id)
    risk = RiskSource(
        project_id=context.project.id,
        name=args.name.strip(),
        level=args.level,
        risk_type=args.risk_type.strip(),
        planned_start=args.planned_start,
        planned_finish=args.planned_finish,
        responsible_user_id=args.responsible_user_id,
        confirmer_user_id=args.confirmer_user_id,
        material_requirements=args.material_requirements,
        control_requirements=args.control_requirements,
        status="active",
    )
    db.add(risk)
    db.flush()
    _audit(
        db,
        context,
        "Dobby 新增风险源",
        f"新增风险源「{risk.name}」",
        "risk",
        risk.id,
    )
    db.commit()
    db.refresh(risk)
    return _public_row(
        risk,
        (
            "id", "name", "level", "risk_type", "responsible_user_id",
            "confirmer_user_id", "material_requirements",
            "control_requirements", "status", "created_at",
        ),
    )


def _update_wbs(
    db: Session,
    context: ToolContext,
    args: UpdateWbsArgs,
) -> dict[str, Any]:
    _require_admin_write(context)
    item = _project_entity(
        db,
        WbsItem,
        args.wbs_item_id,
        context.project.id,
        "WBS 工序不存在",
    )
    previous = f"{item.progress}%/{item.status}"
    item.progress = args.progress
    if args.status is not None:
        item.status = args.status
    _audit(
        db,
        context,
        "Dobby 更新 WBS 进度",
        (
            f"工序「{item.code} {item.name}」由 {previous} 更新为 "
            f"{item.progress}%/{item.status}"
            + (f"，说明：{args.note}" if args.note else "")
        ),
        "wbs",
        item.id,
    )
    db.commit()
    db.refresh(item)
    return _public_row(
        item,
        ("id", "code", "name", "progress", "status", "updated_at"),
    )


def _dispose_information(
    db: Session,
    context: ToolContext,
    args: DisposeInformationArgs,
) -> dict[str, Any]:
    _require_write(context)
    row = _project_entity(
        db,
        ProjectInformationRecord,
        args.record_id,
        context.project.id,
        "信息记录不存在",
    )
    if args.action == "revise" and not (args.content or "").strip():
        raise HTTPException(status_code=422, detail="修订信息不能为空")
    row.status = {
        "confirm": "已确认",
        "deny": "已否认",
        "revise": "已修订",
    }[args.action]
    if args.action == "revise":
        row.content = (args.content or "").strip()
    _audit(
        db,
        context,
        "Dobby 处置信息",
        f"信息「{row.source_name}」已{row.status}",
        "project_information_record",
        row.id,
    )
    db.commit()
    db.refresh(row)
    return _public_row(
        row,
        (
            "id", "source_type", "source_name", "status", "confidence",
            "content", "source_refs", "updated_at",
        ),
    )


def _create_change(
    db: Session,
    context: ToolContext,
    args: CreateProjectChangeArgs,
) -> dict[str, Any]:
    _require_write(context)
    row = ProjectChange(
        project_id=context.project.id,
        category=args.category.strip(),
        title=args.title.strip(),
        content=args.content.strip(),
        status="pending",
        source_refs=args.source_refs,
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        context,
        "Dobby 登记项目变更",
        f"登记项目变更「{row.title}」",
        "project_change",
        row.id,
    )
    db.commit()
    db.refresh(row)
    return _public_row(
        row,
        (
            "id", "category", "title", "content", "status", "source_refs",
            "created_at",
        ),
    )


def _update_document_category(
    db: Session,
    context: ToolContext,
    args: UpdateDocumentCategoryArgs,
) -> dict[str, Any]:
    _require_write(context)
    attachment = _project_entity(
        db,
        Attachment,
        args.attachment_id,
        context.project.id,
        "资料不存在",
    )
    attachment.category = args.category.strip()
    _audit(
        db,
        context,
        "Dobby 更新资料分类",
        f"资料「{attachment.file_name}」分类更新为「{attachment.category}」",
        "attachment",
        attachment.id,
    )
    db.commit()
    db.refresh(attachment)
    return _public_row(
        attachment,
        ("id", "file_name", "category", "version", "updated_at"),
    )


def execute_tool_operation(
    db: Session,
    context: ToolContext,
    operation: OperationName,
    arguments: dict[str, Any],
) -> tuple[Any, str]:
    """Dispatch one allow-listed semantic operation."""
    if operation == "get_project_overview":
        if arguments:
            raise HTTPException(status_code=422, detail="该操作不接受参数")
        return _overview(db, context), "已读取当前项目概览"
    if operation == "list_project_items":
        args = _parse_args(ListItemsArgs, arguments)
        assert isinstance(args, ListItemsArgs)
        return _list_items(db, context, args), "已读取当前项目数据"
    if operation == "search_documents":
        args = _parse_args(SearchDocumentsArgs, arguments)
        assert isinstance(args, SearchDocumentsArgs)
        return _search_documents(db, context, args), "已检索当前项目资料"
    if operation == "create_task":
        args = _parse_args(CreateTaskArgs, arguments)
        assert isinstance(args, CreateTaskArgs)
        return _create_task(db, context, args), "任务已创建"
    if operation == "update_task":
        args = _parse_args(UpdateTaskArgs, arguments)
        assert isinstance(args, UpdateTaskArgs)
        return _update_task(db, context, args), "任务已更新"
    if operation == "create_risk":
        args = _parse_args(CreateRiskArgs, arguments)
        assert isinstance(args, CreateRiskArgs)
        return _create_risk(db, context, args), "风险源已创建"
    if operation == "update_wbs_progress":
        args = _parse_args(UpdateWbsArgs, arguments)
        assert isinstance(args, UpdateWbsArgs)
        return _update_wbs(db, context, args), "WBS 进度已更新"
    if operation == "dispose_information":
        args = _parse_args(DisposeInformationArgs, arguments)
        assert isinstance(args, DisposeInformationArgs)
        return _dispose_information(db, context, args), "信息记录已处置"
    if operation == "create_project_change":
        args = _parse_args(CreateProjectChangeArgs, arguments)
        assert isinstance(args, CreateProjectChangeArgs)
        return _create_change(db, context, args), "项目变更已登记"
    args = _parse_args(UpdateDocumentCategoryArgs, arguments)
    assert isinstance(args, UpdateDocumentCategoryArgs)
    return _update_document_category(db, context, args), "资料分类已更新"


@router.get("/context", dependencies=[Depends(_require_service_token)])
def get_agent_tool_context(
    agentscope_session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Expose only the capabilities needed to assemble session-bound tools."""
    context = resolve_tool_context(db, agentscope_session_id)
    return _ok(
        {
            "conversation_type": context.conversation.conversation_type,
            "agent_id": context.conversation.agent_id,
            "capabilities": {
                "read": True,
                "write": context.can_write,
                "admin_write": context.can_admin_write,
            },
        },
    )


@router.post("/execute", dependencies=[Depends(_require_service_token)])
def execute_agent_tool(
    payload: ToolExecuteRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = resolve_tool_context(db, payload.agentscope_session_id)
    data, message = execute_tool_operation(
        db,
        context,
        payload.operation,
        payload.arguments,
    )
    return _ok(data, message)
