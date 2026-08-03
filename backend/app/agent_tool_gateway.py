"""Internal, session-bound tool gateway used by AgentScope agents.

The browser never calls this router.  Every request is authenticated with an
internal service token and is scoped by an AgentScope session ID.  The platform
database is the authority for the account, project and role behind that
session; callers cannot provide or override those identifiers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
    ProjectInitializationDraftSection,
    ProjectInitializationDraftWorkflow,
    ProjectInitializationFile,
    ProjectInitializationArtifact,
    ProjectInitializationNormalization,
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
    BeginInitializationDraftArgs,
    BeginInitializationNormalizationArgs,
    FinalizeInitializationDraftArgs,
    FinalizeInitializationNormalizationArgs,
    ImportInitializationArtifactArgs,
    INITIALIZATION_ARTIFACT_BATCH_LIMIT,
    INITIALIZATION_ARTIFACT_ERROR_LIMIT,
    INITIALIZATION_ARTIFACT_MAX_BYTES,
    InitializationAgentRole,
    PersonnelDraft,
    ProjectDetailsDraft,
    ProjectInitializationPayload,
    QualityRequirementDraft,
    ReadInitializationArtifactArgs,
    ReadInitializationDraftArgs,
    RiskDraftItem,
    WbsDraft,
    WritableInitializationDraftSection,
    WriteInitializationArtifactArgs,
    WriteInitializationDraftSectionArgs,
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
    "read_project_initialization_artifact",
    "begin_project_initialization_normalization",
    "write_project_initialization_artifact",
    "finalize_project_initialization_normalization",
    "begin_project_initialization_draft",
    "import_project_initialization_artifact",
    "write_project_initialization_draft_section",
    "finalize_project_initialization_draft",
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
    actor_agent_id: str | None = Field(default=None, max_length=128)
    initialization_role: InitializationAgentRole | None = None
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
            detail=_compact_validation_error_detail(
                exc,
                message="工具参数校验失败",
            ),
        ) from exc


def _compact_validation_error_detail(
    exc: ValidationError,
    *,
    message: str,
    expected_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Return bounded validation feedback without echoing large raw inputs."""

    errors = exc.errors(include_url=False, include_input=False)
    visible = []
    for error in errors[:INITIALIZATION_ARTIFACT_ERROR_LIMIT]:
        location = ".".join(str(item) for item in error.get("loc", ())) or "$"
        visible.append(
            {
                "path": location,
                "message": str(error.get("msg") or "字段不合法"),
                "type": str(error.get("type") or "validation_error"),
            },
        )
    detail: dict[str, Any] = {
        "message": message,
        "error_count": len(errors),
        "errors": visible,
        "truncated": len(errors) > len(visible),
    }
    if expected_fields is not None:
        detail["expected_fields"] = expected_fields
    return detail


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
            "id", "serial_no", "related_process_name", "risk_part", "risk_level",
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
        draft = _initialization_draft_for_context(db, context)
        if draft is not None and state.get("latest_draft"):
            state["latest_draft"]["workflow"] = (
                initialization_draft_workflow_summary(db, draft)
            )
        normalization = _latest_normalization_for_context(db, context)
        state["latest_normalization"] = (
            _normalization_summary(db, normalization)
            if normalization is not None
            else None
        )
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


_INITIALIZATION_SECTION_BY_ROLE: dict[
    InitializationAgentRole,
    WritableInitializationDraftSection,
] = {
    "project": "project",
    "personnel": "personnel",
    "wbs": "wbs",
    "risks": "risks",
    "quality_requirements": "quality_requirements",
}


def _require_initialization_actor(
    context: ToolContext,
    role: InitializationAgentRole | None,
    allowed_roles: set[InitializationAgentRole],
) -> InitializationAgentRole:
    if not context.can_submit_initialization_draft:
        raise HTTPException(
            status_code=403,
            detail="只有项目初始化智能体会话可以执行该操作",
        )
    if role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="当前初始化智能体职责不允许执行该操作",
        )
    return role


def _initialization_files_by_ids(
    db: Session,
    context: ToolContext,
    file_ids: list[int],
) -> list[ProjectInitializationFile]:
    unique_ids = list(dict.fromkeys(file_ids))
    if not unique_ids:
        return []
    rows = db.scalars(
        select(ProjectInitializationFile).where(
            ProjectInitializationFile.id.in_(unique_ids),
            ProjectInitializationFile.project_id == context.project.id,
            ProjectInitializationFile.conversation_id == context.conversation.id,
        ),
    ).all()
    by_id = {row.id: row for row in rows}
    if any(file_id not in by_id for file_id in unique_ids):
        raise HTTPException(
            status_code=422,
            detail="标准化资料引用了不存在或不属于当前会话的附件",
        )
    return [by_id[file_id] for file_id in unique_ids]


