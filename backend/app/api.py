from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from task_engine.domain.flow import TransitionError
from task_engine.domain.models import Assignee
from task_engine.engine import TaskEngine
from task_engine.generator.llm import AIFlowGenerationError
from task_engine.serialize import schedule_json

from .chat_membership_policy import chat_auto_sync
from .api_common import (
    ModelType,
    audit,
    entity_or_404,
    get_current_user,
    ok,
    project_connector_view,
    project_for_user_or_403,
    project_or_404,
    require_admin,
    serialize,
    user_connector_view,
)
from .project_status_details import meeting_status_details, project_status_tasks
from .chat_api import ensure_project_chat_channel
from .connector_secrets import encrypt_connector_secret
from .db import get_db
from .engineering_document_catalog import (
    local_folder_tree_view,
    local_knowledge_page,
    local_workspace_view,
    reconcile_name_based_catalogue_permissions,
)
from .initialization_draft_queries import (
    compose_initialization_draft_payload,
    initialization_draft_workflow_summary,
    latest_initialization_validation_issues,
    serialize_initialization_validation_issue,
)
from .initialization_validation import (
    InitializationValidationError,
    latest_initialization_validation_run,
    run_project_initialization_validation,
    validation_run_view,
)
from .models import (
    Attachment,
    AttachmentText,
    ChatChannel,
    ChatChannelMember,
    DailyReport,
    FillPackage,
    Notification,
    PlatformFieldMapping,
    Project,
    ProjectChange,
    ProjectConnectorConfig,
    ProjectInformationRecord,
    ProjectInitializationDraft,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    ProjectSettings,
    ProjectStatusSnapshot,
    QualityMetric,
    RiskDraft,
    RiskSource,
    Task,
    User,
    UserConnectorConfig,
    WbsItem,
    WbsPredecessor,
    WbsRiskLink,
)
from .project_initialization import (
    ApplyInitializationDraftInput,
    InitializationApplyError,
    apply_initialization_draft,
    build_initialization_state,
    suggest_unique_username,
)
from .personnel_policy import (
    PROJECT_MANAGER_POSITION_NAME,
    PROJECT_POSITION_DEFINITIONS,
    UnsupportedProjectPositionError,
    reconcile_user_management_role,
    require_supported_project_position,
)
from .schemas import (
    DailyReportInput,
    DailyReportUpdate,
    DraftInput,
    DraftReviewInput,
    FillPackageInput,
    LoginRequest,
    MemberInput,
    PasswordChangeInput,
    PlatformFieldMappingInput,
    ProfileUpdate,
    ProjectChangeInput,
    ProjectConnectorConfigInput,
    ProjectConnectorType,
    ProjectInformationDispositionInput,
    ProjectInput,
    ProjectSettingsInput,
    QualityMetricInput,
    RiskInput,
    TaskFlowGenerateInput,
    TaskInput,
    TaskNoteInput,
    TaskReassignInput,
    TaskStepUpdate,
    TaskTransitionInput,
    UserConnectorConfigInput,
    UserConnectorType,
    WbsInput,
    WbsRiskLinkInput,
)
from .security import create_access_token, hash_password, verify_password
from .task_action_gateway import (
    current_task_action,
    execute_ready_automation_chain,
)
from .task_engine_gateway import (
    DOBBY_TO_ENGINE_STATE,
    PRIORITY_TO_RISK,
    TASK_MESSAGE_AGENT_ID,
    TASK_MESSAGE_AGENT_NAME,
    _to_int,
    build_flow,
    dispatch_platform_task,
    get_engine,
    get_generator,
    to_api_history,
    to_api_task,
)
from .wecom_notification_gateway import (
    WeComDeliveryError,
    enqueue_task_notification,
    is_wecom_webhook_url,
    safe_wecom_error,
    send_project_wecom_test,
    validate_wecom_webhook_url,
)


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
_active_task_flow_generations: dict[tuple[int, str], asyncio.Task[Any]] = {}
_cancelled_task_flow_generations: dict[tuple[int, str], float] = {}


def _prune_cancelled_task_flow_generations() -> None:
    """清理极短竞态窗口使用的停止标记，避免无界占用内存。"""
    cutoff = time.monotonic() - 300
    for key, cancelled_at in list(_cancelled_task_flow_generations.items()):
        if cancelled_at < cutoff:
            _cancelled_task_flow_generations.pop(key, None)


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    query = select(Project)
    if user.role != "admin":
        query = (
            query.join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .distinct()
        )
    rows = db.scalars(query.order_by(Project.updated_at.desc())).all()
    return ok([serialize(row) for row in rows])


