# -*- coding: utf-8 -*-
"""Workspace router — manage MCP clients and skills on a workspace."""
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..deps import (
    get_current_principal,
    get_current_user_id,
    get_extra_agent_tool_catalog,
    get_extra_agent_tools,
    get_optional_mcp_registry_manager,
    get_storage,
    get_workspace_manager,
)
from .._auth import AgentScopePrincipal
from .._session_access import require_runtime_session_access
from .._types import (
    AgentToolCatalogFactory,
    AgentToolDescriptor,
    AgentToolFactory,
)
from ..workspace_manager import WorkspaceManagerBase
from ..mcp_registry import MCPRegistryManager
from ..storage import StorageBase
from ...mcp import MCPClient
from ...skill import Skill
from ...workspace import WorkspaceBase

workspace_router = APIRouter(prefix="/workspace", tags=["workspace"])


class AddSkillRequest(BaseModel):
    """The request to add skill."""

    skill_path: str


class UpdateSkillRequest(BaseModel):
    """Editable fields stored in a skill's ``SKILL.md`` file."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    markdown: str = ""


class ToolInfo(BaseModel):
    """The tool info."""

    name: str
    description: str | None = None


class WorkspaceToolInfo(ToolInfo):
    """A fixed direct tool and the layer that contributes it."""

    source: str
    category: Literal["database", "workspace", "general"]
    display_name: str | None = None
    assigned: bool = True
    read_only: bool
    input_schema: dict = Field(default_factory=dict)


class MCPClientStatus(MCPClient):
    """MCPClient enriched with live tool list and health status."""

    is_healthy: bool = False
    tools: list[ToolInfo] = Field(default_factory=list)


def _default_workspace_tool_catalog() -> list[AgentToolDescriptor]:
    """Describe built-in workspace tools without creating a chat session.

    System tools are fixed platform capabilities shared by every agent, while
    the live backend/path belongs to a session workspace. The catalogue
    therefore comes from the built-in tool classes; a concrete workspace is
    needed only when a tool is called. Keep this list aligned with
    :meth:`LocalWorkspace.list_tools` and the platform-wide execution policy.
    """
    from ...tool import Bash, Edit, Glob, Grep, Read, Write

    tool_types = [Edit, Glob, Grep, Read, Write]
    if os.name != "nt":
        tool_types.insert(0, Bash)
    return [
        AgentToolDescriptor(
            name=tool_type.name,
            description=tool_type.description,
            category="workspace",
            input_schema=tool_type.input_schema,
            read_only=tool_type.is_read_only,
        )
        for tool_type in tool_types
    ]


async def _resolve_workspace(
    user_id: str,
    agent_id: str,
    session_id: str,
    storage: StorageBase,
    workspace_manager: WorkspaceManagerBase,
    principal: AgentScopePrincipal,
) -> WorkspaceBase:
    """Resolve the workspace for the given session, raising 404 if not
    found."""
    session_record = await storage.get_session(user_id, agent_id, session_id)
    if session_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found.",
        )
    require_runtime_session_access(principal, session_record)
    return await workspace_manager.get_workspace(
        user_id,
        agent_id,
        session_id,
        session_record.config.workspace_id,
    )


# ---------------------------------------------------------------------------
# Direct tool endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("/tool")
async def list_workspace_tools(
    agent_id: str = Query(...),
    session_id: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
    extra_factory: AgentToolFactory | None = Depends(get_extra_agent_tools),
    catalog_factory: AgentToolCatalogFactory | None = Depends(
        get_extra_agent_tool_catalog,
    ),
    mcp_registry_manager: MCPRegistryManager | None = Depends(
        get_optional_mcp_registry_manager,
    ),
) -> list[WorkspaceToolInfo]:
    """Return the fixed direct-tool catalogue shared by every agent.

    Assignable MCP tools and skills are excluded because the WebUI exposes
    them in neighboring tabs. Packages designated as fixed system tools are
    included here instead: every agent receives them and management clients
    can inspect but never assign or disable them. Both application and
    workspace catalogues are available before a management-chat session; a
    session is required only to bind tools to a live execution backend.
    """
    agent_record = await storage.get_agent(user_id, agent_id)
    if agent_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id!r} not found.",
        )

    workspace_tools = _default_workspace_tool_catalog()
    if session_id is not None:
        workspace = await _resolve_workspace(
            user_id,
            agent_id,
            session_id,
            storage,
            workspace_manager,
            principal,
        )
        workspace_tools = await workspace.list_tools()

    if catalog_factory is not None:
        platform_tools = await catalog_factory(user_id, agent_id)
    elif extra_factory is not None and session_id is not None:
        platform_tools = await extra_factory(user_id, agent_id, session_id)
    else:
        platform_tools = []

    system_tools: list[AgentToolDescriptor] = []
    if mcp_registry_manager is not None:
        for record in await mcp_registry_manager.list_system_tool_records():
            for tool in record.tools:
                system_tools.append(
                    AgentToolDescriptor(
                        name=tool.name,
                        display_name=tool.display_name,
                        description=tool.description,
                        category="general",
                        read_only=tool.read_only,
                        input_schema=tool.input_schema,
                    ),
                )

    results: list[WorkspaceToolInfo] = []
    seen: set[str] = set()
    for source, tools in (
        ("platform", system_tools),
        ("platform", platform_tools),
        ("workspace", workspace_tools),
    ):
        for tool in tools:
            if tool.name == "PowerShell" or tool.name in seen:
                continue
            seen.add(tool.name)
            results.append(
                WorkspaceToolInfo(
                    name=tool.name,
                    description=tool.description,
                    source=source,
                    category=getattr(
                        tool,
                        "category",
                        "workspace" if source == "workspace" else "general",
                    ),
                    display_name=getattr(tool, "display_name", None),
                    assigned=True,
                    read_only=bool(
                        getattr(
                            tool,
                            "read_only",
                            getattr(tool, "is_read_only", False),
                        ),
                    ),
                    input_schema=getattr(tool, "input_schema", {}) or {},
                ),
            )
    return results


# ---------------------------------------------------------------------------
# MCP endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("/mcp")
async def list_mcps(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> list[MCPClientStatus]:
    """Return all MCP clients with live tool list and health status."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    clients = await workspace.list_mcps()

    results = []
    for client in clients:
        base = client.model_dump()
        try:
            mcp_tools = await client.list_tools()
            tools = [
                ToolInfo(name=t.name, description=t.description)
                for t in mcp_tools
            ]
            results.append(
                MCPClientStatus(
                    **base,
                    is_healthy=True,
                    tools=tools,
                ),
            )
        except Exception:
            results.append(
                MCPClientStatus(
                    **base,
                    is_healthy=False,
                ),
            )

    return results


