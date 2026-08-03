# -*- coding: utf-8 -*-
"""Authorization boundary between management and platform sessions."""
from fastapi import HTTPException, status

from ._auth import AgentScopePrincipal
from .storage import SessionRecord, SessionSource


def runtime_session_visible(
    principal: AgentScopePrincipal,
    session: SessionRecord,
) -> bool:
    """Return whether a session belongs in the caller's interactive UI."""
    is_platform = session.source == SessionSource.PLATFORM
    return is_platform if principal.kind == "service" else not is_platform


def require_runtime_session_access(
    principal: AgentScopePrincipal,
    session: SessionRecord,
) -> None:
    """Prevent either principal from crossing the interactive boundary."""
    if runtime_session_visible(principal, session):
        return
    if principal.kind == "management":
        detail = (
            "平台用户会话只能在“平台交互审计”中只读查看，"
            "管理账号不能发送、确认、中断或修改。"
        )
    else:
        detail = "平台服务凭证不能操作管理端测试会话。"
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def require_management_audit_access(
    principal: AgentScopePrincipal,
) -> None:
    """Allow management (and unauthenticated legacy mode) to audit only."""
    if principal.kind != "service":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="平台服务凭证无权访问管理端交互审计。",
    )