@router.get("/project-positions/catalog")
def get_project_position_catalog(
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    return ok(
        [
            {
                "name": item.name,
                "code": item.code,
                "category": item.category,
                "management_account": item.name == PROJECT_MANAGER_POSITION_NAME,
            }
            for item in PROJECT_POSITION_DEFINITIONS
        ],
    )


@router.post("/projects")
def create_project(payload: ProjectInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_name = payload.name.strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="项目名称不能为空")
    values = payload.model_dump()
    values["name"] = project_name
    if values.get("contract_start_date") and values.get("contract_end_date") and values["contract_end_date"] < values["contract_start_date"]:
        raise HTTPException(status_code=422, detail="合同结束日期不能早于开始日期")
    project = Project(**values)
    db.add(project); db.flush()
    audit(db, user, "创建项目", f"创建项目「{project.name}」", project.id, "project", project.id)
    db.commit(); db.refresh(project)
    return ok(serialize(project), "项目已创建")


@router.patch("/projects/{project_id}")
def update_project(project_id: int, payload: ProjectInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    project_name = payload.name.strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="项目名称不能为空")
    values = payload.model_dump(exclude_unset=True)
    values["name"] = project_name
    contract_start_date = values.get("contract_start_date", project.contract_start_date)
    contract_end_date = values.get("contract_end_date", project.contract_end_date)
    if contract_start_date and contract_end_date and contract_end_date < contract_start_date:
        raise HTTPException(status_code=422, detail="合同结束日期不能早于开始日期")
    for key, value in values.items():
        setattr(project, key, value)
    audit(db, user, "更新项目", f"更新项目「{project.name}」", project.id, "project", project.id)
    db.commit(); db.refresh(project)
    return ok(serialize(project), "项目已更新")


@router.get("/projects/{project_id}/initialization-state")
def get_project_initialization_state(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    return ok(build_initialization_state(db, project))


def _initialization_draft_review(
    db: Session,
    draft: ProjectInitializationDraft,
) -> dict[str, Any]:
    data = serialize(draft)
    payload_model = compose_initialization_draft_payload(db, draft)
    payload = payload_model.model_dump(mode="json")
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


@router.get("/projects/{project_id}/initialization-drafts/latest")
def get_latest_project_initialization_draft(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    draft = db.scalar(
        select(ProjectInitializationDraft)
        .where(ProjectInitializationDraft.project_id == project_id)
        .order_by(ProjectInitializationDraft.updated_at.desc()),
    )
    return ok(_initialization_draft_review(db, draft) if draft else None)


@router.get("/projects/{project_id}/initialization-drafts/{draft_id}")
def get_project_initialization_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    draft = db.get(ProjectInitializationDraft, draft_id)
    if draft is None or draft.project_id != project_id:
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    return ok(_initialization_draft_review(db, draft))


@router.post("/projects/{project_id}/initialization-drafts/{draft_id}/apply")
def apply_project_initialization_draft(
    project_id: int,
    draft_id: int,
    payload: ApplyInitializationDraftInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    draft = db.get(ProjectInitializationDraft, draft_id)
    if draft is None or draft.project_id != project_id:
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    try:
        result = apply_initialization_draft(db, draft, payload)
        from .business_learning_sources import record_initialization_applied
        record_initialization_applied(db, draft, user.id, result)
        audit(
            db,
            user,
            "确认项目初始化草稿",
            f"确认初始化草稿第 {draft.revision} 版并写入项目",
            project.id,
            "project_initialization_draft",
            draft.id,
        )
        db.commit()
        db.refresh(draft)
    except InitializationApplyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "issues": exc.issues},
        ) from exc
    return ok(
        {
            "draft": serialize(draft),
            "result": result,
            "initialization_state": build_initialization_state(db, project),
        },
        "项目初始化数据已确认入库",
    )


@router.post("/projects/{project_id}/initialization-drafts/{draft_id}/validate")
def validate_project_initialization_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    draft = db.get(ProjectInitializationDraft, draft_id)
    if draft is None or draft.project_id != project_id:
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    try:
        result = run_project_initialization_validation(db, draft)
        audit(
            db,
            user,
            "重新核验项目初始化草稿",
            f"使用版本化 MCP 重新核验初始化草稿第 {draft.revision} 版",
            project.id,
            "project_initialization_draft",
            draft.id,
        )
        db.commit()
    except InitializationValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ok(result, "项目初始化草稿核验完成")


@router.get("/projects/{project_id}/settings")
def get_project_settings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = db.get(ProjectSettings, project_id)
    return ok(serialize(row) if row else {"project_id": project_id, "main_dir": "", "archive_dir": "", "temp_dir": "", "failed_dir": "", "backup_dir": "", "scan_interval": 30, "enabled": False, "reminder_rules": [], "weknora_agent_id": None})


@router.put("/projects/{project_id}/settings")
def save_project_settings(project_id: int, payload: ProjectSettingsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = db.get(ProjectSettings, project_id)
    if not row:
        row = ProjectSettings(project_id=project_id)
        db.add(row)
    values = payload.model_dump()
    for key, value in values.items():
        setattr(row, key, value)
    db.flush()
    audit(
        db,
        user,
        "更新项目资料配置",
        "更新资料来源及预警规则",
        project_id,
        "project_settings",
        project_id,
    )
    db.commit()
    db.refresh(row)
    return ok(serialize(row), "项目资料配置已保存")


@router.get("/projects/{project_id}/connectors")
def list_project_connectors(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    rows = db.scalars(
        select(ProjectConnectorConfig)
        .where(ProjectConnectorConfig.project_id == project_id)
        .order_by(ProjectConnectorConfig.id),
    ).all()
    return ok([project_connector_view(row) for row in rows])


@router.put("/projects/{project_id}/connectors/{connector_type}")
def save_project_connector(
    project_id: int,
    connector_type: ProjectConnectorType,
    payload: ProjectConnectorConfigInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    row = db.scalar(
        select(ProjectConnectorConfig).where(
            ProjectConnectorConfig.project_id == project_id,
            ProjectConnectorConfig.connector_type == connector_type,
        ),
    )
    is_new = row is None
    if is_new:
        row = ProjectConnectorConfig(
            project_id=project_id,
            connector_type=connector_type,
            connection_id=payload.connection_id.strip(),
        )
        db.add(row)
    assert row is not None

    connection_id = payload.connection_id.strip()
    provided_secret = (payload.secret or "").strip()
    if connector_type == "wecom":
        legacy_webhook = connection_id if is_wecom_webhook_url(connection_id) else ""
        if legacy_webhook:
            connection_id = "项目群机器人"
        secret = provided_secret or legacy_webhook
        if not secret and not row.secret_encrypted and is_wecom_webhook_url(row.connection_id):
            secret = row.connection_id
        if secret:
            try:
                secret = validate_wecom_webhook_url(secret)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            row.secret_encrypted = encrypt_connector_secret(secret)
        if not row.secret_encrypted:
            raise HTTPException(
                status_code=422,
                detail="请填写企业微信群机器人 Webhook",
            )
        row.connection_id = connection_id or "项目群机器人"
        row.configured = True
    else:
        row.connection_id = connection_id
        if provided_secret:
            row.secret_encrypted = encrypt_connector_secret(provided_secret)
        row.configured = True
    db.flush()
    audit(
        db,
        user,
        "保存项目连接配置",
        f"保存项目{connector_type}连接配置",
        project_id,
        "project_connector_config",
        row.id,
    )
    db.commit()
    db.refresh(row)
    return ok(project_connector_view(row), "项目连接配置已保存")


@router.post("/projects/{project_id}/connectors/wecom/test")
def test_project_wecom_connector(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """由管理员主动向当前项目群发送一条无 @ 人员的连接测试消息。"""

    project_for_user_or_403(db, project_id, user)
    try:
        result = send_project_wecom_test(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (httpx.HTTPError, WeComDeliveryError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"企业微信测试消息发送失败：{safe_wecom_error(exc)}",
        ) from exc
    audit(
        db,
        user,
        "测试企业微信连接",
        "向当前项目群发送企业微信机器人测试消息",
        project_id,
        "project_connector_config",
        None,
    )
    db.commit()
    return ok(result, "企业微信测试消息已发送")


@router.delete("/projects/{project_id}/connectors/{connector_type}")
def delete_project_connector(
    project_id: int,
    connector_type: ProjectConnectorType,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    row = db.scalar(
        select(ProjectConnectorConfig).where(
            ProjectConnectorConfig.project_id == project_id,
            ProjectConnectorConfig.connector_type == connector_type,
        ),
    )
    if row is None:
        return ok(None, "项目连接配置已清除")
    row_id = row.id
    db.delete(row)
    audit(
        db,
        user,
        "清除项目连接配置",
        f"清除项目{connector_type}连接配置",
        project_id,
        "project_connector_config",
        row_id,
    )
    db.commit()
    return ok(None, "项目连接配置已清除")


def refresh_project_notifications(project_id: int, db: Session) -> None:
    overdue = [
        task
        for task in get_engine().list_tasks(state="overdue", limit=500)
        if task.scope.get("project_id") == project_id
    ]
    waiting_dailies = db.scalars(select(DailyReport).where(DailyReport.project_id == project_id, DailyReport.status == "pending_confirm")).all()
    for task in overdue:
        exists = db.scalar(select(Notification).where(Notification.project_id == project_id, Notification.source_type == "task", Notification.source_id == 0, Notification.notification_type == "overdue", Notification.content == task.title))
        if not exists: db.add(Notification(project_id=project_id, notification_type="overdue", title="任务已逾期", content=task.title, priority="high", source_type="task", source_id=0))
    for report in waiting_dailies:
        exists = db.scalar(select(Notification).where(Notification.project_id == project_id, Notification.source_type == "daily_report", Notification.source_id == report.id, Notification.notification_type == "daily_confirm"))
        if not exists: db.add(Notification(project_id=project_id, notification_type="daily_confirm", title="日报待确认", content=report.file_name, priority="normal", source_type="daily_report", source_id=report.id))
    db.commit()


PROJECT_STATUS_BASE_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "项目名称"),
    ("engineering_type_description", "工程类型"),
    ("contract_start_date", "合同开工日期"),
    ("contract_end_date", "合同竣工日期"),
    ("contract_duration_days", "合同工期"),
    ("contract_amount_wan_yuan", "合同金额"),
    ("construction_unit_name", "建设单位"),
    ("general_contractor_unit_name", "施工总承包单位"),
    ("supervision_unit_name", "监理单位"),
    ("design_unit_name", "设计单位"),
    ("survey_unit_name", "勘察单位"),
)

PROJECT_STATUS_HIGH_RISK_LEVELS = {
    "critical",
    "high",
    "重大",
    "重大风险",
    "较大",
    "较大风险",
    "一级",
    "二级",
}


def _project_status_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _project_status_folder_count(folders: list[dict[str, Any]] | None) -> int:
    return sum(
        1 + _project_status_folder_count(folder.get("children") or [])
        for folder in folders or []
    )


@router.get("/projects/{project_id}/status-overview")
def project_status_overview(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """汇总项目现有页面已经维护的数据，不生成新的业务判断。"""
    project = project_for_user_or_403(db, project_id, user)

    missing_fields = [
        label
        for field, label in PROJECT_STATUS_BASE_FIELDS
        if not _project_status_value_present(getattr(project, field))
    ]
    completed_fields = len(PROJECT_STATUS_BASE_FIELDS) - len(missing_fields)

    wbs_rows = list(
        db.scalars(
            select(WbsItem)
            .where(WbsItem.project_id == project_id)
            .order_by(WbsItem.sort_order, WbsItem.id),
        ).all(),
    )
    parent_ids = {row.parent_id for row in wbs_rows if row.parent_id is not None}
    leaf_rows = [row for row in wbs_rows if row.id not in parent_ids]
    progress_rate = (
        round(
            sum(float(row.progress_percent or 0) for row in leaf_rows)
            / len(leaf_rows),
        )
        if leaf_rows
        else None
    )

    task_counts = {
        "pending": 0,
        "processing": 0,
        "waiting_confirm": 0,
        "overdue": 0,
    }
    for task in project_status_tasks(get_engine(), project_id):
        if _to_int((task.scope or {}).get("project_id")) != project_id:
            continue
        row = to_api_task(task)
        if row["task_type"] == "automation":
            continue
        if row["status"] in {"done", "completed", "cancelled"}:
            continue
        status_value = row["status"]
        if status_value == "pending_confirm":
            status_value = "waiting_confirm"
        elif status_value == "need_more_info":
            status_value = "pending"
        if status_value in task_counts:
            task_counts[status_value] += 1

    risks = list(
        db.scalars(
            select(RiskSource)
            .where(RiskSource.project_id == project_id)
            .order_by(RiskSource.serial_no, RiskSource.id),
        ).all(),
    )
    high_risk_count = sum(
        1
        for risk in risks
        if risk.risk_level.strip().lower() in PROJECT_STATUS_HIGH_RISK_LEVELS
    )
    quality_requirements = list(
        db.scalars(
            select(QualityMetric).where(QualityMetric.project_id == project_id),
        ).all(),
    )

    workspace = local_workspace_view(db, project_id, user)
    document_total = 0
    document_folder_count = 0
    knowledge_bases: list[dict[str, Any]] = []
    recent_files: list[dict[str, Any]] = []
    for knowledge_base in workspace["knowledge_bases"]:
        folder_tree = local_folder_tree_view(
            db,
            project_id,
            knowledge_base["id"],
            user,
        )
        total_document_count = int(folder_tree.get("total_document_count") or 0)
        folder_count = _project_status_folder_count(folder_tree.get("folders"))
        document_total += total_document_count
        document_folder_count += folder_count
        knowledge_bases.append({
            "id": knowledge_base["id"],
            "name": knowledge_base["name"],
            "folder_count": folder_count,
            "total_document_count": total_document_count,
        })
        knowledge_page = local_knowledge_page(
            db,
            project_id,
            knowledge_base["id"],
            user,
            page=1,
            page_size=5,
            folder_path=None,
            folder_recursive=True,
            keyword="",
        )
        recent_files.extend({
            "id": str(file_row.get("id") or file_row.get("node_id") or ""),
            "name": file_row.get("file_name") or file_row.get("title") or "未命名资料",
            "file_type": file_row.get("file_type") or "",
            "file_size": int(file_row.get("file_size") or 0),
            "folder_path": file_row.get("folder_path") or "",
            "created_at": file_row.get("created_at"),
            "knowledge_base_id": knowledge_base["id"],
            "knowledge_base_name": knowledge_base["name"],
        } for file_row in knowledge_page["knowledge"])
    recent_files.sort(
        key=lambda file_row: str(file_row.get("created_at") or ""),
        reverse=True,
    )
    details = meeting_status_details(db, project_id, user, risks, quality_requirements)
    member_count = int(
        db.scalar(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.project_id == project_id,
            ),
        )
        or 0,
    )

    return ok({
        "base_info": {
            "completed_fields": completed_fields,
            "total_fields": len(PROJECT_STATUS_BASE_FIELDS),
            "missing_fields": missing_fields,
        },
        "wbs": {
            "configured": bool(wbs_rows),
            "total_items": len(wbs_rows),
            "leaf_items": len(leaf_rows),
            "progress_rate": progress_rate,
        },
        "tasks": {
            "total": sum(task_counts.values()),
            **task_counts,
        },
        "risks": {
            "configured": bool(risks),
            "total": len(risks),
            "high_level_count": high_risk_count,
        },
        "quality": {
            "configured": bool(quality_requirements),
            "total": len(quality_requirements),
        },
        "safety": details["safety"],
        "documents": {
            **details["documents"],
            "total_files": document_total,
            "folder_count": document_folder_count,
            "knowledge_base_count": len(knowledge_bases),
            "knowledge_bases": knowledge_bases,
            "recent_files": recent_files[:5],
        },
        "members": {"total": member_count},
    })


@router.get("/projects/{project_id}/dashboard")
def project_dashboard(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user); refresh_project_notifications(project_id, db)
    wbs = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)).all()
    tasks = [
        task
        for task in get_engine().list_tasks(limit=500)
        if task.scope.get("project_id") == project_id
    ]
    risks = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id)).all()
    metrics = db.scalars(select(QualityMetric).where(QualityMetric.project_id == project_id)).all()
    changes = db.scalars(select(ProjectChange).where(ProjectChange.project_id == project_id, ProjectChange.status != "closed")).all()
    notifications = db.scalars(select(Notification).where(Notification.project_id == project_id, Notification.is_read.is_(False))).all()
    snapshot = db.get(ProjectStatusSnapshot, project_id)
    if snapshot:
        return ok({"progress_rate": snapshot.progress_rate, "progress_status": snapshot.progress_status, "planned_delta": snapshot.planned_delta,
                   "risk_warnings": snapshot.risk_warnings, "safety_issues": snapshot.safety_issues, "quality_issues": snapshot.quality_issues,
                   "task_completion_rate": snapshot.task_completion_rate, "open_changes": len(changes), "unread_notifications": len(notifications),
                   "main_risk": snapshot.main_risk, "main_safety": snapshot.main_safety, "main_quality": snapshot.main_quality, "overall": snapshot.overall})
    done = sum(1 for task in tasks if str(task.state) == "done")
    parent_ids = {item.parent_id for item in wbs if item.parent_id is not None}
    progress_items = [item for item in wbs if item.id not in parent_ids] or wbs
    progress_rate = (
        round(
            sum(float(item.progress_percent or 0) for item in progress_items)
            / len(progress_items),
        )
        if progress_items
        else 0
    )
    high_levels = {
        "critical",
        "high",
        "重大",
        "重大风险",
        "较大",
        "较大风险",
        "一级",
        "二级",
    }

    def is_high_risk(risk: RiskSource) -> bool:
        return risk.risk_level.strip().lower() in high_levels

    def is_safety_risk(risk: RiskSource) -> bool:
        content = " ".join(
            filter(
                None,
                (
                    risk.related_process_name,
                    risk.risk_part,
                    risk.summary,
                    risk.evaluation_condition,
                ),
            ),
        )
        return "安全" in content or "隐患" in content

    high_risks = [risk for risk in risks if is_high_risk(risk)]
    safety_risks = [risk for risk in risks if is_safety_risk(risk)]
    pending_quality = [
        metric
        for metric in metrics
        if metric.status not in {"passed", "completed", "合格", "已完成"}
    ]
    return ok({
        "progress_rate": progress_rate,
        "progress_status": "正常",
        "planned_delta": "基本一致",
        "risk_warnings": len(high_risks),
        "safety_issues": len(safety_risks),
        "quality_issues": len(pending_quality),
        "task_completion_rate": round(done * 100 / len(tasks)) if tasks else 0,
        "open_changes": len(changes),
        "unread_notifications": len(notifications),
        "main_risk": high_risks[0].risk_part if high_risks else "暂无重大风险",
        "main_safety": safety_risks[0].risk_part if safety_risks else "暂无新增安全隐患",
        "main_quality": pending_quality[0].quality_acceptance_item if pending_quality else "暂无待核查质量项",
        "overall": "项目整体状态待核对",
    })


@router.get("/projects/{project_id}/information-records")
def list_information_records(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = db.scalars(select(ProjectInformationRecord).where(ProjectInformationRecord.project_id == project_id).order_by(ProjectInformationRecord.recorded_at.desc(), ProjectInformationRecord.id.desc())).all()
    return ok([serialize(row) for row in rows])


@router.post("/information-records/{record_id}/dispose")
def dispose_information_record(record_id: int, payload: ProjectInformationDispositionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, ProjectInformationRecord, record_id, "信息记录不存在")
    action_status = {"confirm": "已确认", "deny": "已否认", "revise": "已修订"}
    if payload.action == "revise" and not (payload.content or "").strip():
        raise HTTPException(status_code=422, detail="修订信息不能为空")
    row.status = action_status[payload.action]
    if payload.action == "revise":
        row.content = payload.content.strip()
    audit(db, user, f"信息{action_status[payload.action]}", f"处置项目最新信息「{row.source_name}」", row.project_id, "project_information_record", row.id)
    db.commit(); db.refresh(row)
    return ok(serialize(row), f"信息已{action_status[payload.action]}")


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
    members = db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.id),
    ).all()
    return ok([serialize_project_member(db, member) for member in members])


def serialize_project_member(db: Session, member: ProjectMember) -> dict[str, Any]:
    user = entity_or_404(db, User, member.user_id, "用户不存在")
    assignments = db.execute(
        select(ProjectMemberPosition, ProjectPosition)
        .join(
            ProjectPosition,
            ProjectPosition.id == ProjectMemberPosition.position_id,
        )
        .where(ProjectMemberPosition.project_member_id == member.id)
        .order_by(ProjectMemberPosition.serial_no),
    ).all()
    return {
        **serialize(member),
        "user": serialize(user),
        "positions": [
            {
                **serialize(assignment),
                "position_name": position.position_name,
            }
            for assignment, position in assignments
        ],
    }


@router.post("/projects/{project_id}/members")
def add_member(project_id: int, payload: MemberInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    try:
        position_name = require_supported_project_position(payload.position_name)
    except UnsupportedProjectPositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    account = db.scalar(
        select(User).where(User.identity_card_no == payload.identity_card_no),
    )
    if account is None:
        username = payload.username or suggest_unique_username(
            payload.real_name,
            payload.identity_card_no,
            set(db.scalars(select(User.username)).all()),
        )
        owner = db.scalar(select(User).where(User.username == username))
        if owner is not None:
            raise HTTPException(status_code=409, detail="登录账号已被其他人员使用")
        if not payload.password:
            raise HTTPException(status_code=422, detail="新人员必须设置初始密码")
        account = User(
            username=username,
            password_hash=hash_password(payload.password),
            real_name=payload.real_name,
            identity_card_no=payload.identity_card_no,
            role="user",
        )
        db.add(account)
        db.flush()

    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == account.id,
        ),
    )
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=account.id)
        db.add(member)
        db.flush()

    position = db.scalar(
        select(ProjectPosition).where(
            ProjectPosition.project_id == project_id,
            ProjectPosition.position_name == position_name,
        ),
    )
    if position is None:
        position = ProjectPosition(
            project_id=project_id,
            position_name=position_name,
        )
        db.add(position)
        db.flush()
    if db.scalar(
        select(ProjectMemberPosition.id).where(
            ProjectMemberPosition.project_member_id == member.id,
            ProjectMemberPosition.position_id == position.id,
        ),
    ) is not None:
        raise HTTPException(status_code=409, detail="该人员已经承担此岗位")
    next_serial = (
        db.scalar(
            select(func.max(ProjectMemberPosition.serial_no)).where(
                ProjectMemberPosition.project_id == project_id,
            ),
        )
        or 0
    ) + 1
    assignment = ProjectMemberPosition(
        project_id=project_id,
        project_member_id=member.id,
        position_id=position.id,
        serial_no=next_serial,
        certificate_no=payload.certificate_no,
        responsibility_description=payload.responsibility_description,
    )
    db.add(assignment)
    db.flush()
    reconcile_user_management_role(db, account)
    reconcile_name_based_catalogue_permissions(db, project_id)
    audit(
        db,
        user,
        "添加项目成员岗位",
        f"为「{payload.real_name}」添加岗位「{position_name}」",
        project_id,
        "project_member_position",
        assignment.id,
    )
    db.commit()
    db.refresh(member)
    return ok(serialize_project_member(db, member), "成员岗位已添加")


