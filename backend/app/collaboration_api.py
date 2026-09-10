from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_common import audit, entity_or_404, get_current_user, ok, project_or_404, serialize
from .agent_api_support import _agentscope_client
from .agentscope_client import AgentScopeGatewayError
from .db import get_db
from .models import (
    Attachment,
    AttachmentText,
    CollaborationMessage,
    CollaborationSession,
    DailyReport,
    MeetingMinute,
    PlatformFieldMapping,
    QualityMetric,
    RiskSource,
    Task,
    User,
    WbsItem,
)
from .schemas import CollaborationMessageInput, CollaborationSessionInput
from .task_engine_gateway import dispatch_platform_task, get_engine, to_api_task


router = APIRouter(prefix="/api")


def collaboration_reply(project_id: int, content: str, db: Session) -> tuple[str, list[str]]:
    project = project_or_404(db, project_id)
    tasks = [
        task
        for task in get_engine().list_tasks(open_only=True, limit=200)
        if task.scope.get("project_id") == project_id
    ]
    wbs_items = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id).order_by(WbsItem.wbs_code).limit(30)).all()
    risk_sources = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id).order_by(RiskSource.updated_at.desc()).limit(30)).all()
    quality_metrics = db.scalars(select(QualityMetric).where(QualityMetric.project_id == project_id).order_by(QualityMetric.updated_at.desc()).limit(30)).all()
    daily_reports = db.scalars(select(DailyReport).where(DailyReport.project_id == project_id).order_by(DailyReport.updated_at.desc()).limit(20)).all()
    field_mappings = db.scalars(select(PlatformFieldMapping).where(PlatformFieldMapping.project_id == project_id).order_by(PlatformFieldMapping.platform_name, PlatformFieldMapping.target_field).limit(30)).all()
    materials = db.execute(
        select(
            Attachment.file_name,
            Attachment.category,
            AttachmentText.content,
            AttachmentText.parse_status,
            AttachmentText.parse_error,
        )
        .outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id)
        .where(Attachment.project_id == project_id)
        .order_by(Attachment.created_at.desc())
        .limit(12)
    ).all()
    material_context = "；".join(
        f"{file_name}（{category}）"
        + (
            f"：{(content or '')[:360]}"
            if parse_status == "ready" and content
            else f"：[附件解析失败：{parse_error or '未知原因'}]"
            if parse_status == "failed"
            else "：[历史资料尚未经过统一附件解析]"
            if parse_status == "legacy"
            else ""
        )
        for file_name, category, content, parse_status, parse_error in materials
    ) or "暂无已入库资料"
    project_context = (
        f"项目：{project.name}；建设单位：{project.construction_unit_name or '未填写'}；说明：{(project.engineering_type_description or '未填写')[:360]}\n"
        + "WBS：" + ("；".join(f"{item.wbs_code} {item.name}（{float(item.progress_percent or 0)}%/{item.status_text or '未设置'}）" for item in wbs_items) or "暂无") + "\n"
        + "风险源：" + ("；".join(f"{item.risk_part}（{item.risk_level}/{item.status}）" for item in risk_sources) or "暂无") + "\n"
        + "质量指标：" + ("；".join(f"{item.quality_acceptance_item}（{item.inspection_frequency or '未设置频次'}）" for item in quality_metrics) or "暂无") + "\n"
        + "日报：" + ("；".join(f"{item.file_name}（{item.report_date or '日期待确认'}/{item.status}）" for item in daily_reports) or "暂无") + "\n"
        + "字段映射：" + ("；".join(f"{item.platform_name}:{item.source_field}→{item.target_field}" for item in field_mappings) or "暂无")
    )
    related = [task.id for task in tasks[:4]]
    prompt = (
        "你是工程项目资料智能体。请只依据已入库资料和项目待办给出简洁、可执行、可追溯的建议。"
        "优先说明：资料可归入的类别、可补全的项目字段、仍缺少的资料；未知内容必须明确标注为待确认，不能编造。"
        f"\n用户请求：{content}\n项目当前数据：{project_context}\n已入库资料：{material_context}\n待办任务："
        + "；".join(f"{task.title}（{task.state}，截止{task.due_at or '未设置'}）" for task in tasks[:8])
    )
    try:
        answer = _agentscope_client().complete_platform_text(
            system_prompt="给出简洁、可执行、可追溯的工程资料补全建议。",
            prompt=prompt,
        )
        return answer, related
    except (AgentScopeGatewayError, ValueError):
        pass
    overdue = next((task for task in tasks if str(task.state) == "overdue"), None)
    focus = overdue or (tasks[0] if tasks else None)
    if focus:
        return f"已基于当前项目的 {len(materials)} 份已入库资料和待办记录生成建议：优先处理「{focus.title}」，状态为{focus.state}，截止日期{focus.due_at or '未设置'}。请核对资料类别、明确对应 WBS/风险项，再补齐缺少材料后提交复核。", related
    return f"当前项目已入库 {len(materials)} 份资料，暂无未闭环任务。可先让智能体核对资料类别与资料缺口，再补充 WBS、风险源或质量指标。", []


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


