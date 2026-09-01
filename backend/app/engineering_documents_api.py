from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .agentscope_client import AgentScopeGatewayError
from .agent_api_support import (
    _agentscope_client,
    _engineering_document_catalogue_state,
    _engineering_knowledge_conversation_or_404,
    _engineering_knowledge_conversation_view,
    _engineering_knowledge_message_view,
    _project_weknora_agent_id,
    _raise_agentscope_http_error,
    _ready_project_weknora_agent_id,
    _reset_unsafe_engineering_knowledge_session,
    _restricted_engineering_knowledge_ids,
    _sse_frame,
)
from .api_common import (
    audit,
    entity_or_404,
    get_current_user,
    ok,
    project_for_user_or_403,
    project_or_404,
    require_admin,
    serialize,
)
from .config import get_settings
from .db import get_db
from .engineering_document_catalog import (
    add_local_folder,
    add_pending_local_file,
    authorized_qa_payload,
    delete_local_file,
    delete_local_folder_subtree,
    filter_search_result,
    find_catalogue_node,
    local_file_view,
    local_folder_tree_view,
    local_knowledge_page,
    local_workspace_view,
    move_local_files,
    normalize_folder_path,
    permission_configuration_view,
    readable_external_ids,
    require_catalogue_capability,
    set_catalogue_access_mode,
    sync_state_view,
    update_local_folder_path,
    upsert_catalogue_permission,
)
from .models import (
    Attachment,
    AttachmentText,
    DailyReport,
    DocumentFolder,
    DocumentFolderItem,
    EngineeringDocumentPermission,
    EngineeringKnowledgeConversation,
    EngineeringKnowledgeMessage,
    OperationLog,
    User,
    WbsItem,
)
from .schemas import (
    AttachmentUpdate,
    DocumentFolderInput,
    EngineeringDocumentAccessModeInput,
    EngineeringDocumentAskInput,
    EngineeringDocumentFolderCreateInput,
    EngineeringDocumentFolderUpdateInput,
    EngineeringDocumentMoveInput,
    EngineeringDocumentPermissionInput,
    EngineeringDocumentSearchInput,
    EngineeringDocumentUrlInput,
    EngineeringKnowledgeConversationCreateInput,
    EngineeringKnowledgeConversationUpdateInput,
    EngineeringKnowledgeMessageInput,
    OperationLogInput,
)
from .system_attachment_parser import (
    SystemAttachmentParserError,
    parse_uploaded_attachment,
)
from .task_engine_gateway import dispatch_platform_task


router = APIRouter(prefix="/api", tags=["engineering-documents"])