@router.patch("/projects/{project_id}/member-positions/{assignment_id}")
def update_member_position(
    project_id: int,
    assignment_id: int,
    payload: MemberInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_or_404(db, project_id)
    try:
        position_name = require_supported_project_position(payload.position_name)
    except UnsupportedProjectPositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assignment = db.scalar(
        select(ProjectMemberPosition).where(
            ProjectMemberPosition.id == assignment_id,
            ProjectMemberPosition.project_id == project_id,
        ),
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="项目岗位任职不存在")
    member = entity_or_404(
        db,
        ProjectMember,
        assignment.project_member_id,
        "项目成员不存在",
    )
    account = entity_or_404(db, User, member.user_id, "用户不存在")
    if payload.identity_card_no != account.identity_card_no:
        raise HTTPException(status_code=409, detail="不能通过项目岗位修改人员身份证号")
    position = db.scalar(
        select(ProjectPosition).where(
            ProjectPosition.project_id == project_id,
            ProjectPosition.position_name == position_name,
        ),
    )
    if position is None:
        position = ProjectPosition(
            project_id=project_id,
            position_name=position_name,
        )
        db.add(position)
        db.flush()
    duplicate = db.scalar(
        select(ProjectMemberPosition.id).where(
            ProjectMemberPosition.project_member_id == member.id,
            ProjectMemberPosition.position_id == position.id,
            ProjectMemberPosition.id != assignment.id,
        ),
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="该人员已经承担此岗位")
    assignment.position_id = position.id
    assignment.certificate_no = payload.certificate_no
    assignment.responsibility_description = payload.responsibility_description
    db.flush()
    reconcile_user_management_role(db, account)
    reconcile_name_based_catalogue_permissions(db, project_id)
    audit(
        db,
        user,
        "更新项目成员岗位",
        f"更新「{payload.real_name}」的岗位「{position_name}」",
        project_id,
        "project_member_position",
        assignment.id,
    )
    db.commit()
    db.refresh(member)
    return ok(serialize_project_member(db, member), "成员岗位已更新")


def list_for_project(model: type[ModelType], project_id: int, db: Session) -> list[dict[str, Any]]:
    project_or_404(db, project_id)
    return [serialize(row) for row in db.scalars(select(model).where(model.project_id == project_id).order_by(model.id.desc())).all()]


def serialize_project_wbs(db: Session, project_id: int) -> list[dict[str, Any]]:
    """Return the normalized WBS tree together with lightweight legacy aliases."""
    project_or_404(db, project_id)
    rows = db.scalars(
        select(WbsItem)
        .where(WbsItem.project_id == project_id)
        .order_by(WbsItem.sort_order, WbsItem.id),
    ).all()
    row_by_id = {row.id: row for row in rows}
    predecessor_ids: dict[int, list[int]] = {row.id: [] for row in rows}
    if row_by_id:
        links = db.scalars(
            select(WbsPredecessor)
            .where(WbsPredecessor.wbs_item_id.in_(row_by_id))
            .order_by(WbsPredecessor.id),
        ).all()
        for link in links:
            if link.predecessor_wbs_item_id in row_by_id:
                predecessor_ids.setdefault(link.wbs_item_id, []).append(
                    link.predecessor_wbs_item_id,
                )

    result: list[dict[str, Any]] = []
    for row in rows:
        predecessors = predecessor_ids.get(row.id, [])
        result.append({
            **serialize(row),
            # These aliases keep older workbench consumers functional while the
            # formal-data view uses the normalized field names above.
            "code": row.wbs_code,
            "planned_start": row.planned_start_at.isoformat() if row.planned_start_at else None,
            "planned_finish": row.planned_finish_at.isoformat() if row.planned_finish_at else None,
            "progress": float(row.progress_percent or 0),
            "status": row.status_text,
            "responsible_user_id": row.responsible_user_id,
            "raw_data": row.raw_data or {},
            "predecessor_ids": predecessors,
            "predecessor_codes": [row_by_id[item_id].wbs_code for item_id in predecessors],
        })
    return result


def serialize_project_risks(db: Session, project_id: int) -> list[dict[str, Any]]:
    project_or_404(db, project_id)
    rows = db.scalars(
        select(RiskSource)
        .where(RiskSource.project_id == project_id)
        .order_by(RiskSource.serial_no, RiskSource.id),
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append({
            **serialize(row),
            "name": row.risk_part,
            "level": row.risk_level,
            "risk_type": row.related_process_name,
            "planned_start": row.risk_window_start_date.isoformat() if row.risk_window_start_date else None,
            "planned_finish": row.risk_window_end_date.isoformat() if row.risk_window_end_date else None,
            "responsible_user_id": row.responsible_user_id,
            "confirmer_user_id": row.confirmer_user_id,
            "material_requirements": row.material_requirements or [],
            "control_requirements": row.evaluation_condition,
            "status": row.status,
        })
    return result


def serialize_project_quality_metrics(db: Session, project_id: int) -> list[dict[str, Any]]:
    project_or_404(db, project_id)
    wbs_rows = db.scalars(
        select(WbsItem)
        .where(WbsItem.project_id == project_id)
        .order_by(WbsItem.sort_order, WbsItem.id),
    ).all()
    wbs_by_code = {row.wbs_code: row for row in wbs_rows}
    quality_by_code = {
        row.wbs_code: row
        for row in db.scalars(
            select(QualityMetric).where(QualityMetric.project_id == project_id),
        ).all()
    }
    result: list[dict[str, Any]] = []
    for code, wbs in wbs_by_code.items():
        row = quality_by_code.get(code)
        if row is None:
            continue
        result.append({
            **serialize(row),
            "wbs_item_id": wbs.id,
            "wbs_name": wbs.name,
            "name": row.quality_acceptance_item,
            "requirement": row.control_indicator,
            "required_materials": row.required_materials or [],
            "owner_user_id": row.owner_user_id,
            "status": row.status,
        })
    return result


def parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name}格式不正确") from exc


def parse_optional_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name}格式不正确") from exc


