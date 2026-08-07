"""Regression tests for the shared Dobby command-execution tool policy."""

from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from agentscope.app._router._workspace import list_workspace_tools
from agentscope.app._router._schema._agent import (
    CreateAgentRequest,
    UpdateAgentRequest,
)
from agentscope.app._service._toolkit import (
    _filter_globally_disabled_tools,
)
from agentscope.app._types import AgentToolDescriptor
from agentscope.app.storage import AgentToolConfig
from agentscope.workspace import LocalWorkspace


class GlobalToolPolicyTest(TestCase):
    """PowerShell must stay absent regardless of the contributing source."""

    def test_powershell_is_removed_from_assembled_direct_tools(self) -> None:
        tools = [
            SimpleNamespace(name="Read"),
            SimpleNamespace(name="PowerShell"),
            SimpleNamespace(name="dobby_list_project_items"),
        ]

        filtered = _filter_globally_disabled_tools(tools)

        self.assertEqual(
            [tool.name for tool in filtered],
            ["Read", "dobby_list_project_items"],
        )

    def test_legacy_tool_names_are_retained_but_cannot_disable_tools(self) -> None:
        config = AgentToolConfig(
            allowed_tool_names=[" Read ", "Read", "", "dobby_list_project_items"],
        )

        self.assertEqual(
            config.allowed_tool_names,
            ["Read", "dobby_list_project_items"],
        )
        self.assertTrue(config.allows("Read"))
        self.assertTrue(config.allows("Write"))

    def test_agent_management_schema_has_no_tool_assignment(self) -> None:
        self.assertNotIn("tool_config", CreateAgentRequest.model_fields)
        self.assertNotIn("tool_config", UpdateAgentRequest.model_fields)

class LocalWorkspaceToolPolicyTest(IsolatedAsyncioTestCase):
    """The default local workspace must not expose PowerShell."""

    async def test_local_workspace_does_not_list_powershell(self) -> None:
        with TemporaryDirectory() as workdir:
            workspace = LocalWorkspace(workdir=workdir)

            tools = await workspace.list_tools()

            self.assertNotIn("PowerShell", [tool.name for tool in tools])


class AgentOnlyToolCatalogTest(IsolatedAsyncioTestCase):
    """Fixed platform tools are visible before a chat session exists."""

    async def test_platform_catalog_is_available_without_session(self) -> None:
        storage = SimpleNamespace(
            get_agent=AsyncMock(
                return_value=SimpleNamespace(
                    data=SimpleNamespace(
                        tool_config=AgentToolConfig(
                            allowed_tool_names=["dobby_list_project_items"],
                        ),
                    ),
                ),
            ),
        )

        async def catalog_factory(
            user_id: str,
            agent_id: str,
        ) -> list[AgentToolDescriptor]:
            self.assertEqual(user_id, "admin")
            self.assertEqual(agent_id, "global-main")
            return [
                AgentToolDescriptor(
                    name="dobby_list_project_items",
                    display_name="项目数据查询",
                    description="读取项目数据。",
                    category="database",
                    read_only=True,
                ),
            ]

        result = await list_workspace_tools(
            agent_id="global-main",
            session_id=None,
            user_id="admin",
            principal=object(),
            storage=storage,
            workspace_manager=object(),
            extra_factory=None,
            catalog_factory=catalog_factory,
            mcp_registry_manager=SimpleNamespace(
                list_system_tool_records=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            manifest=SimpleNamespace(name="attachment-parser"),
                            tools=[
                                SimpleNamespace(
                                    name="parse_attachment",
                                    display_name="解析附件",
                                    description="解析平台授权附件。",
                                    input_schema={"type": "object"},
                                    read_only=True,
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        )

        by_name = {tool.name: tool for tool in result}
        self.assertIn("dobby_list_project_items", by_name)
        self.assertIn("Read", by_name)
        self.assertIn("Write", by_name)
        self.assertIn("parse_attachment", by_name)
        self.assertNotIn("PowerShell", by_name)
        self.assertEqual(
            by_name["dobby_list_project_items"].source,
            "platform",
        )
        self.assertEqual(
            by_name["dobby_list_project_items"].category,
            "database",
        )
        self.assertTrue(by_name["dobby_list_project_items"].assigned)
        self.assertTrue(by_name["dobby_list_project_items"].read_only)
        self.assertEqual(by_name["Read"].source, "workspace")
        self.assertEqual(by_name["Read"].category, "workspace")
        self.assertTrue(by_name["Read"].assigned)
        self.assertTrue(by_name["Read"].read_only)
        system_tool = by_name["parse_attachment"]
        self.assertEqual(system_tool.display_name, "解析附件")
        self.assertEqual(system_tool.source, "platform")
        self.assertEqual(system_tool.category, "general")
        self.assertTrue(system_tool.assigned)
