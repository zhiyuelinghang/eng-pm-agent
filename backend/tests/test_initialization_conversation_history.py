"""Multiple real DB-backed initialization sessions preserve earlier batches."""
import importlib.util
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, update

from backend.tests.test_engineering_knowledge_conversations import db, _admin
from backend.app.agent_conversations_api import create_agent_conversation, list_agent_conversations
from backend.app.models import AgentConversation, Project, ProjectInitializationDraft
from backend.app.schemas import AgentConversationInput


def test_same_project_user_can_start_second_initialization_session_and_keep_old_draft(db):
    user = _admin(db, "multiple-initializations")
    project = Project(name="多轮资料导入")
    db.add(project)
    db.commit()
    gateway = Mock()
    gateway.get_catalog.return_value = {"project_initializer": {"id": "initializer", "name": "资料助手"}}
    gateway.create_session.side_effect = ["initialization-first", "initialization-second"]
    with patch("backend.app.agent_conversations_api._agentscope_client", return_value=gateway):
        first = create_agent_conversation(project.id, AgentConversationInput(
            conversation_type="initialization", title="首批资料",
        ), db, user)["data"]
        draft = ProjectInitializationDraft(project_id=project.id, conversation_id=first["id"],
                                           created_by_user_id=user.id, status="ready", payload={"project": {"construction_unit_name": "首批单位"}})
        db.add(draft)
        db.commit()
        second = create_agent_conversation(project.id, AgentConversationInput(
            conversation_type="initialization", title="更新资料",
        ), db, user)["data"]
    assert first["id"] != second["id"]
    assert first["agentscope_session_id"] != second["agentscope_session_id"]
    assert gateway.create_session.call_args_list[0].kwargs["workspace_id"] != gateway.create_session.call_args_list[1].kwargs["workspace_id"]
    db.execute(update(AgentConversation).where(AgentConversation.id.in_([first["id"], second["id"]])).values(updated_at=datetime(2026, 9, 10, 12, 0)))
    db.commit()
    history = list_agent_conversations(project.id, "initialization", None, db, user)["data"]
    assert {row["id"] for row in history} == {first["id"], second["id"]}
    assert history[0]["id"] == second["id"]
    db.refresh(draft)
    assert draft.conversation_id == first["id"] and draft.payload["project"]["construction_unit_name"] == "首批单位"


def test_incremental_index_migration_preserves_old_session_and_allows_next_batch(db):
    user = _admin(db, "index-migration")
    project = Project(name="迁移前已有会话")
    db.add(project)
    db.flush()
    first = AgentConversation(project_id=project.id, user_id=user.id, agent_id="initializer",
                              agent_name="资料助手", conversation_type="initialization", title="旧会话")
    db.add(first)
    db.commit()
    connection = db.connection()
    connection.exec_driver_sql("DROP INDEX ix_agent_conversations_project_user_initialization")
    connection.exec_driver_sql("CREATE UNIQUE INDEX uq_agent_conversations_project_user_initialization ON agent_conversations(project_id,user_id) WHERE conversation_type = 'initialization'")
    path = Path(__file__).resolve().parents[1] / "alembic/versions/ff95db38c426_允许项目资料多次会话.py"
    spec = importlib.util.spec_from_file_location("initialization_history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    second = AgentConversation(project_id=project.id, user_id=user.id, agent_id="initializer",
                               agent_name="资料助手", conversation_type="initialization", title="新会话")
    db.add(second)
    db.commit()
    assert len(list(db.scalars(select(AgentConversation)))) == 2
    assert db.get(AgentConversation, first.id).title == "旧会话"
    indexes = {item["name"]: item for item in inspect(db.connection()).get_indexes("agent_conversations")}
    assert "uq_agent_conversations_project_user_initialization" not in indexes
    assert not indexes["ix_agent_conversations_project_user_initialization"]["unique"]
