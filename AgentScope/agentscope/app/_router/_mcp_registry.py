# -*- coding: utf-8 -*-
"""Management endpoints for dependency-complete MCP packages."""
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from .._auth import AgentScopePrincipal
from ..deps import (
    get_current_principal,
    get_current_user_id,
    get_mcp_registry_manager,
    get_resource_access_service,
    get_storage,
)
from ...message import TextBlock, ToolResultState
from ..mcp_registry import (
    MCPPackageConflictError,
    MCPPackageError,
    MCPPackageView,
    MCPRegistryManager,
)
from ..storage import StorageBase
from .._service import ResourceAccessService


mcp_registry_router = APIRouter(
    prefix="/mcp-registry",
    tags=["managed-mcp"],
)


_INITIALIZATION_VALIDATOR_PACKAGE = "project-initialization-validator"
_INITIALIZATION_VALIDATOR_CAPABILITY = "project_initialization_validation"
_INITIALIZATION_VALIDATOR_TOOL = "validate_project_initialization"


class ProjectInitializationValidationRequest(BaseModel):
    """Canonical draft payload supplied by the engineering platform."""

    payload: dict[str, Any] = Field(default_factory=dict)


@mcp_registry_router.post("/platform/project-initialization-validation")
async def validate_project_initialization(
    request: ProjectInitializationValidationRequest,
    principal: AgentScopePrincipal = Depends(get_current_principal),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> dict[str, Any]:
    """Execute the active versioned validator MCP without an LLM turn."""
    if principal.kind != "service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该接口仅供工程平台核验流程调用。",
        )
    record = await manager.get_record(_INITIALIZATION_VALIDATOR_PACKAGE)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="项目初始化核验 MCP 尚未上传。",
        )
    if (
        _INITIALIZATION_VALIDATOR_CAPABILITY
        not in record.manifest.platform_capabilities
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前 MCP 未声明项目初始化核验能力。",
        )

    started = time.perf_counter()
    try:
        client = await manager.get_platform_client(
            record.id,
            runtime_id="project-initialization-validation",
        )
        tool = await client.get_tool(_INITIALIZATION_VALIDATOR_TOOL)
        if tool is None:
            raise RuntimeError("核验 MCP 缺少约定工具")
        chunk = await tool.call(draft=request.payload)
        raw = "\n".join(
            block.text
            for block in chunk.content
            if isinstance(block, TextBlock)
        ).strip()
        if chunk.state == ToolResultState.ERROR:
            raise RuntimeError(raw or "核验 MCP 执行失败")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise RuntimeError("核验 MCP 返回值不是对象")
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"项目初始化核验 MCP 执行失败：{exc}",
        ) from exc

    return {
        "package_id": record.id,
        "package_version": record.manifest.version,
        "tool_name": _INITIALIZATION_VALIDATOR_TOOL,
        "duration_ms": max(0, round((time.perf_counter() - started) * 1000)),
        "result": result,
    }


@mcp_registry_router.get("/", response_model=list[MCPPackageView])
async def list_mcp_packages(
    agent_id: str = Query(..., min_length=1),
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> list[MCPPackageView]:
    """List every published package and its assignment for one agent."""
    agent = await access.resolve_agent(user_id, agent_id)
    return await manager.list_views(set(agent.data.mcp_config.allowed_mcp_ids))


@mcp_registry_router.post(
    "/upload",
    response_model=MCPPackageView,
    status_code=status.HTTP_201_CREATED,
)
async def upload_mcp_package(
    file: UploadFile = File(...),
    _user_id: str = Depends(get_current_user_id),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> MCPPackageView:
    """Verify and publish one complete ZIP/MCP package."""
    try:
        filename = (file.filename or "").lower()
        if not filename.endswith((".zip", ".mcp", ".mcpb")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="MCP package must be a .zip, .mcp or .mcpb archive.",
            )
        record = await manager.install_archive(file.file)
    except MCPPackageConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except MCPPackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        await file.close()
    return MCPPackageView.from_record(record)


@mcp_registry_router.delete(
    "/{package_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mcp_package(
    package_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> None:
    """Delete an unassigned MCP package and all retained versions."""
    if manager.is_system_tool_package(package_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="系统工具是平台固定能力，不能在智能体管理端删除。",
        )
    assigned_agents = [
        agent.data.name
        for agent in await storage.list_agents(user_id)
        if package_id in agent.data.mcp_config.allowed_mcp_ids
    ]
    if assigned_agents:
        names = "、".join(assigned_agents[:5])
        suffix = " 等" if len(assigned_agents) > 5 else ""
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"请先从智能体「{names}{suffix}」取消分配该 MCP。",
        )
    if not await manager.delete_package(package_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP package {package_id!r} not found.",
        )
