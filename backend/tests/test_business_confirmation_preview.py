"""Human confirmation must show real values without mutating business rows."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.tests.test_database_interactions import db, _context, _task_policy
from backend.app.database_interactions import (
    TableInteractionInput, create_table_interaction, update_agent_assignments,
)
from backend.app.database_interaction_router import ExecuteInteractionRequest, preview_interaction
from backend.app.models import OperationLog, Project, Task


def prepare_preview(db, operation="update"):
    context = _context(db)
    policy = _task_policy(db)
    interaction = create_table_interaction(db, TableInteractionInput(
        key=f"preview_task_{operation}", display_name="任务变更", table_policy_id=policy["id"],
        table_operation=operation, requires_confirmation=True,
    ))
    update_agent_assignments(db, context.conversation.agent_id, [interaction["id"]])
    task = Task(project_id=context.project.id, title="原任务", status="pending", task_type="daily_confirm")
    db.add(task)
    db.commit()
    payload = ExecuteInteractionRequest(
        agentscope_session_id=context.conversation.agentscope_session_id,
        actor_agent_id=context.conversation.agent_id, platform_agent_id=context.conversation.agent_id,
        interaction_key=interaction["key"], arguments={"record_id": task.id, "values": {"title": "新任务"}},
    )
    return context, task, payload


def test_preview_shows_before_after_without_performing_the_write(db):
    context, task, payload = prepare_preview(db)
    result = preview_interaction(payload, db)["data"]
    assert result["target_name"] == "原任务"
    assert result["project_name"] == context.project.name
    assert result["affected_count"] == 1
    assert result["changes"] == [{"field": "title", "before": "原任务", "after": "新任务"}]
    db.refresh(task)
    assert task.title == "原任务"
    assert db.scalar(select(OperationLog).where(OperationLog.action == "agent_database_preview"))
    assert not db.scalar(select(OperationLog).where(OperationLog.action == "agent_database_update"))


@pytest.mark.parametrize("attack", ["record", "agent", "field", "assignment"])
def test_preview_rejects_out_of_scope_or_revoked_operations(db, attack):
    context, task, payload = prepare_preview(db)
    if attack == "record":
        other = Project(name="不可访问项目")
        db.add(other)
        db.flush()
        task.project_id = other.id
        db.commit()
    elif attack == "agent":
        payload.platform_agent_id = "other-agent"
    elif attack == "field":
        payload.arguments["values"]["project_id"] = 999
    else:
        update_agent_assignments(db, context.conversation.agent_id, [])
    with pytest.raises(HTTPException):
        preview_interaction(payload, db)
    assert not db.scalar(select(OperationLog).where(OperationLog.action == "agent_database_preview"))
