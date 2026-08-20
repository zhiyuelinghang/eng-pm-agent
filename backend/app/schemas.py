from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    real_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=100)
    org_name: str | None = Field(default=None, max_length=200)


class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


UserConnectorType = Literal[
    "platform",
    "mail",
    "wecom",
    "feishu",
    "dingtalk",
]
ProjectConnectorType = Literal["wecom", "feishu", "dingtalk"]


class UserConnectorConfigInput(BaseModel):
    account_identifier: str = Field(min_length=1, max_length=500)
    platform_type: str | None = Field(default=None, max_length=100)
    secret: str | None = Field(default=None, max_length=4000)


class ProjectConnectorConfigInput(BaseModel):
    connection_id: str = Field(min_length=1, max_length=1000)
    secret: str | None = Field(default=None, max_length=4000)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    engineering_type_description: str | None = Field(default=None, max_length=5000)
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contract_duration_days: int | None = Field(default=None, gt=0)
    contract_amount_wan_yuan: Decimal | None = Field(default=None, ge=0)
    construction_unit_name: str | None = Field(default=None, max_length=300)
    general_contractor_unit_name: str | None = Field(default=None, max_length=300)
    supervision_unit_name: str | None = Field(default=None, max_length=300)
    design_unit_name: str | None = Field(default=None, max_length=300)
    survey_unit_name: str | None = Field(default=None, max_length=300)


class ProjectSettingsInput(BaseModel):
    main_dir: str = ""
    archive_dir: str = ""
    temp_dir: str = ""
    failed_dir: str = ""
    backup_dir: str = ""
    scan_interval: int = Field(default=30, ge=1, le=1440)
    enabled: bool = False
    reminder_rules: list[dict[str, Any]] = Field(default_factory=list)


class DocumentFolderInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None


class AttachmentUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=100)


class EngineeringDocumentSearchInput(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=20)
    vector_threshold: float = Field(default=0.5, ge=0, le=1)
    keyword_threshold: float = Field(default=0.3, ge=0, le=1)


class EngineeringDocumentUrlInput(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=4096)
    title: str = Field(default="", max_length=512)
    enable_multimodel: bool = True