def _normalization_for_context_by_id(
    db: Session,
    context: ToolContext,
    normalization_id: int,
) -> ProjectInitializationNormalization:
    normalization = db.get(ProjectInitializationNormalization, normalization_id)
    if (
        normalization is None
        or normalization.project_id != context.project.id
        or normalization.conversation_id != context.conversation.id
    ):
        raise HTTPException(status_code=404, detail="初始化标准化批次不存在")
    return normalization


def _latest_normalization_for_context(
    db: Session,
    context: ToolContext,
) -> ProjectInitializationNormalization | None:
    return db.scalar(
        select(ProjectInitializationNormalization)
        .where(
            ProjectInitializationNormalization.project_id == context.project.id,
            ProjectInitializationNormalization.conversation_id
            == context.conversation.id,
        )
        .order_by(
            ProjectInitializationNormalization.updated_at.desc(),
            ProjectInitializationNormalization.id.desc(),
        ),
    )


def _normalization_artifact_rows(
    db: Session,
    normalization_id: int,
    section: WritableInitializationDraftSection | None = None,
) -> list[ProjectInitializationArtifact]:
    stmt = select(ProjectInitializationArtifact).where(
        ProjectInitializationArtifact.normalization_id == normalization_id,
    )
    if section is not None:
        stmt = stmt.where(ProjectInitializationArtifact.section == section)
    return list(
        db.scalars(
            stmt.order_by(
                ProjectInitializationArtifact.section,
                ProjectInitializationArtifact.artifact_format,
                ProjectInitializationArtifact.part_index,
            ),
        ).all(),
    )


def _normalization_summary(
    db: Session,
    normalization: ProjectInitializationNormalization,
) -> dict[str, Any]:
    artifacts = _normalization_artifact_rows(db, normalization.id)
    sections: dict[str, dict[str, Any]] = {}
    for row in artifacts:
        item = sections.setdefault(
            row.section,
            {
                "parts": 0,
                "json_parts": 0,
                "markdown_parts": 0,
                "formats": [],
                "json_import_ready": False,
            },
        )
        item["parts"] += 1
        if row.artifact_format not in item["formats"]:
            item["formats"].append(row.artifact_format)
        if row.artifact_format == "json":
            item["json_import_ready"] = True
            item["json_parts"] += 1
        else:
            item["markdown_parts"] += 1
    return {
        "id": normalization.id,
        "status": normalization.status,
        "draft_id": normalization.draft_id,
        "source_file_ids": list(normalization.source_file_ids or []),
        "source_files": list(normalization.source_files or []),
        "expected_sections": list(normalization.expected_sections or []),
        "validation_issues": list(normalization.validation_issues or []),
        "sections": sections,
        "created_at": (
            normalization.created_at.isoformat()
            if normalization.created_at is not None
            else None
        ),
        "updated_at": (
            normalization.updated_at.isoformat()
            if normalization.updated_at is not None
            else None
        ),
    }


def _begin_initialization_normalization(
    db: Session,
    context: ToolContext,
    args: BeginInitializationNormalizationArgs,
    actor_agent_id: str | None,
) -> dict[str, Any]:
    if not actor_agent_id:
        raise HTTPException(status_code=403, detail="无法确认初始化主智能体")
    files = _initialization_files_by_ids(db, context, args.source_file_ids)
    normalization = ProjectInitializationNormalization(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        created_by_agent_id=actor_agent_id,
        status="collecting",
        source_file_ids=[row.id for row in files],
        source_files=[row.file_name for row in files],
        expected_sections=[],
        validation_issues=[],
    )
    db.add(normalization)
    db.flush()
    _audit(
        db,
        context,
        "Dobby 开始标准化项目初始化资料",
        (
            f"标准化批次 {normalization.id}；"
            f"{len(files)} 个原始附件；编排智能体 {actor_agent_id}"
        ),
        "project_initialization_normalization",
        normalization.id,
    )
    db.commit()
    db.refresh(normalization)
    return _normalization_summary(db, normalization)


