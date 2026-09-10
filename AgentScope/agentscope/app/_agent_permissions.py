"""Use saved agent permissions for management/debug sessions."""

from fastapi import HTTPException

from .storage import AgentData, SessionRecord, SessionSource
from ..permission import PermissionMode
from ..state import AgentState


def uses_agent_permission_config(session: SessionRecord) -> bool:
    return (
        session.source == SessionSource.USER
        and session.config.platform_context is None
    )


def configured_permission_mode(
    agent: AgentData,
    requested: PermissionMode | None = None,
) -> PermissionMode:
    mode = agent.platform_config.permission_mode
    if requested is not None and requested != mode:
        raise HTTPException(
            status_code=409,
            detail="调试权限由智能体配置决定，请在编辑智能体中修改。",
        )
    return mode


def sync_agent_permission_mode(
    agent: AgentData,
    session: SessionRecord,
) -> AgentState:
    """Refresh the mode at each run, preserving scoped rules and pending calls."""
    if not uses_agent_permission_config(session):
        return session.state
    return session.state.model_copy(update={
        "permission_context": session.state.permission_context.model_copy(
            update={"mode": configured_permission_mode(agent)},
        ),
    })