def normalized_risk_level_text(value: str) -> str:
    return {
        "critical": "重大",
        "high": "较大",
        "medium": "一般",
        "low": "低",
    }.get(value, value)


def validate_risk_window(start: date | None, finish: date | None) -> None:
    if start and finish and finish < start:
        raise HTTPException(status_code=422, detail="风险结束日期不能早于开始日期")


def validate_wbs_schedule(
    planned_start: datetime | None,
    planned_finish: datetime | None,
) -> None:
    if planned_start and planned_finish and planned_finish < planned_start:
        raise HTTPException(status_code=422, detail="计划完成时间不能早于计划开始时间")


def validate_wbs_parent(
    db: Session,
    project_id: int,
    parent_id: int | None,
    current_item_id: int | None = None,
) -> WbsItem | None:
    if parent_id is None:
        return None
    parent = db.scalar(
        select(WbsItem).where(
            WbsItem.id == parent_id,
            WbsItem.project_id == project_id,
        ),
    )
    if parent is None:
        raise HTTPException(status_code=404, detail="上级WBS工序不存在")
    visited: set[int] = set()
    cursor: WbsItem | None = parent
    while cursor is not None and cursor.id not in visited:
        if current_item_id is not None and cursor.id == current_item_id:
            raise HTTPException(status_code=422, detail="不能把当前工序或其下级设为上级工序")
        visited.add(cursor.id)
        cursor = db.get(WbsItem, cursor.parent_id) if cursor.parent_id else None
    return parent


