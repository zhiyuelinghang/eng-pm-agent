"""Persist reviewed change selections and independently applied draft records."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class AppliedInitializationChange(Base):
    __tablename__ = "project_initialization_applied_changes"
    __table_args__ = (UniqueConstraint("draft_id", "change_key", name="uq_initialization_applied_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"), index=True)
    change_key: Mapped[str] = mapped_column(String(200))
    record_id: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class InitializationChangePreview(Base):
    __tablename__ = "project_initialization_change_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    draft_revision: Mapped[int] = mapped_column(Integer)
    baseline_hash: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    review: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
