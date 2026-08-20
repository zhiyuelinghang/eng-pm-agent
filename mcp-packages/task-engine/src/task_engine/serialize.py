"""领域对象 → JSON 的序列化。

MCP 工具的返回值直接面向调用方（可能是模型，也可能是前端），所以这里刻意做了两件事：
1. 附上人类可读的中文标签（`state_label`），模型不必猜 `pending` 是什么意思
2. 附上派生信息（进度、当前责任人、是否逾期），省掉调用方二次计算
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .domain.models import (
    Activity,
    Assignee,
    Schedule,
    Site,
    Step,
    StepState,
    TaskFlow,
    TaskInstance,
    TaskState,
)

STATE_LABELS: dict[str, str] = {
    "pending": "待开始",
    "running": "进行中",
    "blocked": "受阻",
    "review": "待验收",
    "done": "已完成",
    "cancelled": "已取消",
    "overdue": "已逾期",
}

STEP_STATE_LABELS: dict[str, str] = {
    "waiting": "未开始",
    "active": "进行中",
    "done": "已完成",
    "skipped": "已跳过",
    "blocked": "受阻",
}

ACTIVITY_LABELS: dict[str, str] = {
    "created": "创建任务",
    "step_activated": "节点开始",
    "step_done": "节点完成",
    "step_skipped": "节点跳过",
    "step_blocked": "节点受阻",
    "forwarded": "转办",
    "state_changed": "状态变更",
    "note_added": "添加说明",
    "attachment_added": "上传材料",
    "overdue_marked": "标记逾期",
    "fired": "定时触发",
}


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def assignee_json(assignee: Assignee | None) -> dict[str, str] | None:
    if assignee is None:
        return None
    return {"ref": assignee.ref, "name": assignee.display_name}


def site_json(site: Site | None) -> dict[str, str] | None:
    if site is None:
        return None
    return {"ref": site.ref, "name": site.name, "code": site.code, "label": str(site)}


def step_json(step: Step) -> dict[str, Any]:
    return {
        "seq": step.seq,
        "name": step.name,
        "state": str(step.state),
        "state_label": STEP_STATE_LABELS.get(str(step.state), str(step.state)),
        "assignee": assignee_json(step.assignee),
        "due_at": iso(step.due_at),
        "deliverable": step.deliverable,
        "instruction": step.instruction,
        "requires_attachment": step.requires_attachment,
        "optional": step.optional,
        "started_at": iso(step.started_at),
        "finished_at": iso(step.finished_at),
        "finished_by": step.finished_by,
        "comment": step.comment,
        "attachments": list(step.attachments),
        # 被退回重做——前端可据此提示"需重新提交材料"
        "reopened": step.reopened,
    }


def activity_json(activity: Activity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "kind": str(activity.kind),
        "kind_label": ACTIVITY_LABELS.get(str(activity.kind), str(activity.kind)),
        "at": iso(activity.at),
        "actor": activity.actor,
        "step_seq": activity.step_seq,
        "summary": activity.summary,
        "detail": activity.detail,
    }


def task_json(task: TaskInstance, *, include_history: bool = False) -> dict[str, Any]:
    done, total = task.progress
    current = task.current_step
    payload: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "summary": task.summary,
        "state": str(task.state),
        "state_label": STATE_LABELS.get(str(task.state), str(task.state)),
        "priority": task.priority,
        "category": task.category,
        "flow_id": task.flow_id,
        "trigger_note": task.trigger_note,
        "progress": {"done": done, "total": total, "text": f"{done}/{total}"},
        "current_step": (
            {"seq": current.seq, "name": current.name, "assignee": assignee_json(current.assignee),
             "due_at": iso(current.due_at)}
            if current else None
        ),
        "current_assignee": assignee_json(task.current_assignee),
        "site": site_json(task.site),
        "confirmer": assignee_json(task.confirmer),
        "due_at": iso(task.due_at),
        "watchers": [assignee_json(w) for w in task.watchers],
        "tags": list(task.tags),
        "scope": task.scope,
        "steps": [step_json(step) for step in task.steps],
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
        "closed_at": iso(task.closed_at),
    }
    if include_history:
        payload["history"] = [activity_json(act) for act in task.activities]
    return payload


def task_brief(task: TaskInstance) -> dict[str, Any]:
    """列表用的精简视图——省掉节点明细，避免长列表撑爆上下文。"""
    done, total = task.progress
    current = task.current_step
    return {
        "id": task.id,
        "title": task.title,
        "state": str(task.state),
        "state_label": STATE_LABELS.get(str(task.state), str(task.state)),
        "priority": task.priority,
        "category": task.category,
        "progress": f"{done}/{total}",
        "current_step": current.name if current else None,
        "current_assignee": assignee_json(task.current_assignee),
        "site": site_json(task.site),
        "confirmer": assignee_json(task.confirmer),
        "due_at": iso(task.due_at),
        "updated_at": iso(task.updated_at),
    }


def flow_json(flow: TaskFlow) -> dict[str, Any]:
    return {
        "id": flow.id,
        "title": flow.title,
        "summary": flow.summary,
        "category": flow.category,
        "priority": flow.priority,
        "origin": flow.origin,
        "origin_note": flow.origin_note,
        "trigger": {
            "run_mode": str(flow.trigger.run_mode),
            "first_at": iso(flow.trigger.first_at),
            "interval_value": flow.trigger.interval_value,
            "interval_unit": str(flow.trigger.interval_unit),
            "until": iso(flow.trigger.until),
            "max_fires": flow.trigger.max_fires,
            "description": flow.trigger.describe(),
        },
        "watchers": [assignee_json(w) for w in flow.watchers],
        "site": site_json(flow.site),
        "confirmer": assignee_json(flow.confirmer),
        "tags": list(flow.tags),
        "scope": flow.scope,
        "steps": [
            {
                "seq": index,
                "name": spec.name,
                "assignee": assignee_json(spec.assignee),
                "due_offset_days": spec.due_offset_days,
                "deliverable": spec.deliverable,
                "instruction": spec.instruction,
                "requires_attachment": spec.requires_attachment,
                "optional": spec.optional,
            }
            for index, spec in enumerate(flow.steps)
        ],
    }


def schedule_json(schedule: Schedule) -> dict[str, Any]:
    status = "已停用"
    if schedule.active and schedule.paused:
        status = "已暂停"
    elif schedule.active:
        status = "生效中"

    return {
        "id": schedule.id,
        "flow_id": schedule.flow.id,
        "title": schedule.flow.title,
        "status": status,
        "active": schedule.active,
        "paused": schedule.paused,
        "trigger_description": schedule.flow.trigger.describe(),
        "next_fire_at": iso(schedule.next_fire_at),
        "last_fire_at": iso(schedule.last_fire_at),
        "fire_count": schedule.fire_count,
        "last_error": schedule.last_error,
        "step_count": len(schedule.flow.steps),
    }
