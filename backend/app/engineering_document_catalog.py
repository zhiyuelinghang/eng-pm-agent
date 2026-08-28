"""Local WeKnora catalogue, synchronization and hierarchical authorization.

WeKnora remains the binary/content system of record.  This module makes the
platform database authoritative for navigation metadata and access decisions,
so ordinary page loads never need to crawl the remote directory API.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .agentscope_client import AgentScopeClient
from .config import get_settings
from .db import SessionLocal
from .models import (
    EngineeringDocumentNode,
    EngineeringDocumentPermission,
    EngineeringDocumentSyncState,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    User,
)


CATALOG_CAPABILITIES = (
    "can_read",
    "can_create",
    "can_update",
    "can_delete",
    "can_manage",
)


def normalize_folder_path(value: str | None) -> str:
    """Normalize a WeKnora path without changing user-visible segment text."""

    return "/".join(
        segment.strip()
        for segment in str(value or "").replace("\\", "/").split("/")
        if segment.strip() and segment.strip() != "."
    )


def catalogue_node_key(
    node_type: str,
    knowledge_base_id: str,
    identity: str,
) -> str:
    raw = f"{node_type}\0{knowledge_base_id}\0{identity}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _as_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def local_catalogue_knowledge_base_ids(
    db: Session,
    project_id: int,
) -> list[str]:
    """Return the knowledge bases currently mirrored for one project."""

    return list(
        db.scalars(
            select(EngineeringDocumentNode.knowledge_base_id)
            .where(
                EngineeringDocumentNode.project_id == project_id,
                EngineeringDocumentNode.node_type == "knowledge_base",
            )
            .order_by(EngineeringDocumentNode.name, EngineeringDocumentNode.id),
        ).all(),
    )


def sync_state_view(
    state: EngineeringDocumentSyncState | None,
    *,
    knowledge_base_ids: Iterable[str] = (),
) -> dict[str, Any]:
    selected_ids = list(dict.fromkeys(knowledge_base_ids))
    if state is None:
        return {
            "status": "uninitialized",
            "access_mode": "project",
            "revision": 0,
            "knowledge_base_ids": selected_ids,
            "last_started_at": None,
            "last_completed_at": None,
            "last_error": None,
        }
    return {
        "status": state.status,
        "access_mode": state.access_mode,
        "revision": state.revision,
        "knowledge_base_ids": selected_ids,
        "last_started_at": (
            state.last_started_at.isoformat() if state.last_started_at else None
        ),
        "last_completed_at": (
            state.last_completed_at.isoformat()
            if state.last_completed_at
            else None
        ),
        "last_error": state.last_error,
    }


def get_or_create_sync_state(
    db: Session,
    project_id: int,
    agent_id: str | None = None,
) -> EngineeringDocumentSyncState:
    state_row = db.get(EngineeringDocumentSyncState, project_id)
    if state_row is None:
        state_row = EngineeringDocumentSyncState(
            project_id=project_id,
            weknora_agent_id=agent_id,
            status="pending",
        )
        db.add(state_row)
        db.flush()
    elif agent_id is not None:
        state_row.weknora_agent_id = agent_id
    return state_row


def mark_catalogue_pending(
    db: Session,
    project_id: int,
    agent_id: str,
) -> EngineeringDocumentSyncState:
    previous_state = db.get(EngineeringDocumentSyncState, project_id)
    if (
        previous_state is not None
        and previous_state.weknora_agent_id
        and previous_state.weknora_agent_id != agent_id
    ):
        # A different robot is a different source boundary.  Keeping the old
        # tree while the new source initializes would expose stale metadata
        # and preserve grants against unrelated nodes.
        clear_document_catalogue(db, project_id)
    state_row = get_or_create_sync_state(db, project_id, agent_id)
    state_row.status = "pending"
    state_row.last_error = None
    return state_row


def clear_document_catalogue(db: Session, project_id: int) -> None:
    """Remove stale metadata when a project is explicitly unbound."""

    db.execute(
        delete(EngineeringDocumentPermission).where(
            EngineeringDocumentPermission.project_id == project_id,
        ),
    )
    rows = db.scalars(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project_id,
        ),
    ).all()
    for row in sorted(rows, key=_delete_sort_key):
        db.delete(row)
        db.flush()
    state_row = db.get(EngineeringDocumentSyncState, project_id)
    if state_row is not None:
        db.delete(state_row)
        db.flush()


def _delete_sort_key(node: EngineeringDocumentNode) -> tuple[int, int]:
    type_rank = {"file": 0, "folder": 1, "knowledge_base": 2}
    depth = normalize_folder_path(node.folder_path).count("/")
    return (type_rank.get(node.node_type, 3), -depth)


def _folder_payloads(tree: dict[str, Any]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def ensure_path(path: str) -> None:
        current = ""
        for segment in normalize_folder_path(path).split("/"):
            if not segment:
                continue
            current = f"{current}/{segment}" if current else segment
            rows.setdefault(
                current,
                {
                    "path": current,
                    "name": segment,
                    "document_count": 0,
                    "total_count": 0,
                },
            )

    def walk(items: Iterable[dict[str, Any]]) -> None:
        for raw in items:
            path = normalize_folder_path(raw.get("path"))
            if not path:
                continue
            ensure_path(path)
            rows[path].update(
                {
                    "path": path,
                    "name": str(raw.get("name") or path.rsplit("/", 1)[-1]),
                    "document_count": _safe_int(raw.get("document_count")),
                    "total_count": _safe_int(raw.get("total_count")),
                },
            )
            children = raw.get("children")
            if isinstance(children, list):
                walk(item for item in children if isinstance(item, dict))

    folders = tree.get("folders")
    if isinstance(folders, list):
        walk(item for item in folders if isinstance(item, dict))
    return sorted(rows.values(), key=lambda item: (item["path"].count("/"), item["path"]))


def _collect_remote_catalogue(
    client: AgentScopeClient,
    agent_id: str,
    knowledge_base_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    response = client.list_weknora_knowledge_bases(agent_id)
    knowledge_bases = response.get("knowledge_bases", [])
    if not isinstance(knowledge_bases, list):
        knowledge_bases = []

    available_by_id = {
        str(item.get("id") or "").strip(): item
        for item in knowledge_bases
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if knowledge_base_ids is None:
        selected_bases = list(available_by_id.values())
    else:
        selected_ids = list(
            dict.fromkeys(
                str(item).strip()
                for item in knowledge_base_ids
                if str(item).strip()
            ),
        )
        if not selected_ids:
            raise ValueError("请至少选择一个需要同步的 WeKnora 知识库")
        missing_ids = [item for item in selected_ids if item not in available_by_id]
        if missing_ids:
            raise ValueError(
                "所选知识库不属于当前项目绑定的机器人："
                + "、".join(missing_ids),
            )
        selected_bases = [available_by_id[item] for item in selected_ids]

    desired: list[dict[str, Any]] = []
    for base in selected_bases:
        knowledge_base_id = str(base.get("id") or "").strip()
        if not knowledge_base_id:
            continue
        tree = client.get_weknora_folder_tree(agent_id, knowledge_base_id)
        root_key = catalogue_node_key(
            "knowledge_base",
            knowledge_base_id,
            knowledge_base_id,
        )
        desired.append(
            {
                "node_type": "knowledge_base",
                "node_key": root_key,
                "parent_key": None,
                "knowledge_base_id": knowledge_base_id,
                "external_id": knowledge_base_id,
                "name": str(base.get("name") or knowledge_base_id),
                "folder_path": "",
                "description": _as_text(base.get("description")),
                "document_count": _safe_int(tree.get("root_document_count")),
                "total_count": _safe_int(tree.get("total_document_count")),
                "external_created_at": _as_text(base.get("created_at")),
                "external_updated_at": _as_text(base.get("updated_at")),
                "extra_metadata": dict(base),
            },
        )

        known_folder_paths: set[str] = set()
        for folder in _folder_payloads(tree):
            path = folder["path"]
            known_folder_paths.add(path)
            parent_path = path.rpartition("/")[0]
            desired.append(
                {
                    "node_type": "folder",
                    "node_key": catalogue_node_key(
                        "folder",
                        knowledge_base_id,
                        path,
                    ),
                    "parent_key": catalogue_node_key(
                        "folder",
                        knowledge_base_id,
                        parent_path,
                    ) if parent_path else root_key,
                    "knowledge_base_id": knowledge_base_id,
                    "external_id": None,
                    "name": folder["name"],
                    "folder_path": path,
                    "document_count": folder["document_count"],
                    "total_count": folder["total_count"],
                    "extra_metadata": {},
                },
            )

        knowledge_rows: list[dict[str, Any]] = []
        total = 0
        for page in range(1, 10001):
            page_result = client.list_weknora_knowledge(
                agent_id,
                knowledge_base_id,
                page=page,
                page_size=100,
            )
            page_rows = page_result.get("knowledge", [])
            if not isinstance(page_rows, list):
                page_rows = []
            knowledge_rows.extend(
                item for item in page_rows if isinstance(item, dict)
            )
            total = max(total, _safe_int(page_result.get("total")))
            if not page_rows or (total and len(knowledge_rows) >= total):
                break

        # Some WeKnora versions omit empty/implicit folders from the tree.
        # Build those paths from file metadata so the local hierarchy is whole.
        for item in knowledge_rows:
            path = normalize_folder_path(item.get("folder_path"))
            current = ""
            for segment in path.split("/") if path else []:
                current = f"{current}/{segment}" if current else segment
                if current in known_folder_paths:
                    continue
                known_folder_paths.add(current)
                parent_path = current.rpartition("/")[0]
                desired.append(
                    {
                        "node_type": "folder",
                        "node_key": catalogue_node_key(
                            "folder", knowledge_base_id, current,
                        ),
                        "parent_key": catalogue_node_key(
                            "folder", knowledge_base_id, parent_path,
                        ) if parent_path else root_key,
                        "knowledge_base_id": knowledge_base_id,
                        "external_id": None,
                        "name": segment,
                        "folder_path": current,
                        "document_count": 0,
                        "total_count": 0,
                        "extra_metadata": {},
                    },
                )

        for item in knowledge_rows:
            external_id = str(item.get("id") or "").strip()
            if not external_id:
                continue
            path = normalize_folder_path(item.get("folder_path"))
            parent_key = (
                catalogue_node_key("folder", knowledge_base_id, path)
                if path
                else root_key
            )
            desired.append(
                {
                    "node_type": "file",
                    "node_key": catalogue_node_key(
                        "file", knowledge_base_id, external_id,
                    ),
                    "parent_key": parent_key,
                    "knowledge_base_id": knowledge_base_id,
                    "external_id": external_id,
                    "name": str(
                        item.get("title")
                        or item.get("file_name")
                        or external_id
                    ),
                    "folder_path": path,
                    "description": _as_text(item.get("description")),
                    "file_type": _as_text(item.get("file_type")),
                    "file_size": _safe_int(item.get("file_size")),
                    "source": _as_text(item.get("source")),
                    "channel": _as_text(item.get("channel")),
                    "parse_status": _as_text(item.get("parse_status")),
                    "enable_status": _as_text(item.get("enable_status")),
                    "external_created_at": _as_text(item.get("created_at")),
                    "external_updated_at": _as_text(item.get("updated_at")),
                    "processed_at": _as_text(item.get("processed_at")),
                    "extra_metadata": dict(item),
                },
            )
    return desired


_MIRRORED_FIELDS = (
    "node_type",
    "node_key",
    "knowledge_base_id",
    "external_id",
    "name",
    "folder_path",
    "description",
    "file_type",
    "file_size",
    "source",
    "channel",
    "parse_status",
    "enable_status",
    "document_count",
    "total_count",
    "external_created_at",
    "external_updated_at",
    "processed_at",
    "extra_metadata",
)


def _catalogue_diff_item(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_key": str(payload.get("node_key") or ""),
        "node_type": str(payload.get("node_type") or ""),
        "knowledge_base_id": str(payload.get("knowledge_base_id") or ""),
        "name": str(payload.get("name") or ""),
        "folder_path": normalize_folder_path(payload.get("folder_path")),
    }


def compare_document_catalogue(
    db: Session,
    project_id: int,
    agent_id: str,
    client: AgentScopeClient | None = None,
    *,
    knowledge_base_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Compare the remote source with the local mirror without writing data."""

    agent_id = agent_id.strip()
    if not agent_id:
        raise ValueError("WeKnora 机器人标识不能为空")
    desired_rows = _collect_remote_catalogue(
        client or AgentScopeClient(get_settings()),
        agent_id,
        knowledge_base_ids,
    )
    desired = {row["node_key"]: row for row in desired_rows}
    existing_rows = db.scalars(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project_id,
        ),
    ).all()
    existing = {row.node_key: row for row in existing_rows}
    existing_keys_by_id = {row.id: row.node_key for row in existing_rows}

    added_keys = sorted(set(desired) - set(existing))
    removed_keys = sorted(set(existing) - set(desired))
    changed: list[dict[str, Any]] = []
    for node_key in sorted(set(desired) & set(existing)):
        payload = desired[node_key]
        row = existing[node_key]
        changed_fields = [
            field
            for field in _MIRRORED_FIELDS
            if field in payload and getattr(row, field) != payload[field]
        ]
        expected_parent_key = payload.get("parent_key")
        actual_parent_key = existing_keys_by_id.get(row.parent_id)
        if actual_parent_key != expected_parent_key:
            changed_fields.append("parent")
        if changed_fields:
            changed.append(
                {
                    **_catalogue_diff_item(payload),
                    "changed_fields": changed_fields,
                },
            )

    added = [_catalogue_diff_item(desired[key]) for key in added_keys]
    removed = [
        _catalogue_diff_item(
            {
                "node_key": existing[key].node_key,
                "node_type": existing[key].node_type,
                "knowledge_base_id": existing[key].knowledge_base_id,
                "name": existing[key].name,
                "folder_path": existing[key].folder_path,
            },
        )
        for key in removed_keys
    ]
    return {
        "matches": not added and not removed and not changed,
        "remote_node_count": len(desired),
        "local_node_count": len(existing),
        "added_count": len(added),
        "changed_count": len(changed),
        "removed_count": len(removed),
        "added": added[:100],
        "changed": changed[:100],
        "removed": removed[:100],
        "truncated": len(added) > 100 or len(changed) > 100 or len(removed) > 100,
    }