@workspace_router.post("/mcp", status_code=status.HTTP_201_CREATED)
async def add_mcp(
    mcp: MCPClient,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> None:
    """Add an MCP client to the session's workspace."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    await workspace.add_mcp(mcp)


@workspace_router.delete(
    "/mcp/{mcp_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_mcp(
    mcp_name: str,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> None:
    """Remove an MCP client from the session's workspace by name."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    await workspace.remove_mcp(mcp_name)


# ---------------------------------------------------------------------------
# Skill endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("/skill")
async def list_skills(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> list[Skill]:
    """Return all skills available in the session's workspace."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    return await workspace.list_skills(agent_id=agent_id)


@workspace_router.post("/skill", status_code=status.HTTP_201_CREATED)
async def add_skill(
    body: AddSkillRequest,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> None:
    """Add a skill to the session's workspace from the given path."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    await workspace.add_skill(body.skill_path, agent_id=agent_id)


@workspace_router.put("/skill/{skill_name}")
async def update_skill(
    skill_name: str,
    body: UpdateSkillRequest,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> None:
    """Update an existing skill in the session's workspace."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    try:
        await workspace.update_skill(
            skill_name,
            new_name=body.name,
            description=body.description,
            markdown=body.markdown,
            agent_id=agent_id,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@workspace_router.delete(
    "/skill/{skill_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_skill(
    skill_name: str,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    principal: AgentScopePrincipal = Depends(get_current_principal),
    storage: StorageBase = Depends(get_storage),
    workspace_manager: WorkspaceManagerBase = Depends(get_workspace_manager),
) -> None:
    """Remove a skill from the session's workspace by name."""
    workspace = await _resolve_workspace(
        user_id,
        agent_id,
        session_id,
        storage,
        workspace_manager,
        principal,
    )
    await workspace.remove_skill(skill_name, agent_id=agent_id)
