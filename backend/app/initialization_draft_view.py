"""Read sparse draft proposals without filling unrecognized fields."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .initialization_draft_queries import sync_initialization_draft_section_records
from .models import ProjectInitializationDraft, ProjectInitializationDraftRecord, ProjectInitializationDraftSection


def draft_review_payload(db: Session, draft: ProjectInitializationDraft) -> dict[str, Any]:
    data: dict[str, Any] = {"project": {"record_id": None}, "personnel": [], "wbs": [], "risks": [], "quality_requirements": []}
    for section in db.scalars(select(ProjectInitializationDraftSection).where(
        ProjectInitializationDraftSection.draft_id == draft.id,
    ).order_by(ProjectInitializationDraftSection.id)).all():
        records = list(db.scalars(select(ProjectInitializationDraftRecord).where(
            ProjectInitializationDraftRecord.section_id == section.id,
            ProjectInitializationDraftRecord.active.is_(True),
        ).order_by(ProjectInitializationDraftRecord.ordinal)).all())
        if not records and section.payload:
            records = sync_initialization_draft_section_records(db, section)
        values = [{**dict(record.payload or {}), "record_id": record.id} for record in records]
        if section.section == "project":
            data["project"] = values[0] if values else {"record_id": None}
        else:
            data[section.section] = values
    return data


from .api_common import serialize
from .initialization_draft_queries import initialization_draft_workflow_summary, latest_initialization_validation_issues, serialize_initialization_validation_issue
from .initialization_validation import latest_initialization_validation_run, validation_run_view
from .project_initialization import suggest_unique_username
from .models import User


def build_initialization_draft_review(
    db: Session,
    draft: ProjectInitializationDraft,
) -> dict[str, Any]:
    data = serialize(draft)
    payload = draft_review_payload(db, draft)
    workflow = initialization_draft_workflow_summary(db, draft)
    current_issues = [] if draft.status == "building" else [
        serialize_initialization_validation_issue(issue)
        for issue in latest_initialization_validation_issues(db, draft.id)
    ]
    data["payload"] = payload
    data["workflow"] = workflow
    data["validation_issues"] = current_issues
    latest_validation = latest_initialization_validation_run(db, draft.id)
    data["validation"] = validation_run_view(latest_validation)
    if draft.status == "building":
        data["status"] = (
            "reviewing"
            if latest_validation is not None
            and latest_validation.status == "running"
            else "collecting"
        )
    elif draft.status not in {"applied", "rejected"}:
        data["status"] = (
            "invalid"
            if any(issue["level"] == "error" for issue in current_issues)
            else "ready"
        )
    personnel = (
        payload.get("personnel", [])
        if isinstance(payload.get("personnel", []), list)
        else []
    )
    identity_cards = [
        str(item.get("identity_card_no"))
        for item in personnel
        if isinstance(item, dict) and item.get("identity_card_no")
    ]
    existing_users = {
        user.identity_card_no: user
        for user in (
            db.scalars(
                select(User).where(User.identity_card_no.in_(identity_cards)),
            ).all()
            if identity_cards
            else []
        )
    }
    unavailable_usernames = set(db.scalars(select(User.username)).all())
    required_credentials: list[dict[str, str]] = []
    seen_new_cards: set[str] = set()
    for item in personnel:
        if not isinstance(item, dict) or not item.get("identity_card_no"):
            continue
        identity_card_no = str(item["identity_card_no"])
        if identity_card_no in existing_users or identity_card_no in seen_new_cards:
            continue
        suggested_username = suggest_unique_username(
            str(item.get("real_name") or ""),
            identity_card_no,
            unavailable_usernames,
        )
        unavailable_usernames.add(suggested_username)
        seen_new_cards.add(identity_card_no)
        required_credentials.append(
            {
                "identity_card_no": identity_card_no,
                "real_name": str(item.get("real_name") or ""),
                "position_name": str(item.get("position_name") or ""),
                "suggested_username": suggested_username,
            },
        )
    data["required_personnel_credentials"] = required_credentials
    data["existing_personnel_accounts"] = [
        {
            "identity_card_no": identity_card_no,
            "user_id": user.id,
            "username": user.username,
            "real_name": user.real_name,
        }
        for identity_card_no, user in existing_users.items()
    ]
    data["summary"] = {
        "project_fields": sum(
            value not in (None, "")
            for key, value in (
                payload.get("project", {}).items()
                if isinstance(payload.get("project"), dict)
                else []
            )
            if key != "record_id"
        ),
        "personnel": len(set(identity_cards)),
        "position_assignments": len(personnel),
        "wbs": len(payload.get("wbs", []))
        if isinstance(payload.get("wbs"), list)
        else 0,
        "risks": len(payload.get("risks", []))
        if isinstance(payload.get("risks"), list)
        else 0,
        "quality_requirements": len(payload.get("quality_requirements", []))
        if isinstance(payload.get("quality_requirements"), list)
        else 0,
    }
    return data