def sync_document_catalogue(
    db: Session,
    project_id: int,
    agent_id: str,
    client: AgentScopeClient | None = None,
    *,
    knowledge_base_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Fetch once, then atomically replace one local catalogue revision."""

    agent_id = agent_id.strip()
    if not agent_id:
        raise ValueError("WeKnora 机器人标识不能为空")
    state_row = mark_catalogue_pending(db, project_id, agent_id)
    state_row.status = "syncing"
    state_row.last_started_at = datetime.now(UTC)
    state_row.last_error = None
    db.commit()

    try:
        desired = _collect_remote_catalogue(
            client or AgentScopeClient(get_settings()),
            agent_id,
            knowledge_base_ids,
        )
        state_row = get_or_create_sync_state(db, project_id, agent_id)
        revision = state_row.revision + 1
        existing = {
            row.node_key: row
            for row in db.scalars(
                select(EngineeringDocumentNode).where(
                    EngineeringDocumentNode.project_id == project_id,
                ),
            ).all()
        }
        current: dict[str, EngineeringDocumentNode] = {}
        ordered = sorted(
            desired,
            key=lambda item: (
                {"knowledge_base": 0, "folder": 1, "file": 2}.get(
                    item["node_type"], 3,
                ),
                normalize_folder_path(item.get("folder_path")).count("/"),
            ),
        )
        for payload in ordered:
            row = existing.get(payload["node_key"])
            if row is None:
                row = EngineeringDocumentNode(
                    project_id=project_id,
                    node_type=payload["node_type"],
                    node_key=payload["node_key"],
                    knowledge_base_id=payload["knowledge_base_id"],
                    name=payload["name"],
                )
                db.add(row)
            for field in _MIRRORED_FIELDS:
                if field in payload:
                    setattr(row, field, payload[field])
            parent_key = payload.get("parent_key")
            row.parent_id = current[parent_key].id if parent_key else None
            row.sync_revision = revision
            db.flush()
            current[row.node_key] = row

        stale = [row for key, row in existing.items() if key not in current]
        if stale:
            stale_ids = [row.id for row in stale]
            db.execute(
                delete(EngineeringDocumentPermission).where(
                    EngineeringDocumentPermission.node_id.in_(stale_ids),
                ),
            )
            for row in sorted(stale, key=_delete_sort_key):
                db.delete(row)
                db.flush()

        state_row.status = "ready"
        state_row.revision = revision
        state_row.weknora_agent_id = agent_id
        state_row.last_completed_at = datetime.now(UTC)
        state_row.last_error = None
        db.commit()
        return {
            **sync_state_view(
                state_row,
                knowledge_base_ids=(
                    row.knowledge_base_id
                    for row in current.values()
                    if row.node_type == "knowledge_base"
                ),
            ),
            "node_count": len(current),
            "knowledge_base_count": sum(
                row.node_type == "knowledge_base" for row in current.values()
            ),
            "folder_count": sum(
                row.node_type == "folder" for row in current.values()
            ),
            "file_count": sum(
                row.node_type == "file" for row in current.values()
            ),
        }
    except Exception as exc:
        db.rollback()
        state_row = get_or_create_sync_state(db, project_id, agent_id)
        state_row.status = "error"
        state_row.last_error = str(exc)[:4000]
        db.commit()
        raise


def sync_document_catalogue_in_background(
    project_id: int,
    agent_id: str,
    knowledge_base_ids: tuple[str, ...],
) -> None:
    """FastAPI background-task entry point with its own database session."""

    with SessionLocal() as db:
        try:
            sync_document_catalogue(
                db,
                project_id,
                agent_id,
                knowledge_base_ids=knowledge_base_ids,
            )
        except Exception:
            # sync_document_catalogue has already persisted the actionable error.
            return


def _subject_scope(
    db: Session,
    project_id: int,
    user: User,
) -> tuple[int, set[int]]:
    membership_id = db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ),
    )
    if membership_id is None:
        return user.id, set()
    position_ids = set(
        db.scalars(
            select(ProjectMemberPosition.position_id).where(
                ProjectMemberPosition.project_id == project_id,
                ProjectMemberPosition.project_member_id == membership_id,
            ),
        ).all(),
    )
    return user.id, position_ids


def _catalogue_access_is_open(
    db: Session,
    project_id: int,
    user: User,
) -> bool:
    """Return whether every project member may access the whole catalogue."""

    state_row = db.get(EngineeringDocumentSyncState, project_id)
    return (
        user.role == "admin"
        or state_row is None
        or state_row.access_mode == "project"
    )


def _all_catalogue_capabilities() -> dict[str, bool]:
    return {name: True for name in CATALOG_CAPABILITIES}


def _restricted_catalogue_access_snapshot(
    db: Session,
    project_id: int,
    user: User,
) -> tuple[list[Any], dict[int, dict[str, bool]], set[int]]:
    """Resolve restricted access without loading file descriptions or metadata."""

    rows = db.execute(
        select(
            EngineeringDocumentNode.id,
            EngineeringDocumentNode.parent_id,
            EngineeringDocumentNode.node_type,
            EngineeringDocumentNode.knowledge_base_id,
            EngineeringDocumentNode.external_id,
            EngineeringDocumentNode.folder_path,
        )
        .where(EngineeringDocumentNode.project_id == project_id)
        .order_by(EngineeringDocumentNode.id),
    ).mappings().all()
    user_id, position_ids = _subject_scope(db, project_id, user)
    subject_filters = [
        (
            EngineeringDocumentPermission.subject_type == "user"
        ) & (EngineeringDocumentPermission.subject_id == user_id),
    ]
    if position_ids:
        subject_filters.append(
            (
                EngineeringDocumentPermission.subject_type == "position"
            ) & EngineeringDocumentPermission.subject_id.in_(position_ids),
        )
    grants = db.scalars(
        select(EngineeringDocumentPermission).where(
            EngineeringDocumentPermission.project_id == project_id,
            or_(*subject_filters),
        ),
    ).all()
    grants_by_node: dict[int, list[EngineeringDocumentPermission]] = {}
    for grant in grants:
        grants_by_node.setdefault(grant.node_id, []).append(grant)

    rows_by_id = {int(row["id"]): row for row in rows}
    all_allowed = _all_catalogue_capabilities()
    capabilities: dict[int, dict[str, bool]] = {}
    for row in rows:
        node_id = int(row["id"])
        values = {name: False for name in CATALOG_CAPABILITIES}
        cursor_id: int | None = node_id
        while cursor_id is not None:
            for grant in grants_by_node.get(cursor_id, []):
                if cursor_id != node_id and not grant.inherit_to_children:
                    continue
                for name in CATALOG_CAPABILITIES:
                    values[name] = values[name] or bool(getattr(grant, name))
            cursor = rows_by_id.get(cursor_id)
            cursor_id = (
                int(cursor["parent_id"])
                if cursor is not None and cursor["parent_id"] is not None
                else None
            )
        if values["can_manage"]:
            values = dict(all_allowed)
        capabilities[node_id] = values

    visible = {
        node_id
        for node_id, values in capabilities.items()
        if any(values.values())
    }
    for node_id in list(visible):
        cursor = rows_by_id.get(node_id)
        while cursor is not None and cursor["parent_id"] is not None:
            parent_id = int(cursor["parent_id"])
            visible.add(parent_id)
            cursor = rows_by_id.get(parent_id)
    return list(rows), capabilities, visible


def require_catalogue_capability(
    db: Session,
    project_id: int,
    user: User,
    node: EngineeringDocumentNode,
    capability: str,
) -> None:
    if capability not in CATALOG_CAPABILITIES:
        raise ValueError(f"Unknown catalogue capability: {capability}")
    if _catalogue_access_is_open(db, project_id, user):
        return
    _, capabilities, _ = _restricted_catalogue_access_snapshot(
        db,
        project_id,
        user,
    )
    if not capabilities.get(node.id, {}).get(capability, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有操作该工程资料或目录的权限。",
        )


def find_catalogue_node(
    db: Session,
    project_id: int,
    *,
    knowledge_base_id: str | None = None,
    node_type: str | None = None,
    external_id: str | None = None,
    folder_path: str | None = None,
) -> EngineeringDocumentNode | None:
    query = select(EngineeringDocumentNode).where(
        EngineeringDocumentNode.project_id == project_id,
    )
    if knowledge_base_id is not None:
        query = query.where(
            EngineeringDocumentNode.knowledge_base_id == knowledge_base_id,
        )
    if node_type is not None:
        query = query.where(EngineeringDocumentNode.node_type == node_type)
    if external_id is not None:
        query = query.where(EngineeringDocumentNode.external_id == external_id)
    if folder_path is not None:
        query = query.where(
            EngineeringDocumentNode.folder_path
            == normalize_folder_path(folder_path),
        )
    return db.scalar(query)


def _node_capabilities_view(
    capabilities: dict[int, dict[str, bool]],
    node_id: int,
) -> dict[str, bool]:
    return dict(capabilities.get(node_id, {}))


def local_workspace_view(
    db: Session,
    project_id: int,
    user: User,
) -> dict[str, Any]:
    if _catalogue_access_is_open(db, project_id, user):
        bases = db.scalars(
            select(EngineeringDocumentNode)
            .where(
                EngineeringDocumentNode.project_id == project_id,
                EngineeringDocumentNode.node_type == "knowledge_base",
            )
            .order_by(EngineeringDocumentNode.id),
        ).all()
        capabilities = {
            node.id: _all_catalogue_capabilities()
            for node in bases
        }
    else:
        access_rows, capabilities, visible = (
            _restricted_catalogue_access_snapshot(
                db,
                project_id,
                user,
            )
        )
        base_ids = [
            int(row["id"])
            for row in access_rows
            if row["node_type"] == "knowledge_base"
            and int(row["id"]) in visible
        ]
        bases = list(
            db.scalars(
                select(EngineeringDocumentNode)
                .where(
                    EngineeringDocumentNode.project_id == project_id,
                    EngineeringDocumentNode.node_type == "knowledge_base",
                    EngineeringDocumentNode.id.in_(base_ids),
                )
                .order_by(EngineeringDocumentNode.id),
            ).all(),
        ) if base_ids else []
    return {
        "knowledge_bases": [
            {
                "id": node.knowledge_base_id,
                "name": node.name,
                "description": node.description or "",
                "created_at": node.external_created_at,
                "updated_at": node.external_updated_at,
                "capabilities": _node_capabilities_view(capabilities, node.id),
            }
            for node in bases
        ],
        "total": len(bases),
    }


def local_folder_tree_view(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    user: User,
) -> dict[str, Any]:
    if _catalogue_access_is_open(db, project_id, user):
        relevant = list(
            db.scalars(
                select(EngineeringDocumentNode)
                .where(
                    EngineeringDocumentNode.project_id == project_id,
                    EngineeringDocumentNode.knowledge_base_id
                    == knowledge_base_id,
                    EngineeringDocumentNode.node_type.in_(
                        ("knowledge_base", "folder"),
                    ),
                )
                .order_by(EngineeringDocumentNode.id),
            ).all(),
        )
        capabilities = {
            node.id: _all_catalogue_capabilities()
            for node in relevant
        }
        readable_file_paths = list(
            db.scalars(
                select(EngineeringDocumentNode.folder_path).where(
                    EngineeringDocumentNode.project_id == project_id,
                    EngineeringDocumentNode.knowledge_base_id
                    == knowledge_base_id,
                    EngineeringDocumentNode.node_type == "file",
                ),
            ).all(),
        )
    else:
        access_rows, capabilities, visible = (
            _restricted_catalogue_access_snapshot(db, project_id, user)
        )
        relevant_ids = [
            int(row["id"])
            for row in access_rows
            if row["knowledge_base_id"] == knowledge_base_id
            and row["node_type"] in {"knowledge_base", "folder"}
            and int(row["id"]) in visible
        ]
        relevant = list(
            db.scalars(
                select(EngineeringDocumentNode)
                .where(EngineeringDocumentNode.id.in_(relevant_ids))
                .order_by(EngineeringDocumentNode.id),
            ).all(),
        ) if relevant_ids else []
        readable_file_paths = [
            str(row["folder_path"] or "")
            for row in access_rows
            if row["knowledge_base_id"] == knowledge_base_id
            and row["node_type"] == "file"
            and capabilities.get(int(row["id"]), {}).get("can_read", False)
        ]
    root = next(
        (node for node in relevant if node.node_type == "knowledge_base"),
        None,
    )
    if root is None:
        raise HTTPException(status_code=404, detail="知识库不存在或无权访问。")
    folders = [node for node in relevant if node.node_type == "folder"]
    direct_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}
    for file_path in readable_file_paths:
        path = normalize_folder_path(file_path)
        direct_counts[path] = direct_counts.get(path, 0) + 1
        current = path
        while current:
            total_counts[current] = total_counts.get(current, 0) + 1
            current = current.rpartition("/")[0]
    by_parent: dict[int, list[EngineeringDocumentNode]] = {}
    for folder in folders:
        by_parent.setdefault(folder.parent_id or root.id, []).append(folder)

    def build(parent_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for folder in sorted(
            by_parent.get(parent_id, []),
            key=lambda item: item.name.casefold(),
        ):
            path = normalize_folder_path(folder.folder_path)
            result.append(
                {
                    "path": path,
                    "name": folder.name,
                    "document_count": direct_counts.get(path, 0),
                    "total_count": total_counts.get(path, 0),
                    "children": build(folder.id),
                    "node_id": folder.id,
                    "capabilities": _node_capabilities_view(
                        capabilities, folder.id,
                    ),
                },
            )
        return result

    return {
        "root_document_count": direct_counts.get("", 0),
        "total_document_count": len(readable_file_paths),
        "folders": build(root.id),
        "root_node_id": root.id,
        "capabilities": _node_capabilities_view(capabilities, root.id),
    }


def _file_view(
    node: EngineeringDocumentNode,
    capabilities: dict[int, dict[str, bool]],
) -> dict[str, Any]:
    metadata = dict(node.extra_metadata or {})
    return {
        **metadata,
        "id": node.external_id,
        "knowledge_base_id": node.knowledge_base_id,
        "type": metadata.get("type") or "file",
        "title": node.name,
        "description": node.description or "",
        "file_name": metadata.get("file_name") or node.name,
        "folder_path": normalize_folder_path(node.folder_path),
        "file_type": node.file_type or "",
        "file_size": node.file_size,
        "source": node.source or "",
        "channel": node.channel or "",
        "parse_status": node.parse_status or "",
        "enable_status": node.enable_status or "",
        "created_at": node.external_created_at,
        "updated_at": node.external_updated_at,
        "processed_at": node.processed_at,
        "node_id": node.id,
        "capabilities": _node_capabilities_view(capabilities, node.id),
    }


def local_knowledge_page(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    user: User,
    *,
    page: int,
    page_size: int,
    folder_path: str | None,
    folder_recursive: bool,
    keyword: str,
) -> dict[str, Any]:
    path = normalize_folder_path(folder_path)
    filters: list[Any] = [
        EngineeringDocumentNode.project_id == project_id,
        EngineeringDocumentNode.knowledge_base_id == knowledge_base_id,
        EngineeringDocumentNode.node_type == "file",
    ]
    if folder_path is not None:
        if folder_recursive and path:
            escaped_path = (
                path.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            filters.append(
                or_(
                    EngineeringDocumentNode.folder_path == path,
                    EngineeringDocumentNode.folder_path.like(
                        f"{escaped_path}/%",
                        escape="\\",
                    ),
                ),
            )
        elif not folder_recursive:
            filters.append(EngineeringDocumentNode.folder_path == path)

    query_text = keyword.strip()
    if query_text:
        escaped_query = (
            query_text.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        filters.append(
            or_(
                EngineeringDocumentNode.name.ilike(pattern, escape="\\"),
                EngineeringDocumentNode.description.ilike(
                    pattern,
                    escape="\\",
                ),
                EngineeringDocumentNode.folder_path.ilike(
                    pattern,
                    escape="\\",
                ),
            ),
        )

    if _catalogue_access_is_open(db, project_id, user):
        restricted_capabilities: dict[int, dict[str, bool]] | None = None
    else:
        access_rows, restricted_capabilities, _ = (
            _restricted_catalogue_access_snapshot(db, project_id, user)
        )
        readable_ids = [
            int(row["id"])
            for row in access_rows
            if row["knowledge_base_id"] == knowledge_base_id
            and row["node_type"] == "file"
            and restricted_capabilities.get(int(row["id"]), {}).get(
                "can_read",
                False,
            )
        ]
        if not readable_ids:
            return {
                "knowledge": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
            }
        filters.append(EngineeringDocumentNode.id.in_(readable_ids))

    total = int(
        db.scalar(
            select(func.count(EngineeringDocumentNode.id)).where(*filters),
        ) or 0,
    )
    rows = list(
        db.scalars(
            select(EngineeringDocumentNode)
            .where(*filters)
            .order_by(
                EngineeringDocumentNode.external_created_at.desc(),
                EngineeringDocumentNode.name.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size),
        ).all(),
    )
    capabilities = (
        restricted_capabilities
        if restricted_capabilities is not None
        else {
            node.id: _all_catalogue_capabilities()
            for node in rows
        }
    )
    return {
        "knowledge": [
            _file_view(node, capabilities)
            for node in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def local_file_view(
    db: Session,
    project_id: int,
    knowledge_id: str,
    user: User,
    capability: str = "can_read",
) -> tuple[EngineeringDocumentNode, dict[str, Any]]:
    node = find_catalogue_node(
        db,
        project_id,
        node_type="file",
        external_id=knowledge_id,
    )
    if node is None:
        raise HTTPException(status_code=404, detail="工程资料不存在。")
    if _catalogue_access_is_open(db, project_id, user):
        capabilities = {node.id: _all_catalogue_capabilities()}
    else:
        _, capabilities, _ = _restricted_catalogue_access_snapshot(
            db,
            project_id,
            user,
        )
    if not capabilities.get(node.id, {}).get(capability, False):
        raise HTTPException(status_code=403, detail="你没有访问该工程资料的权限。")
    return node, _file_view(node, capabilities)


def readable_external_ids(
    db: Session,
    project_id: int,
    user: User,
    knowledge_base_ids: Iterable[str] | None = None,
) -> set[str]:
    allowed_bases = set(knowledge_base_ids or [])
    if _catalogue_access_is_open(db, project_id, user):
        query = select(EngineeringDocumentNode.external_id).where(
            EngineeringDocumentNode.project_id == project_id,
            EngineeringDocumentNode.node_type == "file",
            EngineeringDocumentNode.external_id.is_not(None),
        )
        if allowed_bases:
            query = query.where(
                EngineeringDocumentNode.knowledge_base_id.in_(allowed_bases),
            )
        return {
            str(value)
            for value in db.scalars(query).all()
            if value
        }

    access_rows, capabilities, _ = _restricted_catalogue_access_snapshot(
        db,
        project_id,
        user,
    )
    return {
        str(row["external_id"])
        for row in access_rows
        if row["node_type"] == "file"
        and row["external_id"]
        and (
            not allowed_bases
            or row["knowledge_base_id"] in allowed_bases
        )
        and capabilities.get(int(row["id"]), {}).get("can_read", False)
    }


def authorized_qa_payload(
    db: Session,
    project_id: int,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Constrain restricted QA to explicit locally authorized document IDs."""

    state_row = db.get(EngineeringDocumentSyncState, project_id)
    if user.role == "admin" or state_row is None or state_row.access_mode == "project":
        return payload
    requested_ids = {
        str(value).strip()
        for value in payload.get("knowledge_ids", [])
        if str(value).strip()
    }
    requested_bases = {
        str(value).strip()
        for value in payload.get("knowledge_base_ids", [])
        if str(value).strip()
    }
    readable = readable_external_ids(
        db,
        project_id,
        user,
        requested_bases or None,
    )
    if requested_ids:
        denied = requested_ids - readable_external_ids(db, project_id, user)
        if denied:
            raise HTTPException(status_code=403, detail="问答范围包含无权访问的工程资料。")
        readable &= requested_ids
    if not readable:
        raise HTTPException(status_code=403, detail="当前问答范围内没有可访问的工程资料。")
    readable_bases = {
        str(value)
        for value in db.scalars(
            select(EngineeringDocumentNode.knowledge_base_id).where(
                EngineeringDocumentNode.project_id == project_id,
                EngineeringDocumentNode.node_type == "file",
                EngineeringDocumentNode.external_id.in_(readable),
            ),
        ).all()
        if value
    }
    if not readable_bases:
        raise HTTPException(status_code=409, detail="授权资料缺少对应的知识库信息。")
    return {
        **payload,
        "knowledge_base_ids": sorted(readable_bases),
        "knowledge_ids": sorted(readable),
    }


def _catalogue_root(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
) -> EngineeringDocumentNode:
    root = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=knowledge_base_id,
        node_type="knowledge_base",
    )
    if root is None:
        raise HTTPException(status_code=409, detail="本地工程资料目录尚未完成同步。")
    return root


