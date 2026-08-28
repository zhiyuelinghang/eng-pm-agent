"""任务引擎接入层。

引擎持有任务实体、节点流转、触发计划与审计轨迹；Dobby 持有项目、人员、WBS
和风险源。两者通过 ``TaskInstance.scope`` 关联，scope 在登记时写入，触发时
原样带回，因此引擎本身不依赖任何宿主业务。

责任制三要素：责任人、工点（WBS 条目）、确认人。Dobby 的项目成员在这里被
解析成引擎要求的具体人，WBS 条目被解析成工点。
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from task_engine.domain.models import (
    Assignee,
    CalendarMode,
    IntervalUnit,
    RunMode,
    Site,
    StepSpec,
    TaskFlow,
    TaskInstance,
    Trigger,
)
from task_engine.engine import TaskEngine
from task_engine.generator.llm import FlowGenerator, LLMConfig
from task_engine.store.postgres import PostgresStore

from .config import get_settings
from .db import database_backend, engine as database_engine
from .models import ProjectMember, User, WbsItem


ENGINE_TO_DOBBY_STATE = {
    "pending": "pending",
    "running": "processing",
    "blocked": "need_more_info",
    "review": "pending_confirm",
    "done": "completed",
    "cancelled": "cancelled",
    "overdue": "overdue",
}

DOBBY_TO_ENGINE_STATE = {value: key for key, value in ENGINE_TO_DOBBY_STATE.items()}

ENGINE_TO_DOBBY_STEP = {
    "waiting": "pending",
    "active": "processing",
    "done": "completed",
    "skipped": "completed",
    "blocked": "blocked",
}

RISK_TO_PRIORITY = {
    "critical": "urgent",
    "high": "high",
    "medium": "normal",
    "low": "low",
}
PRIORITY_TO_RISK = {value: key for key, value in RISK_TO_PRIORITY.items()}


@lru_cache
def get_engine() -> TaskEngine:
    """全局单例；平台后端与任务引擎 MCP 共用同一 PostgreSQL schema。"""
    settings = get_settings()
    if database_backend == "sqlite":
        from task_engine.store.sqlite import Store

        db_path = Path(__file__).resolve().parents[2] / "data" / "task_engine.db"
        return TaskEngine(timezone=settings.task_engine_tz, store=Store(db_path))
    store = PostgresStore(database_engine, schema=settings.task_engine_schema)
    return TaskEngine(timezone=settings.task_engine_tz, store=store)


@lru_cache
def get_generator() -> FlowGenerator:
    """复用平台已有的模型配置生成任务流。"""
    settings = get_settings()
    return FlowGenerator(
        LLMConfig(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            model=settings.ai_model,
        ),
    )


def engine_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().task_engine_tz)


def resolve_person(
    db: Session,
    user_id: int | str | None,
    project_id: int,
) -> Assignee | None:
    """把用户 id 解析成引擎要求的具体人。"""
    if not user_id:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    row = db.execute(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id, User.id == uid),
    ).scalar_one_or_none()
    if row is None:
        return None
    return Assignee(ref=str(uid), display_name=row.real_name or f"用户{uid}")


def resolve_site(db: Session, wbs_item_id: int | str | None) -> Site | None:
    """把 WBS 条目解析成引擎的工点。"""
    if not wbs_item_id:
        return None
    try:
        wid = int(wbs_item_id)
    except (TypeError, ValueError):
        return None
    item = db.get(WbsItem, wid)
    if item is None:
        return None
    return Site(ref=str(wid), name=item.name, code=item.wbs_code or "")


def member_names(db: Session, project_id: int) -> dict[str, str]:
    """{user_id: 姓名}，用于批量补全显示名。"""
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id),
    ).all()
    return {str(member.user_id): user.real_name for member, user in rows}


def to_api_task(task: TaskInstance) -> dict[str, Any]:
    """转成现有前端 ``ApiTask`` 能消费的形状。"""
    scope = task.scope or {}
    current = task.current_step
    return {
        "id": task.id,
        "project_id": scope.get("project_id"),
        "title": task.title,
        "task_type": scope.get("task_type", "risk_alert"),
        "risk_level": PRIORITY_TO_RISK.get(task.priority, "medium"),
        "assignee_user_id": (
            _to_int(current.assignee.ref)
            if current and current.assignee
            else None
        ),
        "confirmer_user_id": _to_int(task.confirmer.ref) if task.confirmer else None,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "wbs_item_id": _to_int(task.site.ref) if task.site else None,
        "risk_source_id": scope.get("risk_source_id"),
        "trigger_reason": task.trigger_note,
        "required_materials": [
            step.deliverable for step in task.steps if step.deliverable
        ],
        "workflow_steps": [to_api_step(step, task) for step in task.steps],
        "status": ENGINE_TO_DOBBY_STATE.get(str(task.state), "pending"),
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
        "closed_at": task.closed_at.isoformat() if task.closed_at else "",
    }


def to_api_step(step, task: TaskInstance) -> dict[str, Any]:
    """转成前端 ``workflowSteps`` 元素。"""
    return {
        "name": step.name,
        "node_type": "manual",
        "owner": step.assignee.display_name if step.assignee else "",
        "owner_user_id": step.assignee.ref if step.assignee else None,
        "due_at": step.due_at.strftime("%Y-%m-%d") if step.due_at else None,
        "order": step.seq + 1,
        "next_step": step.seq + 2 if step.seq + 1 < len(task.steps) else None,
        "status": ENGINE_TO_DOBBY_STEP.get(str(step.state), "pending"),
        "note": step.comment,
        "attachments": list(step.attachments),
        "material": step.deliverable,
        "reopened": step.reopened,
    }


def to_api_history(task: TaskInstance) -> list[dict[str, Any]]:
    """转成 ``get_task`` 返回的 history 数组。"""
    return [
        {
            "id": activity.id,
            "task_id": task.id,
            "kind": str(activity.kind),
            "step_seq": activity.step_seq,
            "from_status": activity.detail.get("from"),
            "to_status": activity.detail.get("to"),
            "note": activity.summary,
            "changed_by": _to_int(activity.actor),
            "created_at": activity.at.isoformat() if activity.at else "",
        }
        for activity in task.activities
    ]


def build_flow(
    db: Session,
    project_id: int,
    payload,
) -> TaskFlow:
    """把前端提交的任务表单转成引擎的任务流定义。"""
    names = member_names(db, project_id)
    steps = build_steps(payload.workflow_steps, names)
    scope: dict[str, Any] = {
        "project_id": project_id,
        "task_type": payload.task_type,
        "risk_source_id": payload.risk_source_id,
    }
    return TaskFlow(
        title=payload.title,
        steps=steps,
        summary=payload.trigger_reason or "",
        category=payload.task_type,
        priority=RISK_TO_PRIORITY.get(payload.risk_level, "normal"),
        trigger=build_trigger(payload),
        site=resolve_site(db, payload.wbs_item_id),
        confirmer=resolve_person(db, payload.confirmer_user_id, project_id),
        watchers=parse_cc(payload.cc),
        scope=scope,
    )


def build_steps(
    workflow_steps: list[dict],
    names: dict[str, str],
) -> tuple[StepSpec, ...]:
    """把 Dobby 的 workflow_steps 转成引擎的 StepSpec。"""
    specs: list[StepSpec] = []
    previous_date: datetime | None = None

    for index, step in enumerate(workflow_steps or []):
        owner_id = str(step.get("owner_user_id") or "").strip()
        offset = 1
        raw_due = step.get("due_at")
        if raw_due:
            try:
                current = datetime.strptime(raw_due[:10], "%Y-%m-%d")
                if previous_date:
                    offset = max(1, (current - previous_date).days)
                previous_date = current
            except ValueError:
                pass

        material = (step.get("material") or "").strip()
        specs.append(
            StepSpec(
                name=(step.get("name") or f"节点 {index + 1}").strip(),
                assignee=(
                    Assignee(
                        ref=owner_id,
                        display_name=step.get("owner") or names.get(owner_id, ""),
                    )
                    if owner_id
                    else None
                ),
                due_offset_days=offset,
                deliverable=material,
                requires_attachment=bool(material),
            ),
        )

    return tuple(specs) or (StepSpec(name="执行任务"),)


def build_trigger(payload) -> Trigger:
    """前端触发配置转成引擎 Trigger。"""
    timezone = engine_tz()
    now = datetime.now(timezone)
    raw_date = payload.trigger_date or now.strftime("%Y-%m-%d")
    raw_time = payload.trigger_time or "09:00"

    try:
        first_at = datetime.strptime(
            f"{raw_date} {raw_time}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=timezone)
    except ValueError as exc:
        raise ValueError("执行时间格式不正确，请重新选择日期与时间") from exc

    if payload.run_mode in {"recurring", "scheduled", "calendar"}:
        until = None
        max_fires = None
        if payload.trigger_end_mode == "until":
            if not payload.trigger_until_date:
                raise ValueError("周期执行选择按日期结束时，必须填写结束日期")
            try:
                until = datetime.strptime(
                    f"{payload.trigger_until_date} {raw_time}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=timezone)
            except ValueError as exc:
                raise ValueError("周期执行的结束日期格式不正确") from exc
            if until < first_at:
                raise ValueError("周期执行的结束日期不能早于首次触发日期")
        elif payload.trigger_end_mode == "count":
            if not payload.trigger_max_fires:
                raise ValueError("周期执行选择按次数结束时，必须填写执行次数")
            max_fires = payload.trigger_max_fires

        if payload.run_mode == "calendar":
            calendar_mode = CalendarMode(payload.trigger_calendar_mode)
            weekdays = tuple(sorted(set(payload.trigger_weekdays)))
            if calendar_mode is CalendarMode.WEEKLY and not weekdays:
                raise ValueError("按星期触发至少需要选择一天")
            calendar_day = payload.trigger_day_of_month
            if calendar_mode is CalendarMode.MONTHLY and calendar_day is None:
                calendar_day = first_at.day
            return Trigger(
                run_mode=RunMode.CALENDAR,
                first_at=first_at,
                timezone=str(timezone),
                until=until,
                max_fires=max_fires,
                calendar_mode=calendar_mode,
                calendar_weekdays=weekdays,
                calendar_day=calendar_day,
            )

        return Trigger(
            run_mode=RunMode.RECURRING,
            first_at=first_at,
            interval_value=max(1, payload.trigger_interval_value or 1),
            interval_unit=IntervalUnit(payload.trigger_interval_unit or "week"),
            timezone=str(timezone),
            until=until,
            max_fires=max_fires,
        )
    if payload.run_mode in {"immediate", "single"}:
        first_at = now
    return Trigger(
        run_mode=RunMode.ONCE,
        first_at=first_at,
        timezone=str(timezone),
    )


def parse_cc(cc: str | None) -> tuple[Assignee, ...]:
    """抄送人：中英文逗号分隔，姓名本身即可，不参与流转。"""
    if not cc:
        return ()
    return tuple(
        Assignee(ref=name.strip(), display_name=name.strip())
        for name in cc.replace("，", ",").split(",")
        if name.strip()
    )


def dispatch_platform_task(
    db: Session,
    *,
    project_id: int,
    title: str,
    task_type: str,
    risk_level: str,
    assignee_user_id: int | str | None,
    confirmer_user_id: int | str | None,
    wbs_item_id: int | str | None,
    actor: int | str,
    trigger_reason: str,
    deliverables: list[str] | None = None,
    risk_source_id: int | None = None,
    step_name: str = "执行任务",
) -> TaskInstance:
    """让平台内其他业务入口也通过同一个引擎布置结构化任务。"""
    materials = [item.strip() for item in (deliverables or []) if item.strip()]
    assignee = resolve_person(db, assignee_user_id, project_id)
    steps = tuple(
        StepSpec(
            name=(
                step_name
                if len(materials) <= 1
                else f"{step_name}（{index + 1}/{len(materials)}）"
            ),
            assignee=assignee,
            due_offset_days=1,
            deliverable=material,
            requires_attachment=True,
        )
        for index, material in enumerate(materials)
    ) or (StepSpec(name=step_name, assignee=assignee, due_offset_days=1),)

    flow = TaskFlow(
        title=title,
        steps=steps,
        summary=trigger_reason,
        category=task_type,
        priority=RISK_TO_PRIORITY.get(risk_level, "normal"),
        site=resolve_site(db, wbs_item_id),
        confirmer=resolve_person(db, confirmer_user_id, project_id),
        scope={
            "project_id": project_id,
            "task_type": task_type,
            "risk_source_id": risk_source_id,
        },
    )
    return get_engine().dispatch(
        flow,
        actor=str(actor),
        trigger_note=trigger_reason,
    )


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
