"""Final capability checks, including tools discovered after lazy activation."""

from .database_interactions import DatabaseInteractionTool
from ..tool import ToolBase


_DOBBY_TOOLS = frozenset({
    "agent_search", "agent_invoke", "agent_run_status", "agent_cancel",
    "agent_retry_or_switch", "search_memory", "add_memory", "forget_memory", "learn_from_task", "learning_feedback", "reset_tools",
})
_TASK_DRAFT_TOOLS = frozenset({"generate_task_flow", "list_templates", "create_flow_from_template"})


class PlatformToolPolicy:
    def __init__(self, *, global_main: bool, management: bool) -> None:
        self.global_main = global_main
        self.management = management

    def __call__(self, tool: ToolBase) -> bool:
        if tool.name in {"AgentCreate", "PowerShell"}:
            return False
        if not self.management and tool.name in {"search_memory", "add_memory", "forget_memory", "learn_from_task", "learning_feedback"}:
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
