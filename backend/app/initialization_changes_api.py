"""User-reviewed incremental project data imports."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_common import audit, get_current_user, ok, project_for_user_or_403, require_admin
from .db import get_db
from .initialization_change_contracts import ApplyInitializationChangesInput, PreviewInitializationChangesInput
from .initialization_change_service import apply_change_preview, create_change_preview
from .models import ProjectInitializationDraft, User
from .project_initialization import InitializationApplyError

router = APIRouter(prefix="/api")


def _draft(db: Session, project_id: int, draft_id: int, user: User) -> ProjectInitializationDraft:
    project_for_user_or_403(db, project_id, user)
    row = db.get(ProjectInitializationDraft, draft_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目资料草稿不存在")
    return row


@router.post("/projects/{project_id}/initialization-drafts/{draft_id}/change-preview")
def preview_project_changes(
    project_id: int, draft_id: int, payload: PreviewInitializationChangesInput,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft = _draft(db, project_id, draft_id, user)
    try:
        review = create_change_preview(db, draft, user, payload)
        if user.role != "admin":
            review = {**review, "can_apply": False}
        return ok(review)
    except (InitializationApplyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/projects/{project_id}/initialization-drafts/{draft_id}/apply-changes")
def apply_project_changes(
    project_id: int, draft_id: int, payload: ApplyInitializationChangesInput,
    db: Session = Depends(get_db), user: User = Depends(require_admin),
) -> dict[str, Any]:
    draft = _draft(db, project_id, draft_id, user)
    try:
        result = apply_change_preview(db, draft, user, payload)
        audit(db, user, "确认项目资料变更", f"确认草稿第 {draft.revision} 版所选内容，剩余 {result['remaining']} 项", project_id, "project_initialization_draft", draft_id)
        # Existing learning records describe the whole draft, so they may only
        # be produced once the whole reviewed draft has actually been applied.
        if result["status"] == "applied":
            from .business_learning_sources import record_initialization_applied
            record_initialization_applied(db, draft, user.id, result)
        db.commit()
        return ok({"result": result}, "所选项目资料已保存")
    except (InitializationApplyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="项目数据或账号存在冲突，请刷新差异并重新核对。") from exc