def _catalogue_parent(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    folder_path: str,
) -> EngineeringDocumentNode:
    path = normalize_folder_path(folder_path)
    if not path:
        return _catalogue_root(db, project_id, knowledge_base_id)
    parent = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=knowledge_base_id,
        node_type="folder",
        folder_path=path,
    )
    if parent is None:
        raise HTTPException(status_code=409, detail="目标目录尚未同步到平台。")
    return parent


def add_local_folder(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    folder_path: str,
) -> EngineeringDocumentNode:
    path = normalize_folder_path(folder_path)
    parent_path, _, name = path.rpartition("/")
    parent = _catalogue_parent(db, project_id, knowledge_base_id, parent_path)
    key = catalogue_node_key("folder", knowledge_base_id, path)
    row = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project_id,
            EngineeringDocumentNode.node_key == key,
        ),
    )
    if row is None:
        state_row = get_or_create_sync_state(db, project_id)
        row = EngineeringDocumentNode(
            project_id=project_id,
            parent_id=parent.id,
            node_type="folder",
            node_key=key,
            knowledge_base_id=knowledge_base_id,
            name=name,
            folder_path=path,
            sync_revision=state_row.revision,
        )
        db.add(row)
        db.flush()
    return row


def update_local_folder_path(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    source_path: str,
    target_path: str,
) -> EngineeringDocumentNode:
    source = normalize_folder_path(source_path)
    target = normalize_folder_path(target_path)
    row = find_catalogue_node(
        db,
        project_id,
        knowledge_base_id=knowledge_base_id,
        node_type="folder",
        folder_path=source,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="本地目录记录不存在，请先重新同步。")
    target_parent_path, _, target_name = target.rpartition("/")
    target_parent = _catalogue_parent(
        db, project_id, knowledge_base_id, target_parent_path,
    )
    affected = db.scalars(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project_id,
            EngineeringDocumentNode.knowledge_base_id == knowledge_base_id,
            EngineeringDocumentNode.node_type.in_(("folder", "file")),
        ),
    ).all()
    for node in affected:
        old_path = normalize_folder_path(node.folder_path)
        if old_path != source and not old_path.startswith(f"{source}/"):
            continue
        suffix = old_path[len(source):].lstrip("/")
        new_path = f"{target}/{suffix}" if suffix else target
        node.folder_path = new_path
        if node.node_type == "folder":
            node.node_key = catalogue_node_key(
                "folder", knowledge_base_id, new_path,
            )
            if node.id == row.id:
                node.name = target_name
                node.parent_id = target_parent.id
    db.flush()
    return row


