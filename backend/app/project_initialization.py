"""Validated project-initialization drafts and transactional application."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import re
from typing import Any, Literal

from pypinyin import lazy_pinyin
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    Project,
    ProjectInitializationDraft,
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
from .security import hash_password


class ProjectDetailsDraft(BaseModel):
    engineering_type_description: str | None = Field(default=None, max_length=10000)
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contract_duration_days: int | None = Field(default=None, gt=0)
    contract_amount_wan_yuan: Decimal | None = Field(default=None, ge=0)
    construction_unit_name: str | None = Field(default=None, max_length=300)
    general_contractor_unit_name: str | None = Field(default=None, max_length=300)
    supervision_unit_name: str | None = Field(default=None, max_length=300)
    design_unit_name: str | None = Field(default=None, max_length=300)
    survey_unit_name: str | None = Field(default=None, max_length=300)


class PersonnelDraft(BaseModel):
    serial_no: int = Field(gt=0)
    real_name: str = Field(min_length=1, max_length=100)
    identity_card_no: str = Field(min_length=1, max_length=30)
    position_name: str = Field(min_length=1, max_length=100)
    certificate_no: str = Field(min_length=1, max_length=100)
    responsibility_description: str = Field(min_length=1, max_length=10000)


class WbsDraft(BaseModel):
    wbs_code: str = Field(min_length=1, max_length=128)
    parent_wbs_code: str | None = Field(max_length=128)
    predecessor_wbs_codes: list[str] = Field(default_factory=list, max_length=100)
    sort_order: int = Field(default=0, ge=0)
    color_value: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=300)
    assigned_to_text: str | None = Field(default=None, max_length=300)
    planned_start_at: datetime | None
    planned_finish_at: datetime | None
    deadline_at: datetime | None = None
    progress_percent: Decimal | None = Field(ge=0, le=100)
    duration_hours: Decimal | None = Field(default=None, ge=0)
    estimated_hours: Decimal | None = Field(default=None, ge=0)
    time_log_minutes: int | None = Field(default=None, ge=0)
    status_text: str | None = Field(max_length=100)
    priority_text: str | None = Field(max_length=100)
    description: str | None = Field(default=None, max_length=20000)
    budget: Decimal | None = Field(default=None, ge=0)
    actual_cost: Decimal | None = Field(default=None, ge=0)
    msp_uid: str | None = Field(default=None, max_length=100)
    msp_id: str | None = Field(default=None, max_length=100)
    source_created_at: datetime | None = None
    source_creator: str | None = Field(default=None, max_length=200)
    item_type: str | None = Field(default=None, max_length=100)
    source_project_path: str | None = Field(default=None, max_length=10000)
    level: int = Field(gt=0, le=100)


class RiskDraftItem(BaseModel):
    serial_no: int = Field(gt=0)
    related_wbs_code: str | None = Field(default=None, max_length=128)
    related_process_name: str = Field(min_length=1, max_length=300)
    risk_part: str = Field(min_length=1, max_length=300)
    risk_level: str = Field(min_length=1, max_length=50)
    evaluation_condition: str = Field(min_length=1, max_length=20000)
    risk_window_start_date: date | None = None
    risk_window_end_date: date | None = None
    summary: str | None = Field(default=None, max_length=20000)


class QualityRequirementDraft(BaseModel):
    wbs_code: str = Field(min_length=1, max_length=128)
    quality_acceptance_item: str = Field(min_length=1, max_length=20000)
    control_indicator: str = Field(min_length=1, max_length=20000)
    inspection_frequency: str = Field(min_length=1, max_length=10000)
    related_documents: str = Field(min_length=1, max_length=20000)


class ProjectInitializationPayload(BaseModel):
    project: ProjectDetailsDraft = Field(default_factory=ProjectDetailsDraft)
    personnel: list[PersonnelDraft] = Field(default_factory=list, max_length=2000)
    wbs: list[WbsDraft] = Field(default_factory=list, max_length=10000)
    risks: list[RiskDraftItem] = Field(default_factory=list, max_length=5000)
    quality_requirements: list[QualityRequirementDraft] = Field(
        default_factory=list,
        max_length=10000,
    )


class SubmitInitializationDraftArgs(BaseModel):
    draft_id: int | None = Field(default=None, gt=0)
    payload: ProjectInitializationPayload
    source_files: list[str] = Field(default_factory=list, max_length=100)


InitializationDraftSection = Literal[
    "project",
    "personnel",
    "wbs",
    "risks",
    "quality_requirements",
    "validation_issues",
]


class ReadInitializationDraftArgs(BaseModel):
    section: InitializationDraftSection
    start: int = Field(default=1, ge=1)
    limit: int = Field(default=100, ge=1, le=500)


class ProjectInitializationPatch(BaseModel):
    project: ProjectDetailsDraft | None = None
    personnel: list[PersonnelDraft] | None = Field(default=None, max_length=2000)
    wbs: list[WbsDraft] | None = Field(default=None, max_length=10000)
    risks: list[RiskDraftItem] | None = Field(default=None, max_length=5000)
    quality_requirements: list[QualityRequirementDraft] | None = Field(
        default=None,
        max_length=10000,
    )

    @model_validator(mode="after")
    def require_non_null_section(self) -> "ProjectInitializationPatch":
        if not self.model_fields_set:
            raise ValueError("至少需要提供一个待更新的草稿分区")
        if any(
            getattr(self, field_name) is None
            for field_name in self.model_fields_set
        ):
            raise ValueError("草稿分区不能为 null；清空列表分区时请传空数组")
        return self


class UpdateInitializationDraftArgs(BaseModel):
    draft_id: int = Field(gt=0)
    expected_revision: int = Field(gt=0)
    patch: ProjectInitializationPatch
    source_files: list[str] = Field(default_factory=list, max_length=100)


class PersonnelCredentialInput(BaseModel):
    identity_card_no: str = Field(min_length=1, max_length=30)
    username: str = Field(min_length=1, max_length=64)
    initial_password: str = Field(min_length=8, max_length=128)


class ApplyInitializationDraftInput(BaseModel):
    allow_partial: bool = False
    personnel_credentials: list[PersonnelCredentialInput] = Field(
        default_factory=list,
        max_length=2000,
    )


ValidationLevel = Literal["error", "warning"]


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


def _issue(
    level: ValidationLevel,
    path: str,
    message: str,
) -> dict[str, str]:
    return {"level": level, "path": path, "message": message}


def _duplicates(values: list[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _wbs_code_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Sort dotted WBS codes by their numeric hierarchy."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in value.split(".")
    )


def validate_initialization_payload(
    payload: ProjectInitializationPayload,
) -> list[dict[str, str]]:
    """Validate cross-record relationships that Pydantic cannot express."""
    issues: list[dict[str, str]] = []
    project = payload.project
    if (
        project.contract_start_date
        and project.contract_end_date
        and project.contract_end_date < project.contract_start_date
    ):
        issues.append(
            _issue(
                "error",
                "project.contract_end_date",
                "合同竣工日期不能早于合同开工日期",
            ),
        )

    project_values = project.model_dump()
    missing_project_fields = [
        name for name, value in project_values.items() if value in (None, "")
    ]
    if missing_project_fields:
        issues.append(
            _issue(
                "warning",
                "project",
                "仍有项目基本信息未识别，可继续询问用户或由用户确认部分初始化",
            ),
        )

    if not payload.personnel:
        issues.append(_issue("warning", "personnel", "未识别到项目人员"))
    if not payload.wbs:
        issues.append(_issue("warning", "wbs", "未识别到 WBS 数据"))
    if not payload.risks:
        issues.append(_issue("warning", "risks", "未识别到风险清单"))
    if not payload.quality_requirements:
        issues.append(
            _issue(
                "warning",
                "quality_requirements",
                "未识别到工序质量指标",
            ),
        )

    for serial_no in sorted(_duplicates([item.serial_no for item in payload.personnel])):
        issues.append(
            _issue(
                "error",
                "personnel",
                f"人员序号 {serial_no} 重复",
            ),
        )
    personnel_by_card: dict[str, list[PersonnelDraft]] = {}
    for person in payload.personnel:
        personnel_by_card.setdefault(person.identity_card_no, []).append(person)
    for card_no, assignments in sorted(personnel_by_card.items()):
        if len(assignments) < 2:
            continue
        position_names = [item.position_name for item in assignments]
        for position_name in sorted(_duplicates(position_names)):
            issues.append(
                _issue(
                    "error",
                    "personnel",
                    f"身份证号 {card_no} 的岗位「{position_name}」重复",
                ),
            )
        unique_positions = list(dict.fromkeys(position_names))
        if len(unique_positions) < 2:
            continue
        positions = "、".join(unique_positions)
        issues.append(
            _issue(
                "warning",
                "personnel",
                (
                    f"身份证号 {card_no} 对应多个岗位（{positions}）；"
                    "这些岗位将共用同一个平台账号，请核对是否为本人兼任"
                ),
            ),
        )

    wbs_by_code: dict[str, WbsDraft] = {}
    for item in payload.wbs:
        if item.wbs_code in wbs_by_code:
            issues.append(
                _issue("error", "wbs", f"WBS 编码 {item.wbs_code} 重复"),
            )
        else:
            wbs_by_code[item.wbs_code] = item
        if (
            item.planned_start_at
            and item.planned_finish_at
            and item.planned_finish_at < item.planned_start_at
        ):
            issues.append(
                _issue(
                    "error",
                    f"wbs.{item.wbs_code}.planned_finish_at",
                    "计划结束时间不能早于计划开始时间",
                ),
            )
        if item.name.strip() in {"任务名称", "未命名任务", "未命名工序"}:
            issues.append(
                _issue(
                    "warning",
                    f"wbs.{item.wbs_code}.name",
                    f"WBS {item.wbs_code} 的名称“{item.name}”疑似占位内容，请核对",
                ),
            )

    siblings_by_parent: dict[str | None, list[WbsDraft]] = {}
    for item in payload.wbs:
        siblings_by_parent.setdefault(item.parent_wbs_code, []).append(item)
    for siblings in siblings_by_parent.values():
        siblings.sort(key=lambda item: _wbs_code_sort_key(item.wbs_code))
        latest_started_item: WbsDraft | None = None
        for item in siblings:
            if item.planned_start_at is None:
                continue
            if (
                latest_started_item is not None
                and latest_started_item.planned_start_at is not None
                and item.planned_start_at < latest_started_item.planned_start_at
            ):
                issues.append(
                    _issue(
                        "warning",
                        f"wbs.{item.wbs_code}.planned_start_at",
                        (
                            f"WBS {item.wbs_code} 的计划开始早于编码在前的"
                            f"同级 WBS {latest_started_item.wbs_code}；"
                            "同级 WBS 编码顺序与开始时间顺序冲突，请核对原始计划"
                        ),
                    ),
                )
            if (
                latest_started_item is None
                or latest_started_item.planned_start_at is None
                or item.planned_start_at >= latest_started_item.planned_start_at
            ):
                latest_started_item = item

    for item in payload.wbs:
        if item.parent_wbs_code:
            parent = wbs_by_code.get(item.parent_wbs_code)
            if parent is None:
                issues.append(
                    _issue(
                        "error",
                        f"wbs.{item.wbs_code}.parent_wbs_code",
                        f"父级 WBS {item.parent_wbs_code} 不存在",
                    ),
                )
            elif parent.level >= item.level:
                issues.append(
                    _issue(
                        "error",
                        f"wbs.{item.wbs_code}.level",
                        "子节点层级必须大于父节点层级",
                    ),
                )
            elif (
                item.planned_start_at
                and parent.planned_start_at
                and item.planned_start_at < parent.planned_start_at
            ):
                issues.append(
                    _issue(
                        "warning",
                        f"wbs.{item.wbs_code}.planned_start_at",
                        (
                            f"WBS {item.wbs_code} 的计划开始早于父级 "
                            f"{item.parent_wbs_code}，请核对父级汇总日期"
                        ),
                    ),
                )
            elif (
                item.planned_finish_at
                and parent.planned_finish_at
                and item.planned_finish_at > parent.planned_finish_at
            ):
                issues.append(
                    _issue(
                        "warning",
                        f"wbs.{item.wbs_code}.planned_finish_at",
                        (
                            f"WBS {item.wbs_code} 的计划完成晚于父级 "
                            f"{item.parent_wbs_code}，请核对父级汇总日期"
                        ),
                    ),
                )
        expected_parent_code = (
            item.wbs_code.rsplit(".", 1)[0]
            if "." in item.wbs_code
            else None
        )
        if expected_parent_code != item.parent_wbs_code:
            issues.append(
                _issue(
                    "error",
                    f"wbs.{item.wbs_code}.parent_wbs_code",
                    (
                        f"WBS {item.wbs_code} 按编码应归属 "
                        f"{expected_parent_code or '根节点'}，"
                        f"当前上级为 {item.parent_wbs_code or '空'}"
                    ),
                ),
            )
        expected_level = item.wbs_code.count(".") + 1
        if item.level != expected_level:
            issues.append(
                _issue(
                    "error",
                    f"wbs.{item.wbs_code}.level",
                    (
                        f"WBS {item.wbs_code} 按编码应为第 {expected_level} 层，"
                        f"当前为第 {item.level} 层"
                    ),
                ),
            )
        for predecessor_code in item.predecessor_wbs_codes:
            if predecessor_code == item.wbs_code:
                issues.append(
                    _issue(
                        "error",
                        f"wbs.{item.wbs_code}.predecessor_wbs_codes",
                        "WBS 节点不能把自己设为前任",
                    ),
                )
            elif predecessor_code not in wbs_by_code:
                issues.append(
                    _issue(
                        "error",
                        f"wbs.{item.wbs_code}.predecessor_wbs_codes",
                        f"前任 WBS {predecessor_code} 不存在",
                    ),
                )
            else:
                predecessor = wbs_by_code[predecessor_code]
                if (
                    item.planned_start_at
                    and predecessor.planned_finish_at
                    and item.planned_start_at < predecessor.planned_finish_at
                ):
                    issues.append(
                        _issue(
                            "warning",
                            f"wbs.{item.wbs_code}.planned_start_at",
                            (
                                f"WBS {item.wbs_code} 的计划开始早于前任 "
                                f"{predecessor_code} 的计划完成；如属于搭接施工"
                                "或开始-开始关系，请人工确认"
                            ),
                        ),
                    )

    parent_by_code = {
        item.wbs_code: item.parent_wbs_code
        for item in payload.wbs
        if item.parent_wbs_code
    }
    for code in parent_by_code:
        visited: set[str] = set()
        cursor: str | None = code
        while cursor is not None:
            if cursor in visited:
                issues.append(
                    _issue("error", f"wbs.{code}", "WBS 父子关系存在循环"),
                )
                break
            visited.add(cursor)
            cursor = parent_by_code.get(cursor)

    predecessor_by_code = {
        item.wbs_code: tuple(item.predecessor_wbs_codes)
        for item in payload.wbs
    }
    for code in predecessor_by_code:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit_predecessor(current: str) -> bool:
            if current in visiting:
                return True
            if current in visited:
                return False
            visiting.add(current)
            for predecessor in predecessor_by_code.get(current, ()):
                if predecessor in predecessor_by_code and visit_predecessor(predecessor):
                    return True
            visiting.remove(current)
            visited.add(current)
            return False

        if visit_predecessor(code):
            issues.append(
                _issue(
                    "error",
                    f"wbs.{code}.predecessor_wbs_codes",
                    "WBS 前置关系存在循环",
                ),
            )

    for serial_no in sorted(_duplicates([item.serial_no for item in payload.risks])):
        issues.append(_issue("error", "risks", f"风险序号 {serial_no} 重复"))
    for item in payload.risks:
        if item.related_wbs_code and item.related_wbs_code not in wbs_by_code:
            issues.append(
                _issue(
                    "error",
                    f"risks.{item.serial_no}.related_wbs_code",
                    f"关联 WBS {item.related_wbs_code} 不存在",
                ),
            )
        if (
            item.risk_window_start_date
            and item.risk_window_end_date
            and item.risk_window_end_date < item.risk_window_start_date
        ):
            issues.append(
                _issue(
                    "error",
                    f"risks.{item.serial_no}.risk_window_end_date",
                    "风险窗口结束日期不能早于开始日期",
                ),
            )

    quality_codes = [item.wbs_code for item in payload.quality_requirements]
    for code in sorted(_duplicates(quality_codes)):
        issues.append(
            _issue(
                "error",
                "quality_requirements",
                f"WBS {code} 存在多条质量指标记录",
            ),
        )
    for item in payload.quality_requirements:
        if item.wbs_code not in wbs_by_code:
            issues.append(
                _issue(
                    "error",
                    f"quality_requirements.{item.wbs_code}",
                    f"关联 WBS {item.wbs_code} 不存在",
                ),
            )
    return issues


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
            {
                **_row(
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
                ),
                "related_wbs_code": (
                    wbs_by_id[item.related_wbs_item_id].wbs_code
                    if item.related_wbs_item_id in wbs_by_id
                    else None
                ),
            }
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
    def __init__(self, message: str, issues: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.issues = issues or []


def apply_initialization_draft(
    db: Session,
    draft: ProjectInitializationDraft,
    request: ApplyInitializationDraftInput,
) -> dict[str, Any]:
    """Replace initialization sections atomically inside the caller transaction."""
    if draft.status == "applied":
        raise InitializationApplyError("该初始化草稿已经入库")
    payload = ProjectInitializationPayload.model_validate(draft.payload)
    issues = validate_initialization_payload(payload)
    errors = [item for item in issues if item["level"] == "error"]
    warnings = [item for item in issues if item["level"] == "warning"]
    if errors:
        raise InitializationApplyError("草稿仍有结构错误，不能入库", errors)
    if warnings and not request.allow_partial:
        raise InitializationApplyError(
            "草稿仍有未识别内容；确认部分初始化后才能继续",
            warnings,
        )

    credentials = {
        item.identity_card_no: item for item in request.personnel_credentials
    }
    if len(credentials) != len(request.personnel_credentials):
        raise InitializationApplyError("人员登录凭证中存在重复身份证号")

    cards = [item.identity_card_no for item in payload.personnel]
    existing_users = {
        item.identity_card_no: item
        for item in db.scalars(
            select(User).where(User.identity_card_no.in_(cards)),
        ).all()
    } if cards else {}
    username_owners = {
        item.username: item
        for item in db.scalars(select(User)).all()
    }
    for person in payload.personnel:
        existing = existing_users.get(person.identity_card_no)
        credential = credentials.get(person.identity_card_no)
        if existing is None and credential is None:
            raise InitializationApplyError(
                f"新人员「{person.real_name}」缺少登录账号和初始密码",
            )
        if credential is not None:
            owner = username_owners.get(credential.username)
            if owner is not None and owner.identity_card_no != person.identity_card_no:
                raise InitializationApplyError(
                    f"登录账号 {credential.username} 已被其他人员使用",
                )

    project = db.get(Project, draft.project_id)
    if project is None:
        raise InitializationApplyError("草稿关联项目不存在")
    if db.scalar(
        select(Task.id).where(Task.project_id == project.id).limit(1),
    ) is not None:
        raise InitializationApplyError(
            "项目已经产生业务任务，不能再整体替换初始化数据",
        )
    for field, value in payload.project.model_dump().items():
        setattr(project, field, value)

    # Confirmed initialization is the source of truth for these five sections.
    db.execute(
        delete(QualityMetric).where(QualityMetric.project_id == project.id),
    )
    db.execute(delete(WbsRiskLink).where(WbsRiskLink.project_id == project.id))
    db.execute(delete(RiskSource).where(RiskSource.project_id == project.id))
    wbs_ids = tuple(
        db.scalars(
            select(WbsItem.id).where(WbsItem.project_id == project.id),
        ).all(),
    )
    if wbs_ids:
        db.execute(
            delete(WbsPredecessor).where(
                WbsPredecessor.wbs_item_id.in_(wbs_ids),
            ),
        )
    db.execute(delete(WbsItem).where(WbsItem.project_id == project.id))
    db.execute(
        delete(ProjectMemberPosition).where(
            ProjectMemberPosition.project_id == project.id,
        ),
    )
    db.execute(
        delete(ProjectPosition).where(ProjectPosition.project_id == project.id),
    )
    for membership in db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id),
    ).all():
        db.delete(membership)
    db.flush()

    new_usernames: list[str] = []
    members_by_user_id: dict[int, ProjectMember] = {}
    positions_by_name: dict[str, ProjectPosition] = {}
    for person in payload.personnel:
        user = existing_users.get(person.identity_card_no)
        if user is None:
            credential = credentials[person.identity_card_no]
            user = User(
                username=credential.username,
                password_hash=hash_password(credential.initial_password),
                role="user",
                real_name=person.real_name,
                identity_card_no=person.identity_card_no,
            )
            db.add(user)
            db.flush()
            existing_users[person.identity_card_no] = user
            new_usernames.append(user.username)
        membership = members_by_user_id.get(user.id)
        if membership is None:
            membership = ProjectMember(
                project_id=project.id,
                user_id=user.id,
            )
            db.add(membership)
            db.flush()
            members_by_user_id[user.id] = membership
        position = positions_by_name.get(person.position_name)
        if position is None:
            position = ProjectPosition(
                project_id=project.id,
                position_name=person.position_name,
            )
            db.add(position)
            db.flush()
            positions_by_name[person.position_name] = position
        db.add(
            ProjectMemberPosition(
                project_id=project.id,
                project_member_id=membership.id,
                position_id=position.id,
                serial_no=person.serial_no,
                certificate_no=person.certificate_no,
                responsibility_description=person.responsibility_description,
            ),
        )

    wbs_by_code: dict[str, WbsItem] = {}
    for item in payload.wbs:
        row = WbsItem(
            project_id=project.id,
            parent_id=None,
            sort_order=item.sort_order,
            color_value=item.color_value,
            wbs_code=item.wbs_code,
            name=item.name,
            assigned_to_text=item.assigned_to_text,
            planned_start_at=item.planned_start_at,
            planned_finish_at=item.planned_finish_at,
            deadline_at=item.deadline_at,
            progress_percent=item.progress_percent,
            duration_hours=item.duration_hours,
            estimated_hours=item.estimated_hours,
            time_log_minutes=item.time_log_minutes,
            status_text=item.status_text,
            priority_text=item.priority_text,
            description=item.description,
            budget=item.budget,
            actual_cost=item.actual_cost,
            msp_uid=item.msp_uid,
            msp_id=item.msp_id,
            source_created_at=item.source_created_at,
            source_creator=item.source_creator,
            item_type=item.item_type,
            source_project_path=item.source_project_path,
            level=item.level,
        )
        db.add(row)
        db.flush()
        wbs_by_code[item.wbs_code] = row
    for item in payload.wbs:
        row = wbs_by_code[item.wbs_code]
        if item.parent_wbs_code:
            row.parent_id = wbs_by_code[item.parent_wbs_code].id
        for predecessor_code in item.predecessor_wbs_codes:
            db.add(
                WbsPredecessor(
                    wbs_item_id=row.id,
                    predecessor_wbs_item_id=wbs_by_code[predecessor_code].id,
                ),
            )

    for item in payload.risks:
        db.add(
            RiskSource(
                project_id=project.id,
                serial_no=item.serial_no,
                related_wbs_item_id=(
                    wbs_by_code[item.related_wbs_code].id
                    if item.related_wbs_code
                    else None
                ),
                related_process_name=item.related_process_name,
                risk_part=item.risk_part,
                risk_level=item.risk_level,
                evaluation_condition=item.evaluation_condition,
                risk_window_start_date=item.risk_window_start_date,
                risk_window_end_date=item.risk_window_end_date,
                summary=item.summary,
            ),
        )
    for item in payload.quality_requirements:
        db.add(
            QualityMetric(
                project_id=project.id,
                wbs_code=item.wbs_code,
                quality_acceptance_item=item.quality_acceptance_item,
                control_indicator=item.control_indicator,
                inspection_frequency=item.inspection_frequency,
                related_documents=item.related_documents,
            ),
        )

    draft.status = "applied"
    draft.validation_issues = issues
    draft.applied_at = datetime.now(UTC)
    db.flush()
    return {
        "draft_id": draft.id,
        "project_id": project.id,
        "status": draft.status,
        "created_usernames": new_usernames,
        "counts": {
            "personnel": len({item.identity_card_no for item in payload.personnel}),
            "positions": len({item.position_name for item in payload.personnel}),
            "position_assignments": len(payload.personnel),
            "wbs": len(payload.wbs),
            "risks": len(payload.risks),
            "quality_requirements": len(payload.quality_requirements),
        },
    }
