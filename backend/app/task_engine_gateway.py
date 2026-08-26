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

import re
from datetime import datetime
from functools import lru_cache
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
from task_engine.generator.rules import parse_trigger
from task_engine.store.postgres import PostgresStore

from .config import get_settings
from .db import engine as database_engine
from .models import ChatChannel, ChatChannelMember, ProjectMember, User, WbsItem

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


def build_project_chat_generation_draft(
    db: Session,
    project_id: int,
    requirement: str,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """把明确的群聊发送需求生成为一个平台动作节点。

    通用任务引擎只负责触发与节点流转，不应认识 Dobby 的群聊、智能体或 @ 语义；
    因此这层宿主适配必须在调用通用流程生成器之前完成。返回值与生成任务流接口一致，
    前端仍可自由增删、排序或改回人工节点。
    """
    text = requirement.strip()
    target_words = ("群发", "项目群", "群聊", "群里", "群内")
    send_words = ("发送", "发一条", "发消息", "通知", "提醒")
    if not any(word in text for word in target_words) or not any(
        word in text for word in send_words
    ):
        return None

    channel = db.scalars(
        select(ChatChannel)
        .where(
            ChatChannel.project_id == project_id,
            ChatChannel.channel_type == "project",
            ChatChannel.archived_at.is_(None),
        )
        .order_by(ChatChannel.id),
    ).first()
    if channel is None:
        return None

    quoted_parts = re.findall(r'[“"]([^”"]+)[”"]', text)
    quoted_parts.extend(re.findall(r"[‘']([^’']+)[’']", text))
    content = max(quoted_parts, key=len).strip() if quoted_parts else ""
    if not content:
        tail = re.search(
            r"(?:群发|发送|发一条|发消息)(?:一条)?(?:消息)?\s*[：:,，]?\s*(.+)$",
            text,
        )
        if tail:
            content = tail.group(1).strip().rstrip("。")
    if not content:
        return None

    trigger = parse_trigger(text, now=now)
    first_at = trigger.first_at or now
    mention_mode = (
        "all"
        if any(word in text for word in ("@全体", "＠全体", "全体成员", "艾特全体"))
        else "none"
    )
    title_prefix = content.split("：", 1)[0].strip()
    title = title_prefix if 2 <= len(title_prefix) <= 30 else "群聊定时通知"

    return {
        "title": title,
        "task_type": "automation",
        "risk_level": "low",
        "assignee_user_id": None,
        "confirmer_user_id": None,
        "wbs_item_id": None,
        "risk_source_id": None,
        "run_mode": str(trigger.run_mode),
        "trigger_date": first_at.strftime("%Y-%m-%d"),
        "trigger_time": first_at.strftime("%H:%M"),
        "trigger_rule": trigger.describe(),
        "trigger_interval_value": trigger.interval_value,
        "trigger_interval_unit": str(trigger.interval_unit),
        "cc": "",
        "steps": [
            {
                "name": "发送群聊消息",
                "node_type": "project_chat_message",
                "owner_user_id": None,
                "due_at": None,
                "material": "",
                "action": {
                    "type": "project_chat_message",
                    "channel_id": channel.id,
                    "sender_agent_id": "dobby-task-engine",
                    "sender_agent_name": "Dobby（任务引擎）",
                    "mention_mode": mention_mode,
                    "mentioned_user_ids": [],
                    "content": content,
                },
            },
        ],
        "generated_by": "rules",
        "generation_note": (
            "Dobby 已识别为群聊发送动作，并生成 1 个可编辑的自动消息节点；"
            "未创建 WBS 工程流程节点。"
        ),
    }


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
    step_actions = scope.get("step_actions") or {}
    pure_automation = (
        isinstance(step_actions, dict)
        and bool(task.steps)
        and len(step_actions) == len(task.steps)
    )

    return {
        "id": task.id,  # 字符串 id，前端 String() 后正常
        "project_id": scope.get("project_id"),
        "title": task.title,
        "task_type": (
            "automation"
            if task.is_automation or pure_automation
            else scope.get("task_type", "risk_alert")
        ),
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
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
        "closed_at": task.closed_at.isoformat() if task.closed_at else "",
    }


def to_api_step(step, task: TaskInstance) -> dict[str, Any]:
    """转成前端 workflowSteps 元素。

    order / next_step 是 1-based，与前端展示一致；引擎的 seq 是 0-based。
    reopened 是退回重做的标记——前端据此提示“需重新提交材料”，
    避免用户点完成时才被引擎拒绝。
    """
    step_actions = (task.scope or {}).get("step_actions") or {}
    action = step_actions.get(str(step.seq)) if isinstance(step_actions, dict) else None
    if action is None and task.is_automation and step.seq == 0:
        root_action = (task.scope or {}).get("action")
        action = root_action if isinstance(root_action, dict) else None
    return {
        "name": step.name,
        "node_type": "project_chat_message" if action else "manual",
        "action": action,
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


# ── 前端 → 引擎 ───────────────────────────────────────────

def build_flow(
    db: Session,
    project_id: int,
    payload,
    *,
    actor_user_id: int | None = None,
) -> TaskFlow:
    """把前端提交的任务表单转成引擎的任务流定义。

    责任制三要素（责任人 / 工点 / 确认人）在这里被解析成引擎认识的对象。
    解析不出来时留空，由引擎的 require_dispatchable() 统一报错——
    这样错误信息集中在一处，措辞也一致。
    """
    names = member_names(db, project_id)

    if payload.action_type == "project_chat_message":
        content = (payload.message_content or "").strip()
        if not content:
            raise ValueError("群聊消息内容不能为空")
        if payload.mention_mode == "users" and not payload.mentioned_user_ids:
            raise ValueError("选择指定成员时，至少需要选择一位接收人")

        channel = None
        if payload.target_channel_id:
            channel = db.get(ChatChannel, payload.target_channel_id)
            if (
                channel is None
                or channel.project_id != project_id
                or channel.archived_at is not None
            ):
                raise ValueError("目标群聊不存在或不属于当前项目")

        project_member_ids = set(
            db.scalars(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project_id,
                ),
            ).all(),
        )
        available_user_ids = project_member_ids
        if channel is not None and channel.channel_type != "project":
            available_user_ids = set(
                db.scalars(
                    select(ChatChannelMember.user_id).where(
                        ChatChannelMember.channel_id == channel.id,
                        ChatChannelMember.left_at.is_(None),
                    ),
                ).all(),
            )
            if (
                channel.channel_type == "private"
                and actor_user_id not in available_user_ids
            ):
                raise ValueError("目标私聊对当前用户不可见")

        selected_user_ids = list(dict.fromkeys(payload.mentioned_user_ids))
        if any(user_id not in available_user_ids for user_id in selected_user_ids):
            raise ValueError("消息接收人必须是目标群聊的当前成员")

        return TaskFlow(
            title=payload.title,
            steps=(
                StepSpec(
                    name="发送群聊消息",
                    due_offset_days=0,
                    instruction=content,
                    automated=True,
                ),
            ),
            summary=content,
            category="automation",
            priority="normal",
            trigger=build_trigger(payload),
            origin="manual",
            scope={
                "project_id": project_id,
                "task_type": "automation",
                "execution_kind": "automation",
                "action": {
                    "type": "project_chat_message",
                    "channel_id": channel.id if channel else None,
                    "sender_agent_id": "dobby-task-engine",
                    "sender_agent_name": "Dobby（任务引擎）",
                    "mention_mode": payload.mention_mode,
                    "mentioned_user_ids": selected_user_ids,
                    "content": content,
                    "created_by_user_id": actor_user_id,
                },
            },
        )

    steps = build_steps(payload.workflow_steps, names)
    step_actions = build_step_actions(
        db,
        project_id,
        payload.workflow_steps,
        actor_user_id=actor_user_id,
    )
    pure_automation = bool(steps) and len(step_actions) == len(steps)
    scope: dict[str, Any] = {
        "project_id": project_id,
        "task_type": "automation" if pure_automation else payload.task_type,
        "risk_source_id": payload.risk_source_id,
        "step_actions": step_actions,
    }
    if pure_automation:
        scope["execution_kind"] = "automation"
        if len(step_actions) == 1:
            scope["action"] = next(iter(step_actions.values()))
    return TaskFlow(
        title=payload.title,
        steps=steps,
        summary=payload.trigger_reason or "",
        category="automation" if pure_automation else payload.task_type,
        priority=RISK_TO_PRIORITY.get(payload.risk_level, "normal"),
        trigger=build_trigger(payload),
        site=resolve_site(db, payload.wbs_item_id),
        confirmer=resolve_person(db, payload.confirmer_user_id, project_id),
        watchers=parse_cc(payload.cc),
        scope=scope,
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
        automated = step.get("node_type") == "project_chat_message"
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
                    if owner_id and not automated
                    else None
                ),
                due_offset_days=offset,
                deliverable=material,
                # 有交付物要求的节点强制留痕——工程场景的可追溯性要求
                requires_attachment=bool(material),
                automated=automated,
            ),
        )

    return tuple(specs) or (StepSpec(name="执行任务"),)


