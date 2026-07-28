"""Regression tests for the caller-to-callee agent allowlist."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._service._toolkit import get_toolkit
from agentscope.app._tool import AgentInvite
from agentscope.app.storage import (
    AgentCallConfig,
    AgentData,
    AgentRecord,
    InviteConfig,
    PlatformAgentConfig,
)


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

    def test_old_agent_data_defaults_to_all(self) -> None:
        old_data = AgentData.model_validate(
            {
                "name": "legacy",
                "context_config": {},
                "react_config": {},
                "invite_config": {},
            },
        )
        self.assertEqual(old_data.call_config.scope, "all")

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

    async def test_global_main_sees_all_enabled_non_main_agents(self) -> None:
        caller = _agent(
            CALLER_ID,
            "Caller",
            platform_config=PlatformAgentConfig(role="global_main"),
        )
        visible_agents = [
            caller,
            _agent(TARGET_A_ID, "Published", invitable=True),
            _agent(
                TARGET_B_ID,
                "Unpublished",
                invitable=True,
                platform_config=PlatformAgentConfig(published=False),
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
                platform_config=PlatformAgentConfig(enabled=False),
            ),
        ]
        targets = await self._invite_targets_for(caller, visible_agents)

        self.assertEqual(len(targets or []), 3)
        self.assertTrue(
            any(target.startswith("Published@") for target in targets or []),
        )
        self.assertTrue(
            any(target.startswith("Unpublished@") for target in targets or []),
        )
        self.assertTrue(
            any(target.startswith("Internal@") for target in targets or []),
        )
        self.assertFalse(
            any(target.startswith("Disabled@") for target in targets or []),
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
        workspace = SimpleNamespace(
            list_tools=AsyncMock(return_value=[]),
            list_skills=AsyncMock(return_value=[]),
            list_mcps=AsyncMock(return_value=[]),
        )
        toolkit = await get_toolkit(
            storage=SimpleNamespace(get_team=AsyncMock(return_value=None)),
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
