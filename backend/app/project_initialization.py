"""Initialization storage types and transactional application; MCP owns rules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import re
from typing import Any

from pypinyin import lazy_pinyin
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .engineering_document_catalog import (
    reconcile_name_based_catalogue_permissions,
)
from .models import (
    EngineeringDocumentPermission,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationValidationRun,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    QualityMetric,
    RiskSource,
    Task,
    User,
    WbsItem,
    WbsPredecessor,
    WbsRiskLink,
)
from .personnel_policy import (
    reconcile_user_management_roles,
)
from .security import hash_password


class StrictInitializationModel(BaseModel):
    """Storage field types only; requiredness and business rules belong to MCP.

    Draft ingestion uses the Any-valued patch envelope. These representations
    are constructed only for serialization/storage after the MCP decision.
    """

    model_config = ConfigDict(extra="forbid")


class ProjectDetailsDraft(StrictInitializationModel):
    record_id: int | None = Field(default=None)
    engineering_type_description: str | None = Field(default=None)
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contract_duration_days: int | None = Field(default=None)
    contract_amount_wan_yuan: Decimal | None = Field(default=None)
    construction_unit_name: str | None = Field(default=None)
    general_contractor_unit_name: str | None = Field(default=None)
    supervision_unit_name: str | None = Field(default=None)
    design_unit_name: str | None = Field(default=None)
    survey_unit_name: str | None = Field(default=None)


class PersonnelDraft(StrictInitializationModel):
    record_id: int | None = Field(default=None)
    serial_no: int = Field(default=None)
    real_name: str = Field(default=None)
    identity_card_no: str = Field(default=None)
    position_name: str = Field(default=None)
    certificate_no: str = Field(default=None)
    responsibility_description: str = Field(default=None)


class WbsDraft(StrictInitializationModel):
    record_id: int | None = Field(default=None)
    wbs_code: str = Field(default=None)
    parent_wbs_code: str | None = Field(default=None)
    predecessor_wbs_codes: list[str] = Field(default_factory=list)
    sort_order: int = Field(default=0)
    color_value: str | None = Field(default=None)
    name: str = Field(default=None)
    assigned_to_text: str | None = Field(default=None)
    planned_start_at: datetime | None = None
    planned_finish_at: datetime | None = None
    deadline_at: datetime | None = None
    progress_percent: Decimal | None = Field(default=None)
    duration_hours: Decimal | None = Field(default=None)
    estimated_hours: Decimal | None = Field(default=None)
    time_log_minutes: int | None = Field(default=None)
    status_text: str | None = Field(default=None)
    priority_text: str | None = Field(default=None)
    description: str | None = Field(default=None)
    budget: Decimal | None = Field(default=None)
    actual_cost: Decimal | None = Field(default=None)
    msp_uid: str | None = Field(default=None)
    msp_id: str | None = Field(default=None)
    source_created_at: datetime | None = None
    source_creator: str | None = Field(default=None)
    item_type: str | None = Field(default=None)
    source_project_path: str | None = Field(default=None)
    level: int = Field(default=None)


class RiskDraftItem(StrictInitializationModel):
    record_id: int | None = Field(default=None)
    serial_no: int = Field(default=None)
    related_process_name: str = Field(default=None)
    risk_part: str = Field(default=None)
    risk_level: str = Field(default=None)
    evaluation_condition: str = Field(default=None)
    risk_window_start_date: date | None = None
    risk_window_end_date: date | None = None
    summary: str | None = Field(default=None)


class QualityRequirementDraft(StrictInitializationModel):
    record_id: int | None = Field(default=None)
    wbs_code: str = Field(default=None)
    quality_acceptance_item: str = Field(default=None)
    control_indicator: str = Field(default=None)
    inspection_frequency: str = Field(default=None)
    related_documents: str = Field(default=None)


class ProjectInitializationPayload(StrictInitializationModel):
    project: ProjectDetailsDraft = Field(default_factory=ProjectDetailsDraft)
    personnel: list[PersonnelDraft] = Field(default_factory=list, max_length=2000)
    wbs: list[WbsDraft] = Field(default_factory=list, max_length=10000)
    risks: list[RiskDraftItem] = Field(default_factory=list, max_length=5000)
    quality_requirements: list[QualityRequirementDraft] = Field(
        default_factory=list,
        max_length=10000,
    )


class PersonnelCredentialInput(BaseModel):
    identity_card_no: str = Field(min_length=1, max_length=30)
    username: str = Field(min_length=1, max_length=64)
    initial_password: str = Field(min_length=8, max_length=128)


class ApplyInitializationDraftInput(BaseModel):
    preview_id: str | None = Field(default=None, max_length=36)
    allow_partial: bool = False
    personnel_credentials: list[PersonnelCredentialInput] = Field(
        default_factory=list,
        max_length=2000,
    )


def suggest_unique_username(
    real_name: str,
    identity_card_no: str,
    unavailable_usernames: set[str],
) -> str:
    """Create a readable lowercase username and avoid current account collisions."""
    pinyin_name = "".join(lazy_pinyin(real_name)).lower()
    base = re.sub(r"[^a-z0-9]+", "", pinyin_name)
    if not base:
        identity_suffix = re.sub(r"[^a-zA-Z0-9]+", "", identity_card_no)[-6:].lower()
        base = f"user{identity_suffix or 'new'}"
    base = base[:56]
    unavailable_lower = {item.lower() for item in unavailable_usernames}
    candidate = base
    sequence = 2
    while candidate.lower() in unavailable_lower:
        suffix = str(sequence)
        candidate = f"{base[:64 - len(suffix)]}{suffix}"
        sequence += 1
    return candidate


def draft_status(issues: list[dict[str, str]]) -> str:
    return "invalid" if any(item["level"] == "error" for item in issues) else "ready"


def _value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _value(getattr(row, field)) for field in fields}


def build_initialization_state(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """Return the canonical initialization sections for one project."""
    member_rows = db.execute(
        select(ProjectMemberPosition, ProjectMember, ProjectPosition, User)
        .join(
            ProjectMember,
            ProjectMember.id == ProjectMemberPosition.project_member_id,
        )
        .join(
            ProjectPosition,
            ProjectPosition.id == ProjectMemberPosition.position_id,
        )
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMemberPosition.project_id == project.id)
        .order_by(ProjectMemberPosition.serial_no),
    ).all()
    wbs_rows = db.scalars(
        select(WbsItem)
        .where(WbsItem.project_id == project.id)
        .order_by(WbsItem.sort_order, WbsItem.wbs_code),
    ).all()
    wbs_by_id = {item.id: item for item in wbs_rows}
    predecessor_codes: dict[int, list[str]] = {}
    if wbs_by_id:
        predecessors = db.scalars(
            select(WbsPredecessor).where(
                WbsPredecessor.wbs_item_id.in_(tuple(wbs_by_id)),
            ),
        ).all()
        for relation in predecessors:
            predecessor = wbs_by_id.get(relation.predecessor_wbs_item_id)
            if predecessor:
                predecessor_codes.setdefault(relation.wbs_item_id, []).append(
                    predecessor.wbs_code,
                )

    risks = db.scalars(
        select(RiskSource)
        .where(RiskSource.project_id == project.id)
        .order_by(RiskSource.serial_no),
    ).all()
    quality = db.scalars(
        select(QualityMetric)
        .where(QualityMetric.project_id == project.id)
        .order_by(QualityMetric.wbs_code),
    ).all()
    latest_draft = db.scalar(
        select(ProjectInitializationDraft)
        .where(ProjectInitializationDraft.project_id == project.id)
        .order_by(ProjectInitializationDraft.updated_at.desc()),
    )
    return {
        "project": _row(
            project,
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
        "personnel": [
            {
                **_row(
                    assignment,
                    (
                        "id",
                        "project_member_id",
                        "position_id",
                        "serial_no",
                        "certificate_no",
                        "responsibility_description",
                    ),
                ),
                "position_name": position.position_name,
                "user_id": user.id,
                "username": user.username,
                "real_name": user.real_name,
                "identity_card_no": user.identity_card_no,
                "role": user.role,
            }
            for assignment, member, position, user in member_rows
        ],
        "wbs": [
            {
                **_row(
                    item,
                    (
                        "id",
                        "sort_order",
                        "color_value",
                        "wbs_code",
                        "name",
                        "assigned_to_text",
                        "planned_start_at",
                        "planned_finish_at",
                        "deadline_at",
                        "progress_percent",
                        "duration_hours",
                        "estimated_hours",
                        "time_log_minutes",
                        "status_text",
                        "priority_text",
                        "description",
                        "budget",
                        "actual_cost",
                        "msp_uid",
                        "msp_id",
                        "source_created_at",
                        "source_creator",
                        "item_type",
                        "source_project_path",
                        "level",
                    ),
                ),
                "parent_wbs_code": (
                    wbs_by_id[item.parent_id].wbs_code
                    if item.parent_id in wbs_by_id
                    else None
                ),
                "predecessor_wbs_codes": predecessor_codes.get(item.id, []),
            }
            for item in wbs_rows
        ],
        "risks": [
            _row(
                item,
                (
                    "id",
                    "serial_no",
                    "related_process_name",
                    "risk_part",
                    "risk_level",
                    "evaluation_condition",
                    "risk_window_start_date",
                    "risk_window_end_date",
                    "summary",
                ),
            )
            for item in risks
        ],
        "quality_requirements": [
            _row(
                item,
                (
                    "id",
                    "wbs_code",
                    "quality_acceptance_item",
                    "control_indicator",
                    "inspection_frequency",
                    "related_documents",
                ),
            )
            for item in quality
        ],
        "latest_draft": (
            {
                "id": latest_draft.id,
                "status": latest_draft.status,
                "revision": latest_draft.revision,
                "validation_issues": latest_draft.validation_issues,
                "source_files": latest_draft.source_files,
                "updated_at": _value(latest_draft.updated_at),
            }
            if latest_draft
            else None
        ),
    }


class InitializationApplyError(ValueError):
    def __init__(self, message: str, issues: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.issues = issues or []


def apply_initialization_draft(
    db: Session,
    draft: ProjectInitializationDraft,
    request: ApplyInitializationDraftInput,
) -> dict[str, Any]:
    """Legacy endpoint also requires a reviewed incremental selection."""
    if not request.preview_id:
        raise InitializationApplyError("请先打开新版差异确认窗口，核对并选择本次要保存的内容。")
    from .initialization_change_contracts import ApplyInitializationChangesInput
    from .initialization_change_models import InitializationChangePreview
    from .initialization_change_service import apply_change_preview
    preview = db.get(InitializationChangePreview, request.preview_id)
    user = db.get(User, preview.user_id) if preview else None
    if user is None:
        raise InitializationApplyError("差异预览不存在，请重新核对。")
    return apply_change_preview(db, draft, user, ApplyInitializationChangesInput(
        preview_id=request.preview_id, allow_warnings=request.allow_partial,
        personnel_credentials=request.personnel_credentials,
    ))
