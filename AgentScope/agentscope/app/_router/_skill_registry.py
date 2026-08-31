# -*- coding: utf-8 -*-
"""Management endpoints for platform-managed, versioned skills."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .._service import ResourceAccessService
from ..deps import (
    get_current_user_id,
    get_resource_access_service,
    get_skill_registry_manager,
    get_storage,
)
from ..skill_registry import (
    SkillPackageConflictError,
    SkillPackageError,
    SkillPackageRecord,
    SkillPackageVersionView,
    SkillPackageView,
    SkillRegistryManager,
)
from ..storage import StorageBase


skill_registry_router = APIRouter(
    prefix="/skill-registry",
    tags=["managed-skills"],
)


class SkillPackageInput(BaseModel):
    """Editable fields of a pure ``SKILL.md`` package."""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    markdown: str = Field(min_length=1, max_length=2 * 1024 * 1024)


async def _current_view(
    manager: SkillRegistryManager,
    record: SkillPackageRecord,
    *,
    assigned: bool = False,
) -> SkillPackageView:
    views = await manager.list_views({record.id} if assigned else set())
    for view in views:
        if view.id == record.id:
            return view
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="技能已保存，但无法读取已发布版本。",
    )


@skill_registry_router.get("/", response_model=list[SkillPackageView])
async def list_skill_packages(
    agent_id: str = Query(..., min_length=1),
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    manager: SkillRegistryManager = Depends(get_skill_registry_manager),
) -> list[SkillPackageView]:
    """List the platform skill catalogue and one agent's assignments."""
    agent = await access.resolve_agent(user_id, agent_id)
    return await manager.list_views(set(agent.data.skill_config.allowed_skill_ids))


@skill_registry_router.post(
    "/",
    response_model=SkillPackageView,
    status_code=status.HTTP_201_CREATED,
)
async def create_skill_package(
    body: SkillPackageInput,
    _user_id: str = Depends(get_current_user_id),
    manager: SkillRegistryManager = Depends(get_skill_registry_manager),
) -> SkillPackageView:
    """Create a managed skill from fields edited in the browser."""
    try:
        record = await manager.create_skill(
            name=body.name,
            description=body.description,
            markdown=body.markdown,
        )
    except SkillPackageConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except SkillPackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return await _current_view(manager, record)


@skill_registry_router.put(
    "/{package_id}",
    response_model=SkillPackageView,
)
async def update_skill_package(
    package_id: str,
    body: SkillPackageInput,
    _user_id: str = Depends(get_current_user_id),
    manager: SkillRegistryManager = Depends(get_skill_registry_manager),
) -> SkillPackageView:
    """Save browser edits as a new immutable version."""
    try:
        record = await manager.update_skill(
            package_id,
            name=body.name,
            description=body.description,
            markdown=body.markdown,
        )
    except SkillPackageConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except SkillPackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return await _current_view(manager, record)


@skill_registry_router.get(
    "/{package_id}/versions",
    response_model=list[SkillPackageVersionView],
)
async def list_skill_package_versions(
    package_id: str,
    _user_id: str = Depends(get_current_user_id),
    manager: SkillRegistryManager = Depends(get_skill_registry_manager),
) -> list[SkillPackageVersionView]:
    """List retained versions of one managed skill."""
    if await manager.get_record(package_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在。")
    return await manager.list_version_views(package_id)


@skill_registry_router.get(
    "/{package_id}/versions/{version}/download",
    response_class=FileResponse,
)
async def download_skill_package_version(
    package_id: str,
    version: int,
    _user_id: str = Depends(get_current_user_id),
    manager: SkillRegistryManager = Depends(get_skill_registry_manager),
) -> FileResponse:
    """Download an exact retained version for offline maintenance."""
    try:
        archive = await manager.build_version_archive(package_id, version)
    except SkillPackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"{package_id}-v{version}.zip",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@skill_registry_router.delete(
    "/{package_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill_package(
    package_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: SkillRegistryManager = Depends(get_skill_registry_manager),
) -> None:
    """Delete an unassigned skill package and all retained versions."""
    assigned_agents = [
        agent.data.name
        for agent in await storage.list_agents(user_id)
        if package_id in agent.data.skill_config.allowed_skill_ids
    ]
    if assigned_agents:
        names = "、".join(assigned_agents[:5])
        suffix = " 等" if len(assigned_agents) > 5 else ""
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"请先从智能体「{names}{suffix}」取消分配该技能。",
        )
    if not await manager.delete_package(package_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在。")