def _canonical_artifact_payload(
    section: WritableInitializationDraftSection,
    rows: list[ProjectInitializationArtifact],
) -> dict[str, Any] | list[dict[str, Any]]:
    json_rows = [row for row in rows if row.artifact_format == "json"]
    if not json_rows:
        raise HTTPException(
            status_code=409,
            detail=f"{section} 标准资料只有 Markdown，尚不能直接批量写入草稿",
        )
    if section == "project":
        if len(json_rows) != 1 or not isinstance(json_rows[0].json_payload, dict):
            raise HTTPException(
                status_code=422,
                detail="工程基本信息必须使用一个 JSON 对象标准化",
            )
        return _normalize_initialization_section(
            section,
            json_rows[0].json_payload,
        )

    combined: list[dict[str, Any]] = []
    for row in json_rows:
        if not isinstance(row.json_payload, list):
            raise HTTPException(
                status_code=422,
                detail=f"{section} 的每个 JSON 分片都必须是数组",
            )
        combined.extend(row.json_payload)
    return _normalize_initialization_section(section, combined)


def _write_initialization_artifact(
    db: Session,
    context: ToolContext,
    args: WriteInitializationArtifactArgs,
    actor_agent_id: str | None,
) -> dict[str, Any]:
    if not actor_agent_id:
        raise HTTPException(status_code=403, detail="无法确认标准资料写入智能体")
    normalization = _normalization_for_context_by_id(
        db,
        context,
        args.normalization_id,
    )
    if normalization.status != "collecting":
        raise HTTPException(
            status_code=409,
            detail="标准化批次已经完成，不能继续修改",
        )
    batch_file_ids = set(normalization.source_file_ids or [])
    if any(file_id not in batch_file_ids for file_id in args.source_file_ids):
        raise HTTPException(
            status_code=422,
            detail="标准资料只能引用本标准化批次中的原始附件",
        )
    _initialization_files_by_ids(db, context, args.source_file_ids)

    safe_name = Path(args.file_name).name
    if safe_name != args.file_name:
        raise HTTPException(status_code=422, detail="标准资料名称不能包含路径")
    suffix = Path(safe_name).suffix.lower()
    expected_suffixes = (
        {".json"}
        if args.artifact_format == "json"
        else {".md", ".markdown"}
    )
    if suffix not in expected_suffixes:
        raise HTTPException(
            status_code=422,
            detail=(
                "标准资料名称后缀必须与格式一致："
                + (".json" if args.artifact_format == "json" else ".md")
            ),
        )

    existing_rows = _normalization_artifact_rows(
        db,
        normalization.id,
        args.section,
    )
    format_rows = [
        row
        for row in existing_rows
        if row.artifact_format == args.artifact_format
    ]
    row = next(
        (item for item in format_rows if item.part_index == args.part_index),
        None,
    )
    if row is None:
        expected_part_index = (
            max(item.part_index for item in format_rows) + 1
            if format_rows
            else 1
        )
        if args.part_index != expected_part_index:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{args.artifact_format} 分片必须连续写入；"
                    f"当前应写第 {expected_part_index} 部分"
                ),
            )

    json_payload: Any | None = None
    markdown_content: str | None = None
    record_count: int | None = None
    write_stage = "markdown"
    if args.artifact_format == "json":
        if args.section == "project" and args.part_index != 1:
            raise HTTPException(
                status_code=422,
                detail="工程基本信息 JSON 不允许拆成多个分片",
            )
        if args.section != "project":
            if not isinstance(args.json_data, list):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{args.section} 标准 JSON 必须使用记录数组；"
                        "第一部分只放 1 条，后续每部分最多 "
                        f"{INITIALIZATION_ARTIFACT_BATCH_LIMIT} 条"
                    ),
                )
            record_count = len(args.json_data)
            if args.part_index == 1 and record_count != 1:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "首个 JSON 分片必须只提交 1 条记录进行字段试写；"
                        "试写成功后再从第 2 部分开始批量提交"
                    ),
                )
            if args.part_index > 1 and not (
                1 <= record_count <= INITIALIZATION_ARTIFACT_BATCH_LIMIT
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "批量 JSON 分片每次最多 "
                        f"{INITIALIZATION_ARTIFACT_BATCH_LIMIT} 条记录，"
                        "且至少提交 1 条"
                    ),
                )
            write_stage = (
                "probe_accepted"
                if args.part_index == 1
                else "batch_accepted"
            )
        else:
            record_count = 1
            write_stage = "single_object_accepted"
        json_payload = _normalize_initialization_section(
            args.section,
            args.json_data,
        )
        encoded = json.dumps(
            json_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    else:
        markdown_content = (args.markdown_content or "").strip()
        encoded = markdown_content.encode("utf-8")

    if len(encoded) > INITIALIZATION_ARTIFACT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "单个标准资料分片不能超过 "
                f"{INITIALIZATION_ARTIFACT_MAX_BYTES // 1024}KB；"
                "请继续拆分后写入"
            ),
        )

    values = {
        "artifact_format": args.artifact_format,
        "file_name": safe_name,
        "json_payload": json_payload,
        "markdown_content": markdown_content,
        "source_file_ids": list(args.source_file_ids),
        "source_locations": list(args.source_locations),
        "writer_agent_id": actor_agent_id,
        "schema_version": 1,
        "content_size": len(encoded),
        "content_hash": hashlib.sha256(encoded).hexdigest(),
    }
    if row is None:
        row = ProjectInitializationArtifact(
            normalization_id=normalization.id,
            project_id=context.project.id,
            conversation_id=context.conversation.id,
            section=args.section,
            part_index=args.part_index,
            revision=1,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.revision += 1
    normalization.validation_issues = []
    db.flush()
    _audit(
        db,
        context,
        "Dobby 写入项目初始化标准资料",
        (
            f"标准化批次 {normalization.id}；{args.section}；"
            f"第 {args.part_index} 部分；{args.artifact_format}"
        ),
        "project_initialization_artifact",
        row.id,
    )
    db.commit()
    db.refresh(row)
    return {
        "artifact_id": row.id,
        "normalization_id": normalization.id,
        "section": row.section,
        "format": row.artifact_format,
        "part_index": row.part_index,
        "file_name": row.file_name,
        "revision": row.revision,
        "content_size": row.content_size,
        "content_hash": row.content_hash,
        "record_count": record_count,
        "write_stage": write_stage,
        "schema_validated": args.artifact_format == "json",
        "batch_limit": INITIALIZATION_ARTIFACT_BATCH_LIMIT,
        "max_bytes": INITIALIZATION_ARTIFACT_MAX_BYTES,
        "next_part_index": max(
            (
                item.part_index
                for item in _normalization_artifact_rows(
                    db,
                    normalization.id,
                    args.section,
                )
                if item.artifact_format == args.artifact_format
            ),
            default=0,
        )
        + 1,
    }


def _finalize_initialization_normalization(
    db: Session,
    context: ToolContext,
    args: FinalizeInitializationNormalizationArgs,
) -> dict[str, Any]:
    normalization = _normalization_for_context_by_id(
        db,
        context,
        args.normalization_id,
    )
    if normalization.status != "collecting":
        raise HTTPException(
            status_code=409,
            detail="标准化批次已经完成",
        )
    rows = _normalization_artifact_rows(db, normalization.id)
    by_section: dict[str, list[ProjectInitializationArtifact]] = {}
    for row in rows:
        by_section.setdefault(row.section, []).append(row)

    issues: list[dict[str, Any]] = []
    for section in args.expected_sections:
        section_rows = by_section.get(section, [])
        if not section_rows:
            issues.append(
                {
                    "section": section,
                    "message": "缺少该业务分区的标准资料",
                },
            )
            continue
        json_rows = [
            row
            for row in section_rows
            if row.artifact_format == "json"
        ]
        if not json_rows:
            issues.append(
                {
                    "section": section,
                    "message": (
                        "该业务分区只有 Markdown，"
                        "或尚未写入可入草稿的标准 JSON"
                    ),
                },
            )
            continue
        indices = sorted(row.part_index for row in json_rows)
        expected_indices = list(range(1, max(indices) + 1))
        if indices != expected_indices:
            issues.append(
                {
                    "section": section,
                    "message": "标准资料分片编号必须从 1 连续排列",
                },
            )
        try:
            _canonical_artifact_payload(section, section_rows)
        except HTTPException as exc:
            issues.append(
                {
                    "section": section,
                    "message": exc.detail,
                },
            )

    normalization.expected_sections = list(args.expected_sections)
    normalization.validation_issues = issues
    if issues:
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "message": "标准资料尚未通过校验",
                "issues": issues,
            },
        )
    normalization.status = "ready"
    _audit(
        db,
        context,
        "Dobby 完成项目初始化资料标准化",
        (
            f"标准化批次 {normalization.id}；"
            f"分区：{'、'.join(args.expected_sections)}"
        ),
        "project_initialization_normalization",
        normalization.id,
    )
    db.commit()
    db.refresh(normalization)
    return _normalization_summary(db, normalization)