class EngineeringDocumentFolderCreateInput(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    folder_path: str = Field(min_length=1, max_length=4096)


class EngineeringDocumentFolderUpdateInput(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    source_path: str = Field(min_length=1, max_length=4096)
    target_path: str = Field(min_length=1, max_length=4096)


class EngineeringDocumentMoveInput(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    knowledge_ids: list[str] = Field(min_length=1, max_length=200)
    folder_path: str = Field(default="", max_length=4096)


class EngineeringDocumentAskInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=50)
    knowledge_ids: list[str] = Field(default_factory=list, max_length=200)
    session_id: str | None = Field(default=None, max_length=128)


class EngineeringKnowledgeScopeItemInput(BaseModel):
    scope_type: Literal["knowledge_base", "folder", "document"]
    knowledge_id: str | None = Field(default=None, max_length=128)
    knowledge_name: str | None = Field(default=None, max_length=500)
    knowledge_base_id: str | None = Field(default=None, max_length=128)
    folder_path: str | None = Field(default=None, max_length=4096)


class EngineeringKnowledgeConversationCreateInput(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    scope_type: Literal[
        "project",
        "knowledge_base",
        "folder",
        "document",
        "selection",
    ] = "project"
    knowledge_id: str | None = Field(default=None, max_length=128)
    knowledge_name: str | None = Field(default=None, max_length=500)
    knowledge_base_id: str | None = Field(default=None, max_length=128)
    folder_path: str | None = Field(default=None, max_length=4096)
    scope_items: list[EngineeringKnowledgeScopeItemInput] = Field(
        default_factory=list,
        max_length=200,
    )
    first_message: str = Field(min_length=1, max_length=4000)


class EngineeringKnowledgeConversationUpdateInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    weknora_session_id: str | None = Field(default=None, max_length=128)


class EngineeringKnowledgeMessageInput(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100000)
    references: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    failed: bool = False


class MemberInput(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    real_name: str = Field(min_length=1, max_length=100)
    identity_card_no: str = Field(min_length=1, max_length=30)
    password: str | None = Field(default=None, min_length=8)
    system_role: Literal["admin", "user"] = "user"
    position_name: str = Field(min_length=1, max_length=100)
    certificate_no: str = Field(default="", max_length=100)
    responsibility_description: str = Field(default="", max_length=10000)


class WbsInput(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=300)
    level: int = Field(default=1, gt=0, le=100)
    parent_id: int | None = None
    sort_order: int | None = Field(default=None, ge=0)
    color_value: str | None = Field(default=None, max_length=50)
    assigned_to_text: str | None = Field(default=None, max_length=300)
    planned_start: str | None = None
    planned_finish: str | None = None
    deadline: str | None = None
    progress: Decimal | None = Field(default=0, ge=0, le=100)
    duration_hours: Decimal | None = Field(default=None, ge=0)
    estimated_hours: Decimal | None = Field(default=None, ge=0)
    time_log_minutes: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=100)
    priority_text: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=20000)
    budget: Decimal | None = Field(default=None, ge=0)
    actual_cost: Decimal | None = Field(default=None, ge=0)
    item_type: str | None = Field(default=None, max_length=100)
    predecessor_ids: list[int] | None = None
    responsible_user_id: int | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class RiskInput(BaseModel):
    serial_no: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=300)
    level: str = Field(default="一般", min_length=1, max_length=50)
    risk_type: str = Field(default="综合风险", min_length=1, max_length=300)
    planned_start: str | None = None
    planned_finish: str | None = None
    summary: str | None = Field(default=None, max_length=20000)
    responsible_user_id: int | None = None
    confirmer_user_id: int | None = None
    material_requirements: list[str] = Field(default_factory=list)
    control_requirements: str | None = Field(default=None, max_length=20000)
    status: str = "active"


class QualityMetricInput(BaseModel):
    wbs_item_id: int | None = None
    name: str = Field(min_length=1, max_length=300)
    requirement: str = Field(min_length=1, max_length=20000)
    inspection_frequency: str | None = Field(default=None, max_length=10000)
    related_documents: str | None = Field(default=None, max_length=20000)
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


class TaskFlowGenerateInput(BaseModel):
    requirement: str = Field(min_length=4, max_length=4000)
    template_type: str | None = None


class TaskTransitionInput(BaseModel):
    status: str
    note: str | None = None


class TaskStepUpdate(BaseModel):
    status: str = "completed"
    note: str | None = None


class TaskReassignInput(BaseModel):
    assignee_user_id: int
    note: str | None = None


class TaskNoteInput(BaseModel):
    note: str


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


class CollaborationSessionInput(BaseModel):
    title: str = Field(default="新的工程协同", min_length=1, max_length=300)
    summary: str | None = None
    participant_ids: list[int] = Field(default_factory=list)
    task_ids: list[int] = Field(default_factory=list)


class CollaborationMessageInput(BaseModel):
    content: str = Field(min_length=1)


class AgentConversationInput(BaseModel):
    agent_id: str | None = Field(default=None, max_length=64)
    conversation_type: str = Field(
        default="business",
        pattern="^(general|business|initialization)$",
    )
    title: str | None = Field(default=None, max_length=300)


class AgentConversationMessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    initialization_file_ids: list[int] = Field(default_factory=list)


class AgentConversationConfirmInput(BaseModel):
    reply_id: str = Field(min_length=1, max_length=128)
    tool_call: dict[str, Any]
    confirmed: bool
    rules: list[dict[str, Any]] | None = None


class ProjectChangeInput(BaseModel):
    category: str = "工程内容变更"
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    status: str = "pending"
    source_refs: list[str] = Field(default_factory=list)


class ProjectInformationDispositionInput(BaseModel):
    action: str = Field(pattern="^(confirm|deny|revise)$")
    content: str | None = None


class OperationLogInput(BaseModel):
    action: str
    detail: str
    target_type: str | None = None
    target_id: int | None = None
