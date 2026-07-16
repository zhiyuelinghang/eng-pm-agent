import hashlib
import io
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import (Attachment, AttachmentText, CollaborationMessage, CollaborationSession, DailyReport, FillPackage, Notification, OperationLog, PlatformFieldMapping, Project, ProjectChange, ProjectMember, ProjectSettings,
                     QualityMetric, RiskDraft, RiskSource, Task, TaskStatusHistory, User, WbsItem, WbsRiskLink)
from .schemas import (DailyReportInput, DailyReportUpdate, DraftInput, DraftReviewInput, FillPackageInput,
                      LoginRequest, MemberInput, ProjectInput, RiskInput, TaskInput, TaskTransitionInput,
                      WbsInput, WbsRiskLinkInput, OperationLogInput, PlatformFieldMappingInput, ProjectSettingsInput,
                      CollaborationMessageInput, CollaborationSessionInput, ProjectChangeInput, QualityMetricInput, TaskStepUpdate)
from .security import create_access_token, decode_access_token, hash_password, verify_password


router = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)
ModelType = TypeVar("ModelType")


def ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def serialize(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def entity_or_404(db: Session, model: type[ModelType], item_id: int, message: str) -> ModelType:
    entity = db.get(model, item_id)
    if not entity:
        raise HTTPException(status_code=404, detail=message)
    return entity


def audit(db: Session, user: User, action: str, detail: str, project_id: int | None = None, target_type: str | None = None, target_id: int | None = None) -> None:
    db.add(OperationLog(project_id=project_id, operator_id=user.id, action=action, detail=detail, target_type=target_type, target_id=target_id))


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号不可用")
    return ok({"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": serialize(user)})


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(serialize(user))


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok([serialize(row) for row in db.scalars(select(Project).order_by(Project.updated_at.desc())).all()])


@router.post("/projects")
def create_project(payload: ProjectInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project = Project(**payload.model_dump())
    db.add(project); db.flush()
    audit(db, user, "创建项目", f"创建项目「{project.project_name}」", project.id, "project", project.id)
    db.commit(); db.refresh(project)
    return ok(serialize(project), "项目已创建")


@router.patch("/projects/{project_id}")
def update_project(project_id: int, payload: ProjectInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    for key, value in payload.model_dump().items(): setattr(project, key, value)
    audit(db, user, "更新项目", f"更新项目「{project.project_name}」", project.id, "project", project.id)
    db.commit(); db.refresh(project)
    return ok(serialize(project), "项目已更新")


@router.get("/projects/{project_id}/settings")
def get_project_settings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = db.get(ProjectSettings, project_id)
    return ok(serialize(row) if row else {"project_id": project_id, "main_dir": "", "archive_dir": "", "temp_dir": "", "failed_dir": "", "backup_dir": "", "scan_interval": 30, "enabled": False, "reminder_rules": []})


@router.put("/projects/{project_id}/settings")
def save_project_settings(project_id: int, payload: ProjectSettingsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = db.get(ProjectSettings, project_id)
    if not row:
        row = ProjectSettings(project_id=project_id)
        db.add(row)
    for key, value in payload.model_dump().items(): setattr(row, key, value)
    db.flush(); audit(db, user, "更新目录与预警配置", "更新资料目录监控及预警规则", project_id, "project_settings", project_id)
    db.commit(); db.refresh(row)
    return ok(serialize(row), "目录与预警配置已保存")


def refresh_project_notifications(project_id: int, db: Session) -> None:
    overdue = db.scalars(select(Task).where(Task.project_id == project_id, Task.status == "overdue")).all()
    waiting_dailies = db.scalars(select(DailyReport).where(DailyReport.project_id == project_id, DailyReport.status == "pending_confirm")).all()
    for task in overdue:
        exists = db.scalar(select(Notification).where(Notification.project_id == project_id, Notification.source_type == "task", Notification.source_id == task.id, Notification.notification_type == "overdue"))
        if not exists: db.add(Notification(project_id=project_id, notification_type="overdue", title="任务已逾期", content=task.title, priority="high", source_type="task", source_id=task.id))
    for report in waiting_dailies:
        exists = db.scalar(select(Notification).where(Notification.project_id == project_id, Notification.source_type == "daily_report", Notification.source_id == report.id, Notification.notification_type == "daily_confirm"))
        if not exists: db.add(Notification(project_id=project_id, notification_type="daily_confirm", title="日报待确认", content=report.file_name, priority="normal", source_type="daily_report", source_id=report.id))
    db.commit()


@router.get("/projects/{project_id}/dashboard")
def project_dashboard(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); refresh_project_notifications(project_id, db)
    wbs = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)).all()
    tasks = db.scalars(select(Task).where(Task.project_id == project_id)).all()
    risks = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id)).all()
    metrics = db.scalars(select(QualityMetric).where(QualityMetric.project_id == project_id)).all()
    changes = db.scalars(select(ProjectChange).where(ProjectChange.project_id == project_id, ProjectChange.status != "closed")).all()
    notifications = db.scalars(select(Notification).where(Notification.project_id == project_id, Notification.is_read.is_(False))).all()
    done = sum(1 for task in tasks if task.status == "completed")
    return ok({"progress_rate": round(sum(item.progress for item in wbs) / len(wbs)) if wbs else 0, "risk_warnings": sum(1 for risk in risks if risk.level in {"critical", "high"}), "safety_issues": sum(1 for risk in risks if "安全" in risk.risk_type), "quality_issues": sum(1 for metric in metrics if metric.status != "passed"), "task_completion_rate": round(done * 100 / len(tasks)) if tasks else 0, "open_changes": len(changes), "unread_notifications": len(notifications), "main_risk": next((risk.name for risk in risks if risk.level in {"critical", "high"}), "暂无重大风险"), "main_quality": next((metric.name for metric in metrics if metric.status != "passed"), "暂无待核查质量项")})


