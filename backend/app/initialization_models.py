"""Initialization proposal, row and versioned validation persistence."""
from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .model_mixins import TimestampMixin


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
