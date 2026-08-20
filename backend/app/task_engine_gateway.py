"""任务引擎接入层。

职责边界：
  引擎持有  —— 任务实体、节点流转、触发计划、审计轨迹
  Dobby 持有 —— 项目、人员、WBS、风险源

两者通过 TaskInstance.scope 关联。scope 在登记时写入，触发时原样带回，
引擎不解释其内容，因此换一个宿主系统也无需改引擎。

责任制：引擎要求每项待办能追到具体的人、具体的工点、具体的验收责任。
Dobby 的 WBS 条目在这里充当「工点」，project_member 充当「责任人」与「确认人」。
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from task_engine.domain.models import (
    Assignee,
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
from .db import engine as database_engine
from .models import ProjectMember, User, WbsItem

# ── 枚举映射 ──────────────────────────────────────────────
# 前端 uiTaskStatus 只认后端枚举，所以这里必须转成 Dobby 的说法，
# 不能直接把引擎枚举透出去。

ENGINE_TO_DOBBY_STATE = {
    "pending": "pending",
    "running": "processing",
    "blocked": "need_more_info",
    "review": "pending_confirm",
    "done": "completed",
    "cancelled": "cancelled",
    "overdue": "overdue",
}

DOBBY_TO_ENGINE_STATE = {v: k for k, v in ENGINE_TO_DOBBY_STATE.items()}

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
PRIORITY_TO_RISK = {v: k for k, v in RISK_TO_PRIORITY.items()}


# ── 单例 ──────────────────────────────────────────────────

@lru_cache
def get_engine() -> TaskEngine:
    """全局单例；后端与 MCP 共用 PostgreSQL 中的任务引擎 schema。"""
    settings = get_settings()
    store = PostgresStore(database_engine, schema=settings.task_engine_schema)
    return TaskEngine(timezone=settings.task_engine_tz, store=store)


@lru_cache
def get_generator() -> FlowGenerator:
    """复用 Dobby 已有的模型配置。"""
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


# ── 责任制解析：把 Dobby 的 id 换成引擎要的具体人与工点 ────

def resolve_person(
    db: Session,
    user_id: int | str | None,
    project_id: int,
) -> Assignee | None:
    """把用户 id 解析成具体的人。

    引擎不接受抽象角色——这里必须查出真名。查不到就返回 None，
    让上层的责任制校验去报错，而不是塞一个假名字蒙混过关。
    """
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
    """把 WBS 条目解析成工点。

    Dobby 的 WBS 条目天然就是「工点/部位」——它有编号（wbs_code）、
    名称和层级，正好对应引擎的 Site。
    """
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


# ── 引擎 → 前端 ───────────────────────────────────────────

def to_api_task(task: TaskInstance) -> dict[str, Any]:
    """转成前端 mapTask 能消费的形状。

    字段名与 stores/app.ts:129 的 ApiTask 逐一对应，多一个少一个都可能出问题。
    """
    scope = task.scope or {}
    current = task.current_step

    return {
        "id": task.id,  # 字符串 id，前端 String() 后正常
        "project_id": scope.get("project_id"),
        "title": task.title,
        "task_type": scope.get("task_type", "risk_alert"),
        "risk_level": PRIORITY_TO_RISK.get(task.priority, "medium"),
        # 前端用 responsibleId 显示“当前该谁办”，所以给当前节点责任人而非发起人
        "assignee_user_id": (
            _to_int(current.assignee.ref)
            if current and current.assignee
            else None
        ),
        # 确认人现在是引擎的一等字段，不再从 scope 里取
        "confirmer_user_id": (
            _to_int(task.confirmer.ref) if task.confirmer else None
        ),
        "due_at": task.due_at.isoformat() if task.due_at else None,
        # 工点即 WBS 条目，前端用 linkedWbsIds 展示
        "wbs_item_id": _to_int(task.site.ref) if task.site else None,
        "risk_source_id": scope.get("risk_source_id"),
        "trigger_reason": task.trigger_note,
        # 前端用它算 missingCount
        "required_materials": [
            step.deliverable for step in task.steps if step.deliverable
        ],
        "workflow_steps": [to_api_step(step, task) for step in task.steps],
        "status": ENGINE_TO_DOBBY_STATE.get(str(task.state), "pending"),
        "created_at": task.created_at.isoformat() if task.created_at else "",
    }


def to_api_step(step, task: TaskInstance) -> dict[str, Any]:
    """转成前端 workflowSteps 元素。

    order / next_step 是 1-based，与前端展示一致；引擎的 seq 是 0-based。
    reopened 是退回重做的标记——前端据此提示“需重新提交材料”，
    避免用户点完成时才被引擎拒绝。
    """
    return {
        "name": step.name,
        "owner": step.assignee.display_name if step.assignee else "",
        "owner_user_id": step.assignee.ref if step.assignee else None,
        "due_at": step.due_at.strftime("%Y-%m-%d") if step.due_at else None,
        "order": step.seq + 1,
        "next_step": step.seq + 2 if step.seq + 1 < len(task.steps) else None,
        "status": ENGINE_TO_DOBBY_STEP.get(str(step.state), "pending"),
        "note": step.comment,
        "material": step.deliverable,
        # 被退回重做——前端应提示该节点需重新提交材料
        "reopened": step.reopened,
    }


def to_api_history(task: TaskInstance) -> list[dict[str, Any]]:
    """转成 get_task 返回的 history 数组。

    对应原 TaskStatusHistory 的形状，前端任务历史时间线直接可用。
    """
    return [
        {
            "id": activity.id,
            "task_id": task.id,
            "from_status": activity.detail.get("from"),
            "to_status": activity.detail.get("to"),
            "note": activity.summary,
            "changed_by": _to_int(activity.actor),
            "created_at": activity.at.isoformat() if activity.at else "",
        }
        for activity in task.activities
    ]


# ── 前端 → 引擎 ───────────────────────────────────────────

def build_flow(db: Session, project_id: int, payload) -> TaskFlow:
    """把前端提交的任务表单转成引擎的任务流定义。

    责任制三要素（责任人 / 工点 / 确认人）在这里被解析成引擎认识的对象。
    解析不出来时留空，由引擎的 require_dispatchable() 统一报错——
    这样错误信息集中在一处，措辞也一致。
    """
    names = member_names(db, project_id)

    return TaskFlow(
        title=payload.title,
        steps=build_steps(payload.workflow_steps, names),
        summary=payload.trigger_reason or "",
        category=payload.task_type,
        priority=RISK_TO_PRIORITY.get(payload.risk_level, "normal"),
        trigger=build_trigger(payload),
        site=resolve_site(db, payload.wbs_item_id),
        confirmer=resolve_person(db, payload.confirmer_user_id, project_id),
        watchers=parse_cc(payload.cc),
        scope={
            "project_id": project_id,
            "task_type": payload.task_type,
            "risk_source_id": payload.risk_source_id,
        },
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
    """让平台内其他业务入口也通过同一个引擎布置结构化任务。

    该入口沿用指南的三项硬约束，不为自动任务猜测责任人、工点或确认人。
    """
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
    task = get_engine().dispatch(
        flow,
        actor=str(actor),
        trigger_note=trigger_reason,
    )
    # 宿主侧通知是引擎结果的消费者，不改变任务引擎领域模型与流转规则。
    from .wecom_notification_gateway import enqueue_task_notification

    enqueue_task_notification(db, task, "task_created")
    return task


def build_steps(
    workflow_steps: list[dict],
    names: dict[str, str],
) -> tuple[StepSpec, ...]:
    """Dobby 的 workflow_steps → 引擎的 StepSpec。

    关键转换：Dobby 用绝对日期 due_at，引擎用相对天数 due_offset_days。
    因为同一个流程会被反复触发——8/14 那次和 8/21 那次的截止日必须不同，
    绝对日期在模板层面没有意义。这里按相邻节点的日期差还原出工期。
    """
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
                # owner_id 为空时留 None，让引擎统一报“尚未指定责任人”
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
                # 有交付物要求的节点强制留痕——工程场景的可追溯性要求
                requires_attachment=bool(material),
            ),
        )

    return tuple(specs) or (StepSpec(name="执行任务"),)


def build_trigger(payload) -> Trigger:
    """前端的触发配置 → 引擎的 Trigger。

    平台把引擎原生的两类 Trigger 展示成三种交互方式：立即执行通过
    dispatch 落地，定时单次映射 ONCE 计划，周期执行映射 RECURRING 计划。
    single / scheduled 仅用于兼容旧前端。
    """
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

    if payload.run_mode in {"recurring", "scheduled"}:
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
    """抄送人：前端传的是逗号分隔的姓名字符串，中英文逗号都要认。

    抄送人不参与流转，只是知会，所以用姓名本身作 ref 即可，
    不必强求解析到用户 id。
    """
    if not cc:
        return ()
    return tuple(
        Assignee(ref=name.strip(), display_name=name.strip())
        for name in cc.replace("，", ",").split(",")
        if name.strip()
    )


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