def replace_wbs_predecessors(
    db: Session,
    item: WbsItem,
    predecessor_ids: list[int],
) -> None:
    normalized_ids = list(dict.fromkeys(predecessor_ids))
    if item.id in normalized_ids:
        raise HTTPException(status_code=422, detail="WBS工序不能以自身作为前置工序")
    predecessors = db.scalars(
        select(WbsItem).where(
            WbsItem.project_id == item.project_id,
            WbsItem.id.in_(normalized_ids),
        ),
    ).all() if normalized_ids else []
    if len(predecessors) != len(normalized_ids):
        raise HTTPException(status_code=404, detail="部分前置WBS工序不存在")
    project_item_ids = set(db.scalars(
        select(WbsItem.id).where(WbsItem.project_id == item.project_id),
    ).all())
    dependency_graph: dict[int, list[int]] = {item_id: [] for item_id in project_item_ids}
    if project_item_ids:
        links = db.scalars(
            select(WbsPredecessor).where(WbsPredecessor.wbs_item_id.in_(project_item_ids)),
        ).all()
        for link in links:
            if link.wbs_item_id != item.id and link.predecessor_wbs_item_id in project_item_ids:
                dependency_graph[link.wbs_item_id].append(link.predecessor_wbs_item_id)

    def reaches_current(start_id: int) -> bool:
        pending = [start_id]
        visited: set[int] = set()
        while pending:
            candidate = pending.pop()
            if candidate == item.id:
                return True
            if candidate in visited:
                continue
            visited.add(candidate)
            pending.extend(dependency_graph.get(candidate, []))
        return False

    if any(reaches_current(predecessor_id) for predecessor_id in normalized_ids):
        raise HTTPException(status_code=422, detail="前置工序关系不能形成循环")
    existing = db.scalars(
        select(WbsPredecessor).where(WbsPredecessor.wbs_item_id == item.id),
    ).all()
    for link in existing:
        db.delete(link)
    if existing:
        db.flush()
    for predecessor_id in normalized_ids:
        db.add(WbsPredecessor(
            wbs_item_id=item.id,
            predecessor_wbs_item_id=predecessor_id,
        ))


@router.get("/projects/{project_id}/wbs")
def list_wbs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(serialize_project_wbs(db, project_id))


