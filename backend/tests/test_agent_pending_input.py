"""Polling has to surface worker consent and later revisions of that consent."""

from unittest.mock import Mock
import pytest

from backend.app.agent_pending_input import pending_input_message
from backend.app.agentscope_client import AgentScopeConfirmationSubmission, AgentScopeGatewayError
from backend.tests.test_agentscope_client import _client


def pending_payload(revision=1):
    return {"messages": [{"id": "user", "role": "user"}, {
        "id": "interim", "role": "assistant", "content": [], "finished_at": "2026-09-05T10:00:00Z",
    }], "subagent_hitl": [{
        "reply_id": "worker-reply", "worker_session_id": "child", "worker_agent_id": "worker",
        "worker_agent_name": "资料助手", "event_type": "require_user_confirm",
        "event": {"tool_calls": [{"id": "call", "name": "write", "input": "{}",
            "confirmation_revision": revision, "confirmation_preview": {"target_name": "方案"}}]},
    }]}


def test_group_poll_returns_pending_worker_confirmation_instead_of_waiting_forever():
    client = _client()
    client.trigger_chat = Mock(return_value="user")
    client.session_status = Mock(return_value="idle")
    client.list_messages = Mock(return_value=pending_payload())
    client.session_team_state = Mock(return_value=(True, True))
    reply = client.chat(agent_id="leader", session_id="root", content="分析", sender_name="成员", metadata={})
    assert reply.status == "awaiting_permission"
    entry = reply.raw_message["metadata"]["platform_runtime_trace"]["subagent_hitl"][0]
    assert entry["event"]["tool_calls"][0]["confirmation_preview"]["target_name"] == "方案"
    client.session_team_state.assert_not_called()


def test_confirmation_wait_returns_the_new_revision_of_a_workers_request():
    client = _client()
    client.list_messages = Mock(return_value=pending_payload(2))
    client.session_status = Mock(return_value="idle")
    tool_call = {"id": "call", "confirmation_revision": 1}
    assert pending_input_message(pending_payload(1), None, tool_call) is None
    reply = client.wait_for_tool_confirmation(
        agent_id="leader", session_id="root", reply_id="worker-reply", tool_call=tool_call,
        submission=AgentScopeConfirmationSubmission(existing_ids={"interim"}, routed_session_id="child"),
        wait_for_collaboration=True,
    )
    assert reply.status == "awaiting_permission"
    assert reply.raw_message["metadata"]["platform_runtime_trace"]["subagent_hitl"]


def test_confirmation_wait_returns_a_new_primary_request_revision():
    client = _client()
    client.list_messages = Mock(return_value={"messages": [{"id": "reply", "role": "assistant",
        "content": [{"type": "tool_call", "id": "call", "state": "asking", "confirmation_revision": 2}],
    }]})
    client.session_status = Mock(return_value="awaiting_permission")
    reply = client.wait_for_tool_confirmation(
        agent_id="leader", session_id="root", reply_id="reply",
        tool_call={"id": "call", "confirmation_revision": 1},
        submission=AgentScopeConfirmationSubmission(existing_ids=set(), routed_session_id="root"),
    )
    assert reply.status == "awaiting_permission"


def test_old_projected_confirmation_is_rejected_before_enqueuing():
    client = _client()
    client.list_messages = Mock(return_value=pending_payload(2))
    client._request = Mock()
    with pytest.raises(AgentScopeGatewayError) as error:
        client.submit_tool_confirmation(agent_id="leader", session_id="root", reply_id="worker-reply",
            tool_call={"id": "call", "confirmation_revision": 1}, confirmed=True)
    assert error.value.status_code == 409
    client._request.assert_not_called()
