"""Regression tests for the shared Dobby command-execution tool policy."""

from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException

from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._workspace import list_system_tools, list_workspace_tools
from agentscope.app._router._schema._agent import (
    CreateAgentRequest,
    UpdateAgentRequest,
)
from agentscope.app._service._toolkit import (
    PROJECT_DATABASE_TOOL_GROUP,
    _attach_extra_tools,
    _filter_globally_disabled_tools,
)
from agentscope.app.database_interactions import DatabaseInteractionTool
from agentscope.app._types import AgentToolDescriptor
from agentscope.app.storage import AgentToolConfig
from agentscope.tool import Toolkit, ToolGroup
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

    def test_general_platform_database_tools_are_lazy_grouped(self) -> None:
        database_tool = DatabaseInteractionTool(
            definition={
                "key": "dobby_project_overview",
                "description": "读取项目概览",
                "input_schema": {"type": "object", "properties": {}},
                "read_only": True,
            },
            manager=SimpleNamespace(),
            session_id="session-1",
            actor_agent_id="global-main",
            platform_agent_id="global-main",
        )
        direct_tool = SimpleNamespace(name="knowledge_query")
        basic_tools = []
        groups = []

        _attach_extra_tools(
            tools=basic_tools,
            tool_groups=groups,
            extra_tools=[database_tool, direct_tool],
            platform_context=SimpleNamespace(conversation_type="general"),
        )

        self.assertEqual(basic_tools, [direct_tool])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, PROJECT_DATABASE_TOOL_GROUP)
        self.assertEqual(groups[0].tools, [database_tool])

    def test_factory_supplied_lazy_group_remains_unloaded(self) -> None:
        loader = AsyncMock(return_value=[])
        supplied_group = ToolGroup(
            name=PROJECT_DATABASE_TOOL_GROUP,
            description="按需读取当前项目数据",
            tool_loader=loader,
        )
        direct_tool = SimpleNamespace(name="knowledge_query")
        basic_tools = []
        groups = []

        _attach_extra_tools(
            tools=basic_tools,
            tool_groups=groups,
            extra_tools=[supplied_group, direct_tool],
            platform_context=SimpleNamespace(conversation_type="general"),
        )

        self.assertEqual(basic_tools, [direct_tool])
        self.assertEqual(groups, [supplied_group])
        loader.assert_not_awaited()


class LocalWorkspaceToolPolicyTest(IsolatedAsyncioTestCase):
    """The default local workspace must not expose PowerShell."""

    async def test_inactive_lazy_group_does_not_load_runtime_tools(self) -> None:
        database_tool = DatabaseInteractionTool(
            definition={
                "key": "dobby_project_overview",
                "description": "读取项目概览",
                "input_schema": {"type": "object", "properties": {}},
                "read_only": True,
            },
            manager=SimpleNamespace(),
            session_id="session-1",
            actor_agent_id="global-main",
            platform_agent_id="global-main",
        )
        loader = AsyncMock(return_value=[database_tool])
        toolkit = Toolkit(
            tool_groups=[
                ToolGroup(
                    name=PROJECT_DATABASE_TOOL_GROUP,
                    description="按需读取当前项目数据",
                    tool_loader=loader,
                ),
            ],
        )

        inactive_schemas = await toolkit.get_tool_schemas([])

        loader.assert_not_awaited()
        self.assertNotIn(
            database_tool.name,
            [schema["function"]["name"] for schema in inactive_schemas],
        )

        active_schemas = await toolkit.get_tool_schemas(
            [PROJECT_DATABASE_TOOL_GROUP],
        )
        await toolkit.get_tool_schemas([PROJECT_DATABASE_TOOL_GROUP])

        loader.assert_awaited_once_with()
        self.assertIn(
            database_tool.name,
            [schema["function"]["name"] for schema in active_schemas],
        )

    async def test_local_workspace_does_not_list_powershell(self) -> None:
        with TemporaryDirectory() as workdir:
            workspace = LocalWorkspace(workdir=workdir)

            tools = await workspace.list_tools()

            self.assertNotIn("PowerShell", [tool.name for tool in tools])


class AgentOnlyToolCatalogTest(IsolatedAsyncioTestCase):
    """Fixed platform tools are visible before a chat session exists."""

    async def test_system_catalog_needs_no_agent_or_session(self) -> None:
        tools = await list_system_tools(
            principal=AgentScopePrincipal(kind="management", subject="admin"),
            mcp_registry_manager=None,
        )
        by_name = {tool.name: tool for tool in tools}
        self.assertIn("Read", by_name)
        self.assertIn("Write", by_name)
        self.assertNotIn("PowerShell", by_name)
        self.assertTrue(by_name["Read"].read_only)
        self.assertFalse(by_name["Write"].read_only)

    async def test_system_catalog_discovers_fixed_packages_without_executing_them(self) -> None:
        registry = SimpleNamespace(list_system_tool_records=AsyncMock(return_value=[
            SimpleNamespace(tools=[SimpleNamespace(
                name="parse_attachment", display_name="解析附件",
                description="解析当前会话授权附件。", read_only=True,
                input_schema={"type": "object", "properties": {"attachment_id": {"type": "string"}}},
            )]),
        ]))
        tools = await list_system_tools(
            principal=AgentScopePrincipal(kind="management", subject="admin"),
            mcp_registry_manager=registry,
        )
        parser = next(tool for tool in tools if tool.name == "parse_attachment")
        self.assertEqual(parser.display_name, "解析附件")
        self.assertIn("attachment_id", parser.input_schema["properties"])
        registry.list_system_tool_records.assert_awaited_once()

    async def test_system_catalog_rejects_platform_service_principal(self) -> None:
        registry = SimpleNamespace(list_system_tool_records=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await list_system_tools(
                principal=AgentScopePrincipal(kind="service", subject="platform"),
                mcp_registry_manager=registry,
            )
        self.assertEqual(error.exception.status_code, 403)
        registry.list_system_tool_records.assert_not_awaited()

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
        self.assertEqual(system_tool.presentation["label"], "解析附件")
        self.assertEqual(system_tool.presentation["source"], "mcp_title")
        self.assertEqual(by_name["Read"].presentation["label"], "读取文件")
        self.assertEqual(system_tool.source, "platform")
        self.assertEqual(system_tool.category, "general")
        self.assertTrue(system_tool.assigned)
