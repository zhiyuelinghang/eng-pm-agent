"""Adapt a task-engine MCP flow to the platform's editable draft contract."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def _reference(value: Any) -> int | None:
    ref = value.get("ref") if isinstance(value, dict) else None
    try:
        number = int(ref)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.astimezone(ZoneInfo("Asia/Shanghai")) if moment.tzinfo else moment


def normalize_task_flow(flow: dict[str, Any]) -> dict[str, Any]:
    """Keep existing platform flows; translate native MCP fields without writes."""
    trigger = flow.get("trigger")
    if not isinstance(trigger, dict):
        return flow
    if flow.get("origin") not in (None, "ai"):
        raise RuntimeError("任务引擎未返回 AI 生成结果，已拒绝使用替代草稿")
    first_at = _moment(trigger.get("first_at"))
    due_at = first_at
    scope = flow.get("scope") or {}
    actions = scope.get("step_actions") or {}
    steps = []
    for index, original in enumerate(flow.get("steps") or []):
        step = dict(original)
        assignee = step.get("assignee")
        step.setdefault("owner_user_id", _reference(assignee))
        step.setdefault("owner", assignee.get("name", "") if isinstance(assignee, dict) else "")
        step.setdefault("material", str(step.get("deliverable") or ""))
        step.setdefault("node_type", "project_chat_message" if step.get("automated") else "manual")
        if step["node_type"] == "project_chat_message":
            action = step.get("action") or actions.get(str(index))
            if action is None and index == 0:
                action = scope.get("action")
            if not isinstance(action, dict) or action.get("type") != "project_chat_message":
                raise RuntimeError(f"任务引擎返回的第 {index + 1} 个自动节点缺少群聊动作")
            step["action"] = dict(action)
        elif due_at is not None:
            due_at += timedelta(days=max(0, int(step.get("due_offset_days") or 0)))
            step.setdefault("due_at", due_at.strftime("%Y-%m-%d"))
        steps.append(step)
    until = _moment(trigger.get("until"))
    max_fires = trigger.get("max_fires")
    return {
        **flow,
        "steps": steps,
        "risk_level": flow.get("risk_level") or {
            "low": "low", "normal": "medium", "high": "high", "urgent": "critical",
        }.get(flow.get("priority"), "medium"),
        "assignee_user_id": flow.get("assignee_user_id") or next(
            (step["owner_user_id"] for step in steps if step.get("node_type") == "manual" and step.get("owner_user_id")), None,
        ),
        "confirmer_user_id": flow.get("confirmer_user_id") or _reference(flow.get("confirmer")),
        "wbs_item_id": flow.get("wbs_item_id") or _reference(flow.get("site")),
        "run_mode": trigger.get("run_mode") or "once",
        "trigger_date": first_at.strftime("%Y-%m-%d") if first_at else None,
        "trigger_time": first_at.strftime("%H:%M") if first_at else "09:00",
        "trigger_interval_value": trigger.get("interval_value") or 1,
        "trigger_interval_unit": trigger.get("interval_unit") or "week",
        "trigger_rule": trigger.get("description"),
        "trigger_end_mode": "until" if until else "count" if max_fires else "never",
        "trigger_until_date": until.strftime("%Y-%m-%d") if until else None,
        "trigger_max_fires": max_fires,
        "trigger_calendar_mode": trigger.get("calendar_mode") or "weekdays",
        "trigger_weekdays": trigger.get("calendar_weekdays") or [],
        "trigger_day_of_month": trigger.get("calendar_day"),
        "cc": "，".join(str(person.get("name") or "") for person in flow.get("watchers") or [] if isinstance(person, dict)),
        "generation_note": flow.get("origin_note"),
    }
