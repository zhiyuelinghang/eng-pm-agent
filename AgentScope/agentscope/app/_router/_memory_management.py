"""Management of authoritative memory records, revisions and index jobs."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
import psycopg

from .._auth import AgentScopePrincipal
from .._session_access import require_management_audit_access
from ..deps import get_current_principal
from ..memory import get_memory_runtime
from utils.memory_repository import MemoryAccess, MemoryError
from utils.memory_service import get_memory_repository
from utils.learning_repository import LearningRepository
from utils.group_learning_repository import GroupLearningRepository

logger = logging.getLogger(__name__)
MemoryScopeType = Literal["user", "user_project", "project"]
MemoryKind = Literal['fact','preference','decision','reference','reflection','experience','skill']
async def _automatic_memory_management(request: Request, principal: AgentScopePrincipal = Depends(get_current_principal)):
    require_management_audit_access(principal)
    if request.method not in {'GET','HEAD','OPTIONS','DELETE'}:
        raise HTTPException(409,detail={'code':'automatic_memory_management','message':'记忆由系统自动管理，管理端仅支持查看和删除。'})


memory_management_router = APIRouter(prefix="/memory-management", tags=["memory-management"], dependencies=[Depends(_automatic_memory_management)])


class UpdateMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=16000)
    scope_type: MemoryScopeType | None = None
    platform_user_id: str | None = None
    project_id: str | None = None
    status: Literal["active", "candidate", "inactive", "deleted"] | None = None
    publish: bool = False


class AssignLegacyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: MemoryScopeType
    platform_user_id: str = ""
    project_id: str = ""
    content: str = Field(min_length=1,max_length=16000)
    publish: bool = False


def _access(principal: AgentScopePrincipal) -> MemoryAccess:
    require_management_audit_access(principal)
    return MemoryAccess(get_memory_runtime().tenant_id, principal.subject,
                        actor_id=f"management:{principal.subject}", management=True)


async def _run(method, *args, **kwargs):
    try:
        return await asyncio.to_thread(method, *args, **kwargs)
    except MemoryError as exc:
        raise HTTPException(exc.status, detail={"code":exc.code,"message":str(exc)}) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, detail="目标抽屉已有相同事实字段，请先检查并处理冲突。") from exc
    except ValueError as exc:
        raise HTTPException(422, detail="记忆标识或参数无效。") from exc
    except Exception as exc:
        logger.exception("Memory management operation failed")
        raise HTTPException(503, detail="记忆存储暂时不可用，请查看服务日志；已有正文不会被清空。") from exc


async def _catalog(request: Request) -> dict:
    manager = getattr(request.app.state,"database_interaction_manager",None)
    if manager is None:
        raise HTTPException(503, detail="平台身份目录尚未配置。")
    try:
        return await manager.memory_identity_catalog()
    except Exception as exc:
        raise HTTPException(503, detail="无法获取最新用户和项目目录。") from exc


@memory_management_router.get("/memories")
async def list_managed_memories(
    request: Request,
    platform_user_id: str | None = None, project_id: str | None = None,
    scope_type: MemoryScopeType | None = None,
    query: str = Query(default="", max_length=500),
    record_status: Literal["active","candidate","inactive","deleted"] = "active",
    memory_type: MemoryKind | None = None,
    origin: Literal['explicit','learning'] | None = None,
    offset: int = Query(default=0,ge=0), limit: int = Query(default=50,ge=1,le=200),
    principal: AgentScopePrincipal = Depends(get_current_principal),
) -> dict:
    access = _access(principal)
    repo = get_memory_repository()
    page, counts = await asyncio.gather(
        _run(repo.list,access,scope_type=scope_type,user_id=platform_user_id,project_id=project_id,
             query=query,status=record_status,offset=offset,limit=limit,memory_type=memory_type,origin=origin),
        _run(repo.counts,access))
    # Browsing existing records remains possible when the business catalogue is offline.
    warning = None
    try:
        catalog = await _catalog(request)
    except HTTPException as exc:
        catalog = {"users":[],"projects":[],"memberships":[]}
        warning = str(exc.detail)
    users = {u["user_id"]:{**u,"memory_count":0,"user_memory_count":0,"projects":[]} for u in catalog["users"]}
    projects = {p["project_id"]:{**p,"memory_count":0} for p in catalog["projects"]}
    for count in counts:
        uid,pid,n = count["platform_user_id"],count["project_id"],count["count"]
        if pid:
            projects.setdefault(pid,{"project_id":pid,"project_name":pid,"memory_count":0})
        if count["scope_type"] == "project":
            projects[pid]["memory_count"] += n
        else:
            user = users.setdefault(uid,{"user_id":uid,"username":uid,"display_name":uid,"memory_count":0,"user_memory_count":0,"projects":[]})
            user["memory_count"] += n
            if count["scope_type"] == "user":
                user["user_memory_count"] += n
    return {**page,"users":list(users.values()),"projects":list(projects.values()),
            "memberships":catalog["memberships"],"catalog_warning":warning}


@memory_management_router.get("/memories/{memory_id}/history")
async def memory_history(memory_id: UUID, principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(get_memory_repository().history,_access(principal),str(memory_id))


@memory_management_router.patch("/memories/{memory_id}")
async def update_managed_memory(memory_id: UUID, body: UpdateMemoryRequest, request: Request,
                                principal: AgentScopePrincipal = Depends(get_current_principal)):
    access = _access(principal)
    repo = get_memory_repository()
    current = await _run(repo.get,access,str(memory_id))
    scope = body.scope_type or current["scope_type"]
    project = body.project_id if body.project_id is not None else current["project_id"]
    user = body.platform_user_id if body.platform_user_id is not None else current["platform_user_id"]
    if body.scope_type or body.project_id is not None or body.platform_user_id is not None:
        if current["identity_type"] == "management_user":
            if scope != "user" or user != current["platform_user_id"]:
                raise HTTPException(422,detail="管理测试记忆不能转为业务用户或项目共享记忆。")
        else:
            catalog = await _catalog(request)
            known_user = next((u for u in catalog["users"] if u["user_id"]==user),None)
            if scope != "project" and not known_user:
                raise HTTPException(422,detail="请选择当前有效的业务用户。")
            if scope != "user" and project not in {p["project_id"] for p in catalog["projects"]}:
                raise HTTPException(422,detail="请选择当前有效项目。")
            if scope == "user_project" and known_user["role"] != "admin" and not any(
                m["user_id"]==user and m["project_id"]==project for m in catalog["memberships"]):
                raise HTTPException(422,detail="该用户当前不属于所选项目。")
    return await _run(repo.manage,access,str(memory_id),expected_version=body.expected_version,
        content=body.content,scope_type=body.scope_type,user_id=body.platform_user_id,
        project_id=body.project_id,status=body.status,publish=body.publish)


@memory_management_router.delete("/memories/{memory_id}",status_code=204)
async def delete_managed_memory(memory_id: UUID, expected_version: int = Query(ge=1),
                                principal: AgentScopePrincipal = Depends(get_current_principal)) -> None:
    await _run(get_memory_repository().manage,_access(principal),str(memory_id),
               expected_version=expected_version,status="deleted")


@memory_management_router.get("/index-jobs")
async def memory_index_jobs(principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(get_memory_repository().diagnostics,_access(principal))


@memory_management_router.post("/memories/{memory_id}/retry-index")
async def retry_memory_index(memory_id: UUID, principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(get_memory_repository().retry_index,_access(principal),str(memory_id))


@memory_management_router.get("/legacy-review")
async def legacy_memory_reviews(principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(get_memory_repository().legacy_reviews,_access(principal))


@memory_management_router.post("/legacy-review/{legacy_id}/assign")
async def assign_legacy_memory(legacy_id: UUID, body: AssignLegacyRequest, request: Request,
                               principal: AgentScopePrincipal = Depends(get_current_principal)):
    access = _access(principal)
    catalog = await _catalog(request)
    user = next((u for u in catalog["users"] if u["user_id"]==body.platform_user_id),None)
    if body.scope_type != "project" and not user:
        raise HTTPException(422,detail="请选择当前有效用户。")
    if body.scope_type != "user" and body.project_id not in {p["project_id"] for p in catalog["projects"]}:
        raise HTTPException(422,detail="请选择当前有效项目。")
    if body.scope_type == "user_project" and user["role"] != "admin" and not any(
        m["user_id"]==body.platform_user_id and m["project_id"]==body.project_id for m in catalog["memberships"]):
        raise HTTPException(422,detail="该用户当前不属于所选项目。")
    return await _run(get_memory_repository().resolve_legacy,access,str(legacy_id),
        user_id=body.platform_user_id,project_id=body.project_id,scope_type=body.scope_type,
        content=body.content,publish=body.publish)


class ReviewLearningRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    action: Literal['approve','reject','suspend','revise','rollback']
    note: str = Field(min_length=1,max_length=4000)
    content: str | None = Field(default=None,min_length=1,max_length=16000)
    conditions: str | None = Field(default=None,min_length=1,max_length=2000)
    limitations: str | None = Field(default=None,min_length=1,max_length=2000)
    steps: list[str] | None = Field(default=None,max_length=10)
    restore_version: int | None = Field(default=None,ge=1)


@memory_management_router.get('/group-learning')
async def group_learning_dashboard(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(GroupLearningRepository(get_memory_repository()).dashboard, _access(principal), offset=offset, limit=limit)


@memory_management_router.post('/group-learning/channels/{channel_id}/{action}')
async def group_learning_channel_action(channel_id: int, action: Literal['pause', 'resume'],
    principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(GroupLearningRepository(get_memory_repository()).action, _access(principal), channel_id=channel_id, action=action)


@memory_management_router.post('/group-learning/batches/{batch_id}/retry')
async def group_learning_batch_retry(batch_id: UUID, principal: AgentScopePrincipal = Depends(get_current_principal)):
    return await _run(GroupLearningRepository(get_memory_repository()).action, _access(principal), batch_id=str(batch_id), action='retry')


class LearningFeedbackRequest(BaseModel):
    expected_version: int = Field(ge=1)
    outcome: Literal['success','failure','irrelevant']
    evidence: str = Field(min_length=1,max_length=4000)
    request_id: str = Field(min_length=1,max_length=255)


class DeriveLearningRequest(BaseModel):
    memory_ids: list[UUID] = Field(min_length=1,max_length=10)
    action: Literal['consolidate','skill_compile']
    note: str = Field(min_length=1,max_length=4000)


@memory_management_router.get('/learning')
async def learning_dashboard(offset: int=Query(default=0,ge=0),limit: int=Query(default=30,ge=1,le=100),
    state: Literal['recorded','pending','running','done','skipped','failed','cancelled'] | None=None,
    principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).dashboard,_access(principal),offset=offset,limit=limit,state=state)


@memory_management_router.post('/learning/events/{event_id}/{action}')
async def learning_job_action(event_id: UUID,action: Literal['retry','cancel'],principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).job_action,_access(principal),str(event_id),action)


@memory_management_router.post('/learning/derive')
async def derive_learning(body: DeriveLearningRequest,principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).derive,_access(principal),[str(mid) for mid in body.memory_ids],action=body.action,note=body.note)


@memory_management_router.post('/memories/{memory_id}/learning-review')
async def review_learning(memory_id: UUID,body: ReviewLearningRequest,principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).review,_access(principal),str(memory_id),**body.model_dump())


@memory_management_router.get('/memories/{memory_id}/feedback')
async def learning_feedback_history(memory_id: UUID,principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).feedback_history,_access(principal),str(memory_id))


@memory_management_router.post('/memories/{memory_id}/feedback')
async def learning_feedback(memory_id: UUID,body: LearningFeedbackRequest,principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).feedback,_access(principal),str(memory_id),**body.model_dump())


@memory_management_router.get('/memories/{memory_id}/learning-document')
async def export_learning_document(memory_id: UUID,principal: AgentScopePrincipal=Depends(get_current_principal)):
    return await _run(LearningRepository(get_memory_repository()).export_document,_access(principal),str(memory_id))
