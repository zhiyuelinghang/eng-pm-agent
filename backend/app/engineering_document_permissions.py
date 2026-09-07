from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import engineering_document_catalog as _catalogue
from .models import (
    EngineeringDocumentNode,
    EngineeringDocumentPermission,
    EngineeringDocumentSyncState,
    ProjectMember,
    ProjectPosition,
    User,
)


CATALOG_CAPABILITIES = _catalogue.CATALOG_CAPABILITIES
get_or_create_sync_state = _catalogue.get_or_create_sync_state
sync_state_view = _catalogue.sync_state_view


def permission_configuration_view(
    db: Session,
    project_id: int,
    *,
    include_nodes: bool = True,
) -> dict[str, Any]:
    state_row = get_or_create_sync_state(db, project_id)
    # The permission tree only needs hierarchy fields. Selecting the complete ORM
    # entity would also transfer large descriptions and metadata for every file.
    node_rows = (
        db.execute(
            select(
                EngineeringDocumentNode.id,
                EngineeringDocumentNode.parent_id,
                EngineeringDocumentNode.node_type,
                EngineeringDocumentNode.knowledge_base_id,
                EngineeringDocumentNode.external_id,
                EngineeringDocumentNode.name,
                EngineeringDocumentNode.folder_path,
            )
            .where(EngineeringDocumentNode.project_id == project_id)
            .order_by(
                EngineeringDocumentNode.knowledge_base_id,
                EngineeringDocumentNode.id,
            ),
        ).mappings().all()
        if include_nodes
        else []
    )
    grants = db.scalars(
        select(EngineeringDocumentPermission)
        .where(EngineeringDocumentPermission.project_id == project_id)
        .order_by(EngineeringDocumentPermission.id),
    ).all()
    positions = db.scalars(
        select(ProjectPosition)
        .where(ProjectPosition.project_id == project_id)
        .order_by(ProjectPosition.position_name),
    ).all()
    members = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.real_name),
    ).all()
    return {
        "access_mode": state_row.access_mode,
        "sync": sync_state_view(state_row),
        "nodes": [dict(node) for node in node_rows],
        "subjects": {
            "users": [
                {
                    "id": user.id,
                    "name": user.real_name,
                    "username": user.username,
                }
                for _, user in members
            ],
            "positions": [
                {"id": position.id, "name": position.position_name}
                for position in positions
            ],
        },
        "permissions": [
            {
                "id": grant.id,
                "node_id": grant.node_id,
                "subject_type": grant.subject_type,
                "subject_id": grant.subject_id,
                **{
                    name: bool(getattr(grant, name))
                    for name in CATALOG_CAPABILITIES
                },
                "inherit_to_children": grant.inherit_to_children,
            }
            for grant in grants
        ],
    }


def set_catalogue_access_mode(
    db: Session,
    project_id: int,
    access_mode: str,
) -> EngineeringDocumentSyncState:
    if access_mode not in {"project", "restricted"}:
        raise ValueError("Invalid catalogue access mode")
    state_row = get_or_create_sync_state(db, project_id)
    state_row.access_mode = access_mode
    return state_row


def upsert_catalogue_permission(
    db: Session,
    project_id: int,
    *,
    node_id: int,
    subject_type: str,
    subject_id: int,
    values: dict[str, bool],
    granted_by_user_id: int,
) -> EngineeringDocumentPermission:
    node = db.get(EngineeringDocumentNode, node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=404, detail="工程资料目录节点不存在。")
    if subject_type == "user":
        valid_subject = db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == subject_id,
            ),
        )
    elif subject_type == "position":
        valid_subject = db.scalar(
            select(ProjectPosition.id).where(
                ProjectPosition.project_id == project_id,
                ProjectPosition.id == subject_id,
            ),
        )
    else:
        valid_subject = None
    if valid_subject is None:
        raise HTTPException(status_code=422, detail="授权对象不属于当前项目。")
    row = db.scalar(
        select(EngineeringDocumentPermission).where(
            EngineeringDocumentPermission.project_id == project_id,
            EngineeringDocumentPermission.node_id == node_id,
            EngineeringDocumentPermission.subject_type == subject_type,
            EngineeringDocumentPermission.subject_id == subject_id,
        ),
    )
    if row is None:
        row = EngineeringDocumentPermission(
            project_id=project_id,
            node_id=node_id,
            subject_type=subject_type,
            subject_id=subject_id,
            granted_by_user_id=granted_by_user_id,
        )
        db.add(row)
    for name in CATALOG_CAPABILITIES:
        setattr(row, name, bool(values.get(name, False)))
    row.inherit_to_children = bool(values.get("inherit_to_children", True))
    return row