@router.get("/projects/{project_id}/engineering-documents/workspace")
def get_engineering_document_workspace(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    agent_id = _project_weknora_agent_id(db, project_id)
    state_row = _engineering_document_catalogue_state(
        db,
        project_id,
        agent_id,
    )
    workspace = local_workspace_view(db, project_id, user)
    return ok(
        {
            "project_id": project.id,
            "project_name": project.name,
            "weknora_configured": True,
            "weknora_agent_id": agent_id,
            **workspace,
            "sync": sync_state_view(state_row),
        },
    )


@router.get("/projects/{project_id}/engineering-documents/access")
def get_engineering_document_access_configuration(
    project_id: int,
    include_nodes: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    return ok(
        permission_configuration_view(
            db,
            project_id,
            include_nodes=include_nodes,
        ),
    )


@router.put("/projects/{project_id}/engineering-documents/access-mode")
def update_engineering_document_access_mode(
    project_id: int,
    payload: EngineeringDocumentAccessModeInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    state_row = set_catalogue_access_mode(
        db,
        project_id,
        payload.access_mode,
    )
    audit(
        db,
        user,
        "调整工程资料权限模式",
        (
            "启用按岗位授权"
            if payload.access_mode == "restricted"
            else "恢复项目成员默认访问"
        ),
        project_id,
        "engineering_document_permission",
    )
    db.commit()
    db.refresh(state_row)
    return ok(sync_state_view(state_row), "工程资料权限模式已更新")


@router.put("/projects/{project_id}/engineering-documents/permissions")
def save_engineering_document_permission(
    project_id: int,
    payload: EngineeringDocumentPermissionInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    row = upsert_catalogue_permission(
        db,
        project_id,
        node_id=payload.node_id,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        values=payload.model_dump(
            exclude={"node_id", "subject_type", "subject_id"},
        ),
        granted_by_user_id=user.id,
    )
    audit(
        db,
        user,
        "配置工程资料权限",
        f"为{payload.subject_type} {payload.subject_id} 配置目录节点 {payload.node_id}",
        project_id,
        "engineering_document_permission",
    )
    db.commit()
    db.refresh(row)
    return ok(serialize(row), "工程资料权限已保存")


@router.delete(
    "/projects/{project_id}/engineering-documents/permissions/{permission_id}",
)
def delete_engineering_document_permission(
    project_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    row = db.get(EngineeringDocumentPermission, permission_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="工程资料权限记录不存在。")
    db.delete(row)
    audit(
        db,
        user,
        "删除工程资料权限",
        f"删除权限记录 {permission_id}",
        project_id,
        "engineering_document_permission",
        permission_id,
    )
    db.commit()
    return ok({"id": permission_id}, "工程资料权限已删除")


@router.get(
    "/projects/{project_id}/engineering-documents/knowledge-bases/"
    "{knowledge_base_id}/folders",
)
def get_engineering_document_folders(
    project_id: int,
    knowledge_base_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    _ready_project_weknora_agent_id(db, project_id)
    return ok(
        local_folder_tree_view(
            db,
            project_id,
            knowledge_base_id,
            user,
        ),
    )


@router.get(
    "/projects/{project_id}/engineering-documents/knowledge-bases/"
    "{knowledge_base_id}/knowledge",
)
def list_engineering_documents(
    project_id: int,
    knowledge_base_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    folder_path: str | None = Query(default=None, max_length=4096),
    folder_recursive: bool = Query(default=False),
    keyword: str = Query(default="", max_length=512),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    _ready_project_weknora_agent_id(db, project_id)
    return ok(
        local_knowledge_page(
            db,
            project_id,
            knowledge_base_id,
            user,
            page=page,
            page_size=page_size,
            folder_path=folder_path,
            folder_recursive=folder_recursive,
            keyword=keyword,
        ),
    )


@router.post("/projects/{project_id}/engineering-documents/search")
def search_engineering_documents(
    project_id: int,
    payload: EngineeringDocumentSearchInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    if not readable_external_ids(
        db,
        project_id,
        user,
        [payload.knowledge_base_id],
    ):
        raise HTTPException(status_code=403, detail="该知识库内没有可访问的资料。")
    try:
        result = _agentscope_client().search_weknora_knowledge(
            agent_id,
            payload.knowledge_base_id,
            payload.model_dump(exclude={"knowledge_base_id"}),
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    return ok(filter_search_result(db, project_id, user, result))


@router.post("/projects/{project_id}/engineering-documents/upload")
async def upload_engineering_document(
    project_id: int,
    knowledge_base_id: str = Form(..., min_length=1, max_length=128),
    folder_path: str = Form(default="", max_length=4096),
    enable_multimodel: bool = Form(default=True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    normalized_folder_path = normalize_folder_path(folder_path)
    target_parent = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=knowledge_base_id,
        node_type="folder" if normalized_folder_path else "knowledge_base",
        folder_path=normalized_folder_path if normalized_folder_path else None,
    )
    if target_parent is None:
        raise HTTPException(status_code=409, detail="上传目录尚未同步到平台。")
    require_catalogue_capability(
        db, project_id, user, target_parent, "can_create",
    )
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=422, detail="请选择需要上传的资料。")
    content = await file.read(50 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="上传文件不能超过 50 MB。")
    try:
        result = _agentscope_client().upload_weknora_knowledge(
            agent_id,
            knowledge_base_id,
            filename=filename,
            content=content,
            content_type=file.content_type or "application/octet-stream",
            folder_path=normalized_folder_path,
            enable_multimodel=enable_multimodel,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    add_pending_local_file(
        db,
        project_id,
        knowledge_base_id,
        normalized_folder_path,
        result,
        fallback_name=filename,
        file_size=len(content),
        file_type=(Path(filename).suffix.removeprefix(".") or None),
    )
    audit(
        db,
        user,
        "上传工程资料",
        f"上传「{filename}」到 WeKnora",
        project_id,
        "weknora_knowledge",
    )
    db.commit()
    return ok(result, result.get("message", "资料已提交 WeKnora 解析"))


@router.post("/projects/{project_id}/engineering-documents/url")
def create_engineering_document_from_url(
    project_id: int,
    payload: EngineeringDocumentUrlInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    root = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=payload.knowledge_base_id,
        node_type="knowledge_base",
    )
    if root is None:
        raise HTTPException(status_code=409, detail="知识库尚未同步到平台。")
    require_catalogue_capability(db, project_id, user, root, "can_create")
    try:
        result = _agentscope_client().create_weknora_url_knowledge(
            agent_id,
            payload.knowledge_base_id,
            payload.model_dump(exclude={"knowledge_base_id"}),
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    add_pending_local_file(
        db,
        project_id,
        payload.knowledge_base_id,
        "",
        result,
        fallback_name=payload.title or payload.url,
        file_type="url",
    )
    audit(
        db,
        user,
        "添加工程资料 URL",
        f"提交 URL「{payload.url}」到 WeKnora",
        project_id,
        "weknora_knowledge",
    )
    db.commit()
    return ok(result, result.get("message", "URL 已提交 WeKnora 解析"))


@router.post("/projects/{project_id}/engineering-documents/folder")
def create_engineering_document_folder(
    project_id: int,
    payload: EngineeringDocumentFolderCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    normalized_path = normalize_folder_path(payload.folder_path)
    parent_path = normalized_path.rpartition("/")[0]
    parent = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=payload.knowledge_base_id,
        node_type="folder" if parent_path else "knowledge_base",
        folder_path=parent_path if parent_path else None,
    )
    if parent is None:
        raise HTTPException(status_code=409, detail="上级目录尚未同步到平台。")
    require_catalogue_capability(db, project_id, user, parent, "can_create")
    try:
        result = _agentscope_client().create_weknora_folder(
            agent_id,
            payload.knowledge_base_id,
            folder_path=normalized_path,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    local_folder = add_local_folder(
        db,
        project_id,
        payload.knowledge_base_id,
        normalized_path,
    )
    audit(
        db,
        user,
        "创建工程资料目录",
        f"在 WeKnora 创建目录「{payload.folder_path}」",
        project_id,
        "weknora_folder",
    )
    db.commit()
    return ok(
        {**result, "node_id": local_folder.id, "folder_path": normalized_path},
        result.get("message", "文件夹已创建"),
    )


@router.delete("/projects/{project_id}/engineering-documents/folder")
def delete_engineering_document_folder(
    project_id: int,
    knowledge_base_id: str = Query(min_length=1, max_length=128),
    folder_path: str = Query(min_length=1, max_length=4096),
    recursive: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    normalized_path = normalize_folder_path(folder_path)
    folder = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=knowledge_base_id,
        node_type="folder",
        folder_path=normalized_path,
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="目录不存在。")
    require_catalogue_capability(db, project_id, user, folder, "can_delete")
    try:
        _agentscope_client().delete_weknora_folder(
            agent_id,
            knowledge_base_id,
            folder_path=normalized_path,
            recursive=recursive,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    delete_local_folder_subtree(
        db,
        project_id,
        knowledge_base_id,
        normalized_path,
    )
    audit(
        db,
        user,
        "删除工程资料目录",
        (
            f"从 WeKnora 递归删除目录「{folder_path}」及全部内容"
            if recursive
            else f"从 WeKnora 删除空目录「{folder_path}」"
        ),
        project_id,
        "weknora_folder",
    )
    db.commit()
    return ok(None, "目录及其内容已删除" if recursive else "空目录已删除")


@router.put("/projects/{project_id}/engineering-documents/folder")
def update_engineering_document_folder(
    project_id: int,
    payload: EngineeringDocumentFolderUpdateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    source_path = normalize_folder_path(payload.source_path)
    target_path = normalize_folder_path(payload.target_path)
    folder = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=payload.knowledge_base_id,
        node_type="folder",
        folder_path=source_path,
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="目录不存在。")
    require_catalogue_capability(db, project_id, user, folder, "can_update")
    target_parent_path = target_path.rpartition("/")[0]
    target_parent = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=payload.knowledge_base_id,
        node_type="folder" if target_parent_path else "knowledge_base",
        folder_path=target_parent_path if target_parent_path else None,
    )
    if target_parent is None:
        raise HTTPException(status_code=409, detail="目标上级目录不存在。")
    require_catalogue_capability(
        db, project_id, user, target_parent, "can_create",
    )
    try:
        result = _agentscope_client().update_weknora_folder(
            agent_id,
            payload.knowledge_base_id,
            source_path=source_path,
            target_path=target_path,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    local_folder = update_local_folder_path(
        db,
        project_id,
        payload.knowledge_base_id,
        source_path,
        target_path,
    )
    audit(
        db,
        user,
        "调整工程资料目录",
        f"将「{payload.source_path}」调整为「{payload.target_path}」",
        project_id,
        "weknora_folder",
    )
    db.commit()
    return ok(
        {**result, "node_id": local_folder.id, "folder_path": target_path},
        "文件夹已更新",
    )


@router.post("/projects/{project_id}/engineering-documents/move")
def move_engineering_documents(
    project_id: int,
    payload: EngineeringDocumentMoveInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    target_path = normalize_folder_path(payload.folder_path)
    target_parent = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=payload.knowledge_base_id,
        node_type="folder" if target_path else "knowledge_base",
        folder_path=target_path if target_path else None,
    )
    if target_parent is None:
        raise HTTPException(status_code=409, detail="目标目录不存在。")
    require_catalogue_capability(
        db, project_id, user, target_parent, "can_create",
    )
    for knowledge_id in payload.knowledge_ids:
        file_node = find_catalogue_node(
            db,
            project_id,
            knowledge_base_id=payload.knowledge_base_id,
            node_type="file",
            external_id=knowledge_id,
        )
        if file_node is None:
            raise HTTPException(status_code=409, detail="部分资料尚未同步到平台。")
        require_catalogue_capability(
            db, project_id, user, file_node, "can_update",
        )
    try:
        result = _agentscope_client().move_weknora_knowledge(
            agent_id,
            payload.knowledge_base_id,
            knowledge_ids=payload.knowledge_ids,
            folder_path=target_path,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    move_local_files(
        db,
        project_id,
        payload.knowledge_base_id,
        payload.knowledge_ids,
        target_path,
    )
    audit(
        db,
        user,
        "移动工程资料",
        f"移动 {len(payload.knowledge_ids)} 份 WeKnora 资料",
        project_id,
        "weknora_knowledge",
    )
    db.commit()
    return ok(result, "资料已移动")


@router.get(
    "/projects/{project_id}/engineering-documents/knowledge/{knowledge_id}",
)
def get_engineering_document(
    project_id: int,
    knowledge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the current WeKnora location for one project-authorized file."""

    project_for_user_or_403(db, project_id, user)
    _ready_project_weknora_agent_id(db, project_id)
    _, result = local_file_view(db, project_id, knowledge_id, user)
    return ok(result)


@router.delete(
    "/projects/{project_id}/engineering-documents/knowledge/{knowledge_id}",
)
def delete_engineering_document(
    project_id: int,
    knowledge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    local_file_view(db, project_id, knowledge_id, user, "can_delete")
    try:
        _agentscope_client().delete_weknora_knowledge(
            agent_id,
            knowledge_id,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    delete_local_file(db, project_id, knowledge_id)
    audit(
        db,
        user,
        "删除工程资料",
        f"从 WeKnora 删除资料 {knowledge_id}",
        project_id,
        "weknora_knowledge",
    )
    db.commit()
    return ok(None, "资料已删除")


def _engineering_document_content_response(
    project_id: int,
    knowledge_id: str,
    operation: str,
    db: Session,
    user: User,
) -> StreamingResponse:
    project_for_user_or_403(db, project_id, user)
    agent_id = _ready_project_weknora_agent_id(db, project_id)
    local_file_view(db, project_id, knowledge_id, user)
    try:
        content, content_type, content_disposition = (
            _agentscope_client().get_weknora_knowledge_content(
                agent_id,
                knowledge_id,
                operation,
            )
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    headers = {"Cache-Control": "private, no-store"}
    if content_disposition and "\n" not in content_disposition and "\r" not in content_disposition:
        headers["Content-Disposition"] = content_disposition
    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers=headers,
    )


@router.get(
    "/projects/{project_id}/engineering-documents/knowledge/"
    "{knowledge_id}/download",
)
def download_engineering_document(
    project_id: int,
    knowledge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    return _engineering_document_content_response(
        project_id,
        knowledge_id,
        "download",
        db,
        user,
    )


@router.get(
    "/projects/{project_id}/engineering-documents/knowledge/"
    "{knowledge_id}/preview",
)
def preview_engineering_document(
    project_id: int,
    knowledge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    return _engineering_document_content_response(
        project_id,
        knowledge_id,
        "preview",
        db,
        user,
    )


@router.get(
    "/projects/{project_id}/engineering-documents/resources/{resource_id}",
)
def proxy_engineering_document_resource(
    project_id: int,
    resource_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    project_for_user_or_403(db, project_id, user)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", resource_id):
        raise HTTPException(status_code=422, detail="WeKnora 资源句柄无效。")
    try:
        content, content_type, content_disposition = (
            _agentscope_client().get_weknora_resource_content(
                _project_weknora_agent_id(db, project_id),
                resource_id,
            )
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    headers = {"Cache-Control": "private, no-store"}
    if (
        content_disposition
        and "\n" not in content_disposition
        and "\r" not in content_disposition
    ):
        headers["Content-Disposition"] = content_disposition
    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers=headers,
    )


@router.get("/projects/{project_id}/engineering-knowledge-conversations")
def list_engineering_knowledge_conversations(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    rows = db.scalars(
        select(EngineeringKnowledgeConversation)
        .where(
            EngineeringKnowledgeConversation.project_id == project_id,
            EngineeringKnowledgeConversation.user_id == user.id,
        )
        .order_by(
            EngineeringKnowledgeConversation.updated_at.desc(),
            EngineeringKnowledgeConversation.id.desc(),
        )
        .limit(100),
    ).all()
    return ok([
        _engineering_knowledge_conversation_view(row)
        for row in rows
    ])


@router.post("/projects/{project_id}/engineering-knowledge-conversations")
def create_engineering_knowledge_conversation(
    project_id: int,
    payload: EngineeringKnowledgeConversationCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    first_message = payload.first_message.strip()
    if not first_message:
        raise HTTPException(status_code=422, detail="首条消息不能为空")
    knowledge_id = (payload.knowledge_id or "").strip() or None
    knowledge_name = (payload.knowledge_name or "").strip() or None
    knowledge_base_id = (payload.knowledge_base_id or "").strip() or None
    folder_path = (payload.folder_path or "").strip().strip("/") or None
    scope_items: list[dict[str, str | None]] = []
    scope_item_keys: set[tuple[str, str, str]] = set()
    for raw_item in payload.scope_items:
        item_type = raw_item.scope_type
        item_knowledge_id = (raw_item.knowledge_id or "").strip() or None
        item_name = (raw_item.knowledge_name or "").strip() or None
        item_knowledge_base_id = (
            (raw_item.knowledge_base_id or "").strip() or None
        )
        item_folder_path = (
            (raw_item.folder_path or "").strip().strip("/") or None
        )
        if item_type == "document" and item_knowledge_id is None:
            raise HTTPException(status_code=422, detail="多选范围中的文件缺少资料 ID")
        if item_type == "knowledge_base" and item_knowledge_base_id is None:
            raise HTTPException(status_code=422, detail="多选范围中的知识库缺少知识库 ID")
        if item_type == "folder" and (
            item_knowledge_base_id is None or item_folder_path is None
        ):
            raise HTTPException(status_code=422, detail="多选范围中的目录信息不完整")
        item_key = (
            item_type,
            item_knowledge_id or item_knowledge_base_id or "",
            item_folder_path or "",
        )
        if item_key in scope_item_keys:
            continue
        scope_item_keys.add(item_key)
        scope_items.append(
            {
                "scope_type": item_type,
                "knowledge_id": item_knowledge_id,
                "knowledge_name": item_name,
                "knowledge_base_id": item_knowledge_base_id,
                "folder_path": item_folder_path,
            },
        )
    if payload.scope_type == "document" and knowledge_id is None:
        raise HTTPException(status_code=422, detail="单文件问答必须指定资料")
    if payload.scope_type == "knowledge_base" and knowledge_base_id is None:
        raise HTTPException(status_code=422, detail="知识库问答必须指定知识库")
    if payload.scope_type == "folder" and (
        knowledge_base_id is None or folder_path is None
    ):
        raise HTTPException(status_code=422, detail="目录问答必须指定知识库和目录路径")
    if payload.scope_type == "selection" and not scope_items:
        raise HTTPException(status_code=422, detail="多选问答范围不能为空")
    if payload.scope_type == "project":
        knowledge_id = None
        knowledge_name = None
        knowledge_base_id = None
        folder_path = None
        scope_items = []
    elif payload.scope_type == "knowledge_base":
        knowledge_id = None
        folder_path = None
        scope_items = []
    elif payload.scope_type == "folder":
        knowledge_id = None
        scope_items = []
    elif payload.scope_type == "document":
        folder_path = None
        scope_items = []
    else:
        knowledge_id = None
        knowledge_name = None
        knowledge_base_id = None
        folder_path = None
    title = (payload.title or first_message[:60]).strip()
    conversation = EngineeringKnowledgeConversation(
        project_id=project.id,
        user_id=user.id,
        title=title[:300],
        scope_type=payload.scope_type,
        knowledge_id=knowledge_id,
        knowledge_name=knowledge_name,
        knowledge_base_id=knowledge_base_id,
        folder_path=folder_path,
        scope_items=scope_items or None,
    )
    db.add(conversation)
    db.flush()
    message = EngineeringKnowledgeMessage(
        conversation_id=conversation.id,
        role="user",
        content=first_message,
        references=[],
        failed=False,
    )
    db.add(message)
    audit(
        db,
        user,
        "创建知识库对话",
        f"创建知识库对话「{conversation.title}」",
        project.id,
        "engineering_knowledge_conversation",
        conversation.id,
    )
    db.commit()
    db.refresh(conversation)
    db.refresh(message)
    return ok(
        {
            "conversation": _engineering_knowledge_conversation_view(
                conversation,
            ),
            "messages": [_engineering_knowledge_message_view(message)],
        },
        "知识库对话已创建",
    )


@router.patch(
    "/projects/{project_id}/engineering-knowledge-conversations/"
    "{conversation_id}",
)
def update_engineering_knowledge_conversation(
    project_id: int,
    conversation_id: int,
    payload: EngineeringKnowledgeConversationUpdateInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _engineering_knowledge_conversation_or_404(
        db,
        project_id,
        conversation_id,
        user,
    )
    fields = payload.model_fields_set
    if "title" in fields:
        title = (payload.title or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="对话标题不能为空")
        conversation.title = title[:300]
    if "weknora_session_id" in fields:
        conversation.weknora_session_id = (
            (payload.weknora_session_id or "").strip() or None
        )
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)
    return ok(
        _engineering_knowledge_conversation_view(conversation),
        "知识库对话已更新",
    )


@router.get(
    "/projects/{project_id}/engineering-knowledge-conversations/"
    "{conversation_id}/messages",
)
def list_engineering_knowledge_messages(
    project_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _engineering_knowledge_conversation_or_404(
        db,
        project_id,
        conversation_id,
        user,
    )
    rows = db.scalars(
        select(EngineeringKnowledgeMessage)
        .where(
            EngineeringKnowledgeMessage.conversation_id == conversation_id,
        )
        .order_by(
            EngineeringKnowledgeMessage.created_at,
            EngineeringKnowledgeMessage.id,
        ),
    ).all()
    allowed_knowledge_ids = _restricted_engineering_knowledge_ids(
        db,
        project_id,
        user,
    )
    return ok(
        [
            _engineering_knowledge_message_view(
                row,
                allowed_knowledge_ids,
            )
            for row in rows
        ],
    )


@router.post(
    "/projects/{project_id}/engineering-knowledge-conversations/"
    "{conversation_id}/messages",
)
def create_engineering_knowledge_message(
    project_id: int,
    conversation_id: int,
    payload: EngineeringKnowledgeMessageInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _engineering_knowledge_conversation_or_404(
        db,
        project_id,
        conversation_id,
        user,
    )
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    row = EngineeringKnowledgeMessage(
        conversation_id=conversation.id,
        role=payload.role,
        content=content,
        references=payload.references,
        failed=payload.failed,
    )
    db.add(row)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return ok(
        _engineering_knowledge_message_view(
            row,
            _restricted_engineering_knowledge_ids(db, project_id, user),
        ),
        "知识库消息已保存",
    )


@router.delete(
    "/projects/{project_id}/engineering-knowledge-conversations/"
    "{conversation_id}",
)
def delete_engineering_knowledge_conversation(
    project_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _engineering_knowledge_conversation_or_404(
        db,
        project_id,
        conversation_id,
        user,
    )
    title = conversation.title
    db.execute(
        delete(EngineeringKnowledgeMessage).where(
            EngineeringKnowledgeMessage.conversation_id == conversation.id,
        ),
    )
    audit(
        db,
        user,
        "删除知识库对话",
        f"删除知识库对话「{title}」及其聊天记录",
        project_id,
        "engineering_knowledge_conversation",
        conversation.id,
    )
    db.delete(conversation)
    db.commit()
    return ok({"id": conversation_id}, "知识库对话已删除")


@router.post("/projects/{project_id}/engineering-documents/ask")
def ask_engineering_documents(
    project_id: int,
    payload: EngineeringDocumentAskInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    agent_id = _project_weknora_agent_id(db, project_id)
    _ready_project_weknora_agent_id(db, project_id)
    request_body = authorized_qa_payload(
        db,
        project_id,
        user,
        payload.model_dump(exclude_none=True),
    )
    request_body = _reset_unsafe_engineering_knowledge_session(
        db,
        project_id,
        user,
        request_body,
    )
    try:
        result = _agentscope_client().ask_weknora_agent(
            agent_id,
            request_body,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    return ok(filter_search_result(db, project_id, user, result))


def _project_weknora_reference_urls(
    project_id: int,
    event: dict[str, Any],
    allowed_knowledge_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Replace internal AgentScope source URLs with project-authorized URLs."""

    references = event.get("knowledge_references")
    if not isinstance(references, list):
        return event
    rewritten: list[dict[str, Any]] = []
    for raw in references:
        if not isinstance(raw, dict):
            continue
        reference = dict(raw)
        knowledge_id = str(reference.get("knowledge_id") or "").strip()
        if (
            allowed_knowledge_ids is not None
            and knowledge_id not in allowed_knowledge_ids
        ):
            continue
        if knowledge_id:
            encoded_id = quote(knowledge_id, safe="")
            base = (
                f"/api/projects/{project_id}/engineering-documents/"
                f"knowledge/{encoded_id}"
            )
            reference["download_url"] = f"{base}/download"
            reference["preview_url"] = f"{base}/preview"
        rewritten.append(reference)
    return {**event, "knowledge_references": rewritten}


@router.post("/projects/{project_id}/engineering-documents/ask/stream")
async def stream_engineering_document_answer(
    project_id: int,
    payload: EngineeringDocumentAskInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    project_for_user_or_403(db, project_id, user)
    agent_id = _project_weknora_agent_id(db, project_id)
    _ready_project_weknora_agent_id(db, project_id)
    client = _agentscope_client()
    request_body = authorized_qa_payload(
        db,
        project_id,
        user,
        payload.model_dump(exclude_none=True),
    )
    request_body = _reset_unsafe_engineering_knowledge_session(
        db,
        project_id,
        user,
        request_body,
    )
    allowed_knowledge_ids = readable_external_ids(db, project_id, user)

    async def relay() -> AsyncIterator[str]:
        session_id = str(request_body.get("session_id") or "")
        try:
            async with client.weknora_agent_stream(
                agent_id,
                request_body,
            ) as events:
                async for raw_event in events:
                    event = _project_weknora_reference_urls(
                        project_id,
                        raw_event,
                        allowed_knowledge_ids,
                    )
                    remote_session_id = str(
                        event.get("session_id") or "",
                    ).strip()
                    if remote_session_id:
                        session_id = remote_session_id
                    yield _sse_frame("message", event)
        except asyncio.CancelledError:
            if session_id:
                with suppress(Exception):
                    await asyncio.to_thread(
                        client.stop_weknora_agent_session,
                        agent_id,
                        session_id,
                    )
            raise
        except AgentScopeGatewayError as exc:
            yield _sse_frame(
                "message",
                {
                    "response_type": "error",
                    "session_id": session_id,
                    "content": str(exc),
                    "status_code": exc.status_code,
                    "done": True,
                },
            )

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/projects/{project_id}/engineering-documents/sessions")
def create_engineering_document_session(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    try:
        result = _agentscope_client().create_weknora_agent_session(
            _project_weknora_agent_id(db, project_id),
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    return ok(result)


@router.post(
    "/projects/{project_id}/engineering-documents/sessions/"
    "{session_id}/stop",
)
def stop_engineering_document_answer(
    project_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    if not 1 <= len(session_id) <= 128:
        raise HTTPException(status_code=422, detail="WeKnora 会话 ID 无效。")
    try:
        result = _agentscope_client().stop_weknora_agent_session(
            _project_weknora_agent_id(db, project_id),
            session_id,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    return ok(result)


@router.get("/projects/{project_id}/document-folders")
def list_document_folders(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = db.scalars(select(DocumentFolder).where(DocumentFolder.project_id == project_id).order_by(DocumentFolder.created_at, DocumentFolder.id)).all()
    return ok([serialize(row) for row in rows])


@router.post("/projects/{project_id}/document-folders")
def create_document_folder(project_id: int, payload: DocumentFolderInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    name = payload.name.strip()
    if payload.parent_id:
        parent = entity_or_404(db, DocumentFolder, payload.parent_id, "上级文件夹不存在")
        if parent.project_id != project_id:
            raise HTTPException(status_code=422, detail="上级文件夹不属于当前项目")
    stmt = select(DocumentFolder).where(DocumentFolder.project_id == project_id, DocumentFolder.name == name)
    stmt = stmt.where(DocumentFolder.parent_id == payload.parent_id) if payload.parent_id else stmt.where(DocumentFolder.parent_id.is_(None))
    if db.scalar(stmt):
        raise HTTPException(status_code=409, detail="同级目录下已存在同名文件夹")
    row = DocumentFolder(project_id=project_id, parent_id=payload.parent_id, name=name)
    db.add(row); db.flush()
    audit(db, user, "新建资料文件夹", f"新建资料文件夹「{name}」", project_id, "document_folder", row.id)
    db.commit(); db.refresh(row)
    return ok(serialize(row), "文件夹已创建")


@router.post("/projects/{project_id}/attachments")
def upload_attachment(project_id: int, file: UploadFile = File(...), category: str = "未分类", folder_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if folder_id:
        target_folder = entity_or_404(db, DocumentFolder, folder_id, "目标文件夹不存在")
        if target_folder.project_id != project_id:
            raise HTTPException(status_code=422, detail="目标文件夹不属于当前项目")
    settings = get_settings(); folder = settings.upload_dir / str(project_id); folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "attachment").name; target = folder / f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    with target.open("wb") as output: shutil.copyfileobj(file.file, output)
    content = target.read_bytes(); digest = hashlib.sha256(content).hexdigest()
    if category == "自动归类":
        normalized = safe_name.lower()
        category = "日报" if "日报" in normalized else "进度计划" if any(key in normalized for key in ["wbs", "计划", "进度"]) else "风险资料" if any(key in normalized for key in ["风险", "监测", "隐患"]) else "工程资料"
    previous_version = db.scalar(select(func.max(Attachment.version)).where(Attachment.project_id == project_id, Attachment.file_name == safe_name)) or 0
    row = Attachment(project_id=project_id, file_name=safe_name, storage_path=str(target), content_type=file.content_type, file_size=len(content), file_hash=digest, category=category, version=previous_version + 1)
    db.add(row); db.flush()
    if folder_id:
        db.add(DocumentFolderItem(attachment_id=row.id, folder_id=folder_id, project_id=project_id))
    try:
        parsed = parse_uploaded_attachment(
            content,
            file_name=safe_name,
            media_type=file.content_type,
        )
        attachment_text = AttachmentText(
            attachment_id=row.id,
            project_id=project_id,
            content=parsed.content,
            parse_status="ready",
            parser="+".join(parsed.parsers),
            parse_details=parsed.details,
        )
        response_message = "资料已上传并完成附件解析"
    except SystemAttachmentParserError as exc:
        attachment_text = AttachmentText(
            attachment_id=row.id,
            project_id=project_id,
            content="",
            parse_status="failed",
            parse_error=str(exc),
            parse_details={
                "version": 1,
                "status": "failed",
                "file_name": safe_name,
                "error": str(exc),
            },
        )
        response_message = "资料已上传，但附件解析失败"
    db.add(attachment_text)
    audit(db, user, "上传资料", f"上传资料「{safe_name}」", project_id, "attachment", row.id); db.commit(); db.refresh(row)
    return ok(
        {
            **serialize(row),
            "attachment_preprocessing": attachment_text.parse_details,
        },
        response_message,
    )


@router.get("/projects/{project_id}/attachments")
def list_attachments(project_id: int, keyword: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); stmt = select(Attachment, DocumentFolderItem.folder_id, AttachmentText.parse_details).outerjoin(DocumentFolderItem, DocumentFolderItem.attachment_id == Attachment.id).outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id).where(Attachment.project_id == project_id)
    if keyword: stmt = stmt.where(Attachment.file_name.contains(keyword))
    rows = db.execute(stmt.order_by(Attachment.created_at.desc())).all()
    return ok([{**serialize(attachment), "folder_id": folder_id, "attachment_preprocessing": parse_details or {"status": "pending"}} for attachment, folder_id, parse_details in rows])


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """下载项目附件，并在返回文件前校验当前用户的项目成员身份。"""
    attachment = entity_or_404(db, Attachment, attachment_id, "附件不存在")
    project_for_user_or_403(db, attachment.project_id, user)
    path = Path(attachment.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="附件文件不存在")
    return FileResponse(
        path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.file_name,
        headers={"Cache-Control": "private, no-store"},
    )


@router.patch("/attachments/{attachment_id}")
def update_attachment(attachment_id: int, payload: AttachmentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    attachment = entity_or_404(db, Attachment, attachment_id, "资料不存在")
    attachment.category = payload.category.strip()
    audit(db, user, "更新资料分类", f"资料「{attachment.file_name}」分类更新为「{attachment.category}」", attachment.project_id, "attachment", attachment.id)
    db.commit(); db.refresh(attachment)
    return ok(serialize(attachment), "资料分类已更新")


@router.get("/projects/{project_id}/document-search")
def search_documents(project_id: int, keyword: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if not keyword.strip(): return ok([])
    rows = db.execute(select(Attachment, AttachmentText.content, AttachmentText.parse_status, AttachmentText.parse_error, DocumentFolderItem.folder_id).outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id).outerjoin(DocumentFolderItem, DocumentFolderItem.attachment_id == Attachment.id).where(Attachment.project_id == project_id, (Attachment.file_name.contains(keyword) | ((AttachmentText.parse_status == "ready") & AttachmentText.content.contains(keyword)))).order_by(Attachment.created_at.desc())).all()
    result = []
    for attachment, content, parse_status, parse_error, folder_id in rows:
        item = serialize(attachment)
        item["folder_id"] = folder_id
        item["attachment_preprocessing"] = {
            "status": parse_status or "pending",
            "error": parse_error,
        }
        if parse_status == "ready" and content:
            index = content.lower().find(keyword.lower())
            item["snippet"] = content[max(0, index - 40): index + len(keyword) + 80] if index >= 0 else ""
        result.append(item)
    return ok(result)


@router.post("/attachments/{attachment_id}/parse-daily")
def parse_daily_attachment(attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """将已入库日报登记为待确认记录，并生成对应的确认任务。"""
    attachment = entity_or_404(db, Attachment, attachment_id, "资料不存在")
    duplicate = db.scalar(select(DailyReport).where(
        DailyReport.project_id == attachment.project_id,
        DailyReport.file_name == attachment.file_name,
    ))
    if duplicate:
        return ok(serialize(duplicate), "该日报已登记，无需重复创建")

    attachment_text = db.get(AttachmentText, attachment.id)
    content = (
        attachment_text.content[:10000]
        if attachment_text is not None
        and attachment_text.parse_status == "ready"
        else ""
    )
    if not content:
        content = f"已归档文件「{attachment.file_name}」，请在确认前补充施工内容、进度和风险信息。"

    date_match = re.search(r"20\d{2}[-_.年/]?\d{1,2}[-_.月/]?\d{1,2}", attachment.file_name)
    report_date = date_match.group(0).replace("年", "-").replace("月", "-").replace("日", "").replace("_", "-").replace(".", "-").replace("/", "-") if date_match else datetime.now(UTC).date().isoformat()
    candidates = db.scalars(select(WbsItem).where(WbsItem.project_id == attachment.project_id)).all()
    matched = next((item for item in candidates if item.name and item.name.lower() in attachment.file_name.lower()), None)
    report = DailyReport(project_id=attachment.project_id, file_name=attachment.file_name, report_date=report_date, content=content,
                         matched_wbs_id=matched.id if matched else None, confidence=0.85 if matched else 0.45,
                         parse_status="parsed", status="pending_confirm")
    db.add(report); db.flush()
    attachment.source_type = "daily_report"; attachment.source_id = report.id
    try:
        dispatch_platform_task(
            db,
            project_id=attachment.project_id,
            title=f"日报解析确认 — {attachment.file_name}",
            task_type="daily_confirm",
            risk_level="low",
            assignee_user_id=user.id,
            confirmer_user_id=user.id,
            wbs_item_id=report.matched_wbs_id,
            actor=user.id,
            trigger_reason="资料入库后登记日报，等待人工确认解析内容",
            deliverables=[attachment.file_name],
            step_name="确认日报解析内容",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(db, user, "登记日报解析", f"资料「{attachment.file_name}」已生成日报确认任务", attachment.project_id, "daily_report", report.id)
    db.commit(); db.refresh(report)
    return ok(serialize(report), "日报已登记，并生成确认任务")


@router.get("/projects/{project_id}/operation-logs")
def list_operation_logs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    return ok([serialize(row) for row in db.scalars(select(OperationLog).where(OperationLog.project_id == project_id).order_by(OperationLog.created_at.desc())).all()])


@router.post("/projects/{project_id}/operation-logs")
def create_operation_log(project_id: int, payload: OperationLogInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    audit(db, user, payload.action, payload.detail, project_id, payload.target_type, payload.target_id)
    db.commit()
    row = db.scalars(select(OperationLog).where(OperationLog.project_id == project_id).order_by(OperationLog.id.desc())).first()
    return ok(serialize(row), "日志已记录")
