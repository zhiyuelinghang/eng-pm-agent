"""Collaboration and scheduling use effective selections, never stale overrides."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._service._toolkit import get_toolkit
from agentscope.app._tool import AgentCreate, AgentInvite, TeamCreate
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import (
    AgentCallConfig,
    AgentData,
    AgentModelPolicy,
    AgentRecord,
    AsyncSQLAlchemyStorage,
    ChatModelConfig,
    InviteConfig,
    PlatformSettingsData,
    SessionConfig,
)
from agentscope.message import ToolResultState


def model(name):
    return ChatModelConfig(
        type="custom_openai_credential", credential_id="fake-credential",
        model=name, parameters={"thinking_enable": False, "temperature": 0.1},
    )


def agent(name, fixed=None):
    return AgentRecord(
        id=name, user_id="owner",
        data=AgentData(
            name=name, context_config=ContextConfig(), react_config=ReActConfig(),
            model_policy=AgentModelPolicy(
                mode="fixed" if fixed else "inherit_session",
                chat_model_config=model(fixed) if fixed else None,
            ),
            call_config=AgentCallConfig(
                scope="selected", allowed_agent_ids=["worker", "nested"],
            ),
            invite_config=InviteConfig(invitable=True, invite_description="执行专项任务"),
        ),
    )


def workspace():
    return SimpleNamespace(
        assign_workspace_id=lambda **kwargs: f"workspace-{kwargs['agent_id']}",
        list_tools=AsyncMock(return_value=[]),
        list_mcps=AsyncMock(return_value=[]),
        list_skills=AsyncMock(return_value=[]),
    )


async def setup_team(storage, bus, workspaces, leader, *workers):
    await storage.upsert_platform_settings("owner", PlatformSettingsData())
    for record in [leader, *workers]:
        await storage.upsert_agent("owner", record)
    await storage.upsert_session(
        "owner", leader.id,
        SessionConfig(
            workspace_id="root", chat_model_config=model("old-session-model"),
            fallback_chat_model_config=model("fallback-model"),
        ),
        session_id="root",
    )
    result = await TeamCreate(storage, bus, workspaces, "owner", "root", leader.id)(
        "测试团队", "只验证模型继承",
    )
    assert result.state != ToolResultState.ERROR, result.content


async def invited_session(storage, result):
    assert result.state != ToolResultState.ERROR, result.content
    member = result.metadata["collaboration_member"]
    return await storage.get_session("owner", member["worker_agent_id"], member["worker_session_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(("leader_fixed", "worker_fixed", "expected"), [
    ("current-fixed-model", None, "current-fixed-model"),
    (None, None, "old-session-model"),
    ("current-fixed-model", "worker-fixed-model", "worker-fixed-model"),
])
async def test_invite_uses_effective_parent_selection_and_respects_target_policy(
    leader_fixed, worker_fixed, expected,
):
    storage = AsyncSQLAlchemyStorage("sqlite+aiosqlite:///:memory:", create_tables=True)
    bus, workspaces = InMemoryMessageBus(), workspace()
    leader, worker, nested = agent("leader", leader_fixed), agent("worker", worker_fixed), agent("nested")
    async with storage:
        await setup_team(storage, bus, workspaces, leader, worker, nested)
        invite = AgentInvite(storage, bus, workspaces, "owner", "root", leader.id, [worker])
        child = await invited_session(storage, await invite("worker@worker", "分析风险"))
        assert child.config.chat_model_config.model == expected
        assert child.config.chat_model_config.parameters == {}
        assert child.config.fallback_chat_model_config.model == "fallback-model"
        assert child.config.fallback_chat_model_config.parameters == {}

        nested_invite = AgentInvite(storage, bus, workspaces, "owner", child.id, worker.id, [nested])
        grandchild = await invited_session(storage, await nested_invite("nested@nested", "核查依据"))
        assert grandchild.config.chat_model_config.model == expected
        assert grandchild.config.chat_model_config.parameters == {}
        assert grandchild.config.fallback_chat_model_config.parameters == {}

        original = await storage.get_session("owner", leader.id, "root")
        assert original.config.chat_model_config.model == "old-session-model"
        assert original.config.chat_model_config.parameters["thinking_enable"] is False


@pytest.mark.asyncio
async def test_reinviting_settled_worker_refreshes_effective_selection():
    storage = AsyncSQLAlchemyStorage("sqlite+aiosqlite:///:memory:", create_tables=True)
    bus, workspaces = InMemoryMessageBus(), workspace()
    leader, worker = agent("leader", "first-fixed-model"), agent("worker")
    async with storage:
        await setup_team(storage, bus, workspaces, leader, worker)
        invite = AgentInvite(storage, bus, workspaces, "owner", "root", leader.id, [worker])
        child = await invited_session(storage, await invite("worker@worker", "第一阶段"))
        team = await storage.get_team("owner", child.team_id)
        member = next(item for item in team.data.members if item.session_id == child.id)
        member.settled_revision = member.work_revision
        member.work_status = "completed"
        await storage.upsert_team("owner", team)
        leader.data.model_policy.chat_model_config = model("new-fixed-model")
        await storage.upsert_agent("owner", leader)
        refreshed = await invited_session(storage, await invite("worker@worker", "第二阶段"))
        assert refreshed.id == child.id
        assert refreshed.config.chat_model_config.model == "new-fixed-model"
        assert refreshed.config.chat_model_config.parameters == {}
        assert refreshed.config.fallback_chat_model_config.parameters == {}


@pytest.mark.asyncio
async def test_created_worker_inherits_effective_leader_without_parameter_overrides():
    storage = AsyncSQLAlchemyStorage("sqlite+aiosqlite:///:memory:", create_tables=True)
    bus, workspaces = InMemoryMessageBus(), workspace()
    leader = agent("leader", "current-fixed-model")
    async with storage:
        await setup_team(storage, bus, workspaces, leader)
        result = await AgentCreate(storage, bus, workspaces, "owner", "root", leader.id)(
            name="temporary", description="专项执行", prompt="完成分析",
        )
        assert result.state != ToolResultState.ERROR, result.content
        root = await storage.get_session("owner", leader.id, "root")
        team = await storage.get_team("owner", root.team_id)
        member = team.data.members[0]
        child = await storage.get_session("owner", member.agent_id, member.session_id)
        assert child.config.chat_model_config.model == "current-fixed-model"
        assert child.config.chat_model_config.parameters == {}
        assert child.config.fallback_chat_model_config.model == "fallback-model"
        assert child.config.fallback_chat_model_config.parameters == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(("fixed", "session_model", "expected"), [
    ("current-fixed-model", "old-session-model", "current-fixed-model"),
    ("current-fixed-model", None, "current-fixed-model"),
    (None, "session-model", "session-model"),
    (None, None, None),
])
async def test_schedule_tool_receives_effective_selection(fixed, session_model, expected):
    storage = AsyncSQLAlchemyStorage("sqlite+aiosqlite:///:memory:", create_tables=True)
    leader, workspaces = agent("leader", fixed), workspace()
    scheduler = SimpleNamespace(list_tools=AsyncMock(return_value=[]))
    async with storage:
        await storage.upsert_platform_settings("owner", PlatformSettingsData())
        await storage.upsert_agent("owner", leader)
        session = await storage.upsert_session("owner", leader.id, SessionConfig(
            workspace_id="root", chat_model_config=model(session_model) if session_model else None,
        ), session_id="root")
        await get_toolkit(
            storage=storage, workspace=workspaces, workspace_manager=workspaces,
            scheduler_manager=scheduler,
            background_task_manager=SimpleNamespace(list_tools=AsyncMock(return_value=[])),
            message_bus=InMemoryMessageBus(), middlewares=[], user_id="owner",
            agent_record=leader, session_record=session,
            resource_access_service=SimpleNamespace(list_resource=AsyncMock(return_value=[])),
        )
        if expected is None:
            scheduler.list_tools.assert_not_awaited()
        else:
            config = scheduler.list_tools.await_args.kwargs["chat_model_config"]
            assert config.model == expected
            assert config.parameters == {}
