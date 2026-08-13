from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlatformSchemaVersion(Base):
    """Applied versions of the declarative database-interaction catalogue."""

    __tablename__ = "platform_schema_versions"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'user')",
            name="ck_users_role",
        ),
        Index("ix_users_real_name", "real_name"),
        Index("ix_users_role", "role"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    real_name: Mapped[str] = mapped_column(String(100))
    identity_card_no: Mapped[str] = mapped_column(
        String(30),
        unique=True,
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "contract_duration_days IS NULL OR contract_duration_days > 0",
            name="ck_projects_contract_duration_positive",
        ),
        CheckConstraint(
            "contract_amount_wan_yuan IS NULL OR contract_amount_wan_yuan >= 0",
            name="ck_projects_contract_amount_nonnegative",
        ),
        CheckConstraint(
            "contract_end_date IS NULL OR contract_start_date IS NULL "
            "OR contract_end_date >= contract_start_date",
            name="ck_projects_contract_date_order",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    engineering_type_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_amount_wan_yuan: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    construction_unit_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    general_contractor_unit_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supervision_unit_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    design_unit_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    survey_unit_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

class ProjectStatusSnapshot(TimestampMixin, Base):
    """项目状态页的管理口径快照；实际业务数据仍保存在工序、风险、任务等表中。"""

    __tablename__ = "project_status_snapshots"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    progress_rate: Mapped[int] = mapped_column(Integer, default=0)
    progress_status: Mapped[str] = mapped_column(String(32), default="正常")
    planned_delta: Mapped[str] = mapped_column(String(64), default="基本一致")
    risk_warnings: Mapped[int] = mapped_column(Integer, default=0)
    safety_issues: Mapped[int] = mapped_column(Integer, default=0)
    quality_issues: Mapped[int] = mapped_column(Integer, default=0)
    task_completion_rate: Mapped[int] = mapped_column(Integer, default=0)
    main_risk: Mapped[str] = mapped_column(Text, default="暂无新增风险预警")
    main_safety: Mapped[str] = mapped_column(Text, default="暂无新增安全隐患")
    main_quality: Mapped[str] = mapped_column(Text, default="暂无待核查质量项")
    overall: Mapped[str] = mapped_column(Text, default="项目整体状态待核对")


class ProjectInformationRecord(TimestampMixin, Base):
    """项目接收到的多源信息，独立于工程资料库，供项目状态页核验和处置。"""

    __tablename__ = "project_information_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(50))
    source_name: Mapped[str] = mapped_column(String(300))
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="待确认")
    confidence: Mapped[str] = mapped_column(String(16), default="中")
    content: Mapped[str] = mapped_column(Text)
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)


class ProjectSettings(TimestampMixin, Base):
    __tablename__ = "project_settings"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    main_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    archive_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    temp_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    failed_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    backup_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    scan_interval: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ProjectMember(TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            name="uq_project_member_user",
        ),
        UniqueConstraint(
            "project_id",
            "id",
            name="uq_project_member_project_id",
        ),
        Index("ix_project_members_project", "project_id"),
        Index("ix_project_members_user", "user_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class ProjectPosition(TimestampMixin, Base):
    __tablename__ = "project_positions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "position_name",
            name="uq_project_position_name",
        ),
        UniqueConstraint(
            "project_id",
            "id",
            name="uq_project_position_project_id",
        ),
        Index("ix_project_positions_project", "project_id"),
        Index("ix_project_positions_name", "position_name"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    position_name: Mapped[str] = mapped_column(String(100))


class ProjectMemberPosition(TimestampMixin, Base):
    __tablename__ = "project_personnel_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "project_member_id"],
            ["project_members.project_id", "project_members.id"],
            ondelete="CASCADE",
            name="fk_personnel_assignment_member_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "position_id"],
            ["project_positions.project_id", "project_positions.id"],
            ondelete="CASCADE",
            name="fk_personnel_assignment_position_project",
        ),
        UniqueConstraint(
            "project_id",
            "serial_no",
            name="uq_project_personnel_serial",
        ),
        UniqueConstraint(
            "project_member_id",
            "position_id",
            name="uq_project_member_position",
        ),
        Index("ix_project_personnel_project", "project_id"),
        Index("ix_project_personnel_member", "project_member_id"),
        Index("ix_project_personnel_position", "position_id"),
        Index("ix_project_personnel_certificate", "certificate_no"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer)
    project_member_id: Mapped[int] = mapped_column(Integer)
    position_id: Mapped[int] = mapped_column(Integer)
    serial_no: Mapped[int] = mapped_column(Integer)
    certificate_no: Mapped[str] = mapped_column(String(100))
    responsibility_description: Mapped[str] = mapped_column(Text)

