from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import api as _legacy


router = _legacy.router
get_db = _legacy.get_db
get_current_user = _legacy.get_current_user
ok = _legacy.ok
audit = _legacy.audit
serialize = _legacy.serialize
entity_or_404 = _legacy.entity_or_404
project_or_404 = _legacy.project_or_404
list_for_project = _legacy.list_for_project
dispatch_platform_task = _legacy.dispatch_platform_task

from .models import Attachment, DailyReport, FillPackage, PlatformFieldMapping, RiskDraft, RiskSource, User, WbsRiskLink
from .schemas import DailyReportInput, DailyReportUpdate, DraftInput, DraftReviewInput, FillPackageInput, TaskTransitionInput

@router.get("/projects/{project_id}/daily-reports")
def list_daily_reports(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(DailyReport, project_id, db))


@router.post("/projects/{project_id}/daily-reports")
def create_daily_report(project_id: int, payload: DailyReportInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); row = DailyReport(project_id=project_id, parse_status="parsed", **payload.model_dump()); db.add(row); db.flush()
    audit(db, user, "录入日报", f"录入日报「{row.file_name}」", project_id, "daily_report", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "日报已创建")


@router.patch("/daily-reports/{report_id}")
def update_daily_report(report_id: int, payload: DailyReportUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, DailyReport, report_id, "日报不存在")
    for key, value in payload.model_dump(exclude_none=True).items(): setattr(row, key, value)
    audit(db, user, "修正日报", f"修正日报「{row.file_name}」", row.project_id, "daily_report", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "日报已更新")


@router.post("/daily-reports/{report_id}/confirm")
def confirm_daily_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, DailyReport, report_id, "日报不存在"); row.status = "confirmed"
    audit(db, user, "确认日报", f"确认日报「{row.file_name}」", row.project_id, "daily_report", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "日报已确认")


@router.get("/projects/{project_id}/risk-drafts")
def list_drafts(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(RiskDraft, project_id, db))


@router.post("/projects/{project_id}/risk-drafts")
def create_draft(project_id: int, payload: DraftInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); entity_or_404(db, RiskSource, payload.risk_source_id, "风险源不存在")
    row = RiskDraft(project_id=project_id, **payload.model_dump()); db.add(row); db.flush()
    audit(db, user, "生成风险草稿", f"生成草稿「{row.title}」", project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已生成")


@router.post("/projects/{project_id}/risk-drafts/assist/{risk_id}")
def assist_risk_draft(project_id: int, risk_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); risk = entity_or_404(db, RiskSource, risk_id, "风险源不存在")
    attachments = db.scalars(select(Attachment).where(Attachment.project_id == project_id)).all()
    names = [attachment.file_name for attachment in attachments]
    missing = [material for material in (risk.material_requirements or []) if not any(material.lower() in name.lower() or name.lower() in material.lower() for name in names)]
    source_refs = names[-8:]
    content = f"风险源：{risk.risk_part}\n风险等级：{risk.risk_level}\n控制要求：{risk.evaluation_condition or '待补充'}\n已关联资料：{'、'.join(source_refs) or '暂无'}\n缺项资料：{'、'.join(missing) or '无'}\n建议：请核对风险现场状态和资料完整性后提交审核。"
    draft = RiskDraft(project_id=project_id, risk_source_id=risk.id, title=f"{risk.risk_part}风险上报草稿", content=content, source_refs=source_refs, missing_items=missing)
    db.add(draft); db.flush()
    task_id = None
    if missing:
        link = db.scalar(
            select(WbsRiskLink)
            .where(WbsRiskLink.risk_source_id == risk.id)
            .order_by(WbsRiskLink.id),
        )
        try:
            task = dispatch_platform_task(
                db,
                project_id=project_id,
                title=f"补齐风险资料 — {risk.risk_part}",
                task_type="material_missing",
                risk_level=risk.risk_level,
                assignee_user_id=risk.responsible_user_id,
                confirmer_user_id=risk.confirmer_user_id,
                wbs_item_id=link.wbs_item_id if link else None,
                actor=user.id,
                trigger_reason="智能草稿生成时发现风险资料缺项",
                deliverables=missing,
                risk_source_id=risk.id,
                step_name="补齐风险资料",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        task_id = task.id
    audit(db, user, "智能生成风险草稿", f"为风险源「{risk.risk_part}」生成草稿" + ("并创建缺项任务" if task_id else ""), project_id, "risk_draft", draft.id)
    db.commit(); db.refresh(draft)
    return ok({"draft": serialize(draft), "task_id": task_id}, "风险草稿与缺项校验已完成")


@router.post("/risk-drafts/{draft_id}/submit-review")
def submit_draft_review(draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, RiskDraft, draft_id, "草稿不存在"); row.status = "pending_review"
    audit(db, user, "提交草稿审核", f"草稿「{row.title}」提交审核", row.project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已提交审核")


@router.post("/risk-drafts/{draft_id}/confirm")
def confirm_draft(draft_id: int, payload: DraftReviewInput | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, RiskDraft, draft_id, "草稿不存在"); row.status = "confirmed"; row.review_note = payload.note if payload else None
    audit(db, user, "确认风险草稿", f"确认草稿「{row.title}」", row.project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已确认")


@router.post("/risk-drafts/{draft_id}/return")
def return_draft(draft_id: int, payload: DraftReviewInput | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, RiskDraft, draft_id, "草稿不存在"); row.status = "rejected"; row.review_note = payload.note if payload else None
    audit(db, user, "退回风险草稿", f"退回草稿「{row.title}」", row.project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已退回")


@router.post("/risk-drafts/{draft_id}/fill-package")
def create_fill_package(draft_id: int, payload: FillPackageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    draft = entity_or_404(db, RiskDraft, draft_id, "草稿不存在")
    if draft.status != "confirmed": raise HTTPException(status_code=409, detail="仅已确认草稿可生成填报包")
    package_data = payload.model_dump()
    if not package_data["fields"]:
        values = {"draft_title": draft.title, "draft_content": draft.content, "source_refs": "；".join(draft.source_refs)}
        mappings = db.scalars(select(PlatformFieldMapping).where(PlatformFieldMapping.project_id == draft.project_id, PlatformFieldMapping.platform_name == payload.platform_name, PlatformFieldMapping.enabled.is_(True))).all()
        package_data["fields"] = [{"name": mapping.target_field, "value": values.get(mapping.source_field, ""), "required": mapping.required, "transform_rule": mapping.transform_rule} for mapping in mappings]
    row = FillPackage(project_id=draft.project_id, draft_id=draft.id, **package_data); draft.status = "packaged"; db.add(row); db.flush()
    audit(db, user, "生成填报包", f"为草稿「{draft.title}」生成填报包", draft.project_id, "fill_package", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "填报包已生成")


@router.get("/projects/{project_id}/fill-packages")
def list_fill_packages(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(FillPackage, project_id, db))


@router.post("/fill-packages/{package_id}/transition")
def transition_fill_package(package_id: int, payload: TaskTransitionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, FillPackage, package_id, "填报包不存在")
    if payload.status not in {"pending", "filling", "saved", "submitted", "failed", "cancelled"}: raise HTTPException(status_code=422, detail="不支持的填报状态")
    row.status = payload.status; audit(db, user, "更新填报状态", f"填报包状态变更为 {row.status}", row.project_id, "fill_package", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "填报状态已更新")
