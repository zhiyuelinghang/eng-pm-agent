"""Group agents must use the requesting user's fresh, auditable data scope."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app import chat_api  # Initialize the public router and its compatibility exports.
from backend.app.agent_context_gateway import get_agent_knowledge_scope, resolve_tool_context
from backend.app.chat_agent_sessions import create_group_agent_session
from backend.app.agent_api_support import _platform_session_context
from backend.app.db import Base
from backend.app.models import (
    AgentConversation, ChatAgentThread, ChatChannel, ChatMessage, EngineeringDocumentNode,
    EngineeringDocumentPermission, EngineeringDocumentSyncState, OperationLog,
    Project, ProjectMember, ProjectSettings, User,
)


@pytest.fixture()
def scoped_project():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="群聊授权项目")
        users = [User(username=f"user-{i}", real_name=f"成员{i}", password_hash="test",
                      identity_card_no=f"scope-{i}", role="user") for i in range(2)]
        db.add_all([project, *users])
        db.flush()
        db.add_all([ProjectMember(project_id=project.id, user_id=user.id) for user in users])
        db.add(ProjectSettings(project_id=project.id, weknora_agent_id="robot"))
        db.add(EngineeringDocumentSyncState(project_id=project.id, weknora_agent_id="robot",
                                           status="ready", access_mode="restricted"))
        for index, user in enumerate(users):
            node = EngineeringDocumentNode(project_id=project.id, node_type="file",
                node_key=f"document-{index}", knowledge_base_id="kb", external_id=f"doc-{index}",
                name=f"资料{index}.pdf")
            db.add(node)
            db.flush()
            db.add(EngineeringDocumentPermission(project_id=project.id, node_id=node.id,
                subject_type="user", subject_id=user.id, can_read=True))
        db.commit()
        yield db, project, users
    engine.dispose()


def test_each_group_request_has_its_own_account_bound_session(scoped_project):
    db, project, users = scoped_project
    channel = ChatChannel(project_id=project.id, channel_type="project", title="项目群")
    db.add(channel)
    db.flush()
    thread = ChatAgentThread(channel_id=channel.id, agent_id="knowledge-agent", agent_name="资料助手")
    db.add(thread)
    db.commit()
    client = MagicMock()
    client.create_session.side_effect = ["session-a", "session-b"]
    conversations = [create_group_agent_session(db, client, user=user, project=project,
        channel=channel, thread=thread, agent={"id": thread.agent_id}) for user in users]
    assert len({item.id for item in conversations}) == 2
    for index, conversation in enumerate(conversations):
        context = resolve_tool_context(db, conversation.agentscope_session_id)
        assert context.user.id == users[index].id
        assert context.project.id == project.id
        envelope = client.create_session.call_args_list[index].kwargs["platform_context"]
        assert envelope["weknora_knowledge_ids"] == [f"doc-{index}"]
    client.sync_session.assert_not_called()


def test_knowledge_scope_is_rechecked_after_document_and_membership_revocation(scoped_project):
    db, project, users = scoped_project
    user = users[0]
    conversation = AgentConversation(project_id=project.id, user_id=user.id,
        agent_id="knowledge-agent", agent_name="资料助手", title="问答",
        agentscope_session_id="scope-session", conversation_type="business")
    db.add(conversation)
    db.commit()
    first = get_agent_knowledge_scope("scope-session", "knowledge-agent", db)["data"]
    assert first["weknora_knowledge_ids"] == ["doc-0"]
    permission = db.scalar(select(EngineeringDocumentPermission).where(
        EngineeringDocumentPermission.subject_id == user.id))
    db.delete(permission)
    db.commit()
    revoked = get_agent_knowledge_scope("scope-session", "knowledge-agent", db)["data"]
    assert revoked["weknora_knowledge_ids"] == []
    logs = db.scalars(select(OperationLog).where(OperationLog.action == "agent_knowledge_authorization")).all()
    assert len(logs) == 2
    assert all(log.operator_id == user.id and log.target_id == conversation.id for log in logs)
    db.delete(db.scalar(select(ProjectMember).where(ProjectMember.user_id == user.id)))
    db.commit()
    with pytest.raises(HTTPException) as error:
        get_agent_knowledge_scope("scope-session", "knowledge-agent", db)
    assert error.value.status_code == 403


def test_greeting_context_does_not_query_the_document_catalogue(scoped_project):
    db, project, users = scoped_project
    conversation = SimpleNamespace(id=1, title="普通聊天", conversation_type="general", agent_name="Dobby")
    with patch.object(db, "get", side_effect=AssertionError("问候不应读取项目资料")):
        context = _platform_session_context(users[0], project, conversation, db,
                                            knowledge_query_enabled=False)
    assert context["user_id"] == str(users[0].id)
    assert context["weknora_query_enabled"] is False


def group_run(scoped_project, status="queued"):
    db, project, users = scoped_project
    channel = ChatChannel(project_id=project.id, channel_type="project", title="项目群")
    db.add(channel)
    db.flush()
    source = ChatMessage(channel_id=channel.id, sender_type="user", sender_user_id=users[0].id,
                         content="请分析", message_type="text")
    db.add(source)
    db.flush()
    from backend.app.chat_agent_runtime import _create_agent_run_placeholder
    run = _create_agent_run_placeholder(db, channel, source, {"id": "agent", "name": "资料助手"})
    conversation = AgentConversation(project_id=project.id, user_id=users[0].id,
        agent_id="agent", agent_name="资料助手", title="群请求", conversation_type="group_chat",
        agentscope_session_id="original-session", status=status)
    db.add(conversation)
    db.flush()
    run.metadata_json = {**run.metadata_json, "runtime_status": status,
        "platform_conversation_id": conversation.id, "agentscope_session_id": "original-session"}
    db.commit()
    return db, users, channel, source, run, conversation


def test_only_requester_can_stop_and_late_reply_cannot_replace_cancellation(scoped_project):
    from backend.app.chat_agent_runtime import stop_chat_agent_run, _persist_chat_agent_reply
    db, users, channel, source, run, conversation = group_run(scoped_project, "running")
    with patch("backend.app.chat_api._agentscope_client") as factory, patch(
        "backend.app.chat_agent_runtime._queue_chat_message_publish",
    ):
        with pytest.raises(HTTPException) as denied:
            stop_chat_agent_run(run.id, db, users[1])
        assert denied.value.status_code == 403
        factory.assert_not_called()
        stop_chat_agent_run(run.id, db, users[0])
        factory.return_value.interrupt.assert_called_once_with(agent_id="agent", session_id="original-session")
        stop_chat_agent_run(run.id, db, users[0])
        assert factory.return_value.interrupt.call_count == 1
        late = _persist_chat_agent_reply(db, channel, source, SimpleNamespace(agent_id="agent"),
            content="过期结果", metadata={"runtime_status": "completed"})
        assert late.metadata_json["runtime_status"] == "interrupted"
        assert "过期" not in late.content
        assert conversation.status == "interrupted"


def test_group_confirmation_resumes_original_session_and_rejects_other_members(scoped_project):
    from backend.app.chat_agent_confirmation import confirm_chat_agent_tool
    from backend.app.agentscope_client import AgentScopeReply
    from backend.app.schemas import AgentConversationConfirmInput
    db, users, channel, source, run, conversation = group_run(scoped_project, "awaiting_permission")
    db.add(ChatAgentThread(channel_id=channel.id, agent_id="agent", agent_name="资料助手",
                           agentscope_session_id="later-users-session"))
    db.commit()
    payload = AgentConversationConfirmInput(reply_id="reply", confirmed=True,
        tool_call={"id": "tool", "name": "test", "input": "{}"})
    with patch("backend.app.chat_api._agentscope_client") as factory, patch(
        "backend.app.chat_agent_runtime._queue_chat_message_publish",
    ):
        with pytest.raises(HTTPException) as denied:
            confirm_chat_agent_tool(run.id, payload, db, users[1])
        assert denied.value.status_code == 403
        factory.assert_not_called()
        factory.return_value.confirm_tool_call.return_value = AgentScopeReply(
            status="completed", content="处理完成", message_id="result",
            raw_message={"id": "result", "role": "assistant", "content": []})
        result = confirm_chat_agent_tool(run.id, payload, db, users[0])["data"]
        assert factory.return_value.confirm_tool_call.call_args.kwargs["session_id"] == "original-session"
        assert factory.return_value.confirm_tool_call.call_args.kwargs["wait_for_collaboration"] is True
        assert result["id"] == run.id
        assert result["metadata"]["runtime_status"] == "completed"
        assert conversation.status == "completed"
        with pytest.raises(HTTPException) as stale:
            confirm_chat_agent_tool(run.id, payload, db, users[0])
        assert stale.value.status_code == 409
