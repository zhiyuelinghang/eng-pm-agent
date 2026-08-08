"""Helpers for addressable project-initialization draft data."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ProjectInitializationDraft,
    ProjectInitializationDraftRecord,
    ProjectInitializationDraftSection,
    ProjectInitializationValidationIssue,
    ProjectInitializationValidationRun,
)
from .project_initialization import ProjectInitializationPayload


_DRAFT_SECTIONS = frozenset(
    {"project", "personnel", "wbs", "risks", "quality_requirements"},
)
_ARRAY_SECTIONS = frozenset(
    {"personnel", "wbs", "risks", "quality_requirements"},
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


def _record_business_key(section: str, payload: dict[str, Any]) -> str | None:
    """Return a readable locator only; it is never used as row identity."""
    fields = {
        "personnel": ("serial_no", "real_name"),
        "wbs": ("wbs_code", "name"),
        "risks": ("serial_no", "risk_part"),
        "quality_requirements": ("wbs_code", "quality_acceptance_item"),
    }.get(section, ())
    parts = [str(payload.get(name, "")).strip() for name in fields]
    value = " · ".join(item for item in parts if item)
    return value[:300] or None


def _section_items(
    section: str,
    payload: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if section in _ARRAY_SECTIONS:
        raw_items = payload if isinstance(payload, list) else []
    else:
        raw_items = [payload] if isinstance(payload, dict) else []
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        # IDs are allocated by the database and cannot be supplied by agents.
        item.pop("record_id", None)
        items.append(item)
    return items


def sync_initialization_draft_section_records(
    db: Session,
    section_row: ProjectInitializationDraftSection,
) -> list[ProjectInitializationDraftRecord]:
    """Replace one section with a new, addressable draft-row revision."""
    items = _section_items(section_row.section, section_row.payload)
    # A section update is a new draft revision. Reusing an old row ID for a
    # different array position would make historical validation annotations
    # point at the wrong business data, so old rows are deliberately retired.
    previous_records = list(
        db.scalars(
            select(ProjectInitializationDraftRecord).where(
                ProjectInitializationDraftRecord.section_id == section_row.id,
                ProjectInitializationDraftRecord.active.is_(True),
            ),
        ).all(),
    )
    for previous in previous_records:
        previous.active = False
        # Keep the historical row and its validation FK intact while freeing
        # the current (section, ordinal) slot for the new revision.
        previous.ordinal = -previous.id
    db.flush()
    records: list[ProjectInitializationDraftRecord] = []
    for ordinal, item in enumerate(items):
        row = ProjectInitializationDraftRecord(
            section_id=section_row.id,
            draft_id=section_row.draft_id,
            project_id=section_row.project_id,
            conversation_id=section_row.conversation_id,
            section=section_row.section,
            section_revision=section_row.revision,
            active=True,
            ordinal=ordinal,
            business_key=_record_business_key(section_row.section, item),
            payload=item,
        )
        db.add(row)
        records.append(row)
    db.flush()
    return records


def compose_initialization_draft_payload(
    db: Session,
    draft: ProjectInitializationDraft,
) -> ProjectInitializationPayload:
    """Compose a draft from its database-addressable business rows."""
    data = ProjectInitializationPayload().model_dump(mode="python")
    sections = _section_rows(db, draft.id)
    records = list(
        db.scalars(
            select(ProjectInitializationDraftRecord)
            .where(
                ProjectInitializationDraftRecord.draft_id == draft.id,
                ProjectInitializationDraftRecord.active.is_(True),
            )
            .order_by(
                ProjectInitializationDraftRecord.section_id,
                ProjectInitializationDraftRecord.ordinal,
            ),
        ).all(),
    )
    records_by_section_id: dict[int, list[ProjectInitializationDraftRecord]] = (
        defaultdict(list)
    )
    for record in records:
        records_by_section_id[record.section_id].append(record)

    for section_row in sections:
        if section_row.section not in _DRAFT_SECTIONS:
            continue
        section_records = records_by_section_id.get(section_row.id, [])
        if not section_records and _section_items(
            section_row.section,
            section_row.payload,
        ):
            section_records = sync_initialization_draft_section_records(
                db,
                section_row,
            )
        if section_records:
            addressable = [
                {**dict(record.payload or {}), "record_id": record.id}
                for record in section_records
            ]
            data[section_row.section] = (
                addressable if section_row.section in _ARRAY_SECTIONS else addressable[0]
            )
        else:
            # Existing databases are backfilled at startup. This fallback keeps
            # an empty section valid and makes a partially migrated DB readable.
            data[section_row.section] = section_row.payload
    return ProjectInitializationPayload.model_validate(data)


def latest_initialization_validation_issues(
    db: Session,
    draft_id: int,
) -> list[ProjectInitializationValidationIssue]:
    latest_run = db.execute(
        select(
            ProjectInitializationValidationRun.id,
            ProjectInitializationValidationRun.status,
            ProjectInitializationValidationRun.draft_revision,
        )
        .where(
            ProjectInitializationValidationRun.draft_id == draft_id,
        )
        .order_by(ProjectInitializationValidationRun.id.desc()),
    ).first()
    current_revision = db.scalar(
        select(ProjectInitializationDraft.revision).where(
            ProjectInitializationDraft.id == draft_id,
        ),
    )
    if (
        latest_run is None
        or latest_run.status != "completed"
        or current_revision is None
        or latest_run.draft_revision != current_revision
    ):
        return []
    return list(
        db.scalars(
            select(ProjectInitializationValidationIssue)
            .where(
                ProjectInitializationValidationIssue.validation_run_id
                == latest_run.id,
            )
            .order_by(ProjectInitializationValidationIssue.id),
        ).all(),
    )


def serialize_initialization_validation_issue(
    issue: ProjectInitializationValidationIssue,
) -> dict[str, Any]:
    return {
        "id": issue.id,
        "rule_id": issue.rule_id,
        "level": issue.level,
        "section": issue.section,
        "target_record_id": issue.target_record_id,
        "field_name": issue.field_name,
        "label": issue.label,
        "title": issue.title,
        "message": issue.message,
        "suggestion": issue.suggestion,
        "related_record_ids": list(issue.related_record_ids or []),
        "details": dict(issue.details or {}),
    }


def initialization_draft_workflow_summary(
    db: Session,
    draft: ProjectInitializationDraft,
) -> None:
    """Runtime planning lives in AgentScope; draft review needs no shadow plan."""
    del db, draft
    return None