def delete_local_folder_subtree(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    folder_path: str,
) -> None:
    path = normalize_folder_path(folder_path)
    rows = [
        row for row in db.scalars(
            select(EngineeringDocumentNode).where(
                EngineeringDocumentNode.project_id == project_id,
                EngineeringDocumentNode.knowledge_base_id == knowledge_base_id,
                EngineeringDocumentNode.node_type.in_(("folder", "file")),
            ),
        ).all()
        if normalize_folder_path(row.folder_path) == path
        or normalize_folder_path(row.folder_path).startswith(f"{path}/")
    ]
    if rows:
        db.execute(
            delete(EngineeringDocumentPermission).where(
                EngineeringDocumentPermission.node_id.in_([row.id for row in rows]),
            ),
        )
    for row in sorted(rows, key=_delete_sort_key):
        db.delete(row)
        db.flush()


def move_local_files(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    knowledge_ids: Iterable[str],
    folder_path: str,
) -> None:
    target = _catalogue_parent(
        db, project_id, knowledge_base_id, folder_path,
    )
    ids = set(knowledge_ids)
    rows = db.scalars(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project_id,
            EngineeringDocumentNode.knowledge_base_id == knowledge_base_id,
            EngineeringDocumentNode.node_type == "file",
            EngineeringDocumentNode.external_id.in_(ids),
        ),
    ).all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=409, detail="部分资料尚未同步到平台。")
    for row in rows:
        row.folder_path = normalize_folder_path(folder_path)
        row.parent_id = target.id