def _read_initialization_artifact(
    db: Session,
    context: ToolContext,
    args: ReadInitializationArtifactArgs,
) -> dict[str, Any]:
    normalization = _normalization_for_context_by_id(
        db,
        context,
        args.normalization_id,
    )
    rows = _normalization_artifact_rows(
        db,
        normalization.id,
        args.section,
    )
    manifest = [
        {
            "artifact_id": row.id,
            "part_index": row.part_index,
            "file_name": row.file_name,
            "format": row.artifact_format,
            "revision": row.revision,
            "content_size": row.content_size,
            "source_file_ids": list(row.source_file_ids or []),
            "source_locations": list(row.source_locations or []),
        }
        for row in rows
    ]
    if args.part_index is None:
        return {
            "normalization": _normalization_summary(db, normalization),
            "section": args.section,
            "parts": manifest,
            "data": None,
        }
    row = next(
        (
            item
            for item in rows
            if item.part_index == args.part_index
            and item.artifact_format == args.artifact_format
        ),
        None,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="标准资料分片不存在")

    if row.artifact_format == "json":
        content = row.json_payload
        if isinstance(content, list):
            selected = content[
                args.start - 1:args.start - 1 + args.limit
            ]
            total = len(content)
            end = args.start + len(selected) - 1 if selected else None
            next_start = end + 1 if end is not None and end < total else None
            data: Any = selected
        else:
            total = 1
            end = 1
            next_start = None
            data = content
    else:
        lines = (row.markdown_content or "").splitlines()
        selected_lines = lines[
            args.start - 1:args.start - 1 + args.limit
        ]
        total = len(lines)
        end = args.start + len(selected_lines) - 1 if selected_lines else None
        next_start = end + 1 if end is not None and end < total else None
        data = "\n".join(selected_lines)

    return {
        "normalization_id": normalization.id,
        "section": args.section,
        "artifact": next(
            item
            for item in manifest
            if item["part_index"] == args.part_index
            and item["format"] == args.artifact_format
        ),
        "start": args.start,
        "end": end,
        "total": total,
        "next_start": next_start,
        "data": data,
    }


