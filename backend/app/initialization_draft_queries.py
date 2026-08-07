"""Read-only helpers used by the platform's draft review API."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
)
from .project_initialization import ProjectInitializationPayload


_DRAFT_SECTIONS = frozenset(
    {"project", "personnel", "wbs", "risks", "quality_requirements"},
)


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


def compose_initialization_draft_payload(
    db: Session,
    draft: ProjectInitializationDraft,
) -> ProjectInitializationPayload:
    """Compose the persisted draft from specialist-owned sections."""
    base = ProjectInitializationPayload.model_validate(draft.payload or {})
    data = base.model_dump(mode="python")
    for row in _section_rows(db, draft.id):
        if row.section in _DRAFT_SECTIONS:
            data[row.section] = row.payload
    return ProjectInitializationPayload.model_validate(data)


def initialization_draft_workflow_summary(
    db: Session,
    draft: ProjectInitializationDraft,
) -> None:
    """Runtime planning lives in AgentScope; draft review needs no shadow plan."""
    del db, draft
    return None
