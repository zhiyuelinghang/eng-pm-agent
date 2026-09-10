"""Executable regressions for the v1.1 collaboration and confirmation boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agentscope.agent import Agent, ContextConfig, ReActConfig
from agentscope.app._service._chat import ChatService
from agentscope.app._service._permission_review import PermissionReviewerMiddleware
from agentscope.app._service._toolkit import get_toolkit
from agentscope.app._tool import AgentInvite, AgentInvoke
from agentscope.app.database_interactions import DatabaseInteractionTool
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app._platform_tool_policy import PlatformToolPolicy
from agentscope.app._tool._team_say import TeamSay
from agentscope.app.storage import PlatformSettingsRecord, PlatformSettingsData
from agentscope.app.storage import (
    AgentCallConfig, AgentData, AgentRecord, InviteConfig, PlatformAgentConfig,
    SessionConfig, SessionRecord, TeamData, TeamMember, TeamRecord,
    AsyncSQLAlchemyStorage,
)
from agentscope.event import RequireUserConfirmEvent, UserConfirmResultEvent, ConfirmResult
from agentscope.message import AssistantMsg, ToolCallBlock, ToolCallState, ToolResultState, UserMsg
from agentscope.permission import (
    PermissionBehavior, PermissionContext, PermissionMode, PermissionRule,
)
from agentscope.state import AgentState
from agentscope.tool import Toolkit
from agentscope.types import ReplyFinishedReason


def agent_record(agent_id, *, main=False, enabled=True):
    return AgentRecord(
        id=agent_id, user_id="owner",
        data=AgentData(
            name=agent_id, context_config=ContextConfig(), react_config=ReActConfig(),
            invite_config=InviteConfig(invitable=True, invite_description="专项分析"),
            call_config=AgentCallConfig(scope="selected", allowed_agent_ids=["worker"]),
            platform_config=PlatformAgentConfig(
                role="global_main" if main else "business", enabled=enabled,
                allow_global_main_call=True,
            ),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [
    PermissionMode.DEFAULT, PermissionMode.AUTO, PermissionMode.ACCEPT_EDITS,
    PermissionMode.BYPASS,
])
async def test_business_confirmation_survives_modes_and_saved_allow_rules(mode):
    manager = AsyncMock()
    manager.preview_interaction.return_value = {"target_name": "资料7", "changes": []}
    tool = DatabaseInteractionTool(
        definition={
            "key": "dobby_update_document_category", "description": "修改资料分类",
            "input_schema": {"type": "object", "properties": {"record_id": {"type": "integer"}}}, "read_only": False,
            "requires_confirmation": True,
        }, manager=manager, session_id="root", actor_agent_id="dobby",
        platform_agent_id="dobby",
    )
    tool_call = ToolCallBlock(id="write", name=tool.name, input='{"record_id":7}')
    reviewer = SimpleNamespace(review=AsyncMock())
    runner = Agent(
        name="Dobby", system_prompt="test",
        model=SimpleNamespace(count_tokens=AsyncMock(return_value=1)),
        toolkit=Toolkit(tools=[tool]),
        state=AgentState(
            context=[UserMsg(name="user", content="改分类"),
                     AssistantMsg(name="Dobby", content=[tool_call])],
            permission_context=PermissionContext(mode=mode, allow_rules={
                tool.name: [PermissionRule(tool_name=tool.name, rule_content=None, source="user",
                                          behavior=PermissionBehavior.ALLOW)],
            }),
        ),
        middlewares=[PermissionReviewerMiddleware(reviewer)],
    )
    events = [event async for event in runner._execute_tool_call(tool_call)]
    assert any(isinstance(event, RequireUserConfirmEvent) for event in events)
    assert tool_call.confirmation_preview["target_name"] == "资料7"
    manager.execute_interaction.assert_not_awaited()
    reviewer.review.assert_not_awaited()

    changed = tool_call.model_copy(update={"input": '{"record_id":8}'})
    confirmation = UserConfirmResultEvent(reply_id=runner.state.context[-1].id,
        confirm_results=[ConfirmResult(confirmed=True, tool_call=changed)])
    async for _ in runner._handle_incoming_event(confirmation):
        pass
    assert tool_call.state == ToolCallState.PENDING
    manager.preview_interaction.return_value = {"target_name": "资料8", "changes": []}
    retry_events = [event async for event in runner._execute_tool_call(tool_call)]
    assert any(isinstance(event, RequireUserConfirmEvent) for event in retry_events)
    assert tool_call.confirmation_preview["target_name"] == "资料8"
    assert tool_call.confirmation_revision == 2
    manager.execute_interaction.assert_not_awaited()
    async for _ in runner._handle_incoming_event(confirmation):
        pass
    assert tool_call.state == ToolCallState.ASKING


@pytest.mark.asyncio
@pytest.mark.parametrize(("main", "revoked_field"), [
    (True, "enabled"), (True, "allow_global_main_call"),
    (False, "enabled"), (False, "invitable"),
])
async def test_invitation_rechecks_target_permission_after_catalogue_load(main, revoked_field):
    caller, original = agent_record("caller", main=main), agent_record("worker")
    revoked = agent_record("worker")
    if revoked_field == "invitable":
        revoked.data.invite_config.invitable = False
    else:
        setattr(revoked.data.platform_config, revoked_field, False)
    storage = SimpleNamespace(get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id="test", data=PlatformSettingsData(global_main_agent_id='caller' if main else None))),
        get_session=AsyncMock(return_value=SimpleNamespace(team_id="team")),
        get_team=AsyncMock(return_value=SimpleNamespace(id="team", session_id="root")),
        get_agent=AsyncMock(side_effect=[caller, revoked]),
        upsert_session=AsyncMock(),
    )
    invite = AgentInvite(storage, object(), object(), "owner", "root", "caller", [original])
    result = await invite("worker@worker", "执行分析")
    assert result.state == ToolResultState.ERROR
    assert "no longer invitable" in result.content[0].text
    storage.upsert_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_flags", [False, True])
async def test_completed_worker_can_receive_next_stage_without_recreating_team(legacy_flags):
    caller, worker = agent_record("dobby", main=True), agent_record("worker")
    worker.data.invite_config.invitable = legacy_flags
    worker.data.invite_config.invite_description = "专项分析" if legacy_flags else None
    worker.data.platform_config.allow_global_main_call = True
    root = SessionRecord(id="root", user_id="owner", agent_id="dobby", team_id="team",
                         config=SessionConfig(workspace_id="root-workspace"))
    borrowed = SessionRecord(id="borrowed", user_id="owner", agent_id="worker",
                             team_id="team", config=SessionConfig(workspace_id="worker-workspace"))
    team = TeamRecord(id="team", user_id="owner", session_id="root", data=TeamData(
        name="协同", work_revision=1, leader_completed_revision=1,
        members=[TeamMember(owner_id="owner", agent_id="worker", session_id="borrowed",
                            role="invited", work_revision=1, settled_revision=1,
                            work_status="completed")],
    ))
    storage = SimpleNamespace(
        get_session=AsyncMock(side_effect=lambda _u, _a, sid: root if sid == "root" else borrowed),
        get_agent=AsyncMock(side_effect=lambda _u, aid: caller if aid == "dobby" else worker),
        get_team=AsyncMock(return_value=team),
        upsert_team=AsyncMock(), upsert_session=AsyncMock(return_value=borrowed),
        get_platform_settings=AsyncMock(return_value=SimpleNamespace(
            data=SimpleNamespace(global_main_agent_id="dobby"))),
    )
    invoke = AgentInvoke(storage, InMemoryMessageBus(), object(),
                         SimpleNamespace(list_resource=AsyncMock(return_value=[caller, worker])),
                         "owner", "root", "dobby")
    with patch("agentscope.app._tool._team_say.deliver_team_message", new_callable=AsyncMock) as deliver:
        result = await invoke("worker", "根据前一阶段继续分析")
    assert result.state != ToolResultState.ERROR
    assert team.data.members[0].work_revision == 2
    assert team.data.members[0].work_status == "queued"
    assert deliver.await_args.kwargs["recipient_session_id"] == "borrowed"
    assert result.metadata["collaboration_member"]["work_revision"] == 2

    # Already being a team member must not bypass later permission revocation.
    worker.data.platform_config.allow_global_main_call = False
    say = TeamSay(storage, InMemoryMessageBus(), object(), "owner", "root", "dobby", role="leader")
    with patch("agentscope.app._tool._team_say.deliver_team_message", new_callable=AsyncMock) as deliver:
        denied = await say("再执行下一阶段", to="worker@worker")
    assert denied.state == ToolResultState.ERROR
    deliver.assert_not_awaited()
    assert team.data.members[0].work_revision == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [False, True])
async def test_user_stop_also_cancels_the_leaders_workers(running):
    service = object.__new__(ChatService)
    service._storage = SimpleNamespace(get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id="test", data=PlatformSettingsData(global_main_agent_id='dobby'))),
        get_session=AsyncMock(return_value=SimpleNamespace(
            id="root", team_id="team", state=SimpleNamespace(reply_id="reply"))),
        get_team=AsyncMock(return_value=SimpleNamespace(id="team", session_id="root")),
    )
    service._message_bus = SimpleNamespace(is_locked=AsyncMock(return_value=running),
                                           publish=AsyncMock())
    with (
        patch("agentscope.app._service._session.SessionService.delete_team", new_callable=AsyncMock) as cancel,
        patch("agentscope.app._service._chat.enqueue_run_trigger", new_callable=AsyncMock),
    ):
        await service.interrupt("owner", "root", "dobby")
    cancel.assert_awaited_once_with("owner", "team")


@pytest.mark.asyncio
async def test_dobby_capability_boundary_also_applies_outside_homepage():
    caller = agent_record("dobby", main=True)
    workspace = SimpleNamespace(list_tools=AsyncMock(return_value=[]),
                                list_mcps=AsyncMock(return_value=[]),
                                list_skills=AsyncMock(return_value=[]))
    registry = SimpleNamespace(get_session_clients=AsyncMock(return_value=[]))
    await get_toolkit(
        storage=SimpleNamespace(get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id="test", data=PlatformSettingsData(global_main_agent_id='dobby'))), ), workspace=workspace, workspace_manager=object(),
        scheduler_manager=object(), background_task_manager=SimpleNamespace(list_tools=AsyncMock(return_value=[])),
        message_bus=object(), middlewares=[], user_id="owner", agent_record=caller,
        session_record=SessionRecord(id="root", user_id="owner", agent_id="dobby",
                                     config=SessionConfig(workspace_id="root-workspace")),
        resource_access_service=SimpleNamespace(list_resource=AsyncMock(return_value=[])),
        mcp_registry_manager=registry,
    )
    workspace.list_tools.assert_not_awaited()
    workspace.list_mcps.assert_not_awaited()
    workspace.list_skills.assert_not_awaited()
    registry.get_session_clients.assert_not_awaited()


@pytest.mark.asyncio
async def test_invited_management_agent_keeps_its_explicit_call_allowlist():
    caller, worker = agent_record("manager"), agent_record("worker")
    session = SessionRecord(id="manager-session", user_id="owner", agent_id="manager",
                            team_id="team", config=SessionConfig(workspace_id="workspace"))
    root = SessionRecord(id='root', user_id='owner', agent_id='dobby', team_id='team',
                         config=SessionConfig(workspace_id='root-workspace'))
    team = TeamRecord(id='team', user_id='owner', session_id='root', data=TeamData(name='协作团队', members=[
        TeamMember(owner_id='owner', agent_id='manager', session_id=session.id,
                   role='invited', inviter_session_id='root'),
    ]))
    storage = SimpleNamespace(
        get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id='owner',
            data=PlatformSettingsData(global_main_agent_id='dobby'))),
        get_team=AsyncMock(return_value=team),
        get_session=AsyncMock(return_value=root),
        get_agent=AsyncMock(return_value=agent_record('dobby', main=True)),
    )
    toolkit = await get_toolkit(
        storage=storage,
        workspace=SimpleNamespace(list_tools=AsyncMock(return_value=[]), list_mcps=AsyncMock(return_value=[]),
                                  list_skills=AsyncMock(return_value=[])),
        workspace_manager=object(), scheduler_manager=object(),
        background_task_manager=SimpleNamespace(list_tools=AsyncMock(return_value=[])),
        message_bus=object(), middlewares=[], user_id="owner", agent_record=caller,
        session_record=session,
        resource_access_service=SimpleNamespace(list_resource=AsyncMock(return_value=[caller, worker])),
    )
    invite = await toolkit.get_tool("AgentInvite")
    assert invite is not None
    assert invite.input_schema["properties"]["target"]["enum"] == ["worker@worker"]

    worker.data.invite_config.invitable = False
    assert not caller.data.call_config.allowed_agent_ids == []
    toolkit = await get_toolkit(
        storage=storage,
        workspace=SimpleNamespace(list_tools=AsyncMock(return_value=[]), list_mcps=AsyncMock(return_value=[]),
                                  list_skills=AsyncMock(return_value=[])),
        workspace_manager=object(), scheduler_manager=object(),
        background_task_manager=SimpleNamespace(list_tools=AsyncMock(return_value=[])),
        message_bus=object(), middlewares=[], user_id="owner", agent_record=caller,
        session_record=session,
        resource_access_service=SimpleNamespace(list_resource=AsyncMock(return_value=[caller, worker])),
    )
    assert await toolkit.get_tool("AgentInvite") is None


@pytest.mark.asyncio
async def test_nested_delegation_reports_to_caller_and_keeps_parent_pending():
    storage = AsyncSQLAlchemyStorage("sqlite+aiosqlite:///:memory:", create_tables=True)
    bus = InMemoryMessageBus()
    caller, manager, worker = agent_record("dobby", main=True), agent_record("manager"), agent_record("worker")
    workspace = SimpleNamespace(assign_workspace_id=lambda **kwargs: f"workspace-{kwargs['agent_id']}")
    async with storage:
        await storage.upsert_platform_settings("owner", PlatformSettingsData(global_main_agent_id="dobby"))
        for record in [caller, manager, worker]:
            await storage.upsert_agent("owner", record)
        await storage.upsert_session("owner", "worker", SessionConfig(workspace_id="other-users-private-files"),
                                     session_id="unrelated-worker-session")
        await storage.upsert_session("owner", "dobby", SessionConfig(workspace_id="root",
            platform_context={"user_id": "account-a", "username": "member", "display_name": "成员",
                "project_id": "project-a", "project_name": "项目", "conversation_id": "conversation-a",
                "conversation_title": "协同", "conversation_type": "general", "agent_name": "Dobby"}),
            session_id="root")
        invoke = AgentInvoke(storage, bus, workspace,
            SimpleNamespace(list_resource=AsyncMock(return_value=[manager])), "owner", "root", "dobby")
        result = await invoke("manager", "组织专项分析")
        assert result.state != ToolResultState.ERROR, result.content
        manager_sid = result.metadata["collaboration_member"]["worker_session_id"]
        nested = AgentInvite(storage, bus, workspace, "owner", manager_sid, "manager", [worker])
        result = await nested("worker@worker", "分析施工风险")
        assert result.state != ToolResultState.ERROR, result.content
        child_sid = result.metadata["collaboration_member"]["worker_session_id"]
        child = await storage.get_session("owner", "worker", child_sid)
        assert child.config.workspace_id != "other-users-private-files"
        assert child.config.platform_context.user_id == "account-a"
        team_id = result.metadata["collaboration_member"]["team_id"]
        team = await storage.get_team("owner", team_id)
        assert next(m for m in team.data.members if m.session_id == child_sid).inviter_session_id == manager_sid
        # Revoking invitation consent blocks a new assignment through an
        # existing team membership, even while the caller's saved ID remains.
        worker.data.invite_config.invitable = False
        await storage.upsert_agent("owner", worker)
        manager_say = TeamSay(storage, bus, workspace, "owner", manager_sid, "manager", role="worker")
        with patch("agentscope.app._tool._team_say.deliver_team_message", new_callable=AsyncMock) as deliver:
            denied = await manager_say("继续执行", to="worker@worker")
            assert denied.state == ToolResultState.ERROR
            deliver.assert_not_awaited()
        service = object.__new__(ChatService)
        service._storage, service._message_bus = storage, bus
        reply = AssistantMsg(name="manager", content="等待专项结果", finished_reason=ReplyFinishedReason.COMPLETED)
        with patch("agentscope.app._service._chat.deliver_team_message", new_callable=AsyncMock) as deliver:
            await service._auto_report_worker_reply(user_id="owner", session_id=manager_sid,
                agent_id="manager", agent_record=manager, reply_msg=reply)
            deliver.assert_not_awaited()
            team = await storage.get_team("owner", team_id)
            assert next(m for m in team.data.members if m.session_id == manager_sid).settled_revision == 0
            await service._auto_report_worker_reply(user_id="owner", session_id=child_sid,
                agent_id="worker", agent_record=worker,
                reply_msg=AssistantMsg(name="worker", content="风险分析完成", finished_reason=ReplyFinishedReason.COMPLETED))
            assert deliver.await_args.kwargs["recipient_session_id"] == manager_sid
        # A worker may report to its caller, but team membership alone cannot
        # authorize it to dispatch the other worker's next stage.
        worker.data.call_config = AgentCallConfig(scope="none")
        await storage.upsert_agent("owner", worker)
        say = TeamSay(storage, bus, workspace, "owner", child_sid, "worker", role="worker")
        with patch("agentscope.app._tool._team_say.deliver_team_message", new_callable=AsyncMock) as deliver:
            result = await say("越过上级启动总控", to="dobby")
            assert result.state == ToolResultState.ERROR
            deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_lazy_task_engine_tools_cannot_publish_or_read_unscoped_tasks():
    from mcp.types import Tool
    from agentscope.tool import MCPTool, ToolGroup

    names = ["generate_task_flow", "dispatch_task", "create_schedule", "list_tasks"]
    tools = [MCPTool("task-engine", Tool(name=name, inputSchema={"type": "object", "properties": {}}),
                     session=SimpleNamespace()) for name in names]
    toolkit = Toolkit(tool_groups=[ToolGroup(name="drafts", description="任务草稿",
        tool_loader=AsyncMock(return_value=tools))],
        tool_policy=PlatformToolPolicy(global_main=False))
    assert await toolkit.get_tool("mcp__task-engine__generate_task_flow") is not None
    for name in names[1:]:
        assert await toolkit.get_tool(f"mcp__task-engine__{name}") is None
    custom_write = DatabaseInteractionTool(definition={
        "key": "custom_task_writer", "input_schema": {"type": "object"},
        "read_only": False, "requires_confirmation": True, "policy": {"table_name": "tasks"},
    }, manager=AsyncMock(), session_id="root", actor_agent_id="agent", platform_agent_id="agent")
    for main in (True, False):
        assert not PlatformToolPolicy(global_main=main)(custom_write)


@pytest.mark.asyncio
async def test_polling_projection_filters_resolved_worker_prompts():
    from agentscope.app._router._session import list_messages
    from agentscope.app._service._session_projection import SessionProjection
    from agentscope.app._service._projectors._subagent_hitl import SubagentHitlProjector

    bus = InMemoryMessageBus()
    call = ToolCallBlock(id="call", name="write", input="{}", state=ToolCallState.ASKING,
                         confirmation_preview={"target_name": "方案"})
    worker = SessionRecord(id="child", user_id="owner", agent_id="worker",
        config=SessionConfig(workspace_id="worker"),
        state=AgentState(context=[AssistantMsg(id="reply", name="worker", content=[call])]))
    root = SessionRecord(id="root", user_id="owner", agent_id="leader",
                         config=SessionConfig(workspace_id="root"))
    storage = SimpleNamespace(get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id="test", data=PlatformSettingsData(global_main_agent_id='dobby'))),
        get_session=AsyncMock(side_effect=lambda user, agent, sid: root if sid == "root" else worker),
        list_messages=AsyncMock(return_value=([], False)))
    projection = SessionProjection(bus)
    await projection.upsert("root", SubagentHitlProjector.KIND, "child:reply", {
        "worker_agent_id": "worker", "worker_session_id": "child", "reply_id": "reply",
        "event_type": "require_user_confirm", "event": {"tool_calls": [call.model_dump()]},
    })
    with patch("agentscope.app._router._session.require_runtime_session_access"):
        response = await list_messages(session_id="root", agent_id="leader", before=None, offset=None,
            limit=50, user_id="owner", principal=object(), storage=storage, message_bus=bus)
        assert response.subagent_hitl[0]["event"]["tool_calls"][0]["confirmation_preview"]["target_name"] == "方案"
        call.state = ToolCallState.FINISHED
        response = await list_messages(session_id="root", agent_id="leader", before=None, offset=None,
            limit=50, user_id="owner", principal=object(), storage=storage, message_bus=bus)
        assert response.subagent_hitl == []