def _draft_for_context_by_id(
    db: Session,
    context: ToolContext,
    draft_id: int,
) -> ProjectInitializationDraft:
    draft = db.get(ProjectInitializationDraft, draft_id)
    if (
        draft is None
        or draft.project_id != context.project.id
        or draft.conversation_id != context.conversation.id
    ):
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    if draft.status in {"applied", "rejected"}:
        raise HTTPException(status_code=409, detail="该初始化草稿已结束，不能继续修改")
    return draft


def _workflow_for_draft(
    db: Session,
    draft_id: int,
) -> ProjectInitializationDraftWorkflow | None:
    return db.get(ProjectInitializationDraftWorkflow, draft_id)


def _section_rows(
    db: Session,
    draft_id: int,
) -> list[ProjectInitializationDraftSection]:
    return list(
        db.scalars(
            select(ProjectInitializationDraftSection)
            .where(ProjectInitializationDraftSection.draft_id == draft_id)
            .order_by(ProjectInitializationDraftSection.id),
        ).all(),
    )


_INITIALIZATION_SECTION_MODELS: dict[
    WritableInitializationDraftSection,
    type[BaseModel],
] = {
    "project": ProjectDetailsDraft,
    "personnel": PersonnelDraft,
    "wbs": WbsDraft,
    "risks": RiskDraftItem,
    "quality_requirements": QualityRequirementDraft,
}


def _normalize_initialization_section(
    section: WritableInitializationDraftSection,
    data: Any,
) -> dict[str, Any] | list[dict[str, Any]]:
    try:
        normalized = ProjectInitializationPayload.model_validate(
            {section: data},
        )
    except ValidationError as exc:
        expected_fields = list(
            _INITIALIZATION_SECTION_MODELS[section].model_fields,
        )
        raise HTTPException(
            status_code=422,
            detail=_compact_validation_error_detail(
                exc,
                message=f"{section} 标准资料字段校验失败",
                expected_fields=expected_fields,
            ),
        ) from exc
    value = normalized.model_dump(mode="json")[section]
    assert isinstance(value, (dict, list))
    return value


def compose_initialization_draft_payload(
    db: Session,
    draft: ProjectInitializationDraft,
) -> ProjectInitializationPayload:
    """Compose the current draft from independent specialist-owned sections."""
    base = ProjectInitializationPayload.model_validate(draft.payload or {})
    data = base.model_dump(mode="python")
    for row in _section_rows(db, draft.id):
        section = row.section
        if section in _INITIALIZATION_SECTION_BY_ROLE.values():
            data[section] = row.payload
    return ProjectInitializationPayload.model_validate(data)