class WbsItem(TimestampMixin, Base):
    __tablename__ = "project_wbs_items"
    __table_args__ = (
        UniqueConstraint("project_id", "wbs_code", name="uq_project_wbs_code"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_wbs_not_self_parent"),
        CheckConstraint("sort_order >= 0", name="ck_wbs_sort_order_nonnegative"),
        CheckConstraint("level > 0", name="ck_wbs_level_positive"),
        CheckConstraint(
            "planned_finish_at IS NULL OR planned_start_at IS NULL "
            "OR planned_finish_at >= planned_start_at",
            name="ck_wbs_plan_date_order",
        ),
        CheckConstraint(
            "progress_percent IS NULL OR "
            "(progress_percent >= 0 AND progress_percent <= 100)",
            name="ck_wbs_progress_range",
        ),
        CheckConstraint(
            "duration_hours IS NULL OR duration_hours >= 0",
            name="ck_wbs_duration_nonnegative",
        ),
        CheckConstraint(
            "estimated_hours IS NULL OR estimated_hours >= 0",
            name="ck_wbs_estimated_nonnegative",
        ),
        CheckConstraint(
            "time_log_minutes IS NULL OR time_log_minutes >= 0",
            name="ck_wbs_time_log_nonnegative",
        ),
        CheckConstraint("budget IS NULL OR budget >= 0", name="ck_wbs_budget_nonnegative"),
        CheckConstraint(
            "actual_cost IS NULL OR actual_cost >= 0",
            name="ck_wbs_actual_cost_nonnegative",
        ),
        Index("ix_project_wbs_tree", "project_id", "parent_id", "sort_order"),
        Index("ix_project_wbs_level", "project_id", "level"),
        Index("ix_project_wbs_msp_uid", "msp_uid"),
        Index("ix_project_wbs_msp_id", "msp_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_wbs_items.id"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    color_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    wbs_code: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(300))
    assigned_to_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_finish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    progress_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        default=0,
    )
    duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    time_log_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_text: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    priority_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    msp_uid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    msp_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_creator: Mapped[str | None] = mapped_column(String(200), nullable=True)
    item_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_project_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[int] = mapped_column(SmallInteger, default=1)


class WbsPredecessor(Base):
    __tablename__ = "project_wbs_predecessors"
    __table_args__ = (
        UniqueConstraint(
            "wbs_item_id",
            "predecessor_wbs_item_id",
            name="uq_project_wbs_predecessor",
        ),
        CheckConstraint(
            "wbs_item_id <> predecessor_wbs_item_id",
            name="ck_wbs_predecessor_not_self",
        ),
        Index("ix_wbs_predecessor_item", "wbs_item_id"),
        Index("ix_wbs_predecessor_predecessor", "predecessor_wbs_item_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wbs_item_id: Mapped[int] = mapped_column(
        ForeignKey("project_wbs_items.id", ondelete="CASCADE"),
    )
    predecessor_wbs_item_id: Mapped[int] = mapped_column(
        ForeignKey("project_wbs_items.id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class RiskSource(TimestampMixin, Base):
    __tablename__ = "project_risks"
    __table_args__ = (
        UniqueConstraint("project_id", "serial_no", name="uq_project_risk_serial"),
        CheckConstraint(
            "risk_window_end_date IS NULL OR risk_window_start_date IS NULL "
            "OR risk_window_end_date >= risk_window_start_date",
            name="ck_project_risk_date_order",
        ),
        Index("ix_project_risk_project", "project_id"),
        Index("ix_project_risk_level", "risk_level"),
        Index("ix_project_risk_window", "risk_window_start_date", "risk_window_end_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    serial_no: Mapped[int] = mapped_column(Integer)
    related_process_name: Mapped[str] = mapped_column(String(300))
    risk_part: Mapped[str] = mapped_column(String(300))
    risk_level: Mapped[str] = mapped_column(String(50))
    evaluation_condition: Mapped[str] = mapped_column(Text)
    risk_window_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    risk_window_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)



class QualityMetric(TimestampMixin, Base):
    __tablename__ = "project_wbs_quality_requirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "wbs_code"],
            ["project_wbs_items.project_id", "project_wbs_items.wbs_code"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "project_id",
            "wbs_code",
            name="uq_project_wbs_quality_requirement",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer)
    wbs_code: Mapped[str] = mapped_column(String(128))
    quality_acceptance_item: Mapped[str] = mapped_column(Text)
    control_indicator: Mapped[str] = mapped_column(Text)
    inspection_frequency: Mapped[str] = mapped_column(Text)
    related_documents: Mapped[str] = mapped_column(Text)


class PlatformFieldMapping(TimestampMixin, Base):
    __tablename__ = "platform_field_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    platform_name: Mapped[str] = mapped_column(String(200))
    source_field: Mapped[str] = mapped_column(String(100))
    target_field: Mapped[str] = mapped_column(String(200))
    transform_rule: Mapped[str | None] = mapped_column(String(300), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WbsRiskLink(TimestampMixin, Base):
    __tablename__ = "wbs_risk_links"
    __table_args__ = (UniqueConstraint("wbs_item_id", "risk_source_id", name="uq_wbs_risk"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    wbs_item_id: Mapped[int] = mapped_column(
        ForeignKey("project_wbs_items.id", ondelete="CASCADE"),
    )
    risk_source_id: Mapped[int] = mapped_column(
        ForeignKey("project_risks.id", ondelete="CASCADE"),
    )
    alert_days: Mapped[int] = mapped_column(Integer, default=7)
    notify_methods: Mapped[list[str]] = mapped_column(JSON, default=list)
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    task_type: Mapped[str] = mapped_column(String(50))
    risk_level: Mapped[str] = mapped_column(String(32), default="low")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wbs_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_wbs_items.id"),
        nullable=True,
    )
    risk_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_risks.id"),
        nullable=True,
    )
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_materials: Mapped[list[str]] = mapped_column(JSON, default=list)
    workflow_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReport(TimestampMixin, Base):
    __tablename__ = "daily_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(300))
    report_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_wbs_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_wbs_items.id"),
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(default=0.0)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")
    status: Mapped[str] = mapped_column(String(32), default="pending_confirm")


class RiskDraft(TimestampMixin, Base):
    __tablename__ = "risk_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    risk_source_id: Mapped[int] = mapped_column(
        ForeignKey("project_risks.id", ondelete="CASCADE"),
    )
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_items: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class FillPackage(TimestampMixin, Base):
    __tablename__ = "fill_packages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("risk_drafts.id", ondelete="CASCADE"))
    platform_name: Mapped[str] = mapped_column(String(200))
    process_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class CollaborationSession(TimestampMixin, Base):
    __tablename__ = "collaboration_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    participant_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    task_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class CollaborationMessage(Base):
    __tablename__ = "collaboration_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("collaboration_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    generated_task_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentConversation(TimestampMixin, Base):
    """Account-private mapping to one AgentScope conversation session."""

    __tablename__ = "agent_conversations"
    __table_args__ = (
        Index(
            "uq_agent_conversations_project_user_initialization",
            "project_id",
            "user_id",
            unique=True,
            sqlite_where=text("conversation_type = 'initialization'"),
            postgresql_where=text("conversation_type = 'initialization'"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(200))
    conversation_type: Mapped[str] = mapped_column(
        String(32),
        default="business",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300))
    agentscope_session_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectInitializationDraft(TimestampMixin, Base):
    """Agent-produced project initialization data awaiting human review."""

    __tablename__ = "project_initialization_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'invalid', 'ready', 'applied', 'rejected')",
            name="ck_project_initialization_drafts_status",
        ),
        Index(
            "ix_project_initialization_drafts_project_status",
            "project_id",
            "status",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="building", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
    )
    source_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ProjectInitializationDraftSection(TimestampMixin, Base):
    """One independently maintained section of an initialization draft."""

    __tablename__ = "project_initialization_draft_sections"
    __table_args__ = (
        CheckConstraint(
            "section IN ("
            "'project', 'personnel', 'wbs', 'risks', "
            "'quality_requirements'"
            ")",
            name="ck_project_initialization_draft_sections_section",
        ),
        UniqueConstraint(
            "draft_id",
            "section",
            name="uq_project_initialization_draft_sections_draft_section",
        ),
        Index(
            "ix_project_initialization_draft_sections_project",
            "project_id",
            "draft_id",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    section: Mapped[str] = mapped_column(String(40))
    writer_agent_id: Mapped[str] = mapped_column(String(128), index=True)
    workflow_revision: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any] | list[dict[str, Any]]] = mapped_column(
        JSON,
    )
    source_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_notes: Mapped[list[str]] = mapped_column(JSON, default=list)


class ProjectInitializationDraftRecord(TimestampMixin, Base):
    """One addressable business row inside an initialization draft section."""

    __tablename__ = "project_initialization_draft_records"
    __table_args__ = (
        CheckConstraint(
            "section IN ("
            "'project', 'personnel', 'wbs', 'risks', "
            "'quality_requirements'"
            ")",
            name="ck_project_initialization_draft_records_section",
        ),
        UniqueConstraint(
            "section_id",
            "ordinal",
            name="uq_project_initialization_draft_records_section_ordinal",
        ),
        Index(
            "ix_project_initialization_draft_records_draft_section",
            "draft_id",
            "section",
            "ordinal",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_draft_sections.id", ondelete="CASCADE"),
        index=True,
    )
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    section: Mapped[str] = mapped_column(String(40))
    section_revision: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    business_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ProjectInitializationValidationRun(TimestampMixin, Base):
    """One direct execution of the versioned initialization validator MCP."""

    __tablename__ = "project_initialization_validation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_project_initialization_validation_runs_status",
        ),
        CheckConstraint(
            "result_status IS NULL OR result_status IN ('ready', 'invalid')",
            name="ck_project_initialization_validation_runs_result_status",
        ),
        Index(
            "ix_project_initialization_validation_runs_draft",
            "draft_id",
            "created_at",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    draft_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    result_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    package_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ruleset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ProjectInitializationValidationIssue(TimestampMixin, Base):
    """Structured validation annotation targeting a draft row and field."""

    __tablename__ = "project_initialization_validation_issues"
    __table_args__ = (
        CheckConstraint(
            "level IN ('error', 'warning')",
            name="ck_project_initialization_validation_issues_level",
        ),
        CheckConstraint(
            "section IN ("
            "'project', 'personnel', 'wbs', 'risks', "
            "'quality_requirements'"
            ")",
            name="ck_project_initialization_validation_issues_section",
        ),
        Index(
            "ix_project_initialization_validation_issues_draft_target",
            "draft_id",
            "target_record_id",
            "field_name",
        ),
        Index(
            "ix_project_initialization_validation_issues_run",
            "validation_run_id",
            "id",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey(
            "project_initialization_validation_runs.id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    draft_revision: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(40))
    target_record_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "project_initialization_draft_records.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_record_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProjectInitializationFile(TimestampMixin, Base):
    """Raw file available only to one project-initialization conversation."""

    __tablename__ = "project_initialization_files"
    __table_args__ = (
        Index(
            "ix_project_initialization_files_conversation",
            "conversation_id",
            "created_at",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    uploaded_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(300))
    storage_path: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)


class ProjectInitializationRun(TimestampMixin, Base):
    """Durable orchestration state for one initialization workflow."""

    __tablename__ = "project_initialization_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'queued', 'parsing', 'extracting', 'validating', 'ready', "
            "'needs_attention', 'failed', 'cancelling', 'cancelled', 'applied'"
            ")",
            name="ck_project_initialization_runs_status",
        ),
        Index(
            "ix_project_initialization_runs_project_status",
            "project_id",
            "status",
            "created_at",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_initialization_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    current_step_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_text: Mapped[str] = mapped_column(Text, default="")
    source_file_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    source_files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    detected_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    completed_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    failed_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
    )
    semantic_review_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ProjectInitializationRunStep(TimestampMixin, Base):
    """One observable step inside an initialization workflow run."""

    __tablename__ = "project_initialization_run_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="ck_project_initialization_run_steps_status",
        ),
        UniqueConstraint(
            "run_id",
            "step_key",
            name="uq_project_initialization_run_steps_key",
        ),
        Index(
            "ix_project_initialization_run_steps_run_order",
            "run_id",
            "sort_order",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_runs.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    step_key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    phase: Mapped[str] = mapped_column(String(40))
    section: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ProjectInitializationParsedChunk(TimestampMixin, Base):
    """Normalized parser output retained for deterministic replay."""

    __tablename__ = "project_initialization_parsed_chunks"
    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_project_initialization_parsed_chunks_index",
        ),
        UniqueConstraint(
            "run_id",
            "file_id",
            "chunk_index",
            name="uq_project_initialization_parsed_chunks_position",
        ),
        Index(
            "ix_project_initialization_parsed_chunks_run_file",
            "run_id",
            "file_id",
            "chunk_index",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_runs.id", ondelete="CASCADE"),
        index=True,
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_files.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    parser: Mapped[str] = mapped_column(String(100))
    content_format: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    structured_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    section_hints: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_location: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

class ProjectInitializationAttachmentChunk(TimestampMixin, Base):
    """Temporary parsed text referenced by initialization agents."""

    __tablename__ = "project_initialization_attachment_chunks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_project_initialization_attachment_chunks_status",
        ),
        CheckConstraint(
            "chunk_index >= 0 AND chunk_count >= 1",
            name="ck_project_initialization_attachment_chunks_position",
        ),
        UniqueConstraint(
            "file_id",
            "chunk_index",
            name="uq_project_initialization_attachment_chunks_position",
        ),
        Index(
            "ix_project_initialization_attachment_chunks_conversation",
            "conversation_id",
            "file_id",
            "chunk_index",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("project_initialization_files.id", ondelete="CASCADE"),
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(300))
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="ready", index=True)
    parser: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MeetingMinute(TimestampMixin, Base):
    __tablename__ = "meeting_minutes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("collaboration_sessions.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    action_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ProjectChange(TimestampMixin, Base):
    __tablename__ = "project_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(100), default="工程内容变更")
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(300))
    storage_path: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(100), default="未分类")
    source_type: Mapped[str] = mapped_column(String(50), default="manual")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class DocumentFolder(TimestampMixin, Base):
    __tablename__ = "document_folders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("document_folders.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))


class DocumentFolderItem(Base):
    __tablename__ = "document_folder_items"
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("document_folders.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)


class AttachmentText(Base):
    __tablename__ = "attachment_texts"
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    parse_status: Mapped[str] = mapped_column(String(32), default="ready")
    parser: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperationLog(Base):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatabaseInteractionTablePolicy(TimestampMixin, Base):
    """Platform-owned whitelist for one business database table.

    The policy is deliberately declarative: agents never receive a database
    connection or submit SQL.  Runtime code resolves the table and columns
    from SQLAlchemy metadata and applies this whitelist before executing a
    structured operation.
    """

    __tablename__ = "database_interaction_table_policies"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('project', 'user', 'global_admin')",
            name="ck_database_interaction_policy_scope_type",
        ),
        CheckConstraint(
            "minimum_role IN ('member', 'admin')",
            name="ck_database_interaction_policy_minimum_role",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    allowed_operations: Mapped[list[str]] = mapped_column(JSON, default=list)
    readable_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    writable_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    filterable_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    scope_type: Mapped[str] = mapped_column(String(24), default="project")
    scope_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    minimum_role: Mapped[str] = mapped_column(String(16), default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class DatabaseInteraction(TimestampMixin, Base):
    """One assignable database capability exposed to an agent."""

    __tablename__ = "database_interactions"
    __table_args__ = (
        CheckConstraint(
            "execution_kind IN ('builtin', 'table')",
            name="ck_database_interactions_execution_kind",
        ),
        CheckConstraint(
            "table_operation IS NULL OR "
            "table_operation IN ('read', 'create', 'update', 'delete')",
            name="ck_database_interactions_table_operation",
        ),
        CheckConstraint(
            "access_mode IN ('agent', 'workflow')",
            name="ck_database_interactions_access_mode",
        ),
        Index("ix_database_interactions_enabled_sort", "enabled", "sort_order"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    execution_kind: Mapped[str] = mapped_column(String(16))
    builtin_operation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    table_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "database_interaction_table_policies.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    table_operation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    join_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
    )
    context_bindings: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        default=list,
    )
    fixed_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    runtime_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    allowed_conversation_types: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: ["general", "business", "initialization"],
    )
    access_mode: Mapped[str] = mapped_column(String(16), default="agent")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    built_in: Mapped[bool] = mapped_column(Boolean, default=False)
    default_assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DatabaseInteractionAgentAssignment(TimestampMixin, Base):
    """Durable assignment state for one AgentScope agent and capability."""

    __tablename__ = "database_interaction_agent_assignments"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "interaction_id",
            name="uq_database_interaction_agent_assignment",
        ),
        Index(
            "ix_database_interaction_assignments_agent",
            "agent_id",
            "assigned",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128))
    interaction_id: Mapped[int] = mapped_column(
        ForeignKey("database_interactions.id", ondelete="CASCADE"),
        index=True,
    )
    assigned: Mapped[bool] = mapped_column(Boolean, default=False)