@router.post("/projects/{project_id}/wbs")
def create_wbs(project_id: int, payload: WbsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    validate_wbs_parent(db, project_id, payload.parent_id)
    planned_start = parse_optional_datetime(payload.planned_start, "计划开始时间")
    planned_finish = parse_optional_datetime(payload.planned_finish, "计划完成时间")
    validate_wbs_schedule(planned_start, planned_finish)
    next_sort_order = payload.sort_order
    if next_sort_order is None:
        next_sort_order = (
            db.scalar(select(func.max(WbsItem.sort_order)).where(WbsItem.project_id == project_id))
            or 0
        ) + 1
    responsible = db.get(User, payload.responsible_user_id) if payload.responsible_user_id else None
    item = WbsItem(
        project_id=project_id,
        parent_id=payload.parent_id,
        sort_order=next_sort_order,
        color_value=payload.color_value or None,
        wbs_code=payload.code,
        name=payload.name,
        assigned_to_text=responsible.real_name if responsible else payload.assigned_to_text or None,
        responsible_user_id=payload.responsible_user_id,
        planned_start_at=planned_start,
        planned_finish_at=planned_finish,
        deadline_at=parse_optional_datetime(payload.deadline, "截止时间"),
        progress_percent=payload.progress,
        duration_hours=payload.duration_hours,
        estimated_hours=payload.estimated_hours,
        time_log_minutes=payload.time_log_minutes,
        status_text=payload.status,
        priority_text=payload.priority_text or None,
        description=payload.description or None,
        budget=payload.budget,
        actual_cost=payload.actual_cost,
        item_type=payload.item_type or "任务",
        raw_data=payload.raw_data,
        level=payload.level,
    )
    db.add(item); db.flush()
    replace_wbs_predecessors(db, item, payload.predecessor_ids or [])
    audit(db, user, "新增WBS工序", f"新增工序「{item.name}」", project_id, "wbs", item.id); db.commit(); db.refresh(item)
    row = next(row for row in serialize_project_wbs(db, project_id) if row["id"] == item.id)
    return ok(row, "WBS工序已添加")


@router.patch("/wbs/{item_id}")
def update_wbs(item_id: int, payload: WbsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, WbsItem, item_id, "WBS工序不存在")
    fields = payload.model_fields_set
    if "parent_id" in fields:
        validate_wbs_parent(db, item.project_id, payload.parent_id, item.id)
        item.parent_id = payload.parent_id
    if "code" in fields: item.wbs_code = payload.code
    if "name" in fields: item.name = payload.name
    if "level" in fields: item.level = payload.level
    if "sort_order" in fields and payload.sort_order is not None: item.sort_order = payload.sort_order
    if "color_value" in fields: item.color_value = payload.color_value or None
    if "assigned_to_text" in fields: item.assigned_to_text = payload.assigned_to_text or None
    if "planned_start" in fields: item.planned_start_at = parse_optional_datetime(payload.planned_start, "计划开始时间")
    if "planned_finish" in fields: item.planned_finish_at = parse_optional_datetime(payload.planned_finish, "计划完成时间")
    validate_wbs_schedule(item.planned_start_at, item.planned_finish_at)
    if "deadline" in fields: item.deadline_at = parse_optional_datetime(payload.deadline, "截止时间")
    if "progress" in fields: item.progress_percent = payload.progress
    if "duration_hours" in fields: item.duration_hours = payload.duration_hours
    if "estimated_hours" in fields: item.estimated_hours = payload.estimated_hours
    if "time_log_minutes" in fields: item.time_log_minutes = payload.time_log_minutes
    if "status" in fields: item.status_text = payload.status
    if "priority_text" in fields: item.priority_text = payload.priority_text or None
    if "description" in fields: item.description = payload.description or None
    if "budget" in fields: item.budget = payload.budget
    if "actual_cost" in fields: item.actual_cost = payload.actual_cost
    if "item_type" in fields: item.item_type = payload.item_type or None
    if "responsible_user_id" in fields:
        responsible = db.get(User, payload.responsible_user_id) if payload.responsible_user_id else None
        item.assigned_to_text = responsible.real_name if responsible else None
        item.responsible_user_id = payload.responsible_user_id
    if "raw_data" in fields: item.raw_data = payload.raw_data
    if "predecessor_ids" in fields:
        replace_wbs_predecessors(db, item, payload.predecessor_ids or [])
    audit(db, user, "更新WBS工序", f"更新工序「{item.name}」", item.project_id, "wbs", item.id); db.commit(); db.refresh(item)
    row = next(row for row in serialize_project_wbs(db, item.project_id) if row["id"] == item.id)
    return ok(row, "WBS工序已更新")


@router.get("/projects/{project_id}/risks")
def list_risks(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(serialize_project_risks(db, project_id))


@router.post("/projects/{project_id}/risks")
def create_risk(project_id: int, payload: RiskInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    next_serial = payload.serial_no
    if next_serial is None:
        next_serial = (
            db.scalar(select(func.max(RiskSource.serial_no)).where(RiskSource.project_id == project_id))
            or 0
        ) + 1
    elif db.scalar(select(RiskSource.id).where(RiskSource.project_id == project_id, RiskSource.serial_no == next_serial)):
        raise HTTPException(status_code=422, detail="风险序号已存在")
    risk_start = parse_optional_date(payload.planned_start, "风险开始日期")
    risk_finish = parse_optional_date(payload.planned_finish, "风险结束日期")
    validate_risk_window(risk_start, risk_finish)
    item = RiskSource(
        project_id=project_id,
        serial_no=next_serial,
        related_process_name=payload.risk_type,
        risk_part=payload.name,
        risk_level=normalized_risk_level_text(payload.level),
        evaluation_condition=payload.control_requirements or "",
        risk_window_start_date=risk_start,
        risk_window_end_date=risk_finish,
        summary=payload.summary if payload.summary is not None else "、".join(payload.material_requirements) or None,
        responsible_user_id=payload.responsible_user_id,
        confirmer_user_id=payload.confirmer_user_id,
        material_requirements=payload.material_requirements,
        status=payload.status,
    )
    db.add(item); db.flush()
    audit(db, user, "新增风险源", f"新增风险源「{item.risk_part}」", project_id, "risk", item.id); db.commit(); db.refresh(item)
    row = next(row for row in serialize_project_risks(db, project_id) if row["id"] == item.id)
    return ok(row, "风险源已添加")


@router.patch("/risks/{risk_id}")
def update_risk(risk_id: int, payload: RiskInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, RiskSource, risk_id, "风险源不存在")
    fields = payload.model_fields_set
    if "serial_no" in fields and payload.serial_no is not None:
        duplicate = db.scalar(
            select(RiskSource.id).where(
                RiskSource.project_id == item.project_id,
                RiskSource.serial_no == payload.serial_no,
                RiskSource.id != item.id,
            ),
        )
        if duplicate:
            raise HTTPException(status_code=422, detail="风险序号已存在")
        item.serial_no = payload.serial_no
    if "name" in fields: item.risk_part = payload.name
    if "level" in fields: item.risk_level = normalized_risk_level_text(payload.level)
    if "risk_type" in fields: item.related_process_name = payload.risk_type
    if "planned_start" in fields: item.risk_window_start_date = parse_optional_date(payload.planned_start, "风险开始日期")
    if "planned_finish" in fields: item.risk_window_end_date = parse_optional_date(payload.planned_finish, "风险结束日期")
    validate_risk_window(item.risk_window_start_date, item.risk_window_end_date)
    if "control_requirements" in fields: item.evaluation_condition = payload.control_requirements or ""
    if "summary" in fields: item.summary = payload.summary or None
    if "material_requirements" in fields:
        item.material_requirements = payload.material_requirements
        if "summary" not in fields:
            item.summary = "、".join(payload.material_requirements) or None
    if "responsible_user_id" in fields: item.responsible_user_id = payload.responsible_user_id
    if "confirmer_user_id" in fields: item.confirmer_user_id = payload.confirmer_user_id
    if "status" in fields: item.status = payload.status
    audit(db, user, "更新风险源", f"更新风险源「{item.risk_part}」", item.project_id, "risk", item.id); db.commit(); db.refresh(item)
    row = next(row for row in serialize_project_risks(db, item.project_id) if row["id"] == item.id)
    return ok(row, "风险源已更新")


@router.get("/projects/{project_id}/quality-metrics")
def list_quality_metrics(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(serialize_project_quality_metrics(db, project_id))


@router.post("/projects/{project_id}/quality-metrics")
def create_quality_metric(project_id: int, payload: QualityMetricInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if not payload.wbs_item_id:
        raise HTTPException(status_code=422, detail="质量要求必须关联WBS工序")
    wbs = db.scalar(
        select(WbsItem).where(
            WbsItem.id == payload.wbs_item_id,
            WbsItem.project_id == project_id,
        ),
    )
    if wbs is None:
        raise HTTPException(status_code=404, detail="WBS工序不存在")
    item = QualityMetric(
        project_id=project_id,
        wbs_code=wbs.wbs_code,
        quality_acceptance_item=payload.name,
        control_indicator=payload.requirement,
        inspection_frequency=payload.inspection_frequency or "",
        related_documents=payload.related_documents if payload.related_documents is not None else "、".join(payload.required_materials),
        required_materials=payload.required_materials,
        owner_user_id=payload.owner_user_id,
        status=payload.status,
    )
    db.add(item); db.flush()
    audit(db, user, "新增质量指标", f"新增质量指标「{item.quality_acceptance_item}」", project_id, "quality_metric", item.id); db.commit(); db.refresh(item)
    row = next(row for row in serialize_project_quality_metrics(db, project_id) if row["id"] == item.id)
    return ok(row, "质量指标已添加")


@router.patch("/quality-metrics/{metric_id}")
def update_quality_metric(metric_id: int, payload: QualityMetricInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, QualityMetric, metric_id, "质量指标不存在")
    fields = payload.model_fields_set
    if "wbs_item_id" in fields:
        if not payload.wbs_item_id:
            raise HTTPException(status_code=422, detail="质量要求必须关联WBS工序")
        wbs = db.scalar(
            select(WbsItem).where(
                WbsItem.id == payload.wbs_item_id,
                WbsItem.project_id == item.project_id,
            ),
        )
        if wbs is None:
            raise HTTPException(status_code=404, detail="WBS工序不存在")
        item.wbs_code = wbs.wbs_code
    if "name" in fields: item.quality_acceptance_item = payload.name
    if "requirement" in fields: item.control_indicator = payload.requirement
    if "inspection_frequency" in fields: item.inspection_frequency = payload.inspection_frequency or ""
    if "related_documents" in fields: item.related_documents = payload.related_documents or ""
    if "required_materials" in fields:
        item.required_materials = payload.required_materials
        if "related_documents" not in fields:
            item.related_documents = "、".join(payload.required_materials)
    if "owner_user_id" in fields: item.owner_user_id = payload.owner_user_id
    if "status" in fields: item.status = payload.status
    audit(db, user, "更新质量指标", f"更新质量指标「{item.quality_acceptance_item}」", item.project_id, "quality_metric", item.id); db.commit(); db.refresh(item)
    row = next(row for row in serialize_project_quality_metrics(db, item.project_id) if row["id"] == item.id)
    return ok(row, "质量指标已更新")


@router.get("/projects/{project_id}/platform-field-mappings")
def list_platform_mappings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(PlatformFieldMapping, project_id, db))


@router.post("/projects/{project_id}/platform-field-mappings")
def create_platform_mapping(project_id: int, payload: PlatformFieldMappingInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = PlatformFieldMapping(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增平台字段映射", f"新增「{item.platform_name}」字段映射", project_id, "platform_mapping", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "字段映射已添加")


@router.patch("/platform-field-mappings/{mapping_id}")
def update_platform_mapping(mapping_id: int, payload: PlatformFieldMappingInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, PlatformFieldMapping, mapping_id, "字段映射不存在")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    audit(db, user, "更新平台字段映射", f"更新「{item.platform_name}」字段映射", item.project_id, "platform_mapping", item.id)
    db.commit(); db.refresh(item)
    return ok(serialize(item), "字段映射已更新")


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
def list_tasks(
    project_id: int,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """读取项目任务；逾期判定由任务引擎 tick 主动完成。"""
    project_or_404(db, project_id)
    engine = get_engine()

    state = DOBBY_TO_ENGINE_STATE.get(status_filter) if status_filter else None
    tasks = engine.list_tasks(state=state, limit=200)
    tasks = [task for task in tasks if task.scope.get("project_id") == project_id]

    return ok([to_api_task(task) for task in tasks])


@router.get("/projects/{project_id}/tasks/pending-my-review")
def pending_my_review(
    project_id: int,
    engine: TaskEngine = Depends(get_engine),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """查询当前用户作为确认人的待验收任务。"""
    tasks = engine.list_tasks(
        confirmer=str(user.id),
        state="review",
        limit=50,
    )
    tasks = [task for task in tasks if task.scope.get("project_id") == project_id]
    return ok([to_api_task(task) for task in tasks])


@router.get("/projects/{project_id}/wbs/{wbs_item_id}/tasks")
def tasks_by_site(
    project_id: int,
    wbs_item_id: int,
    open_only: bool = True,
    engine: TaskEngine = Depends(get_engine),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """查询指定 WBS 工点上的任务。"""
    tasks = engine.list_tasks(
        site=str(wbs_item_id),
        open_only=open_only,
        limit=100,
    )
    tasks = [task for task in tasks if task.scope.get("project_id") == project_id]
    return ok([to_api_task(task) for task in tasks])


@router.get("/projects/{project_id}/tasks/archive")
def list_archived_tasks(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """合并引擎已闭环任务与旧表只读历史任务。"""
    engine = get_engine()

    closed = [
        task
        for task in engine.list_tasks(limit=500)
        if task.scope.get("project_id") == project_id
        and str(task.state) in ("done", "cancelled")
    ]
    result = [to_api_task(task) for task in closed]

    legacy = db.scalars(
        select(Task).where(
            Task.project_id == project_id,
            Task.status.in_(["completed", "cancelled"]),
        ),
    ).all()
    for row in legacy:
        item = serialize(row)
        item["id"] = f"legacy_{row.id}"
        result.append(item)

    result.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return ok(result)


@router.post("/projects/{project_id}/tasks/generate-flow")
async def generate_task_flow(
    project_id: int,
    payload: TaskFlowGenerateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """通过固定任务助手生成可由现有前端直接编辑的任务流。"""
    project = project_for_user_or_403(db, project_id, user)
    engine = get_engine()

    generator = get_generator()

    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id),
    ).all()
    assignees = [
        Assignee(
            ref=str(member.user_id),
            display_name=member_user.real_name or member_user.username,
        )
        for member, member_user in rows
    ]
    if all(assignee.ref != str(user.id) for assignee in assignees):
        # 管理员可能拥有项目访问权但不是 ProjectMember；“我”仍必须指向当前账号。
        assignees.append(
            Assignee(
                ref=str(user.id),
                display_name=user.real_name or user.username,
            ),
        )

    ensure_project_chat_channel(db, project_id, user)
    private_channel_ids = set(
        db.scalars(
            select(ChatChannelMember.channel_id).where(
                ChatChannelMember.user_id == user.id,
                ChatChannelMember.left_at.is_(None),
            ),
        ).all(),
    )
    chat_channels = [
        channel
        for channel in db.scalars(
            select(ChatChannel)
            .where(
                ChatChannel.project_id == project_id,
                ChatChannel.archived_at.is_(None),
            )
            .order_by(ChatChannel.id.asc()),
        ).all()
        if chat_auto_sync(channel) or channel.id in private_channel_ids
    ]
    channel_member_refs: dict[int, set[str]] = {
        channel.id: set() for channel in chat_channels
    }
    if chat_channels:
        membership_rows = db.execute(
            select(
                ChatChannelMember.channel_id,
                ChatChannelMember.user_id,
            ).where(
                ChatChannelMember.channel_id.in_(
                    [channel.id for channel in chat_channels],
                ),
                ChatChannelMember.left_at.is_(None),
            ),
        ).all()
        for channel_id, member_user_id in membership_rows:
            channel_member_refs[channel_id].add(str(member_user_id))
    project_member_refs = {assignee.ref for assignee in assignees}
    # ensure_project_chat_channel 可能创建群聊或补入当前管理员，需在等待模型前持久化。
    db.commit()

    wbs_items = db.scalars(
        select(WbsItem).where(WbsItem.project_id == project_id),
    ).all()
    risks = db.scalars(
        select(RiskSource).where(
            RiskSource.project_id == project_id,
            RiskSource.status == "active",
        ),
    ).all()

    generation_key = (project_id, payload.generation_id)
    _prune_cancelled_task_flow_generations()
    if _cancelled_task_flow_generations.pop(generation_key, None) is not None:
        raise HTTPException(status_code=409, detail="Dobby AI 生成已由用户停止")
    existing_generation = _active_task_flow_generations.get(generation_key)
    if existing_generation is not None and not existing_generation.done():
        raise HTTPException(status_code=409, detail="该 AI 生成请求正在处理中")

    generation_task = asyncio.create_task(
        generator.generate_async(
            payload.requirement,
            generation_id=payload.generation_id,
            now=engine.now(),
            assignees=assignees,
            context={
                "project": {"id": project.id, "name": project.name},
                "current_user": {
                    "ref": str(user.id),
                    "username": user.username,
                    "display_name": user.real_name or user.username,
                    "system_role": user.role,
                },
                "chat_channels": [
                    {
                        "ref": str(channel.id),
                        "title": channel.title,
                        "channel_type": channel.channel_type,
                        "member_refs": sorted(
                            channel_member_refs[channel.id]
                            if not chat_auto_sync(channel)
                            else project_member_refs,
                        ),
                    }
                    for channel in chat_channels
                ],
                "wbs_items": [
                    {"id": item.id, "code": item.wbs_code, "name": item.name}
                    for item in wbs_items
                ],
                "risk_sources": [
                    {
                        "id": risk.id,
                        "name": risk.risk_part,
                        "level": risk.risk_level,
                    }
                    for risk in risks
                ],
            },
        ),
        name=f"dobby-task-flow-{project_id}-{payload.generation_id}",
    )
    _active_task_flow_generations[generation_key] = generation_task

    try:
        flow = await generation_task
    except asyncio.CancelledError as exc:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise
        logger.info(
            "Dobby AI 任务流生成已由用户停止：project_id=%s generation_id=%s",
            project_id,
            payload.generation_id,
        )
        raise HTTPException(status_code=409, detail="Dobby AI 生成已由用户停止") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AIFlowGenerationError as exc:
        logger.exception("Dobby AI 任务流生成失败：project_id=%s", project_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if _active_task_flow_generations.get(generation_key) is generation_task:
            _active_task_flow_generations.pop(generation_key, None)

    if flow.origin != "ai":
        raise HTTPException(
            status_code=502,
            detail="Dobby AI 未返回 AI 生成结果，已拒绝使用替代结果",
        )

    trigger = flow.trigger
    first_at = trigger.first_at or engine.now()
    raw_step_actions = flow.scope.get("step_actions")
    step_actions = raw_step_actions if isinstance(raw_step_actions, dict) else {}
    generated_steps: list[dict[str, Any]] = []
    for index, step in enumerate(flow.steps):
        if not step.automated:
            generated_steps.append(
                {
                    "name": step.name,
                    "node_type": "manual",
                    "owner_user_id": (
                        _to_int(step.assignee.ref) if step.assignee else None
                    ),
                    "due_at": None,
                    "material": step.deliverable,
                },
            )
            continue

        raw_action = step_actions.get(str(index))
        if raw_action is None and flow.is_automation and index == 0:
            raw_action = flow.scope.get("action")
        if (
            not isinstance(raw_action, dict)
            or raw_action.get("type") != "project_chat_message"
        ):
            raise HTTPException(
                status_code=502,
                detail=f"Dobby AI 返回的第 {index + 1} 个自动节点缺少群聊动作",
            )
        try:
            action_view = {
                "type": "project_chat_message",
                "channel_id": int(raw_action["channel_id"]),
                "sender_agent_id": TASK_MESSAGE_AGENT_ID,
                "sender_agent_name": TASK_MESSAGE_AGENT_NAME,
                "mention_mode": str(raw_action.get("mention_mode") or "none"),
                "mentioned_user_ids": [
                    int(item)
                    for item in (raw_action.get("mentioned_user_ids") or [])
                ],
                "content": str(raw_action["content"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Dobby AI 返回的第 {index + 1} 个群聊动作格式不正确",
            ) from exc
        generated_steps.append(
            {
                "name": step.name,
                "node_type": "project_chat_message",
                "owner_user_id": None,
                "due_at": None,
                "material": "",
                "action": action_view,
            },
        )

    first_manual_assignee = next(
        (step.assignee for step in flow.steps if not step.automated and step.assignee),
        None,
    )
    pure_automation = bool(flow.steps) and all(step.automated for step in flow.steps)
    return ok(
        {
            "title": flow.title,
            "summary": flow.summary,
            "action_type": (
                "project_chat_message"
                if pure_automation and len(generated_steps) == 1
                else "responsibility_task"
            ),
            "task_type": (
                "automation"
                if pure_automation
                else flow.category
                if flow.category
                in {
                    "risk_alert",
                    "material_missing",
                    "daily_confirm",
                    "draft_review",
                    "fill_platform",
                }
                else "risk_alert"
            ),
            "risk_level": PRIORITY_TO_RISK.get(flow.priority, "medium"),
            "assignee_user_id": (
                _to_int(first_manual_assignee.ref)
                if first_manual_assignee
                else None
            ),
            "confirmer_user_id": _to_int(flow.confirmer.ref) if flow.confirmer else None,
            "wbs_item_id": _to_int(flow.site.ref) if flow.site else None,
            "risk_source_id": None,
            "run_mode": str(trigger.run_mode),
            "trigger_date": first_at.strftime("%Y-%m-%d"),
            "trigger_time": first_at.strftime("%H:%M"),
            "trigger_rule": trigger.describe(),
            "trigger_interval_value": trigger.interval_value,
            "trigger_interval_unit": str(trigger.interval_unit),
            "trigger_calendar_mode": str(trigger.calendar_mode) if trigger.calendar_mode else "weekdays",
            "trigger_weekdays": list(trigger.calendar_weekdays),
            "trigger_day_of_month": trigger.calendar_day,
            "trigger_end_mode": "until" if trigger.until else "count" if trigger.max_fires else "never",
            "trigger_until_date": trigger.until.strftime("%Y-%m-%d") if trigger.until else None,
            "trigger_max_fires": trigger.max_fires,
            "cc": "，".join(watcher.display_name for watcher in flow.watchers),
            "steps": generated_steps,
            "generated_by": "ai",
            "generation_origin_token": flow.scope.get('generation_origin_token'),
            "generation_id": payload.generation_id,
            "generation_note": flow.origin_note,
        },
        "任务流已生成",
    )


@router.post("/projects/{project_id}/tasks/generate-flow/{generation_id}/stop")
async def stop_task_flow_generation(
    project_id: int,
    generation_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """按用户指令取消正在等待模型响应的任务流生成请求。"""
    project_or_404(db, project_id)
    generation_key = (project_id, generation_id)
    generation_task = _active_task_flow_generations.get(generation_key)
    if generation_task is None or generation_task.done():
        # 停止请求可能比生成请求先到达另一个 HTTP 连接；短期保留标记，
        # 让随后进入的同一 generation_id 直接结束，而不是在页面停止后继续跑。
        _prune_cancelled_task_flow_generations()
        _cancelled_task_flow_generations[generation_key] = time.monotonic()
        return ok({"stopped": True}, "停止请求已接收")

    generation_task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await generation_task
    return ok({"stopped": True}, "Dobby AI 生成已停止")


@router.post("/projects/{project_id}/tasks")
def create_task(
    project_id: int,
    payload: TaskInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """立即布置任务，或登记由 tick 自动布置的单次/周期计划。"""
    project_for_user_or_403(db, project_id, user)
    from .task_engine_gateway import transaction_engine
    from .business_learning_sources import record_task_event, record_task_plan
    from .business_learning_policy import task_generation_policy
    engine = transaction_engine(db, get_engine())
    try:
        flow = build_flow(
            db,
            project_id,
            payload,
            actor_user_id=user.id,
        )
        if db.info.get('task_learning_source_channel_ids'):
            flow.scope['learning_source_channel_ids'] = list(db.info['task_learning_source_channel_ids'])
        generation_id = db.info.get('task_learning_generation_id')
        flow.scope['learning_policy'] = task_generation_policy(db,
            token=None if generation_id else payload.generation_origin_token, generation_id=generation_id,
            user_id=user.id,project_id=project_id)
        if db.info.get('task_learning_origin_policy') is not None:
            from .business_learning_policy import merge_learning_policies
            flow.scope['learning_policy'] = merge_learning_policies(flow.scope['learning_policy'],db.info['task_learning_origin_policy'])
        if payload.generation_id and not generation_id:
            if payload.generation_origin_token:
                from .business_learning_policy import resolve_generation_origin
                origin = resolve_generation_origin(db,payload.generation_origin_token,user_id=user.id,project_id=project_id)
                if origin.generation_id != payload.generation_id:
                    raise HTTPException(403,'任务生成标识与已签名来源不一致')
            else:
                # A generated draft whose binding was lost must never become an unrestricted manual source.
                flow.scope['learning_policy'] = {'allow_learning':False,'source_run_refs':[]}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.run_mode in {"once", "recurring", "scheduled", "calendar"}:
        try:
            flow.require_dispatchable()
            plan = engine.schedule(flow)
            record_task_plan(db, plan, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        audit(
            db,
            user,
            "登记周期任务" if flow.trigger.is_recurring else "登记定时单次任务",
            f"任务流「{flow.title}」：{flow.trigger.describe()}",
            project_id,
            "task_schedule",
            0,
        )
        db.commit()
        return ok(
            {
                "schedule_id": plan.id,
                "flow_id": flow.id,
                "title": flow.title,
                "trigger_description": flow.trigger.describe(),
                "next_fire_at": (
                    plan.next_fire_at.isoformat() if plan.next_fire_at else None
                ),
            },
            f"执行计划已登记：{flow.trigger.describe()}",
        )

    try:
        task = engine.dispatch(
            flow,
            actor=str(user.id),
            trigger_note=payload.trigger_reason or "手动布置",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if current_task_action(task) is not None:
        executions = execute_ready_automation_chain(db, engine, task)
        failed = next((item for item in executions if not item.ok), None)
        if failed is not None:
            raise HTTPException(
                status_code=502,
                detail=f"自动化动作执行失败：{failed.detail}",
            )
        task = engine.get_task(task.id) or task
    if str(task.state) not in {"done", "cancelled"}:
        enqueue_task_notification(
            db,
            task,
            "task_review" if str(task.state) == "review" else "task_created",
        )
    audit(
        db,
        user,
        "创建任务",
        f"创建任务「{task.title}」",
        project_id,
        "task",
        0,
    )
    record_task_event(db, task, user.id, 'task_published')
    db.commit()
    return ok(to_api_task(task), "任务已创建")


@router.get("/projects/{project_id}/task-schedules")
def list_task_schedules(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = [
        schedule_json(plan)
        for plan in get_engine().list_schedules()
        if int(plan.flow.scope.get("project_id") or 0) == project_id
    ]
    return ok(rows)


@router.post("/task-schedules/{schedule_id}/pause")
def pause_task_schedule(
    schedule_id: str,
    paused: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    plan = get_engine().get_schedule(schedule_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="执行计划不存在")
    project_id = int(plan.flow.scope.get("project_id") or 0)
    project_or_404(db, project_id)
    updated = get_engine().pause_schedule(schedule_id, paused=paused)
    audit(
        db,
        user,
        "暂停执行计划" if paused else "恢复执行计划",
        f"执行计划「{plan.flow.title}」",
        project_id,
        "task_schedule",
        0,
    )
    db.commit()
    return ok(schedule_json(updated), "执行计划已暂停" if paused else "执行计划已恢复")


@router.delete("/task-schedules/{schedule_id}")
def cancel_task_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    plan = get_engine().get_schedule(schedule_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="执行计划不存在")
    project_id = int(plan.flow.scope.get("project_id") or 0)
    project_or_404(db, project_id)
    get_engine().cancel_schedule(schedule_id)
    audit(
        db,
        user,
        "取消执行计划",
        f"执行计划「{plan.flow.title}」",
        project_id,
        "task_schedule",
        0,
    )
    db.commit()
    return ok({"schedule_id": schedule_id}, "执行计划已取消")


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    engine = get_engine()
    task = engine.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    data = to_api_task(task)
    data["history"] = to_api_history(task)
    return ok(data)


@router.post("/tasks/{task_id}/transition")
def transition_task(
    task_id: str,
    payload: TaskTransitionInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """只把验收、退回和取消交给引擎；其余状态由节点流转推导。"""
    from .task_engine_gateway import transaction_engine
    from .business_learning_sources import record_task_event
    engine = transaction_engine(db, get_engine())
    existing = engine.get_task(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    project_for_user_or_403(db, int(existing.scope.get('project_id') or 0), user)
    target = DOBBY_TO_ENGINE_STATE.get(payload.status, payload.status)

    try:
        if target == "done":
            task = engine.accept(
                task_id,
                actor=str(user.id),
                note=payload.note or "",
            )
        elif target == "cancelled":
            task = engine.cancel_task(
                task_id,
                actor=str(user.id),
                reason=payload.note or "",
            )
        elif target == "running":
            task = engine.reject(
                task_id,
                actor=str(user.id),
                reason=payload.note or "",
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=f"状态 {payload.status} 不能直接设置，请通过节点操作推进",
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    event_type = {
        "done": "task_completed",
        "cancelled": "task_cancelled",
        "running": "task_rejected",
    }[target]
    enqueue_task_notification(db, task, event_type)
    record_task_event(db, task, user.id, {
        'done': 'task_accepted', 'cancelled': 'task_cancelled', 'running': 'task_rejected',
    }[target])
    audit(
        db,
        user,
        "任务状态流转",
        f"任务「{task.title}」变更为 {task.state}",
        task.scope.get("project_id"),
        "task",
        0,
    )
    db.commit()
    return ok(to_api_task(task), "任务状态已更新")


@router.post("/tasks/{task_id}/steps/{step_index}")
def update_task_step(
    task_id: str,
    step_index: int,
    payload: TaskStepUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """按引擎顺序约束更新节点，并保留材料附件。"""
    engine = get_engine()

    try:
        if payload.status == "completed":
            task = engine.complete_step(
                task_id,
                step_index,
                actor=str(user.id),
                comment=payload.note or "",
                attachments=payload.attachments,
            )
        elif payload.status == "blocked":
            task = engine.block_step(
                task_id,
                step_index,
                actor=str(user.id),
                reason=payload.note or "",
            )
        elif payload.status == "processing":
            task = engine.unblock_step(
                task_id,
                step_index,
                actor=str(user.id),
                note=payload.note or "",
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=f"不支持的步骤状态：{payload.status}",
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if payload.status == "completed":
        execute_ready_automation_chain(db, engine, task)
        task = engine.get_task(task.id) or task
        event_type = (
            "task_review"
            if str(task.state) == "review"
            else "step_blocked"
            if str(task.state) == "blocked"
            else "step_activated"
        )
    elif payload.status == "blocked":
        event_type = "step_blocked"
    else:
        event_type = "step_activated"
    enqueue_task_notification(db, task, event_type)
    audit(
        db,
        user,
        "更新任务步骤",
        f"任务「{task.title}」步骤 {step_index + 1} → {payload.status}",
        task.scope.get("project_id"),
        "task",
        0,
    )
    db.commit()
    return ok(to_api_task(task), "任务步骤已更新")


@router.post("/tasks/{task_id}/reassign")
def reassign_task(
    task_id: str,
    payload: TaskReassignInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """通过引擎转办当前节点，已完成节点保持历史责任归属。"""
    engine = get_engine()
    task = engine.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    project_id = task.scope.get("project_id")
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == payload.assignee_user_id,
        ),
    )
    if not member:
        raise HTTPException(status_code=422, detail="转交人不属于当前项目")

    current = task.current_step
    if current is None:
        raise HTTPException(status_code=409, detail="任务没有待办节点")

    target_user = db.get(User, payload.assignee_user_id)
    try:
        task = engine.forward_step(
            task_id,
            current.seq,
            to=Assignee(
                ref=str(payload.assignee_user_id),
                display_name=target_user.real_name if target_user else "",
            ),
            actor=str(user.id),
            note=payload.note or "",
        )
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    enqueue_task_notification(
        db,
        task,
        "task_reassigned",
        recipient_user_id=payload.assignee_user_id,
    )
    audit(
        db,
        user,
        "转交任务",
        f"任务「{task.title}」转交给用户 {payload.assignee_user_id}",
        project_id,
        "task",
        0,
    )
    db.commit()
    return ok(to_api_task(task), "任务已转交")


@router.post("/tasks/{task_id}/notes")
def add_task_note(
    task_id: str,
    payload: TaskNoteInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    engine = get_engine()
    try:
        task = engine.add_note(
            task_id,
            note=payload.note,
            actor=str(user.id),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except TransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit(
        db,
        user,
        "记录任务处置",
        f"任务「{task.title}」新增处理说明",
        task.scope.get("project_id"),
        "task",
        0,
    )
    db.commit()
    return ok({"task_id": task.id}, "任务处理说明已记录")

# Compatibility exports preserve the established import surface while route
# responsibilities live in focused modules.
from .account_api import (  # noqa: E402,F401
    change_my_password,
    delete_my_connector,
    list_my_connectors,
    login,
    me,
    save_my_connector,
    update_me,
)
from .project_reporting_api import (  # noqa: E402,F401
    assist_risk_draft,
    confirm_daily_report,
    confirm_draft,
    create_daily_report,
    create_draft,
    create_fill_package,
    list_daily_reports,
    list_drafts,
    list_fill_packages,
    return_draft,
    submit_draft_review,
    transition_fill_package,
    update_daily_report,
)