def initialization_draft_workflow_summary(
    db: Session,
    draft: ProjectInitializationDraft,
) -> dict[str, Any] | None:
    workflow = _workflow_for_draft(db, draft.id)
    if workflow is None:
        return None
    current_sections = {
        row.section
        for row in _section_rows(db, draft.id)
        if row.workflow_revision == workflow.run_revision
    }
    expected = list(workflow.expected_sections or [])
    completed = [section for section in expected if section in current_sections]
    pending = [section for section in expected if section not in current_sections]
    return {
        "stage": workflow.stage,
        "run_revision": workflow.run_revision,
        "expected_sections": expected,
        "completed_sections": completed,
        "pending_sections": pending,
        "reviewer_agent_id": workflow.reviewer_agent_id,
        "semantic_issues": list(workflow.semantic_issues or []),
        "review_summary": workflow.review_summary,
        "updated_at": (
            workflow.updated_at.isoformat()
            if workflow.updated_at is not None
            else None
        ),
    }


def _begin_initialization_draft(
    db: Session,
    context: ToolContext,
    args: BeginInitializationDraftArgs,
    actor_agent_id: str | None,
) -> dict[str, Any]:
    normalization = _normalization_for_context_by_id(
        db,
        context,
        args.normalization_id,
    )
    if normalization.status != "ready":
        raise HTTPException(
            status_code=409,
            detail="必须先完成原始附件标准化，才能建立草稿任务",
        )
    if set(normalization.expected_sections or []) != set(
        args.expected_sections,
    ):
        raise HTTPException(
            status_code=422,
            detail="草稿任务分区必须与已完成的标准化分区一致",
        )
    draft = _initialization_draft_for_context(db, context)
    if draft is None or draft.status in {"applied", "rejected"}:
        draft = ProjectInitializationDraft(
            project_id=context.project.id,
            conversation_id=context.conversation.id,
            created_by_user_id=context.user.id,
            status="invalid",
            revision=1,
            payload=ProjectInitializationPayload().model_dump(mode="json"),
            validation_issues=[],
            source_files=[],
        )
        db.add(draft)
        db.flush()
        workflow = ProjectInitializationDraftWorkflow(
            draft_id=draft.id,
            expected_sections=list(args.expected_sections),
            stage="collecting",
            run_revision=1,
        )
        db.add(workflow)
    else:
        workflow = _workflow_for_draft(db, draft.id)
        if workflow is None:
            workflow = ProjectInitializationDraftWorkflow(
                draft_id=draft.id,
                expected_sections=list(args.expected_sections),
                stage="collecting",
                run_revision=1,
            )
            db.add(workflow)
        else:
            workflow.expected_sections = list(args.expected_sections)
            workflow.stage = "collecting"
            workflow.run_revision += 1
            workflow.reviewer_agent_id = None
            workflow.semantic_issues = []
            workflow.review_summary = None
        draft.status = "invalid"
        draft.validation_issues = []

    source_files = [
        item.strip()
        for item in [
            *(normalization.source_files or []),
            *args.source_files,
        ]
        if item.strip()
    ]
    draft.source_files = list(
        dict.fromkeys([*(draft.source_files or []), *source_files]),
    )
    normalization.status = "consumed"
    normalization.draft_id = draft.id
    _audit(
        db,
        context,
        "Dobby 开始项目初始化草稿任务",
        (
            f"本轮等待分区：{'、'.join(args.expected_sections)}；"
            f"标准化批次 {normalization.id}；"
            f"编排智能体 {actor_agent_id or '未知'}"
        ),
        "project_initialization_draft",
        draft.id,
    )
    db.commit()
    db.refresh(draft)
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
        "workflow": initialization_draft_workflow_summary(db, draft),
        "normalization": _normalization_summary(db, normalization),
    }


