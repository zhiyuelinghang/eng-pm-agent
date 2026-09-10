"""Debug runs must exercise the saved permission policy, including old sessions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._agent_permissions import sync_agent_permission_mode
from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._schema import CreateSessionRequest, UpdateSessionRequest
from agentscope.app._router._session import create_session, update_session
from agentscope.app._service._chat import ChatService
from agentscope.app.storage import (
    AgentData, AgentRecord, PlatformAgentConfig, SessionConfig, SessionRecord,
    SessionSource,
)
from agentscope.message import UserMsg
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.state import AgentState


def setup_case(mode=PermissionMode.EXPLORE):
    agent = AgentRecord(user_id="admin", data=AgentData(
        name="调试助手", platform_config=PlatformAgentConfig(permission_mode=mode),
        context_config=ContextConfig(), react_config=ReActConfig(),
    ))
    session = SessionRecord(
        user_id="admin", agent_id=agent.id,
        config=SessionConfig(workspace_id="debug"),
        state=AgentState(permission_context=PermissionContext(mode=PermissionMode.BYPASS)),
    )
    storage = SimpleNamespace(
        get_platform_settings=AsyncMock(return_value=None),
        get_session=AsyncMock(return_value=session),
        upsert_session=AsyncMock(return_value=session),
    )
    access = SimpleNamespace(resolve_agent=AsyncMock(return_value=agent))
    principal = AgentScopePrincipal(kind="management", subject="admin")
    return agent, session, storage, access, principal


def test_new_debug_session_inherits_saved_policy_without_client_parameter():
    agent, session, storage, access, principal = setup_case()
    response = asyncio.run(create_session(
        body=CreateSessionRequest(agent_id=agent.id), user_id="admin",
        storage=storage, access=access, principal=principal,
        workspace_manager=SimpleNamespace(assign_workspace_id=lambda **_: "debug"),
    ))
    assert response.configuration_applied
    assert storage.upsert_session.await_args.kwargs["state"].permission_context.mode == PermissionMode.EXPLORE


@pytest.mark.parametrize("creating", [True, False])
def test_debug_api_rejects_permission_override(creating):
    agent, session, storage, access, principal = setup_case()
    common = dict(user_id="admin", storage=storage, access=access, principal=principal)
    if creating:
        operation = create_session(
            body=CreateSessionRequest(agent_id=agent.id, permission_mode="bypass"),
            workspace_manager=SimpleNamespace(assign_workspace_id=lambda **_: "debug"),
            **common,
        )
    else:
        operation = update_session(
            session_id=session.id, agent_id=agent.id,
            body=UpdateSessionRequest(permission_mode="bypass"), **common,
        )
    with pytest.raises(HTTPException) as error:
        asyncio.run(operation)
    assert error.value.status_code == 409
    storage.upsert_session.assert_not_awaited()


def test_updating_old_debug_session_drops_stale_mode_override():
    agent, session, storage, access, principal = setup_case()
    asyncio.run(update_session(
        session_id=session.id, agent_id=agent.id,
        body=UpdateSessionRequest(name="历史调试"), user_id="admin",
        storage=storage, access=access, principal=principal,
    ))
    saved = storage.upsert_session.await_args.kwargs
    assert saved["state"].permission_context.mode == PermissionMode.EXPLORE
    assert saved["config"].name == "历史调试"
    assert session.state.permission_context.mode == PermissionMode.BYPASS


@pytest.mark.parametrize("input_msg", [None, UserMsg(name="用户", content="测试")])
def test_runtime_resynchronises_old_and_resumed_debug_sessions_before_execution(input_msg):
    agent, session, storage, access, _ = setup_case()
    service = object.__new__(ChatService)
    service._access = access
    service._storage = storage
    # Stop before constructing tools: inspect the actual runtime assembly path.
    class WorkspaceReached(Exception):
        pass
    service._workspace_manager = SimpleNamespace(
        get_workspace=AsyncMock(side_effect=WorkspaceReached),
    )
    for mode in (PermissionMode.EXPLORE, PermissionMode.DEFAULT):
        agent.data.platform_config.permission_mode = mode
        with pytest.raises(WorkspaceReached):
            asyncio.run(service._run_impl_locked("admin", session.id, agent.id, input_msg))
        assert session.state.permission_context.mode == mode


@pytest.mark.parametrize("source", [SessionSource.SCHEDULE, SessionSource.PLATFORM])
def test_scheduled_and_platform_sessions_retain_their_own_policy(source):
    agent, session, *_ = setup_case()
    session.source = source
    assert sync_agent_permission_mode(agent.data, session) is session.state
    assert session.state.permission_context.mode == PermissionMode.BYPASS


def test_sync_preserves_scoped_permission_rules_and_conversation_state():
    agent, session, *_ = setup_case()
    session.state.middle_context["pending_work"] = {"id": "task-1"}
    original_context = session.state.permission_context.model_dump(exclude={"mode"})
    result = sync_agent_permission_mode(agent.data, session)
    assert result.permission_context.mode == PermissionMode.EXPLORE
    assert result.permission_context.model_dump(exclude={"mode"}) == original_context
    assert result.middle_context["pending_work"] == {"id": "task-1"}