def build_step_actions(
    db: Session,
    project_id: int,
    workflow_steps: list[dict],
    *,
    actor_user_id: int | None,
) -> dict[str, dict[str, Any]]:
    """解析自动节点动作；引擎只持有节点顺序，动作语义由 Dobby 执行。"""
    actions: dict[str, dict[str, Any]] = {}
    project_member_ids = set(
        db.scalars(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project_id,
            ),
        ).all(),
    )

    for index, step in enumerate(workflow_steps or []):
        if step.get("node_type") != "project_chat_message":
            continue
        raw_action = step.get("action") or {}
        if not isinstance(raw_action, dict):
            raise ValueError(f"第 {index + 1} 个消息节点配置格式不正确")

        content = str(raw_action.get("content") or "").strip()
        if not content:
            raise ValueError(f"第 {index + 1} 个消息节点未填写消息内容")

        sender_agent_id = str(
            raw_action.get("sender_agent_id") or "dobby-task-engine",
        ).strip()
        sender_agent_name = str(
            raw_action.get("sender_agent_name") or "Dobby",
        ).strip()
        if not sender_agent_id:
            raise ValueError(f"第 {index + 1} 个消息节点未选择发送智能体")

        channel_id = raw_action.get("channel_id")
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            raise ValueError(f"第 {index + 1} 个消息节点未选择目标群聊") from None
        channel = db.get(ChatChannel, channel_id)
        if (
            channel is None
            or channel.project_id != project_id
            or channel.archived_at is not None
        ):
            raise ValueError(f"第 {index + 1} 个消息节点的目标群聊无效")

        available_user_ids = project_member_ids
        if channel.channel_type != "project":
            available_user_ids = set(
                db.scalars(
                    select(ChatChannelMember.user_id).where(
                        ChatChannelMember.channel_id == channel.id,
                        ChatChannelMember.left_at.is_(None),
                    ),
                ).all(),
            )
            if (
                channel.channel_type == "private"
                and actor_user_id not in available_user_ids
            ):
                raise ValueError(f"第 {index + 1} 个消息节点的目标私聊不可见")

        mention_mode = str(raw_action.get("mention_mode") or "none")
        if mention_mode not in {"none", "all", "users"}:
            raise ValueError(f"第 {index + 1} 个消息节点的提醒方式无效")
        try:
            selected_user_ids = list(
                dict.fromkeys(
                    int(user_id)
                    for user_id in (raw_action.get("mentioned_user_ids") or [])
                ),
            )
        except (TypeError, ValueError):
            raise ValueError(f"第 {index + 1} 个消息节点的提醒成员无效") from None
        if mention_mode == "users" and not selected_user_ids:
            raise ValueError(f"第 {index + 1} 个消息节点至少需要选择一位提醒成员")
        if any(user_id not in available_user_ids for user_id in selected_user_ids):
            raise ValueError(f"第 {index + 1} 个消息节点包含非群聊成员")

        actions[str(index)] = {
            "type": "project_chat_message",
            "channel_id": channel.id,
            "sender_agent_id": sender_agent_id[:128],
            "sender_agent_name": sender_agent_name[:200] or "Dobby",
            "mention_mode": mention_mode,
            "mentioned_user_ids": selected_user_ids,
            "content": content,
            "created_by_user_id": actor_user_id,
        }

    return actions


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
