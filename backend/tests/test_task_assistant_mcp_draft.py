"""The real MCP envelope must reach the editable task draft intact."""
import copy
import json
from datetime import datetime

import pytest
from task_engine.domain.models import CalendarMode, RunMode, StepSpec, TaskFlow, Trigger
from task_engine.serialize import flow_json

from backend.app.agentscope_client import AgentScopeReply
from backend.app.chat_api import _task_flow_from_agent_reply, _task_draft_payload
from backend.app.schemas import TaskInput


def native_flow():
    return {
        "title": "施工资料核查", "summary": "核对清单并提交结果", "origin": "ai",
        "priority": "high", "origin_note": "由模型生成", "category": "document",
        "trigger": {"run_mode": "recurring", "first_at": "2026-09-10T02:30:00Z",
                    "interval_value": 2, "interval_unit": "week", "max_fires": 3},
        "steps": [{"name": "核对资料清单", "assignee": {"ref": "12", "name": "甲"},
                   "deliverable": "缺项清单", "due_offset_days": 2},
                  {"name": "复核结果", "assignee": None, "deliverable": "核查报告",
                   "due_offset_days": 1}],
        "confirmer": {"ref": "13", "name": "乙"}, "site": {"ref": "14", "name": "工点"},
        "watchers": [{"ref": "15", "name": "丙"}],
    }


@pytest.mark.parametrize("name", ["generate_task_flow", "mcp__task-engine__generate_task_flow"])
def test_real_mcp_envelope_keeps_people_deliverables_and_schedule(name):
    flow = native_flow()
    reply = AgentScopeReply(status="completed", content="草稿已生成", message_id="reply", raw_message=None,
        raw_messages=[{"role": "assistant", "content": [
            {"type": "tool_call", "id": "call", "name": name},
            {"type": "tool_result", "tool_call_id": "call", "state": "success",
             "result": [{"type": "text", "text": json.dumps({"flow": flow, "saved": False})}]},
        ]}])
    parsed = _task_flow_from_agent_reply(reply)
    before = copy.deepcopy(parsed)
    draft = _task_draft_payload(parsed, "核查资料")
    assert parsed == before
    assert draft["assignee_user_id"] == 12
    assert draft["confirmer_user_id"] == 13
    assert draft["wbs_item_id"] == 14
    assert draft["risk_level"] == "high"
    assert draft["workflow_steps"][1]["owner_user_id"] is None
    assert draft["required_materials"] == ["缺项清单", "核查报告"]
    assert draft["workflow_steps"][0]["due_at"] == "2026-09-12"
    assert draft["trigger_date"] == "2026-09-10"
    assert draft["trigger_time"] == "10:30"
    assert draft["run_mode"] == "recurring"
    assert draft["trigger_interval_value"] == 2
    assert draft["trigger_interval_unit"] == "week"
    assert draft["trigger_end_mode"] == "count"
    assert draft["trigger_max_fires"] == 3
    assert draft["cc"] == "丙"
    TaskInput.model_validate(draft)


def test_unrelated_mcp_cannot_satisfy_task_engine_call():
    reply = AgentScopeReply(status="completed", content=json.dumps(native_flow()), message_id="reply",
        raw_message={"content": [{"type": "tool_call", "name": "mcp__other__generate_task_flow"}]})
    with pytest.raises(RuntimeError, match="没有调用"):
        _task_flow_from_agent_reply(reply)


@pytest.mark.parametrize("mode,weekdays,day", [
    (CalendarMode.WEEKLY, (2, 4), None),
    (CalendarMode.MONTHLY, (), 15),
])
def test_native_calendar_schedule_reaches_editable_draft(mode, weekdays, day):
    flow = flow_json(TaskFlow(
        title="合成日历任务", origin="ai",
        trigger=Trigger(
            run_mode=RunMode.CALENDAR,
            first_at=datetime.fromisoformat("2026-09-10T09:00:00+08:00"),
            calendar_mode=mode, calendar_weekdays=weekdays, calendar_day=day,
        ),
        steps=(StepSpec(name="合成节点"),),
    ))
    before = copy.deepcopy(flow)

    draft = TaskInput.model_validate(_task_draft_payload(flow, "合成日历需求"))

    assert flow == before
    assert draft.run_mode == "calendar"
    assert draft.trigger_calendar_mode == mode
    assert draft.trigger_weekdays == list(weekdays)
    assert draft.trigger_day_of_month == day


def test_native_rule_fallback_is_not_accepted_as_ai_draft():
    flow = native_flow()
    flow["origin"] = "rule"
    with pytest.raises(RuntimeError, match="拒绝"):
        _task_draft_payload(flow, "核查资料")


def test_native_automation_keeps_action_and_requires_real_action():
    flow = native_flow()
    action = {"type": "project_chat_message", "channel_id": 5, "content": "核查提醒", "mention_mode": "none"}
    flow["steps"] = [{"name": "发送提醒", "automated": True}]
    flow["scope"] = {"step_actions": {"0": action}}
    draft = _task_draft_payload(flow, "提醒")
    assert draft["action_type"] == "project_chat_message"
    assert draft["target_channel_id"] == 5
    assert draft["workflow_steps"][0]["action"] == action
    flow["scope"] = {}
    with pytest.raises(RuntimeError, match="缺少群聊动作"):
        _task_draft_payload(flow, "提醒")