def _write_initialization_draft_section(
    db: Session,
    context: ToolContext,
    args: WriteInitializationDraftSectionArgs,
    actor_agent_id: str | None,
    actor_role: InitializationAgentRole,
) -> dict[str, Any]:
    section = _INITIALIZATION_SECTION_BY_ROLE.get(actor_role)
    if section is None:
        raise HTTPException(status_code=403, detail="当前智能体没有可写入的草稿分区")
    if not actor_agent_id:
        raise HTTPException(status_code=403, detail="无法确认草稿分区写入智能体")
    draft = _draft_for_context_by_id(db, context, args.draft_id)
    workflow = _workflow_for_draft(db, draft.id)
    if workflow is None:
        raise HTTPException(status_code=409, detail="请先由初始化主智能体建立草稿任务")
    if section not in (workflow.expected_sections or []):
        raise HTTPException(
            status_code=409,
            detail=f"本轮初始化任务未要求处理 {section} 分区",
        )

    normalized = _normalize_initialization_section(section, args.data)
    row = db.scalar(
        select(ProjectInitializationDraftSection).where(
            ProjectInitializationDraftSection.draft_id == draft.id,
            ProjectInitializationDraftSection.section == section,
        ),
    )
    source_files = [
        item.strip()
        for item in args.source_files
        if item.strip()
    ]
    notes = [
        item.strip()
        for item in args.extraction_notes
        if item.strip()
    ]
    if row is None:
        row = ProjectInitializationDraftSection(
            draft_id=draft.id,
            project_id=context.project.id,
            conversation_id=context.conversation.id,
            section=section,
            writer_agent_id=actor_agent_id,
            workflow_revision=workflow.run_revision,
            revision=1,
            payload=normalized,
            source_files=source_files,
            extraction_notes=notes,
        )
        db.add(row)
    else:
        row.writer_agent_id = actor_agent_id
        row.workflow_revision = workflow.run_revision
        row.revision += 1
        row.payload = normalized
        row.source_files = source_files
        row.extraction_notes = notes

    draft.source_files = list(
        dict.fromkeys([*(draft.source_files or []), *source_files]),
    )
    db.flush()
    summary = initialization_draft_workflow_summary(db, draft)
    if summary and not summary["pending_sections"]:
        workflow.stage = "reviewing"
    _audit(
        db,
        context,
        "Dobby 写入项目初始化草稿分区",
        f"{actor_agent_id} 完成 {section} 分区",
        "project_initialization_draft",
        draft.id,
    )
    db.commit()
    db.refresh(row)
    return {
        "draft_id": draft.id,
        "section": section,
        "section_revision": row.revision,
        "record_count": len(normalized) if isinstance(normalized, list) else 1,
        "workflow": initialization_draft_workflow_summary(db, draft),
    }


def _import_initialization_artifact(
    db: Session,
    context: ToolContext,
    args: ImportInitializationArtifactArgs,
    actor_agent_id: str | None,
    actor_role: InitializationAgentRole,
) -> dict[str, Any]:
    section = _INITIALIZATION_SECTION_BY_ROLE.get(actor_role)
    if section is None:
        raise HTTPException(status_code=403, detail="当前智能体没有可导入的草稿分区")
    normalization = _normalization_for_context_by_id(
        db,
        context,
        args.normalization_id,
    )
    if (
        normalization.status != "consumed"
        or normalization.draft_id != args.draft_id
    ):
        raise HTTPException(
            status_code=409,
            detail="标准化批次尚未绑定到当前草稿任务",
        )
    rows = _normalization_artifact_rows(
        db,
        normalization.id,
        section,
    )
    normalized = _canonical_artifact_payload(section, rows)
    artifact_refs = [
        f"{row.file_name}#{row.part_index}"
        for row in rows
        if row.artifact_format == "json"
    ]
    result = _write_initialization_draft_section(
        db,
        context,
        WriteInitializationDraftSectionArgs(
            draft_id=args.draft_id,
            data=normalized,
            source_files=list(normalization.source_files or []),
            extraction_notes=[
                f"由标准化批次 {normalization.id} 批量导入："
                + "、".join(artifact_refs),
                *args.extraction_notes,
            ],
        ),
        actor_agent_id,
        actor_role,
    )
    return {
        **result,
        "normalization_id": normalization.id,
        "imported_artifacts": artifact_refs,
    }


