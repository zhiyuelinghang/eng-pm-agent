# -*- coding: utf-8 -*-
"""Management endpoints for dependency-complete MCP packages."""
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

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
    MCPPackageRecord,
    MCPPackageVersionView,
    MCPPackageView,
    MCPRegistryManager,
    PROJECT_INITIALIZATION_VALIDATION_CAPABILITY,
)
from ..storage import PlatformMCPVersionBinding, StorageBase
from .._service import ResourceAccessService


mcp_registry_router = APIRouter(
    prefix="/mcp-registry",
    tags=["managed-mcp"],
)


class ProjectInitializationValidationRequest(BaseModel):
    """Canonical draft payload supplied by the engineering platform."""

    payload: dict[str, Any] = Field(default_factory=dict)


class ProjectInitializationValidationMCPConfig(BaseModel):
    """Installed validator versions plus the exact version in use."""

    current: PlatformMCPVersionBinding | None = None
    versions: list[MCPPackageVersionView] = Field(default_factory=list)


def _is_initialization_validation_package(record: MCPPackageRecord) -> bool:
    """Whether one package version can fill the validation capability slot."""
    return (
        PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
        in record.manifest.platform_capabilities
        and len(record.tools) == 1
    )


async def _load_initialization_validation_binding(
    *,
    storage: StorageBase,
    user_id: str,
    manager: MCPRegistryManager,
) -> PlatformMCPVersionBinding | None:
    """Load the selected version and migrate the sole legacy package once."""
    settings = await storage.get_platform_settings(user_id)
    if (
        settings is not None
        and settings.data.project_initializer_validation_mcp is not None
    ):
        return settings.data.project_initializer_validation_mcp

    candidates = [
        record
        for record in await manager.list_records()
        if _is_initialization_validation_package(record)
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    binding = PlatformMCPVersionBinding(
        package_id=candidate.id,
        version=candidate.manifest.version,
    )
    if settings is not None:
        await storage.upsert_platform_settings(
            user_id,
            settings.data.model_copy(
                update={"project_initializer_validation_mcp": binding},
            ),
        )
    return binding


async def _require_validation_record(
    manager: MCPRegistryManager,
    binding: PlatformMCPVersionBinding,
) -> MCPPackageRecord:
    record = await manager.get_record(binding.package_id, binding.version)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="当前配置的项目初始化核验 MCP 版本不存在。",
        )
    if not _is_initialization_validation_package(record):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前 MCP 版本不符合项目初始化核验能力约定。",
        )
    return record


@mcp_registry_router.post("/platform/project-initialization-validation")
async def validate_project_initialization(
    request: ProjectInitializationValidationRequest,
    principal: AgentScopePrincipal = Depends(get_current_principal),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> dict[str, Any]:
    """Execute the active versioned validator MCP without an LLM turn."""
    if principal.kind != "service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该接口仅供工程平台核验流程调用。",
        )
    binding = await _load_initialization_validation_binding(
        storage=storage,
        user_id=user_id,
        manager=manager,
    )
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="项目初始化尚未选择核验 MCP 版本。",
        )
    record = await _require_validation_record(manager, binding)
    tool_name = record.tools[0].name

    started = time.perf_counter()
    try:
        client = await manager.get_platform_client(
            record.id,
            runtime_id="project-initialization-validation",
            version=binding.version,
        )
        tool = await client.get_tool(tool_name)
        if tool is None:
            raise RuntimeError("核验 MCP 缺少清单声明的工具")
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
        "tool_name": tool_name,
        "duration_ms": max(0, round((time.perf_counter() - started) * 1000)),
        "result": result,
    }


@mcp_registry_router.get(
    "/platform/project-initialization-validation",
    response_model=ProjectInitializationValidationMCPConfig,
)
async def get_project_initialization_validation_mcp_config(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> ProjectInitializationValidationMCPConfig:
    """Return every retained validator version and the selected version."""
    binding = await _load_initialization_validation_binding(
        storage=storage,
        user_id=user_id,
        manager=manager,
    )
    return ProjectInitializationValidationMCPConfig(
        current=binding,
        versions=await manager.list_version_views(
            capability=PROJECT_INITIALIZATION_VALIDATION_CAPABILITY,
        ),
    )


@mcp_registry_router.post(
    "/platform/project-initialization-validation/upload",
    response_model=MCPPackageVersionView,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_initialization_validation_mcp(
    file: UploadFile = File(...),
    _user_id: str = Depends(get_current_user_id),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> MCPPackageVersionView:
    """Publish one immutable validator version without switching versions."""
    record: MCPPackageRecord | None = None
    try:
        filename = (file.filename or "").lower()
        if not filename.endswith((".zip", ".mcp", ".mcpb")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="核验 MCP 必须上传 .zip、.mcp 或 .mcpb 安装包。",
            )
        record = await manager.install_archive(file.file)
        if not _is_initialization_validation_package(record):
            await manager.delete_version(record.id, record.manifest.version)
            record = None
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "安装包必须声明项目初始化核验能力，并只提供一个"
                    "核验入口。"
                ),
            )
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
    if record is None:  # pragma: no cover - guarded by the branches above
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return MCPPackageVersionView.from_record(record)


@mcp_registry_router.get(
    "/platform/project-initialization-validation/{package_id}/{version}/download",
    response_class=FileResponse,
)
async def download_project_initialization_validation_mcp(
    package_id: str,
    version: str,
    _user_id: str = Depends(get_current_user_id),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> FileResponse:
    """Download one exact validator version as an editable archive."""
    record = await manager.get_record(package_id, version)
    if record is None or not _is_initialization_validation_package(record):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的核验 MCP 版本不存在。",
        )
    try:
        archive_path = await manager.build_version_archive(package_id, version)
    except MCPPackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{package_id}-{version}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@mcp_registry_router.delete(
    "/platform/project-initialization-validation/{package_id}/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_initialization_validation_mcp_version(
    package_id: str,
    version: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> None:
    """Delete one unused validator version while protecting the selected one."""
    record = await manager.get_record(package_id, version)
    if record is None or not _is_initialization_validation_package(record):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的核验 MCP 版本不存在。",
        )
    settings = await storage.get_platform_settings(user_id)
    current = (
        settings.data.project_initializer_validation_mcp
        if settings is not None
        else None
    )
    if (
        current is not None
        and current.package_id == package_id
        and current.version == version
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前正在使用该版本，请先选择并保存其他版本。",
        )
    if await manager.active_version_instances(package_id, version):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该版本仍有运行实例，暂时不能删除。",
        )
    if not await manager.delete_version(package_id, version):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的核验 MCP 版本不存在。",
        )


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
        if (
            PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
            in record.manifest.platform_capabilities
        ):
            await manager.delete_version(record.id, record.manifest.version)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="核验 MCP 请在“平台设置”中上传和管理。",
            )
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
    versions = await manager.list_version_records(package_id)
    if any(
        PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
        in record.manifest.platform_capabilities
        for record in versions
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="核验 MCP 请在“平台设置”中按版本管理。",
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
