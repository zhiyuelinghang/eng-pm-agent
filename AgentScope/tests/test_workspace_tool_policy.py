"""Regression tests for the shared Dobby command-execution tool policy."""

from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from agentscope.app._service._toolkit import (
    _filter_agent_assigned_tools,
    _filter_globally_disabled_tools,
)
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

    def test_agent_tool_allowlist_controls_assignable_tools(self) -> None:
        tools = [
            SimpleNamespace(name="Read"),
            SimpleNamespace(name="Write"),
            SimpleNamespace(name="dobby_list_project_items"),
        ]

        filtered = _filter_agent_assigned_tools(
            tools,
            ["Read", "dobby_list_project_items"],
        )

        self.assertEqual(
            [tool.name for tool in filtered],
            ["Read", "dobby_list_project_items"],
        )

    def test_unconfigured_agent_keeps_all_assignable_tools(self) -> None:
        tools = [SimpleNamespace(name="Read"), SimpleNamespace(name="Write")]

        self.assertIs(_filter_agent_assigned_tools(tools, None), tools)

    def test_agent_tool_names_are_normalised(self) -> None:
        config = AgentToolConfig(
            allowed_tool_names=[" Read ", "Read", "", "dobby_list_project_items"],
        )

        self.assertEqual(
            config.allowed_tool_names,
            ["Read", "dobby_list_project_items"],
        )
        self.assertTrue(config.allows("Read"))
        self.assertFalse(config.allows("Write"))

class LocalWorkspaceToolPolicyTest(IsolatedAsyncioTestCase):
    """The default local workspace must not expose PowerShell."""

    async def test_local_workspace_does_not_list_powershell(self) -> None:
        with TemporaryDirectory() as workdir:
            workspace = LocalWorkspace(workdir=workdir)

            tools = await workspace.list_tools()

            self.assertNotIn("PowerShell", [tool.name for tool in tools])