@router.delete("/collaboration-sessions/{session_id}")
def delete_collaboration_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    session = session_or_404(db, session_id)
    project_id, title = session.project_id, session.title
    db.query(MeetingMinute).filter(MeetingMinute.session_id == session_id).delete(synchronize_session=False)
    db.query(CollaborationMessage).filter(CollaborationMessage.session_id == session_id).delete(synchronize_session=False)
    db.delete(session)
    audit(db, user, "删除协同会话", f"删除会话「{title}」；会话生成的任务保留", project_id, "collaboration_session", session_id)
    db.commit()
    return ok(None, "协同会话已删除")


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
    if "创建任务" in payload.content or "生成任务" in payload.content:
        title = payload.content.replace("创建任务", "").replace("生成任务", "").strip(" ：:，,。")[:200] or "协同会话待办"
        source_task = next(
            (
                task
                for task_id in (session.task_ids or [])
                if (task := get_engine().get_task(str(task_id))) is not None
            ),
            None,
        )
        legacy_source = None
        if source_task is None:
            for raw_task_id in session.task_ids or []:
                try:
                    legacy_id = int(str(raw_task_id).removeprefix("legacy_"))
                except ValueError:
                    continue
                legacy_source = db.get(Task, legacy_id)
                if legacy_source is not None:
                    break

        try:
            task = dispatch_platform_task(
                db,
                project_id=session.project_id,
                title=f"协同任务 — {title}",
                task_type="risk_alert",
                risk_level="medium",
                assignee_user_id=user.id,
                confirmer_user_id=(
                    source_task.confirmer.ref
                    if source_task and source_task.confirmer
                    else legacy_source.confirmer_user_id
                    if legacy_source
                    else None
                ),
                wbs_item_id=(
                    source_task.site.ref
                    if source_task and source_task.site
                    else legacy_source.wbs_item_id
                    if legacy_source
                    else None
                ),
                actor=user.id,
                trigger_reason=f"由协同会话「{session.title}」自动创建",
                risk_source_id=(
                    source_task.scope.get("risk_source_id")
                    if source_task
                    else legacy_source.risk_source_id
                    if legacy_source
                    else None
                ),
                step_name="处理协同事项",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        task_ids = list(dict.fromkeys([*task_ids, task.id])); session.task_ids = list(dict.fromkeys([*(session.task_ids or []), task.id]))
        answer = f"已创建任务「{task.title}」。\n{answer}"
    assistant = CollaborationMessage(session_id=session.id, role="assistant", content=answer, generated_task_ids=task_ids)
    db.add(assistant); session.summary = payload.content[:120]
    audit(db, user, "协同会话处理", f"会话「{session.title}」处理新消息", session.project_id, "collaboration_session", session.id)
    db.commit(); db.refresh(assistant); db.refresh(session)
    return ok({"session": serialize(session), "message": serialize(assistant)}, "协同建议已生成")


@router.post("/collaboration-sessions/{session_id}/minutes")
def create_meeting_minute(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    session = session_or_404(db, session_id)
    messages = db.scalars(select(CollaborationMessage).where(CollaborationMessage.session_id == session_id).order_by(CollaborationMessage.created_at)).all()
    task_ids = list(dict.fromkeys([*(session.task_ids or []), *(item for message in messages for item in (message.generated_task_ids or []))]))
    actions: list[dict[str, Any]] = []
    engine = get_engine()
    for raw_task_id in task_ids:
        engine_task = engine.get_task(str(raw_task_id))
        if engine_task is not None:
            task_data = to_api_task(engine_task)
            actions.append(
                {
                    "task_id": engine_task.id,
                    "title": engine_task.title,
                    "status": task_data["status"],
                    "assignee_user_id": task_data["assignee_user_id"],
                    "due_at": task_data["due_at"],
                },
            )
            continue
        try:
            legacy_id = int(str(raw_task_id).removeprefix("legacy_"))
        except ValueError:
            continue
        legacy_task = db.get(Task, legacy_id)
        if legacy_task is not None:
            actions.append(
                {
                    "task_id": f"legacy_{legacy_task.id}",
                    "title": legacy_task.title,
                    "status": legacy_task.status,
                    "assignee_user_id": legacy_task.assignee_user_id,
                    "due_at": legacy_task.due_at,
                },
            )
    discussion = "；".join(message.content[:120] for message in messages[-6:]) or "暂无会话消息"
    row = MeetingMinute(project_id=session.project_id, session_id=session.id, title=f"会议纪要 — {session.title}", summary=f"会话结论：{discussion}", action_items=actions)
    db.add(row); db.flush(); audit(db, user, "生成会议纪要", f"从会话「{session.title}」生成会议纪要", session.project_id, "meeting_minute", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "会议纪要已生成")
