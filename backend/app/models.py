from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    real_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    org_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    status: Mapped[str] = mapped_column(String(32), default="active")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(200), index=True)
    owner_unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")


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
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    member_role: Mapped[str] = mapped_column(String(32), default="member")
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")


class WbsItem(TimestampMixin, Base):
    __tablename__ = "wbs_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("wbs_items.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    level: Mapped[int] = mapped_column(Integer, default=1)
    planned_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planned_finish: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="not_started")
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RiskSource(TimestampMixin, Base):
    __tablename__ = "risk_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    level: Mapped[str] = mapped_column(String(32), default="medium")
    risk_type: Mapped[str] = mapped_column(String(100), default="综合风险")
    planned_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planned_finish: Mapped[str | None] = mapped_column(String(32), nullable=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    material_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    control_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")


class QualityMetric(TimestampMixin, Base):
    __tablename__ = "quality_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    wbs_item_id: Mapped[int | None] = mapped_column(ForeignKey("wbs_items.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    requirement: Mapped[str] = mapped_column(Text)
    inspection_frequency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    required_materials: Mapped[list[str]] = mapped_column(JSON, default=list)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")


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
    wbs_item_id: Mapped[int] = mapped_column(ForeignKey("wbs_items.id", ondelete="CASCADE"))
    risk_source_id: Mapped[int] = mapped_column(ForeignKey("risk_sources.id", ondelete="CASCADE"))
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
    wbs_item_id: Mapped[int | None] = mapped_column(ForeignKey("wbs_items.id"), nullable=True)
    risk_source_id: Mapped[int | None] = mapped_column(ForeignKey("risk_sources.id"), nullable=True)
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
    matched_wbs_id: Mapped[int | None] = mapped_column(ForeignKey("wbs_items.id"), nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.0)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")
    status: Mapped[str] = mapped_column(String(32), default="pending_confirm")


class RiskDraft(TimestampMixin, Base):
    __tablename__ = "risk_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    risk_source_id: Mapped[int] = mapped_column(ForeignKey("risk_sources.id", ondelete="CASCADE"))
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


class AgentConversationMessage(Base):
    """Auditable platform-side mirror of a message handled by AgentScope."""

    __tablename__ = "agent_conversation_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    agentscope_message_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


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
