"""Final capability checks, including tools discovered after lazy activation."""

from collections.abc import Iterable

from .database_interactions import DatabaseInteractionTool
from ..tool import ToolBase


_DOBBY_TOOLS = frozenset({
    "agent_search", "agent_invoke", "agent_run_status", "agent_cancel",
    "agent_retry_or_switch", "TeamSay", "search_memory", "add_memory", "forget_memory", "learn_from_task", "learning_feedback", "reset_tools",
})
_TASK_DRAFT_TOOLS = frozenset({"generate_task_flow", "list_templates", "create_flow_from_template"})
_MEMORY_SCOPES = frozenset({"user", "user_project", "project"})


class PlatformToolPolicy:
    def __init__(
        self,
        *,
        global_main: bool,
        memory_read_scopes: Iterable[str] = (),
        memory_write_scopes: Iterable[str] = (),
        learning_enabled: bool = False,
        learning_use: bool = False,
    ) -> None:
        self.global_main = global_main
        readable = bool(_MEMORY_SCOPES.intersection(memory_read_scopes))
        writable = bool(_MEMORY_SCOPES.intersection(memory_write_scopes))
        self.memory_tools = {
            "search_memory": readable,
            "add_memory": writable,
            "forget_memory": writable,
            "learn_from_task": writable and learning_enabled,
            "learning_feedback": readable and learning_enabled and learning_use,
        }

    def __call__(self, tool: ToolBase) -> bool:
        if tool.name in {"AgentCreate", "PowerShell"}:
            return False
        if tool.name in self.memory_tools and not self.memory_tools[tool.name]:
            return False
        if isinstance(tool, DatabaseInteractionTool) and tool.table_name == "tasks" and not tool.is_read_only:
            return False
        if self.global_main:
            return tool.name in _DOBBY_TOOLS or (
                isinstance(tool, DatabaseInteractionTool)
                and tool.name not in {"dobby_create_task", "dobby_update_task"}
            )
        if getattr(tool, "mcp_name", None) == "task-engine":
            # Publishing is a platform operation performed after the draft
            # dialog. The agent cannot acquire it by activating an MCP group.
            return tool.name.removeprefix("mcp__task-engine__") in _TASK_DRAFT_TOOLS
        if tool.name.startswith("mcp__wecom-notify__wecom_send_"):
            tool.requires_user_confirmation = True
        return True
