"""Persist agent-requested validation of sparse proposals against live data."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from .initialization_change_validation import validate_change_plan
from .initialization_draft_queries import serialize_initialization_validation_issue
from .initialization_draft_view import draft_review_payload
from .initialization_validation_snapshot import save_validation_snapshot, snapshot_key
from .agentscope_client import AgentScopeClient
from .config import get_settings
from .models import ProjectInitializationDraft, ProjectInitializationValidationIssue, ProjectInitializationValidationRun


def run_incremental_validation(db: Session, draft: ProjectInitializationDraft, *, client=None) -> dict[str, Any]:
    from .initialization_changes import build_change_plan
    from .initialization_validation import InitializationValidationError, validation_run_view
    if draft.status in {"applied", "rejected"}:
        raise InitializationValidationError("已结束的项目资料草稿不能重新核验。")
    plan = build_change_plan(db, draft)
    payload = draft_review_payload(db, draft)
    run = ProjectInitializationValidationRun(
        draft_id=draft.id, project_id=draft.project_id, conversation_id=draft.conversation_id,
        draft_revision=draft.revision, status="running", validation_issues=[], started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    run_id, revision = run.id, run.draft_revision
    try:
        validator = client or AgentScopeClient(get_settings())
        key, binding = snapshot_key(plan, validator)
        issues, validation = validate_change_plan(plan, client=validator)
        db.expire_all()
        if draft.revision != revision:
            raise InitializationValidationError("草稿在核验期间已更新，本次结果已作废，请重新核验。")
        refreshed = build_change_plan(db, draft)
        if refreshed["baseline_hash"] != plan["baseline_hash"]:
            raise InitializationValidationError("项目数据在核验期间已更新，请重新核验。")
        save_validation_snapshot(db, draft, plan, key, issues, validation, binding)
        by_key = {row["key"]: row for row in plan["changes"]}
        saved = []
        for issue in issues:
            change = by_key.get(issue.get("change_key"))
            section = change["section"] if change else issue["section"]
            field = issue.get("field_name") if change and issue["section"] == section else None
            row = ProjectInitializationValidationIssue(
                validation_run_id=run_id, draft_id=draft.id, project_id=draft.project_id, draft_revision=revision,
                section=section, target_record_id=change["record_id"] if change else None,
                field_name=field, rule_id=issue.get("rule_id", "platform.change.validation"), level=issue["level"],
                label=issue.get("label", "需要核对"), title=issue["title"], message=issue["message"],
                suggestion=issue.get("suggestion"), related_record_ids=[], details=issue.get("details", {}),
            )
            db.add(row)
            saved.append(row)
        db.flush()
        serialized = [serialize_initialization_validation_issue(row) for row in saved]
        status = "invalid" if validation.get("result_status") == "invalid" or any(row["level"] == "error" for row in issues) else "ready"
        run.status, run.result_status = "completed", status
        run.package_id = validation.get("package_id")
        run.package_version = validation.get("package_version")
        run.ruleset_version = validation.get("ruleset_version")
        run.duration_ms = validation.get("duration_ms", 0)
        run.validation_issues, run.finished_at = serialized, datetime.now(UTC)
        changed = db.execute(update(ProjectInitializationDraft).where(
            ProjectInitializationDraft.id == draft.id, ProjectInitializationDraft.revision == revision,
        ).values(payload=payload, validation_issues=serialized, status=status))
        if changed.rowcount != 1:
            raise InitializationValidationError("草稿在核验期间已更新，请重新核验。")
        db.commit()
        db.refresh(draft)
        db.refresh(run)
        return {"draft_id": draft.id, "draft_revision": revision, "status": status,
                "validation_issues": serialized, "validation": validation_run_view(run)}
    except Exception as exc:
        db.rollback()
        failed = db.get(ProjectInitializationValidationRun, run_id)
        if failed is not None:
            failed.status, failed.error, failed.finished_at = "failed", str(exc), datetime.now(UTC)
            db.commit()
        if isinstance(exc, InitializationValidationError):
            raise
        raise InitializationValidationError(f"项目资料核验失败：{exc}") from exc