def add_pending_local_file(
    db: Session,
    project_id: int,
    knowledge_base_id: str,
    folder_path: str,
    result: dict[str, Any],
    *,
    fallback_name: str,
    file_size: int = 0,
    file_type: str | None = None,
) -> EngineeringDocumentNode:
    external_id = str(
        result.get("knowledge_id") or result.get("id") or "",
    ).strip()
    if not external_id:
        raise HTTPException(status_code=502, detail="WeKnora 未返回新资料标识。")
    parent = _catalogue_parent(
        db, project_id, knowledge_base_id, folder_path,
    )
    key = catalogue_node_key("file", knowledge_base_id, external_id)
    row = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project_id,
            EngineeringDocumentNode.node_key == key,
        ),
    )
    if row is None:
        state_row = get_or_create_sync_state(db, project_id)
        row = EngineeringDocumentNode(
            project_id=project_id,
            parent_id=parent.id,
            node_type="file",
            node_key=key,
            knowledge_base_id=knowledge_base_id,
            external_id=external_id,
            name=str(result.get("title") or result.get("file_name") or fallback_name),
            folder_path=normalize_folder_path(folder_path),
            file_type=file_type,
            file_size=file_size,
            parse_status=_as_text(result.get("parse_status")) or "pending",
            source="platform",
            extra_metadata={
                "id": external_id,
                "file_name": str(result.get("file_name") or fallback_name),
            },
            sync_revision=state_row.revision,
        )
        db.add(row)
        db.flush()
    return row


def delete_local_file(
    db: Session,
    project_id: int,
    knowledge_id: str,
) -> None:
    row = find_catalogue_node(
        db, project_id, node_type="file", external_id=knowledge_id,
    )
    if row is not None:
        db.execute(
            delete(EngineeringDocumentPermission).where(
                EngineeringDocumentPermission.node_id == row.id,
            ),
        )
        db.delete(row)


def filter_search_result(
    db: Session,
    project_id: int,
    user: User,
    result: dict[str, Any],
) -> dict[str, Any]:
    readable = readable_external_ids(db, project_id, user)
    references = result.get("references")
    if not isinstance(references, list):
        return result
    filtered = [
        reference for reference in references
        if isinstance(reference, dict)
        and str(reference.get("knowledge_id") or "") in readable
    ]
    return {**result, "references": filtered, "total": len(filtered)}


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
