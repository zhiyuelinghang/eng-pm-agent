"""Review selections against a baseline, then apply exactly that reviewed batch."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .initialization_change_contracts import ApplyInitializationChangesInput, PreviewInitializationChangesInput
from .initialization_change_models import InitializationChangePreview
from .initialization_change_validation import validate_change_plan
from .initialization_validation import InitializationValidatorClient
from .initialization_validation_snapshot import load_validation_snapshot, save_validation_snapshot, snapshot_key
from .agentscope_client import AgentScopeClient
from .config import get_settings
from .models import AgentConversation, Project, ProjectInitializationDraft, ProjectMember, ProjectMemberPosition, ProjectPosition, QualityMetric, RiskSource, User, WbsItem, WbsPredecessor
from .project_initialization import InitializationApplyError


def _fingerprint(plan: dict[str, Any]) -> str:
    chosen = set(plan["selected_keys"])
    data = [{key: row.get(key) for key in ("key", "operation", "target_id", "before", "after", "fields")} for row in plan["changes"] if row["key"] in chosen]
    # MCP decisions also depend on identity facts outside the current project
    # (e.g. an existing account name). They must stay unchanged until commit.
    reviewed = {"changes": data, "record_targets": plan["record_targets"]}
    return hashlib.sha256(json.dumps(reviewed, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def create_change_preview(
    db: Session, draft: ProjectInitializationDraft, user: User,
    request: PreviewInitializationChangesInput, *, client: InitializationValidatorClient | None = None,
) -> dict[str, Any]:
    from .initialization_changes import build_change_plan
    if draft.status == "rejected":
        raise InitializationApplyError("该草稿已退回，请选择其他草稿。")
    db.flush()
    db.expire_all()
    plan = build_change_plan(db, draft, request.selected_keys, request.resolutions)
    db.flush()
    # Remote validation must not keep a database writer transaction open.
    db.commit()
    validator = client or AgentScopeClient(get_settings())
    key = None
    try:
        key, binding = snapshot_key(plan, validator)
        saved = None if request.force_validation else load_validation_snapshot(db, draft, key)
        db.commit()
        if saved is not None:
            issues, validation = saved
        else:
            issues, validation = validate_change_plan(plan, client=validator)
            validation.update({"reused": False, "validated_at": datetime.now(UTC).isoformat()})
    except Exception as exc:
        issues = []
        validation = {"status": "failed", "error": str(exc) or "核验暂时不可用，请重试。"}
    db.expire_all()
    fresh = db.get(ProjectInitializationDraft, draft.id)
    refreshed = build_change_plan(db, fresh, plan["selected_keys"], request.resolutions)
    if fresh.revision != plan["draft_revision"] or refreshed["baseline_hash"] != plan["baseline_hash"] or _fingerprint(refreshed) != _fingerprint(plan):
        raise InitializationApplyError("核验期间项目数据或草稿发生变化，请刷新差异后重试。")
    if key and not validation.get("reused"):
        save_validation_snapshot(db, fresh, plan, key, issues, validation, binding)
    counts = {kind: sum(row["operation"] == kind for row in plan["changes"]) for kind in ("add", "update", "unchanged", "conflict", "applied")}
    counts["selected"] = len(plan["selected_keys"])
    preview_id = str(uuid4())
    review = {
        "preview_id": preview_id, "draft_id": draft.id, "draft_revision": draft.revision,
        "mode": plan["mode"],
        "baseline_hash": plan["baseline_hash"], "changes": plan["changes"],
        "selected_keys": plan["selected_keys"], "issues": issues,
        "operation_issues": plan.get("issues", []),
        "can_apply": bool(plan["selected_keys"]) and validation["status"] == "completed" and validation.get("result_status") != "invalid" and not any(issue["level"] == "error" for issue in issues + plan.get("issues", [])) and not any(row["selected"] and row["operation"] == "conflict" for row in plan["changes"]),
        "required_personnel_credentials": plan.get("required_personnel_credentials", []),
        "existing_personnel_accounts": plan.get("existing_personnel_accounts", []),
        "validation": validation, "summary": counts,
    }
    db.add(InitializationChangePreview(
        id=preview_id, project_id=draft.project_id, draft_id=draft.id, user_id=user.id,
        draft_revision=draft.revision, baseline_hash=plan["baseline_hash"],
        request={"selected_keys": plan["selected_keys"], "resolutions": request.resolutions, "plan_hash": _fingerprint(plan)},
        review=review,
    ))
    db.commit()
    return review


def _lock_project_data(db: Session, project_id: int) -> None:
    db.execute(select(Project).where(Project.id == project_id).with_for_update()).all()
    for model in (ProjectMember, ProjectMemberPosition, ProjectPosition, WbsItem, RiskSource, QualityMetric):
        db.execute(select(model).where(model.project_id == project_id).with_for_update()).all()
    wbs_ids = select(WbsItem.id).where(WbsItem.project_id == project_id)
    db.execute(select(WbsPredecessor).where(WbsPredecessor.wbs_item_id.in_(wbs_ids)).with_for_update()).all()


def apply_change_preview(
    db: Session, draft: ProjectInitializationDraft, user: User,
    request: ApplyInitializationChangesInput, *, client: InitializationValidatorClient | None = None,
) -> dict[str, Any]:
    from .initialization_changes import apply_change_plan, build_change_plan
    preview = db.get(InitializationChangePreview, request.preview_id)
    if preview is None or preview.draft_id != draft.id or preview.project_id != draft.project_id or preview.user_id != user.id:
        raise InitializationApplyError("未找到当前用户核对的差异，请重新打开确认窗口。")
    if preview.result is not None:
        return preview.result
    if datetime.now(UTC) - preview.created_at.replace(tzinfo=UTC) > timedelta(minutes=30):
        raise InitializationApplyError("本次差异预览已过期，请刷新后确认。")
    if not preview.review.get("can_apply"):
        raise InitializationApplyError("所选内容尚未通过核验，请先处理问题。")
    try:
        binding = (client or AgentScopeClient(get_settings())).get_initialization_validation_binding()
    except Exception as exc:
        raise InitializationApplyError("暂时无法确认当前核验规则版本，请稍后再试。") from exc
    validation = preview.review.get("validation", {})
    if not binding or any(not binding.get(key) or binding[key] != validation.get(key) for key in ("package_id", "package_version")):
        raise InitializationApplyError("核验规则版本已更新，请重新打开草稿载入新版核验结果后确认。")
    if any(issue["level"] == "warning" for issue in preview.review.get("issues", []) + preview.review.get("operation_issues", [])) and not request.allow_warnings:
        raise InitializationApplyError("请核对所选内容的提醒，并勾选确认后提交。")
    # An atomic claim serializes retries, including SQLite writers. Rollback on
    # any subsequent failure leaves the same reviewed selection retryable.
    claimed = db.execute(update(InitializationChangePreview).where(
        InitializationChangePreview.id == preview.id,
        InitializationChangePreview.applied_at.is_(None),
    ).values(applied_at=datetime.now(UTC)))
    if claimed.rowcount != 1:
        db.refresh(preview)
        if preview.result is not None:
            return preview.result
        raise InitializationApplyError("本次提交正在处理，请稍后刷新。")
    _lock_project_data(db, draft.project_id)
    cards = [row["after"].get("identity_card_no") for row in preview.review["changes"]
             if row["key"] in preview.request["selected_keys"] and row["section"] == "personnel"]
    if cards:
        db.execute(select(User).where(User.identity_card_no.in_(cards)).order_by(User.id).with_for_update()).all()
    db.execute(select(ProjectInitializationDraft).where(ProjectInitializationDraft.id == draft.id).with_for_update()).all()
    db.expire_all()
    if draft.revision != preview.draft_revision or draft.status == "rejected":
        raise InitializationApplyError("草稿已经更新，请刷新差异后重新确认。")
    plan = build_change_plan(db, draft, preview.request["selected_keys"], preview.request["resolutions"])
    if plan["baseline_hash"] != preview.baseline_hash or _fingerprint(plan) != preview.request["plan_hash"]:
        raise InitializationApplyError("项目数据已经变化，请刷新差异后重新确认。")
    if any(issue["level"] == "error" for issue in plan.get("issues", [])):
        raise InitializationApplyError("所选内容存在冲突，请重新核对。")
    result = apply_change_plan(db, draft, plan, request.personnel_credentials)
    db.flush()
    remainder = build_change_plan(db, draft, [], {})
    pending = sum(row["operation"] not in {"applied", "unchanged"} for row in remainder["changes"])
    # Keep collecting drafts open: other specialists may still submit sections.
    conversation = db.get(AgentConversation, draft.conversation_id)
    running = conversation is not None and conversation.status in {"creating", "running", "interrupting", "awaiting_permission", "awaiting_external_result"}
    complete = pending == 0 and draft.status != "building" and not running
    draft.status = "applied" if complete else ("building" if draft.status == "building" else "ready")
    draft.applied_at = datetime.now(UTC) if complete else None
    result.update({"draft_id": draft.id, "project_id": draft.project_id, "status": "applied" if complete else "partially_applied", "remaining": pending})
    preview.result = result
    db.flush()
    return result
