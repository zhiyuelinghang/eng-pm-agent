"""Internal, session-bound tool gateway used by AgentScope agents.

The browser never calls this router.  Every request is authenticated with an
internal service token and is scoped by an AgentScope session ID.  The platform
database is the authority for the account, project and role behind that
session; callers cannot provide or override those identifiers.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
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
    ProjectInitializationDraft,
    ProjectInitializationFile,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    ProjectStatusSnapshot,
    QualityMetric,
    RiskSource,
    Task,
    TaskStatusHistory,
    User,
    WbsItem,
)
from .project_initialization import (
    ProjectInitializationPayload,
    ReadInitializationDraftArgs,
    SubmitInitializationDraftArgs,
    UpdateInitializationDraftArgs,
    build_initialization_state,
    draft_status,
    validate_initialization_payload,
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
    "get_project_initialization_state",
    "get_project_initialization_draft",
    "list_project_items",
    "search_documents",
    "submit_project_initialization_draft",
    "update_project_initialization_draft",
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
    serial_no: int = Field(gt=0)
    related_wbs_item_id: int | None = None
    related_process_name: str = Field(min_length=1, max_length=300)
    risk_part: str = Field(min_length=1, max_length=300)
    risk_level: str = Field(min_length=1, max_length=50)
    evaluation_condition: str = Field(min_length=1, max_length=20000)
    risk_window_start_date: date | None = None
    risk_window_end_date: date | None = None
    summary: str | None = Field(default=None, max_length=20000)


class UpdateWbsArgs(BaseModel):
    wbs_item_id: int
    progress_percent: Decimal = Field(ge=0, le=100)
    status_text: str | None = Field(default=None, max_length=100)
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
        return self.user.role == "admin"

    @property
    def can_write(self) -> bool:
        return self.conversation.conversation_type == "general"

    @property
    def can_admin_write(self) -> bool:
        return self.can_write and self.is_admin

    @property
    def can_submit_initialization_draft(self) -> bool:
        return self.conversation.conversation_type == "initialization"


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


def _public_row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in fields:
        value = getattr(row, name)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        data[name] = value
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
    project_assignments = []
    if context.membership is not None:
        rows = db.execute(
            select(ProjectMemberPosition, ProjectPosition)
            .join(
                ProjectPosition,
                ProjectPosition.id == ProjectMemberPosition.position_id,
            )
            .where(
                ProjectMemberPosition.project_member_id == context.membership.id,
            )
            .order_by(ProjectMemberPosition.serial_no),
        ).all()
        project_assignments = [
            {
                **_public_row(
                    assignment,
                    (
                        "id",
                        "serial_no",
                        "certificate_no",
                        "responsibility_description",
                    ),
                ),
                "position_id": position.id,
                "position_name": position.position_name,
            }
            for assignment, position in rows
        ]
    return {
        "project": _public_row(
            context.project,
            (
                "id",
                "name",
                "engineering_type_description",
                "contract_start_date",
                "contract_end_date",
                "contract_duration_days",
                "contract_amount_wan_yuan",
                "construction_unit_name",
                "general_contractor_unit_name",
                "supervision_unit_name",
                "design_unit_name",
                "survey_unit_name",
                "updated_at",
            ),
        ),
        "current_user": {
            **_public_row(
                context.user,
                ("id", "username", "real_name", "role"),
            ),
            "project_member_id": (
                context.membership.id if context.membership else None
            ),
            "project_assignments": project_assignments,
        },
        "dashboard": dashboard,
        "counts": {
            "tasks": count(Task),
            "open_tasks": count(
                Task,
                Task.status.not_in(("completed", "cancelled")),
            ),
            "risks": count(RiskSource),
            "wbs_items": count(WbsItem),
            "quality_requirements": count(QualityMetric),
            "project_personnel": count(ProjectMember),
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
            "can_submit_initialization_draft": (
                context.can_submit_initialization_draft
            ),
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
            stmt = stmt.where(WbsItem.status_text == args.status)
        if keyword:
            stmt = stmt.where(
                or_(
                    WbsItem.wbs_code.contains(keyword),
                    WbsItem.name.contains(keyword),
                    WbsItem.description.contains(keyword),
                ),
            )
        rows = db.scalars(
            stmt.order_by(WbsItem.sort_order, WbsItem.wbs_code).limit(args.limit),
        ).all()
        fields = (
            "id", "parent_id", "sort_order", "color_value", "wbs_code",
            "name", "assigned_to_text", "planned_start_at",
            "planned_finish_at", "deadline_at", "progress_percent",
            "duration_hours", "estimated_hours", "time_log_minutes",
            "status_text", "priority_text", "description", "budget",
            "actual_cost", "msp_uid", "msp_id", "source_created_at",
            "source_creator", "item_type", "source_project_path", "level",
            "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "risks":
        stmt = select(RiskSource).where(RiskSource.project_id == project_id)
        if keyword:
            stmt = stmt.where(
                or_(
                    RiskSource.related_process_name.contains(keyword),
                    RiskSource.risk_part.contains(keyword),
                    RiskSource.risk_level.contains(keyword),
                    RiskSource.evaluation_condition.contains(keyword),
                    RiskSource.summary.contains(keyword),
                ),
            )
        rows = db.scalars(
            stmt.order_by(RiskSource.serial_no).limit(args.limit),
        ).all()
        fields = (
            "id", "serial_no", "related_wbs_item_id",
            "related_process_name", "risk_part", "risk_level",
            "evaluation_condition", "risk_window_start_date",
            "risk_window_end_date", "summary", "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "quality":
        stmt = select(QualityMetric).where(QualityMetric.project_id == project_id)
        if keyword:
            stmt = stmt.where(
                or_(
                    QualityMetric.wbs_code.contains(keyword),
                    QualityMetric.quality_acceptance_item.contains(keyword),
                    QualityMetric.control_indicator.contains(keyword),
                    QualityMetric.related_documents.contains(keyword),
                ),
            )
        rows = db.scalars(
            stmt.order_by(QualityMetric.wbs_code).limit(args.limit),
        ).all()
        fields = (
            "id", "wbs_code", "quality_acceptance_item",
            "control_indicator", "inspection_frequency",
            "related_documents", "updated_at",
        )
        return [_public_row(row, fields) for row in rows]

    if args.resource == "members":
        stmt = select(ProjectMember, User).join(
            User,
            User.id == ProjectMember.user_id,
        ).where(ProjectMember.project_id == project_id)
        if keyword:
            matching_member_ids = (
                select(ProjectMemberPosition.project_member_id)
                .join(
                    ProjectPosition,
                    ProjectPosition.id == ProjectMemberPosition.position_id,
                )
                .where(
                    ProjectMemberPosition.project_id == project_id,
                    or_(
                        ProjectPosition.position_name.contains(keyword),
                        ProjectMemberPosition.certificate_no.contains(keyword),
                        ProjectMemberPosition.responsibility_description.contains(
                            keyword,
                        ),
                    ),
                )
            )
            stmt = stmt.where(
                or_(
                    User.real_name.contains(keyword),
                    User.username.contains(keyword),
                    ProjectMember.id.in_(matching_member_ids),
                ),
            )
        rows = db.execute(stmt.order_by(User.real_name).limit(args.limit)).all()
        member_ids = [member.id for member, _ in rows]
        assignments_by_member: dict[int, list[dict[str, Any]]] = {
            member_id: [] for member_id in member_ids
        }
        if member_ids:
            assignments = db.execute(
                select(ProjectMemberPosition, ProjectPosition)
                .join(
                    ProjectPosition,
                    ProjectPosition.id == ProjectMemberPosition.position_id,
                )
                .where(
                    ProjectMemberPosition.project_member_id.in_(member_ids),
                )
                .order_by(ProjectMemberPosition.serial_no),
            ).all()
            for assignment, position in assignments:
                assignments_by_member[assignment.project_member_id].append(
                    {
                        "assignment_id": assignment.id,
                        "position_id": position.id,
                        "position_name": position.position_name,
                        "serial_no": assignment.serial_no,
                        "certificate_no": assignment.certificate_no,
                        "responsibility_description": (
                            assignment.responsibility_description
                        ),
                    },
                )
        return [
            {
                "project_member_id": member.id,
                "user_id": account.id,
                "username": account.username,
                "real_name": account.real_name,
                "role": account.role,
                "positions": assignments_by_member[member.id],
            }
            for member, account in rows
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


def _get_initialization_state(
    db: Session,
    context: ToolContext,
) -> dict[str, Any]:
    state = build_initialization_state(db, context.project)
    if context.can_submit_initialization_draft:
        files = db.scalars(
            select(ProjectInitializationFile)
            .where(
                ProjectInitializationFile.project_id == context.project.id,
                ProjectInitializationFile.conversation_id
                == context.conversation.id,
            )
            .order_by(ProjectInitializationFile.created_at),
        ).all()
        state["initialization_files"] = [
            _public_row(
                item,
                (
                    "id",
                    "file_name",
                    "content_type",
                    "file_size",
                    "file_hash",
                    "created_at",
                ),
            )
            for item in files
        ]
    return state


def _initialization_draft_for_context(
    db: Session,
    context: ToolContext,
) -> ProjectInitializationDraft | None:
    return db.scalar(
        select(ProjectInitializationDraft)
        .where(
            ProjectInitializationDraft.project_id == context.project.id,
            ProjectInitializationDraft.conversation_id
            == context.conversation.id,
        )
        .order_by(
            ProjectInitializationDraft.updated_at.desc(),
            ProjectInitializationDraft.id.desc(),
        ),
    )


def _get_initialization_draft(
    db: Session,
    context: ToolContext,
    args: ReadInitializationDraftArgs,
) -> dict[str, Any]:
    if not context.can_submit_initialization_draft:
        raise HTTPException(
            status_code=403,
            detail="只有项目初始化智能体会话可以读取初始化草稿",
        )
    draft = _initialization_draft_for_context(db, context)
    if draft is None:
        return {
            "draft": None,
            "section": args.section,
            "data": None,
        }

    payload = ProjectInitializationPayload.model_validate(draft.payload)
    if args.section == "validation_issues":
        section_data: dict[str, Any] | list[Any] = list(
            draft.validation_issues or [],
        )
    else:
        section_data = payload.model_dump(mode="json")[args.section]

    if isinstance(section_data, list):
        selected = section_data[
            args.start - 1:args.start - 1 + args.limit
        ]
        end = args.start + len(selected) - 1 if selected else None
        total = len(section_data)
        next_start = end + 1 if end is not None and end < total else None
        data: dict[str, Any] | list[Any] = selected
    else:
        total = 1
        end = 1
        next_start = None
        data = section_data

    return {
        "draft": _public_row(
            draft,
            (
                "id",
                "project_id",
                "conversation_id",
                "status",
                "revision",
                "source_files",
                "created_at",
                "updated_at",
            ),
        ),
        "section": args.section,
        "start": args.start,
        "end": end,
        "total": total,
        "next_start": next_start,
        "data": data,
    }


def _draft_summary(
    payload: ProjectInitializationPayload,
    issues: list[dict[str, str]],
) -> dict[str, int]:
    return {
        "personnel": len(payload.personnel),
        "wbs": len(payload.wbs),
        "risks": len(payload.risks),
        "quality_requirements": len(payload.quality_requirements),
        "errors": sum(item["level"] == "error" for item in issues),
        "warnings": sum(item["level"] == "warning" for item in issues),
    }


def _submit_initialization_draft(
    db: Session,
    context: ToolContext,
    args: SubmitInitializationDraftArgs,
) -> dict[str, Any]:
    if not context.can_submit_initialization_draft:
        raise HTTPException(
            status_code=403,
            detail="只有项目初始化智能体会话可以提交初始化草稿",
        )
    issues = validate_initialization_payload(args.payload)
    status_value = draft_status(issues)
    source_files = list(dict.fromkeys(item.strip() for item in args.source_files if item.strip()))
    if args.draft_id is None:
        draft = ProjectInitializationDraft(
            project_id=context.project.id,
            conversation_id=context.conversation.id,
            created_by_user_id=context.user.id,
            status=status_value,
            revision=1,
            payload=args.payload.model_dump(mode="json"),
            validation_issues=issues,
            source_files=source_files,
        )
        db.add(draft)
        db.flush()
        action = "Dobby 提交项目初始化草稿"
    else:
        draft = db.get(ProjectInitializationDraft, args.draft_id)
        if (
            draft is None
            or draft.project_id != context.project.id
            or draft.conversation_id != context.conversation.id
        ):
            raise HTTPException(status_code=404, detail="初始化草稿不存在")
        if draft.status == "applied":
            raise HTTPException(status_code=409, detail="已入库草稿不能继续修改")
        draft.status = status_value
        draft.revision += 1
        draft.payload = args.payload.model_dump(mode="json")
        draft.validation_issues = issues
        draft.source_files = source_files
        action = "Dobby 更新项目初始化草稿"
        db.flush()
    _audit(
        db,
        context,
        action,
        f"初始化草稿第 {draft.revision} 版，状态 {draft.status}",
        "project_initialization_draft",
        draft.id,
    )
    db.commit()
    db.refresh(draft)
    return {
        **_public_row(
            draft,
            (
                "id",
                "project_id",
                "conversation_id",
                "status",
                "revision",
                "payload",
                "validation_issues",
                "source_files",
                "created_at",
                "updated_at",
            ),
        ),
        "summary": {
            **_draft_summary(args.payload, issues),
        },
    }


def _update_initialization_draft(
    db: Session,
    context: ToolContext,
    args: UpdateInitializationDraftArgs,
) -> dict[str, Any]:
    if not context.can_submit_initialization_draft:
        raise HTTPException(
            status_code=403,
            detail="只有项目初始化智能体会话可以更新初始化草稿",
        )
    draft = db.get(ProjectInitializationDraft, args.draft_id)
    if (
        draft is None
        or draft.project_id != context.project.id
        or draft.conversation_id != context.conversation.id
    ):
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    if draft.status == "applied":
        raise HTTPException(status_code=409, detail="已入库草稿不能继续修改")
    if draft.revision != args.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=(
                f"初始化草稿已更新，当前修订号为 {draft.revision}；"
                "请重新读取草稿后再提交增量修改"
            ),
        )

    current = ProjectInitializationPayload.model_validate(draft.payload)
    merged_data = current.model_dump(mode="python")
    patch_data = args.patch.model_dump(mode="python", exclude_unset=True)
    if "project" in patch_data:
        merged_project = dict(merged_data.get("project") or {})
        merged_project.update(patch_data["project"])
        patch_data["project"] = merged_project
    merged_data.update(patch_data)
    merged = ProjectInitializationPayload.model_validate(merged_data)
    issues = validate_initialization_payload(merged)

    new_source_files = [
        item.strip()
        for item in args.source_files
        if item.strip()
    ]
    draft.status = draft_status(issues)
    draft.revision += 1
    draft.payload = merged.model_dump(mode="json")
    draft.validation_issues = issues
    draft.source_files = list(
        dict.fromkeys([*(draft.source_files or []), *new_source_files]),
    )
    updated_sections = sorted(args.patch.model_fields_set)
    _audit(
        db,
        context,
        "Dobby 增量更新项目初始化草稿",
        (
            f"更新草稿分区：{'、'.join(updated_sections)}；"
            f"状态 {draft.status}"
        ),
        "project_initialization_draft",
        draft.id,
    )
    db.commit()
    db.refresh(draft)
    return {
        **_public_row(
            draft,
            (
                "id",
                "project_id",
                "conversation_id",
                "status",
                "revision",
                "validation_issues",
                "source_files",
                "created_at",
                "updated_at",
            ),
        ),
        "updated_sections": updated_sections,
        "summary": _draft_summary(merged, issues),
    }


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
    if args.risk_window_start_date and args.risk_window_end_date:
        if args.risk_window_end_date < args.risk_window_start_date:
            raise HTTPException(
                status_code=422,
                detail="风险窗口结束日期不能早于开始日期",
            )
    if args.related_wbs_item_id is not None:
        _project_entity(
            db,
            WbsItem,
            args.related_wbs_item_id,
            context.project.id,
            "关联 WBS 不存在",
        )
    duplicate = db.scalar(
        select(RiskSource).where(
            RiskSource.project_id == context.project.id,
            RiskSource.serial_no == args.serial_no,
        ),
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="当前项目已存在相同风险序号")
    risk = RiskSource(
        project_id=context.project.id,
        serial_no=args.serial_no,
        related_wbs_item_id=args.related_wbs_item_id,
        related_process_name=args.related_process_name.strip(),
        risk_part=args.risk_part.strip(),
        risk_level=args.risk_level.strip(),
        evaluation_condition=args.evaluation_condition.strip(),
        risk_window_start_date=args.risk_window_start_date,
        risk_window_end_date=args.risk_window_end_date,
        summary=args.summary,
    )
    db.add(risk)
    db.flush()
    _audit(
        db,
        context,
        "Dobby 新增风险源",
        f"新增风险源「{risk.serial_no} · {risk.risk_part}」",
        "risk",
        risk.id,
    )
    db.commit()
    db.refresh(risk)
    return _public_row(
        risk,
        (
            "id", "serial_no", "related_wbs_item_id",
            "related_process_name", "risk_part", "risk_level",
            "evaluation_condition", "risk_window_start_date",
            "risk_window_end_date", "summary", "created_at",
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
    previous = f"{item.progress_percent}%/{item.status_text or '未设置'}"
    item.progress_percent = args.progress_percent
    if args.status_text is not None:
        item.status_text = args.status_text
    _audit(
        db,
        context,
        "Dobby 更新 WBS 进度",
        (
            f"工序「{item.wbs_code} {item.name}」由 {previous} 更新为 "
            f"{item.progress_percent}%/{item.status_text or '未设置'}"
            + (f"，说明：{args.note}" if args.note else "")
        ),
        "wbs",
        item.id,
    )
    db.commit()
    db.refresh(item)
    return _public_row(
        item,
        (
            "id",
            "wbs_code",
            "name",
            "progress_percent",
            "status_text",
            "updated_at",
        ),
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
    if operation == "get_project_initialization_state":
        if arguments:
            raise HTTPException(status_code=422, detail="该操作不接受参数")
        return (
            _get_initialization_state(db, context),
            "已读取当前项目初始化数据",
        )
    if operation == "get_project_initialization_draft":
        args = _parse_args(ReadInitializationDraftArgs, arguments)
        assert isinstance(args, ReadInitializationDraftArgs)
        return (
            _get_initialization_draft(db, context, args),
            "已读取当前项目初始化草稿",
        )
    if operation == "list_project_items":
        args = _parse_args(ListItemsArgs, arguments)
        assert isinstance(args, ListItemsArgs)
        return _list_items(db, context, args), "已读取当前项目数据"
    if operation == "search_documents":
        args = _parse_args(SearchDocumentsArgs, arguments)
        assert isinstance(args, SearchDocumentsArgs)
        return _search_documents(db, context, args), "已检索当前项目资料"
    if operation == "submit_project_initialization_draft":
        args = _parse_args(SubmitInitializationDraftArgs, arguments)
        assert isinstance(args, SubmitInitializationDraftArgs)
        return (
            _submit_initialization_draft(db, context, args),
            "项目初始化草稿已提交，等待用户核对",
        )
    if operation == "update_project_initialization_draft":
        args = _parse_args(UpdateInitializationDraftArgs, arguments)
        assert isinstance(args, UpdateInitializationDraftArgs)
        return (
            _update_initialization_draft(db, context, args),
            "项目初始化草稿已增量更新，等待用户核对",
        )
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
                "initialization_draft": (
                    context.can_submit_initialization_draft
                ),
            },
        },
    )


@router.get(
    "/initialization-files/{file_id}/content",
    dependencies=[Depends(_require_service_token)],
    response_class=FileResponse,
)
def get_initialization_file_content(
    file_id: int,
    agentscope_session_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Stream one authorized raw file to the AgentScope-side parser."""
    context = resolve_tool_context(db, agentscope_session_id)
    if not context.can_submit_initialization_draft:
        raise HTTPException(
            status_code=403,
            detail="只有项目初始化智能体可以读取初始化附件",
        )
    row = db.get(ProjectInitializationFile, file_id)
    if (
        row is None
        or row.project_id != context.project.id
        or row.conversation_id != context.conversation.id
    ):
        raise HTTPException(status_code=404, detail="初始化附件不存在")
    path = Path(row.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="初始化附件文件已丢失")
    return FileResponse(
        path,
        media_type=row.content_type or "application/octet-stream",
        filename=row.file_name,
        headers={
            "X-Dobby-File-Extension": path.suffix.lower(),
            "Cache-Control": "no-store",
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
