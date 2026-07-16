from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class ProjectInput(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    owner_unit: str | None = None
    description: str | None = None
    status: str = "active"


class ProjectSettingsInput(BaseModel):
    main_dir: str = ""
    archive_dir: str = ""
    temp_dir: str = ""
    failed_dir: str = ""
    backup_dir: str = ""
    scan_interval: int = Field(default=30, ge=1, le=1440)
    enabled: bool = False
    reminder_rules: list[dict[str, Any]] = Field(default_factory=list)


class MemberInput(BaseModel):
    username: str | None = None
    real_name: str
    password: str | None = Field(default=None, min_length=8)
    phone: str | None = None
    email: str | None = None
    title: str | None = None
    system_role: str = "member"
    member_role: str = "member"
    responsibilities: list[str] = Field(default_factory=list)


class WbsInput(BaseModel):
    code: str
    name: str
    level: int = 1
    parent_id: int | None = None
    planned_start: str | None = None
    planned_finish: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    status: str = "not_started"
    responsible_user_id: int | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class RiskInput(BaseModel):
    name: str
    level: str = "medium"
    risk_type: str = "综合风险"
    planned_start: str | None = None
    planned_finish: str | None = None
    responsible_user_id: int | None = None
    confirmer_user_id: int | None = None
    material_requirements: list[str] = Field(default_factory=list)
    control_requirements: str | None = None
    status: str = "active"


class QualityMetricInput(BaseModel):
    wbs_item_id: int | None = None
    name: str = Field(min_length=1, max_length=300)
    requirement: str = Field(min_length=1)
    inspection_frequency: str | None = None
    required_materials: list[str] = Field(default_factory=list)
    owner_user_id: int | None = None
    status: str = "pending"


class PlatformFieldMappingInput(BaseModel):
    platform_name: str = Field(min_length=1, max_length=200)
    source_field: str = Field(min_length=1, max_length=100)
    target_field: str = Field(min_length=1, max_length=200)
    transform_rule: str | None = None
    required: bool = False
    enabled: bool = True


class WbsRiskLinkInput(BaseModel):
    wbs_item_id: int
    risk_source_id: int
    alert_days: int = Field(default=7, ge=0, le=365)
    notify_methods: list[str] = Field(default_factory=lambda: ["系统通知"])
    basis: str | None = None


class TaskInput(BaseModel):
    title: str
    task_type: str
    risk_level: str = "low"
    assignee_user_id: int | None = None
    confirmer_user_id: int | None = None
    due_at: str | None = None
    wbs_item_id: int | None = None
    risk_source_id: int | None = None
    trigger_reason: str | None = None
    required_materials: list[str] = Field(default_factory=list)
    workflow_steps: list[dict[str, Any]] = Field(default_factory=list)


class TaskTransitionInput(BaseModel):
    status: str
    note: str | None = None


class TaskStepUpdate(BaseModel):
    status: str = "completed"
    note: str | None = None


class DailyReportInput(BaseModel):
    file_name: str
    report_date: str | None = None
    content: str | None = None
    matched_wbs_id: int | None = None
    confidence: float = Field(default=0, ge=0, le=1)


class DailyReportUpdate(BaseModel):
    report_date: str | None = None
    content: str | None = None
    matched_wbs_id: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: str | None = None


class DraftInput(BaseModel):
    risk_source_id: int
    title: str
    content: str
    source_refs: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)


class DraftReviewInput(BaseModel):
    note: str | None = None


class FillPackageInput(BaseModel):
    platform_name: str
    process_name: str
    fields: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class OperationLogInput(BaseModel):
    action: str
    detail: str
    target_type: str | None = None
    target_id: int | None = None
