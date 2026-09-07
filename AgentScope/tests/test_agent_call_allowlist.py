"""Regression tests for the caller-to-callee agent allowlist."""

import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._service._toolkit import get_toolkit
from agentscope.app._tool import AgentInvite, AgentInvoke, AgentRetryOrSwitch
from agentscope.app.storage import (
    AgentCallConfig,
    AgentData,
    AgentRecord,
    InviteConfig,
    PlatformAgentConfig,
)
from agentscope.message import TextBlock
from agentscope.tool import ToolChunk


USER_ID = "allowlist-test"
CALLER_ID = "caller"
TARGET_A_ID = "target-a"
TARGET_B_ID = "target-b"


def _agent(
    agent_id: str,
    name: str,
    *,
    invitable: bool = False,
    call_config: AgentCallConfig | None = None,
    platform_config: PlatformAgentConfig | None = None,
) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        user_id=USER_ID,
        data=AgentData(
            name=name,
            context_config=ContextConfig(),
            react_config=ReActConfig(),
            invite_config=InviteConfig(
                invitable=invitable,
                invite_description=f"{name} capability" if invitable else None,
            ),
            call_config=call_config or AgentCallConfig(),
            platform_config=platform_config or PlatformAgentConfig(),
        ),
    )


class AgentCallConfigTest(IsolatedAsyncioTestCase):
    """Validate configuration compatibility and runtime enforcement."""

    def test_old_agent_data_defaults_to_deny(self) -> None:
        old_data = AgentData.model_validate(
            {
                "name": "legacy",
                "context_config": {},
                "react_config": {},
                "invite_config": {},
            },
        )
        self.assertEqual(old_data.call_config.scope, "none")
        self.assertFalse(
            old_data.platform_config.allow_global_main_call,
        )

    def test_selected_ids_are_normalised(self) -> None:
        config = AgentCallConfig(
            scope="selected",
            allowed_agent_ids=[" target-a ", "target-a", ""],
        )
        self.assertEqual(config.allowed_agent_ids, ["target-a"])
        self.assertTrue(config.allows("target-a"))
        self.assertFalse(config.allows("target-b"))

    async def test_toolkit_filters_the_invite_pool(self) -> None:
        all_targets = await self._invite_targets(AgentCallConfig(scope="all"))
        self.assertEqual(len(all_targets or []), 2)
        self.assertFalse(any(target.startswith("Caller@") for target in all_targets or []))

        selected_targets = await self._invite_targets(
            AgentCallConfig(
                scope="selected",
                allowed_agent_ids=[TARGET_A_ID],
            ),
        )
        self.assertEqual(len(selected_targets or []), 1)
        self.assertTrue((selected_targets or [""])[0].startswith("Target A@"))

        self.assertIsNone(
            await self._invite_targets(AgentCallConfig(scope="selected")),
        )
        self.assertIsNone(
            await self._invite_targets(AgentCallConfig(scope="none")),
        )

    async def test_invite_rechecks_latest_call_config(self) -> None:
        target = _agent(TARGET_A_ID, "Target A", invitable=True)
        caller_after_change = _agent(
            CALLER_ID,
            "Caller",
            call_config=AgentCallConfig(scope="none"),
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(
                return_value=SimpleNamespace(team_id="team"),
            ),
            get_team=AsyncMock(
                return_value=SimpleNamespace(id="team", session_id="session"),
            ),
            get_agent=AsyncMock(return_value=caller_after_change),
        )
        tool = AgentInvite(
            storage=storage,
            message_bus=object(),
            workspace_manager=object(),
            user_id=USER_ID,
            session_id="session",
            agent_id=CALLER_ID,
            invitable_pool=[target],
            caller_owner_id=USER_ID,
        )

        selected = tool.input_schema["properties"]["target"]["enum"][0]
        result = await tool(target=selected, prompt="work")

        self.assertIn("no longer allowed", result.content[0].text)
        self.assertEqual(storage.get_agent.await_count, 1)

    async def test_invite_rejects_oversized_prompt_before_team_lookup(self) -> None:
        target = _agent(TARGET_A_ID, "Target A", invitable=True)
        storage = SimpleNamespace(
            get_session=AsyncMock(),
            get_team=AsyncMock(),
            get_agent=AsyncMock(),
        )
        tool = AgentInvite(
            storage=storage,
            message_bus=object(),
            workspace_manager=object(),
            user_id=USER_ID,
            session_id="session",
            agent_id=CALLER_ID,
            invitable_pool=[target],
            caller_owner_id=USER_ID,
        )

        selected = tool.input_schema["properties"]["target"]["enum"][0]
        result = await tool(target=selected, prompt="资料" * 6_001)

        self.assertIn("prompt 过长", result.content[0].text)
        self.assertEqual(storage.get_session.await_count, 0)

    async def test_recovery_rejects_unauthorised_switch_before_cleanup(self) -> None:
        storage = SimpleNamespace(get_session=AsyncMock())
        tool = AgentRetryOrSwitch(
            storage=storage,
            message_bus=object(),
            workspace_manager=object(),
            resource_access_service=SimpleNamespace(
                list_resource=AsyncMock(return_value=[]),
            ),
            user_id=USER_ID,
            session_id="session",
            agent_id=CALLER_ID,
            caller_owner_id=USER_ID,
        )

        result = await tool(
            agent_id="not-authorised",
            task="改用其他专业智能体恢复执行",
        )

        self.assertIn("不在当前 Dobby 授权范围", result.content[0].text)
        storage.get_session.assert_not_awaited()

    async def test_recovery_cleans_failed_run_then_reinvokes_authorised_target(
        self,
    ) -> None:
        target = _agent(
            TARGET_A_ID,
            "Target A",
            invitable=True,
            platform_config=PlatformAgentConfig(
                allow_global_main_call=True,
            ),
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(
                return_value=SimpleNamespace(team_id="failed-team"),
            ),
            get_team=AsyncMock(
                return_value=SimpleNamespace(
                    id="failed-team",
                    session_id="session",
                ),
            ),
        )
        tool = AgentRetryOrSwitch(
            storage=storage,
            message_bus=object(),
            workspace_manager=object(),
            resource_access_service=SimpleNamespace(
                list_resource=AsyncMock(return_value=[target]),
            ),
            user_id=USER_ID,
            session_id="session",
            agent_id=CALLER_ID,
            caller_owner_id=USER_ID,
        )
        reinvoked = ToolChunk(
            content=[TextBlock(text="reinvoked")],
            metadata={"orchestration": {"operation": "invoke"}},
        )

        with (
            patch(
                "agentscope.app._service.SessionService.delete_team",
                new=AsyncMock(),
            ) as delete_team,
            patch.object(
                AgentInvoke,
                "__call__",
                new=AsyncMock(return_value=reinvoked),
            ) as invoke,
        ):
            result = await tool(
                agent_id=TARGET_A_ID,
                task="用新边界重新分析",
                reason="原执行缺少必要资料",
            )

        delete_team.assert_awaited_once_with(USER_ID, "failed-team")
        invoke.assert_awaited_once_with(
            agent_id=TARGET_A_ID,
            task="用新边界重新分析",
        )
        self.assertEqual(
            result.metadata["orchestration"],
            {
                "operation": "retry_or_switch",
                "previous_team_id": "failed-team",
                "reason": "原执行缺少必要资料",
            },
        )

    async def test_global_main_only_sees_explicitly_enabled_targets(
        self,
    ) -> None:
        caller = _agent(
            CALLER_ID,
            "Caller",
            platform_config=PlatformAgentConfig(role="global_main"),
        )
        visible_agents = [
            caller,
            _agent(
                TARGET_A_ID,
                "Published",
                invitable=True,
                platform_config=PlatformAgentConfig(
                    allow_global_main_call=True,
                ),
            ),
            _agent(
                TARGET_B_ID,
                "Unpublished",
                invitable=True,
                platform_config=PlatformAgentConfig(
                    published=False,
                    allow_global_main_call=True,
                ),
            ),
            _agent(
                "internal",
                "Internal",
                invitable=True,
                platform_config=PlatformAgentConfig(
                    role="system_internal",
                    published=False,
                ),
            ),
            _agent(
                "disabled",
                "Disabled",
                invitable=True,
                platform_config=PlatformAgentConfig(
                    enabled=False,
                    allow_global_main_call=True,
                ),
            ),
        ]
        toolkit = await self._toolkit_for(caller, visible_agents)

        self.assertIsNone(await toolkit.get_tool("AgentInvite"))
        expected = {
            "agent_search",
            "agent_invoke",
            "agent_run_status",
            "agent_cancel",
            "agent_retry_or_switch",
        }
        self.assertTrue(
            expected.issubset(
                {tool.name for tool in toolkit.tool_groups[0].tools},
            ),
        )
        search = await toolkit.get_tool("agent_search")
        self.assertIsNotNone(search)
        result = await search(query="capability", limit=5)
        payload = json.loads(result.content[0].text)
        self.assertEqual(
            {item["name"] for item in payload["candidates"]},
            {"Published", "Unpublished"},
        )

    async def test_dynamic_search_ranks_chinese_professional_capability(self) -> None:
        caller = _agent(
            CALLER_ID,
            "Dobby",
            platform_config=PlatformAgentConfig(role="global_main"),
        )
        knowledge = _agent(
            TARGET_A_ID,
            "资料助手",
            invitable=True,
            platform_config=PlatformAgentConfig(
                category="工程资料",
                description="检索施工方案、合同、图纸和验收标准并整理引用",
                allow_global_main_call=True,
                sort_order=10,
            ),
        )
        risk = _agent(
            TARGET_B_ID,
            "风险研判助手",
            invitable=True,
            platform_config=PlatformAgentConfig(
                category="风险管理",
                description="从施工资料识别风险线索并研判等级",
                allow_global_main_call=True,
                sort_order=200,
            ),
        )
        toolkit = await self._toolkit_for(caller, [caller, knowledge, risk])

        search = await toolkit.get_tool("agent_search")
        result = await search(query="请从施工资料中识别风险", limit=1)
        payload = json.loads(result.content[0].text)

        self.assertEqual(payload["candidates"][0]["agent_id"], TARGET_B_ID)

        result = await search(query="施工方案里的验收标准是什么", limit=1)
        payload = json.loads(result.content[0].text)
        self.assertEqual(payload["candidates"][0]["agent_id"], TARGET_A_ID)

    async def test_global_main_rechecks_target_permission(self) -> None:
        caller = _agent(
            CALLER_ID,
            "Caller",
            platform_config=PlatformAgentConfig(role="global_main"),
        )
        target = _agent(
            TARGET_A_ID,
            "Target A",
            invitable=True,
            platform_config=PlatformAgentConfig(
                allow_global_main_call=True,
            ),
        )
        target_after_change = target.model_copy(
            update={
                "data": target.data.model_copy(
                    update={
                        "platform_config": (
                            target.data.platform_config.model_copy(
                                update={"allow_global_main_call": False},
                            )
                        ),
                    },
                ),
            },
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(
                return_value=SimpleNamespace(team_id="team"),
            ),
            get_team=AsyncMock(
                return_value=SimpleNamespace(id="team", session_id="session"),
            ),
            get_agent=AsyncMock(
                side_effect=[caller, target_after_change],
            ),
        )
        tool = AgentInvite(
            storage=storage,
            message_bus=object(),
            workspace_manager=object(),
            user_id=USER_ID,
            session_id="session",
            agent_id=CALLER_ID,
            invitable_pool=[target],
            caller_owner_id=USER_ID,
        )

        selected = tool.input_schema["properties"]["target"]["enum"][0]
        result = await tool(target=selected, prompt="work")

        self.assertIn("no longer invitable", result.content[0].text)
        self.assertEqual(storage.get_agent.await_count, 2)

    async def test_initialization_worker_keeps_runtime_capabilities(
        self,
    ) -> None:
        caller = _agent(
            CALLER_ID,
            "Initializer",
            call_config=AgentCallConfig(
                scope="selected",
                allowed_agent_ids=[TARGET_A_ID],
            ),
            platform_config=PlatformAgentConfig(
                role="system_internal",
                published=False,
                initialization_role="wbs",
            ),
        )
        target = _agent(
            TARGET_A_ID,
            "WBS与进度专家",
            invitable=True,
            call_config=AgentCallConfig(scope="none"),
            platform_config=PlatformAgentConfig(
                role="system_internal",
                published=False,
                allow_global_main_call=False,
            ),
        )
        settings = SimpleNamespace(
            data=SimpleNamespace(
                global_main_agent_id="platform-main",
                project_initializer_agent_id="initializer-main",
            ),
        )
        storage = SimpleNamespace(
            get_team=AsyncMock(return_value=None),
            get_platform_settings=AsyncMock(return_value=settings),
        )
        workspace = SimpleNamespace(
            list_tools=AsyncMock(return_value=[]),
            list_skills=AsyncMock(return_value=[]),
            list_mcps=AsyncMock(return_value=[]),
        )

        toolkit = await get_toolkit(
            storage=storage,
            workspace=workspace,
            workspace_manager=object(),
            scheduler_manager=object(),
            background_task_manager=SimpleNamespace(
                list_tools=AsyncMock(return_value=[]),
            ),
            message_bus=object(),
            middlewares=[],
            user_id=USER_ID,
            agent_record=caller,
            session_record=SimpleNamespace(
                id="session",
                team_id=None,
                config=SimpleNamespace(chat_model_config=None),
            ),
            resource_access_service=SimpleNamespace(
                list_resource=AsyncMock(return_value=[caller, target]),
            ),
        )
        self.assertIsNotNone(await toolkit.get_tool("TaskCreate"))
        self.assertIsNotNone(await toolkit.get_tool("AgentInvite"))

    async def test_home_general_session_hides_direct_task_engine_mcp(
        self,
    ) -> None:
        caller = _agent(CALLER_ID, "Dobby")
        caller.data.mcp_config.allowed_mcp_ids = ["task-engine", "safe-package"]
        settings = SimpleNamespace(
            data=SimpleNamespace(
                global_main_agent_id=CALLER_ID,
                project_initializer_agent_id=None,
                task_assistant_agent_id=None,
            ),
        )
        storage = SimpleNamespace(
            get_team=AsyncMock(return_value=None),
            get_platform_settings=AsyncMock(return_value=settings),
        )
        mcp_registry = SimpleNamespace(
            get_session_clients=AsyncMock(return_value=[]),
        )
        toolkit = await get_toolkit(
            storage=storage,
            workspace=SimpleNamespace(
                list_tools=AsyncMock(return_value=[]),
                list_skills=AsyncMock(return_value=[]),
                list_mcps=AsyncMock(return_value=[]),
            ),
            workspace_manager=object(),
            scheduler_manager=object(),
            background_task_manager=SimpleNamespace(
                list_tools=AsyncMock(return_value=[]),
            ),
            message_bus=object(),
            middlewares=[],
            user_id=USER_ID,
            agent_record=caller,
            session_record=SimpleNamespace(
                id="home-session",
                team_id=None,
                config=SimpleNamespace(
                    chat_model_config=None,
                    platform_context=SimpleNamespace(
                        conversation_type="general",
                    ),
                ),
            ),
            resource_access_service=SimpleNamespace(
                list_resource=AsyncMock(return_value=[caller]),
            ),
            mcp_registry_manager=mcp_registry,
            input_has_attachments=False,
        )

        mcp_registry.get_session_clients.assert_not_awaited()
        self.assertFalse(
            any(
                client.name == "task-engine"
                for group in toolkit.tool_groups
                for client in group.mcps
            ),
        )

    async def _invite_targets(
        self,
        call_config: AgentCallConfig,
    ) -> list[str] | None:
        caller = _agent(
            CALLER_ID,
            "Caller",
            invitable=True,
            call_config=call_config,
        )
        visible_agents = [
            caller,
            _agent(TARGET_A_ID, "Target A", invitable=True),
            _agent(TARGET_B_ID, "Target B", invitable=True),
        ]
        return await self._invite_targets_for(caller, visible_agents)

    async def _invite_targets_for(
        self,
        caller: AgentRecord,
        visible_agents: list[AgentRecord],
    ) -> list[str] | None:
        toolkit = await self._toolkit_for(caller, visible_agents)
        invite = next(
            (
                tool
                for tool in toolkit.tool_groups[0].tools
                if tool.name == "AgentInvite"
            ),
            None,
        )
        if invite is None:
            return None
        return invite.input_schema["properties"]["target"]["enum"]

    async def _toolkit_for(
        self,
        caller: AgentRecord,
        visible_agents: list[AgentRecord],
    ):
        workspace = SimpleNamespace(
            list_tools=AsyncMock(return_value=[]),
            list_skills=AsyncMock(return_value=[]),
            list_mcps=AsyncMock(return_value=[]),
        )
        toolkit = await get_toolkit(
            storage=SimpleNamespace(
                get_team=AsyncMock(return_value=None),
                get_session=AsyncMock(
                    return_value=SimpleNamespace(
                        config=SimpleNamespace(platform_context=None),
                    ),
                ),
            ),
            workspace=workspace,
            workspace_manager=object(),
            scheduler_manager=object(),
            background_task_manager=SimpleNamespace(
                list_tools=AsyncMock(return_value=[]),
            ),
            message_bus=object(),
            middlewares=[],
            user_id=USER_ID,
            agent_record=caller,
            session_record=SimpleNamespace(
                id="session",
                team_id=None,
                config=SimpleNamespace(chat_model_config=None),
            ),
            resource_access_service=SimpleNamespace(
                list_resource=AsyncMock(return_value=visible_agents),
            ),
        )
        return toolkit