def _finalize_initialization_draft(
    db: Session,
    context: ToolContext,
    args: FinalizeInitializationDraftArgs,
    actor_agent_id: str | None,
) -> dict[str, Any]:
    if not actor_agent_id:
        raise HTTPException(status_code=403, detail="无法确认初始化核验智能体")
    draft = _draft_for_context_by_id(db, context, args.draft_id)
    workflow = _workflow_for_draft(db, draft.id)
    if workflow is None:
        raise HTTPException(status_code=409, detail="初始化草稿尚未建立执行流程")
    summary = initialization_draft_workflow_summary(db, draft)
    assert summary is not None
    if summary["pending_sections"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "仍有专项分区尚未完成："
                + "、".join(summary["pending_sections"])
            ),
        )

    payload = compose_initialization_draft_payload(db, draft)
    deterministic_issues = validate_initialization_payload(payload)
    semantic_issues = [
        item.model_dump(mode="json")
        for item in args.semantic_issues
    ]
    issues = [*deterministic_issues, *semantic_issues]
    draft.payload = payload.model_dump(mode="json")
    draft.validation_issues = issues
    draft.status = draft_status(issues)
    draft.revision += 1
    workflow.stage = "completed"
    workflow.reviewer_agent_id = actor_agent_id
    workflow.semantic_issues = semantic_issues
    workflow.review_summary = args.review_summary
    _audit(
        db,
        context,
        "Dobby 完成项目初始化草稿核验",
        (
            f"核验智能体 {actor_agent_id} 完成审查；"
            f"{len(deterministic_issues)} 项规则问题，"
            f"{len(semantic_issues)} 项语义问题"
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
                "payload",
                "validation_issues",
                "source_files",
                "created_at",
                "updated_at",
            ),
        ),
        "workflow": initialization_draft_workflow_summary(db, draft),
        "summary": _draft_summary(payload, issues),
    }


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

    payload = compose_initialization_draft_payload(db, draft)
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
        "workflow": initialization_draft_workflow_summary(db, draft),
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
            "id", "serial_no", "related_process_name", "risk_part", "risk_level",
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
    *,
    actor_agent_id: str | None = None,
    initialization_role: InitializationAgentRole | None = None,
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
    if operation == "read_project_initialization_artifact":
        _require_initialization_actor(
            context,
            initialization_role,
            {
                "orchestrator",
                "project",
                "personnel",
                "wbs",
                "risks",
                "quality_requirements",
                "validator",
            },
        )
        args = _parse_args(ReadInitializationArtifactArgs, arguments)
        assert isinstance(args, ReadInitializationArtifactArgs)
        return (
            _read_initialization_artifact(db, context, args),
            "已读取项目初始化标准资料",
        )
    if operation == "begin_project_initialization_normalization":
        _require_initialization_actor(
            context,
            initialization_role,
            {"orchestrator"},
        )
        args = _parse_args(BeginInitializationNormalizationArgs, arguments)
        assert isinstance(args, BeginInitializationNormalizationArgs)
        return (
            _begin_initialization_normalization(
                db,
                context,
                args,
                actor_agent_id,
            ),
            "项目初始化资料标准化批次已建立",
        )
    if operation == "write_project_initialization_artifact":
        _require_initialization_actor(
            context,
            initialization_role,
            {"orchestrator"},
        )
        args = _parse_args(WriteInitializationArtifactArgs, arguments)
        assert isinstance(args, WriteInitializationArtifactArgs)
        return (
            _write_initialization_artifact(
                db,
                context,
                args,
                actor_agent_id,
            ),
            "项目初始化标准资料已写入",
        )
    if operation == "finalize_project_initialization_normalization":
        _require_initialization_actor(
            context,
            initialization_role,
            {"orchestrator"},
        )
        args = _parse_args(
            FinalizeInitializationNormalizationArgs,
            arguments,
        )
        assert isinstance(args, FinalizeInitializationNormalizationArgs)
        return (
            _finalize_initialization_normalization(db, context, args),
            "项目初始化标准资料已完成校验",
        )
    if operation == "begin_project_initialization_draft":
        _require_initialization_actor(
            context,
            initialization_role,
            {"orchestrator"},
        )
        args = _parse_args(BeginInitializationDraftArgs, arguments)
        assert isinstance(args, BeginInitializationDraftArgs)
        return (
            _begin_initialization_draft(
                db,
                context,
                args,
                actor_agent_id,
            ),
            "项目初始化草稿任务已建立",
        )
    if operation == "write_project_initialization_draft_section":
        actor_role = _require_initialization_actor(
            context,
            initialization_role,
            set(_INITIALIZATION_SECTION_BY_ROLE),
        )
        args = _parse_args(WriteInitializationDraftSectionArgs, arguments)
        assert isinstance(args, WriteInitializationDraftSectionArgs)
        return (
            _write_initialization_draft_section(
                db,
                context,
                args,
                actor_agent_id,
                actor_role,
            ),
            "项目初始化草稿分区已写入",
        )
    if operation == "import_project_initialization_artifact":
        actor_role = _require_initialization_actor(
            context,
            initialization_role,
            set(_INITIALIZATION_SECTION_BY_ROLE),
        )
        args = _parse_args(ImportInitializationArtifactArgs, arguments)
        assert isinstance(args, ImportInitializationArtifactArgs)
        return (
            _import_initialization_artifact(
                db,
                context,
                args,
                actor_agent_id,
                actor_role,
            ),
            "项目初始化标准资料已批量导入草稿",
        )
    if operation == "finalize_project_initialization_draft":
        _require_initialization_actor(
            context,
            initialization_role,
            {"validator"},
        )
        args = _parse_args(FinalizeInitializationDraftArgs, arguments)
        assert isinstance(args, FinalizeInitializationDraftArgs)
        return (
            _finalize_initialization_draft(
                db,
                context,
                args,
                actor_agent_id,
            ),
            "项目初始化草稿已完成统一核验",
        )
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
        actor_agent_id=payload.actor_agent_id,
        initialization_role=payload.initialization_role,
    )
    return _ok(data, message)
