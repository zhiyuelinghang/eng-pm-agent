"""Independent target consent for main calls and invitations by other agents."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage import AgentRecord


def can_delegate(
    caller: AgentRecord | None,
    target: AgentRecord | None,
    global_main_id: str | None,
    settings=None,
) -> bool:
    """Main needs main-call consent; others need invitation consent and a saved ID.

    Resource visibility and invocation-cycle checks remain the responsibility
    of the caller. Delegation never transfers the target's tool permissions.
    """
    if (
        caller is None
        or target is None
        or caller.id == target.id
        or not caller.data.platform_config.enabled
        or not target.data.platform_config.enabled
    ):
        return False
    # Fixed entry points cannot become delegates through legacy consent flags.
    if target.id in {
        global_main_id,
        getattr(settings, "project_initializer_agent_id", None),
    }:
        return False
    if caller.id == global_main_id:
        if target.id in {
            getattr(settings, "task_assistant_agent_id", None),
            getattr(settings, "knowledge_assistant_agent_id", None),
        }:
            return True
        return target.data.platform_config.allow_global_main_call
    return (
        target.data.invite_config.invitable
        and caller.data.call_config.allows(target.id)
    )