@router.get("/projects/{project_id}/changes")
def list_project_changes(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(ProjectChange, project_id, db))


@router.post("/projects/{project_id}/changes")
def create_project_change(project_id: int, payload: ProjectChangeInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); row = ProjectChange(project_id=project_id, **payload.model_dump()); db.add(row); db.flush()
    audit(db, user, "登记工程变更", f"登记变更「{row.title}」", project_id, "project_change", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "工程变更已登记")


@router.get("/projects/{project_id}/notifications")
def list_notifications(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); refresh_project_notifications(project_id, db)
    rows = db.scalars(select(Notification).where(Notification.project_id == project_id).order_by(Notification.created_at.desc())).all()
    return ok([serialize(row) for row in rows])


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, Notification, notification_id, "通知不存在"); row.is_read = True; db.commit(); db.refresh(row)
    return ok(serialize(row), "通知已标记已读")


@router.get("/projects/{project_id}/members")
def list_members(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
    data = []
    for member in members:
        item = serialize(member); item["user"] = serialize(entity_or_404(db, User, member.user_id, "用户不存在")); data.append(item)
    return ok(data)


@router.post("/projects/{project_id}/members")
def add_member(project_id: int, payload: MemberInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    account = db.scalar(select(User).where(User.username == payload.username)) if payload.username else None
    if not account:
        username = payload.username or f"user_{int(datetime.now(UTC).timestamp())}"
        account = User(username=username, password_hash=hash_password(payload.password or "ChangeMe123!"), real_name=payload.real_name, phone=payload.phone, email=payload.email, title=payload.title, role=payload.system_role)
        db.add(account); db.flush()
    member = ProjectMember(project_id=project_id, user_id=account.id, member_role=payload.member_role, display_name=payload.real_name, phone=payload.phone, responsibilities=payload.responsibilities)
    db.add(member); db.flush(); audit(db, user, "添加项目成员", f"添加成员「{payload.real_name}」", project_id, "project_member", member.id)
    db.commit(); db.refresh(member)
    return ok(serialize(member), "成员已添加")


def list_for_project(model: type[ModelType], project_id: int, db: Session) -> list[dict[str, Any]]:
    project_or_404(db, project_id)
    return [serialize(row) for row in db.scalars(select(model).where(model.project_id == project_id).order_by(model.id.desc())).all()]


@router.get("/projects/{project_id}/wbs")
def list_wbs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(WbsItem, project_id, db))


@router.post("/projects/{project_id}/wbs")
def create_wbs(project_id: int, payload: WbsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = WbsItem(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增WBS工序", f"新增工序「{item.name}」", project_id, "wbs", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "WBS工序已添加")


@router.patch("/wbs/{item_id}")
def update_wbs(item_id: int, payload: WbsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, WbsItem, item_id, "WBS工序不存在")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    audit(db, user, "更新WBS工序", f"更新工序「{item.name}」", item.project_id, "wbs", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "WBS工序已更新")


@router.get("/projects/{project_id}/risks")
def list_risks(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(RiskSource, project_id, db))


@router.post("/projects/{project_id}/risks")
def create_risk(project_id: int, payload: RiskInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = RiskSource(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增风险源", f"新增风险源「{item.name}」", project_id, "risk", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "风险源已添加")


@router.patch("/risks/{risk_id}")
def update_risk(risk_id: int, payload: RiskInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, RiskSource, risk_id, "风险源不存在")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    audit(db, user, "更新风险源", f"更新风险源「{item.name}」", item.project_id, "risk", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "风险源已更新")


@router.get("/projects/{project_id}/quality-metrics")
def list_quality_metrics(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(QualityMetric, project_id, db))


@router.post("/projects/{project_id}/quality-metrics")
def create_quality_metric(project_id: int, payload: QualityMetricInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if payload.wbs_item_id: entity_or_404(db, WbsItem, payload.wbs_item_id, "WBS工序不存在")
    item = QualityMetric(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增质量指标", f"新增质量指标「{item.name}」", project_id, "quality_metric", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "质量指标已添加")


@router.patch("/quality-metrics/{metric_id}")
def update_quality_metric(metric_id: int, payload: QualityMetricInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, QualityMetric, metric_id, "质量指标不存在")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    audit(db, user, "更新质量指标", f"更新质量指标「{item.name}」", item.project_id, "quality_metric", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "质量指标已更新")


@router.get("/projects/{project_id}/platform-field-mappings")
def list_platform_mappings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(PlatformFieldMapping, project_id, db))


@router.post("/projects/{project_id}/platform-field-mappings")
def create_platform_mapping(project_id: int, payload: PlatformFieldMappingInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = PlatformFieldMapping(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增平台字段映射", f"新增「{item.platform_name}」字段映射", project_id, "platform_mapping", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "字段映射已添加")


@router.delete("/platform-field-mappings/{mapping_id}")
def delete_platform_mapping(mapping_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, PlatformFieldMapping, mapping_id, "字段映射不存在"); db.delete(item)
    audit(db, user, "删除平台字段映射", f"删除「{item.platform_name}」字段映射", item.project_id, "platform_mapping", item.id); db.commit()
    return ok({}, "字段映射已删除")


@router.get("/projects/{project_id}/wbs-risk-links")
def list_links(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(WbsRiskLink, project_id, db))


@router.post("/projects/{project_id}/wbs-risk-links")
def create_link(project_id: int, payload: WbsRiskLinkInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = WbsRiskLink(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "建立WBS风险关联", "建立工序与风险源关联", project_id, "wbs_risk_link", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "关联已建立")


@router.delete("/wbs-risk-links/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, WbsRiskLink, link_id, "关联不存在"); db.delete(item)
    audit(db, user, "删除WBS风险关联", "删除工序与风险源关联", item.project_id, "wbs_risk_link", item.id); db.commit()
    return ok({}, "关联已删除")


@router.get("/projects/{project_id}/tasks")
def list_tasks(project_id: int, status_filter: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    open_tasks = db.scalars(select(Task).where(Task.project_id == project_id, Task.status.in_(["pending", "processing", "need_more_info", "pending_confirm"]))).all()
    today = date.today().isoformat()
    for task in open_tasks:
        if task.due_at and task.due_at[:10] < today:
            previous = task.status; task.status = "overdue"
            db.add(TaskStatusHistory(task_id=task.id, from_status=previous, to_status="overdue", note="系统根据截止日期自动标记逾期"))
            db.add(OperationLog(project_id=project_id, action="任务逾期提醒", detail=f"任务「{task.title}」已逾期", target_type="task", target_id=task.id))
    if any(task.due_at and task.due_at[:10] < today for task in open_tasks): db.commit()
    stmt = select(Task).where(Task.project_id == project_id)
    if status_filter: stmt = stmt.where(Task.status == status_filter)
    return ok([serialize(row) for row in db.scalars(stmt.order_by(Task.updated_at.desc())).all()])


@router.post("/projects/{project_id}/tasks")
def create_task(project_id: int, payload: TaskInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); task = Task(project_id=project_id, **payload.model_dump()); db.add(task); db.flush()
    db.add(TaskStatusHistory(task_id=task.id, to_status="pending", changed_by=user.id, note="创建任务"))
    audit(db, user, "创建任务", f"创建任务「{task.title}」", project_id, "task", task.id); db.commit(); db.refresh(task)
    return ok(serialize(task), "任务已创建")


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在"); data = serialize(task)
    data["history"] = [serialize(row) for row in db.scalars(select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id).order_by(TaskStatusHistory.created_at)).all()]
    return ok(data)


@router.post("/tasks/{task_id}/transition")
def transition_task(task_id: int, payload: TaskTransitionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在")
    transitions = {
        "pending": {"processing", "cancelled"}, "processing": {"need_more_info", "pending_confirm", "cancelled"},
        "need_more_info": {"processing", "cancelled"}, "pending_confirm": {"processing", "completed", "cancelled"},
        "overdue": {"processing", "cancelled"}, "completed": set(), "cancelled": set(),
    }
    if payload.status not in transitions.get(task.status, set()): raise HTTPException(status_code=409, detail=f"任务当前为 {task.status}，不能流转到 {payload.status}")
    previous = task.status; task.status = payload.status
    db.add(TaskStatusHistory(task_id=task.id, from_status=previous, to_status=task.status, note=payload.note, changed_by=user.id))
    audit(db, user, "任务状态流转", f"任务「{task.title}」由 {previous} 变更为 {task.status}", task.project_id, "task", task.id); db.commit(); db.refresh(task)
    return ok(serialize(task), "任务状态已更新")


@router.post("/tasks/{task_id}/steps/{step_index}")
def update_task_step(task_id: int, step_index: int, payload: TaskStepUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在")
    steps = list(task.workflow_steps or [])
    if step_index < 0 or step_index >= len(steps): raise HTTPException(status_code=404, detail="任务步骤不存在")
    if payload.status not in {"pending", "processing", "completed", "blocked"}: raise HTTPException(status_code=422, detail="不支持的步骤状态")
    step = {**steps[step_index], "status": payload.status, "note": payload.note, "updated_at": datetime.now(UTC).isoformat(), "updated_by": user.id}
    steps[step_index] = step; task.workflow_steps = steps
    audit(db, user, "更新任务步骤", f"任务「{task.title}」步骤「{step.get('name', step_index + 1)}」更新为 {payload.status}", task.project_id, "task", task.id)
    if steps and all(item.get("status") == "completed" for item in steps) and task.status == "processing":
        previous = task.status; task.status = "pending_confirm"
        db.add(TaskStatusHistory(task_id=task.id, from_status=previous, to_status="pending_confirm", note="全部任务步骤已完成，等待复核", changed_by=user.id))
    db.commit(); db.refresh(task)
    return ok(serialize(task), "任务步骤已更新")


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


def collaboration_reply(project_id: int, content: str, db: Session) -> tuple[str, list[int]]:
    tasks = db.scalars(select(Task).where(Task.project_id == project_id, Task.status.in_(["overdue", "pending", "processing", "need_more_info", "pending_confirm"])).order_by(Task.updated_at.desc())).all()
    related = [task.id for task in tasks[:4]]
    settings = get_settings()
    if settings.ai_api_key:
        prompt = f"你是工程项目协同助手。用户问题：{content}\n待办任务：" + "；".join(f"{task.title}（{task.status}，截止{task.due_at or '未设置'}）" for task in tasks[:8])
        try:
            response = httpx.post(f"{settings.ai_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.ai_api_key}"}, json={"model": settings.ai_model, "messages": [{"role": "system", "content": "给出简洁、可执行、可追溯的工程协同建议。"}, {"role": "user", "content": prompt}]}, timeout=30)
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            return answer, related
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            pass
    overdue = next((task for task in tasks if task.status == "overdue"), None)
    focus = overdue or (tasks[0] if tasks else None)
    if focus:
        return f"已基于当前项目真实数据记录协同意见：优先处理「{focus.title}」，状态为{focus.status}，截止日期{focus.due_at or '未设置'}。建议明确责任人、补齐所需资料后提交复核。", related
    return "当前项目暂无未闭环任务。可先补充工程资料、WBS、风险源或质量指标，再生成协同计划。", []


def extract_attachment_text(content: bytes, suffix: str) -> str:
    try:
        if suffix in {".txt", ".md", ".csv"}:
            return content.decode("utf-8", errors="ignore")[:200000]
        if suffix == ".docx":
            from docx import Document
            return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(content)).paragraphs)[:200000]
        if suffix == ".pdf":
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)[:200000]
    except Exception:
        return ""
    return ""


@router.get("/projects/{project_id}/collaboration-sessions")
def list_collaboration_sessions(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = db.scalars(select(CollaborationSession).where(CollaborationSession.project_id == project_id).order_by(CollaborationSession.updated_at.desc())).all()
    return ok([serialize(row) for row in rows])


@router.post("/projects/{project_id}/collaboration-sessions")
def create_collaboration_session(project_id: int, payload: CollaborationSessionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = CollaborationSession(project_id=project_id, participant_ids=list(set(payload.participant_ids + [user.id])), **payload.model_dump(exclude={"participant_ids"}))
    db.add(row); db.flush(); audit(db, user, "创建协同会话", f"创建会话「{row.title}」", project_id, "collaboration_session", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "协同会话已创建")


def session_or_404(db: Session, session_id: int) -> CollaborationSession:
    return entity_or_404(db, CollaborationSession, session_id, "协同会话不存在")


@router.get("/collaboration-sessions/{session_id}/messages")
def list_collaboration_messages(session_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    session_or_404(db, session_id)
    rows = db.scalars(select(CollaborationMessage).where(CollaborationMessage.session_id == session_id).order_by(CollaborationMessage.created_at)).all()
    return ok([serialize(row) for row in rows])


@router.post("/collaboration-sessions/{session_id}/messages")
def create_collaboration_message(session_id: int, payload: CollaborationMessageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    session = session_or_404(db, session_id)
    db.add(CollaborationMessage(session_id=session.id, role="user", content=payload.content)); db.flush()
    answer, task_ids = collaboration_reply(session.project_id, payload.content, db)
    assistant = CollaborationMessage(session_id=session.id, role="assistant", content=answer, generated_task_ids=task_ids)
    db.add(assistant); session.summary = payload.content[:120]
    audit(db, user, "协同会话处理", f"会话「{session.title}」处理新消息", session.project_id, "collaboration_session", session.id)
    db.commit(); db.refresh(assistant); db.refresh(session)
    return ok({"session": serialize(session), "message": serialize(assistant)}, "协同建议已生成")


@router.post("/projects/{project_id}/attachments")
def upload_attachment(project_id: int, file: UploadFile = File(...), category: str = "未分类", db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    settings = get_settings(); folder = settings.upload_dir / str(project_id); folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "attachment").name; target = folder / f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    with target.open("wb") as output: shutil.copyfileobj(file.file, output)
    content = target.read_bytes(); digest = hashlib.sha256(content).hexdigest()
    if category == "自动归类":
        normalized = safe_name.lower()
        category = "日报" if "日报" in normalized else "进度计划" if any(key in normalized for key in ["wbs", "计划", "进度"]) else "风险资料" if any(key in normalized for key in ["风险", "监测", "隐患"]) else "工程资料"
    previous_version = db.scalar(select(func.max(Attachment.version)).where(Attachment.project_id == project_id, Attachment.file_name == safe_name)) or 0
    row = Attachment(project_id=project_id, file_name=safe_name, storage_path=str(target), content_type=file.content_type, file_size=len(content), file_hash=digest, category=category, version=previous_version + 1)
    db.add(row); db.flush()
    db.add(AttachmentText(attachment_id=row.id, project_id=project_id, content=extract_attachment_text(content, target.suffix.lower())))
    audit(db, user, "上传资料", f"上传资料「{safe_name}」", project_id, "attachment", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "资料已上传")


@router.get("/projects/{project_id}/attachments")
def list_attachments(project_id: int, keyword: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); stmt = select(Attachment).where(Attachment.project_id == project_id)
    if keyword: stmt = stmt.where(Attachment.file_name.contains(keyword))
    return ok([serialize(row) for row in db.scalars(stmt.order_by(Attachment.created_at.desc())).all()])


@router.get("/projects/{project_id}/document-search")
def search_documents(project_id: int, keyword: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if not keyword.strip(): return ok([])
    rows = db.execute(select(Attachment, AttachmentText.content).outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id).where(Attachment.project_id == project_id, (Attachment.file_name.contains(keyword) | AttachmentText.content.contains(keyword))).order_by(Attachment.created_at.desc())).all()
    result = []
    for attachment, content in rows:
        item = serialize(attachment)
        if content:
            index = content.lower().find(keyword.lower())
            item["snippet"] = content[max(0, index - 40): index + len(keyword) + 80] if index >= 0 else ""
        result.append(item)
    return ok(result)


@router.post("/attachments/{attachment_id}/parse-daily")
def parse_daily_attachment(attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """将已入库日报登记为待确认记录，并生成对应的确认任务。"""
    attachment = entity_or_404(db, Attachment, attachment_id, "资料不存在")
    duplicate = db.scalar(select(DailyReport).where(
        DailyReport.project_id == attachment.project_id,
        DailyReport.file_name == attachment.file_name,
    ))
    if duplicate:
        return ok(serialize(duplicate), "该日报已登记，无需重复创建")

    content = ""
    path = Path(attachment.storage_path)
    if path.suffix.lower() in {".txt", ".md", ".csv"}:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:10000]
        except OSError:
            content = ""
    if not content:
        content = f"已归档文件「{attachment.file_name}」，请在确认前补充施工内容、进度和风险信息。"

    date_match = re.search(r"20\d{2}[-_.年/]?\d{1,2}[-_.月/]?\d{1,2}", attachment.file_name)
    report_date = date_match.group(0).replace("年", "-").replace("月", "-").replace("日", "").replace("_", "-").replace(".", "-").replace("/", "-") if date_match else datetime.now(UTC).date().isoformat()
    candidates = db.scalars(select(WbsItem).where(WbsItem.project_id == attachment.project_id)).all()
    matched = next((item for item in candidates if item.name and item.name.lower() in attachment.file_name.lower()), None)
    report = DailyReport(project_id=attachment.project_id, file_name=attachment.file_name, report_date=report_date, content=content,
                         matched_wbs_id=matched.id if matched else None, confidence=0.85 if matched else 0.45,
                         parse_status="parsed", status="pending_confirm")
    db.add(report); db.flush()
    attachment.source_type = "daily_report"; attachment.source_id = report.id
    task = Task(project_id=attachment.project_id, title=f"日报解析确认 — {attachment.file_name}", task_type="daily_confirm", risk_level="low",
                assignee_user_id=user.id, due_at=datetime.now(UTC).date().isoformat(), wbs_item_id=report.matched_wbs_id,
                trigger_reason="资料入库后登记日报，等待人工确认解析内容", required_materials=[])
    db.add(task); db.flush()
    db.add(TaskStatusHistory(task_id=task.id, to_status="pending", changed_by=user.id, note="日报登记后自动创建"))
    audit(db, user, "登记日报解析", f"资料「{attachment.file_name}」已生成日报确认任务", attachment.project_id, "daily_report", report.id)
    db.commit(); db.refresh(report)
    return ok(serialize(report), "日报已登记，并生成确认任务")


@router.get("/projects/{project_id}/operation-logs")
def list_operation_logs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    return ok([serialize(row) for row in db.scalars(select(OperationLog).where(OperationLog.project_id == project_id).order_by(OperationLog.created_at.desc())).all()])


@router.post("/projects/{project_id}/operation-logs")
def create_operation_log(project_id: int, payload: OperationLogInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    audit(db, user, payload.action, payload.detail, project_id, payload.target_type, payload.target_id)
    db.commit()
    row = db.scalars(select(OperationLog).where(OperationLog.project_id == project_id).order_by(OperationLog.id.desc())).first()
    return ok(serialize(row), "日志已记录")
