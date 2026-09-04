from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    OperationLog,
    Project,
    ProjectConnectorConfig,
    ProjectMember,
    User,
    UserConnectorConfig,
)
from .security import decode_access_token
from .wecom_notification_gateway import (
    is_wecom_webhook_url,
    project_wecom_configured,
)


bearer = HTTPBearer(auto_error=False)
ModelType = TypeVar("ModelType")


def ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def serialize(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:
        if column.name == "password_hash":
            continue
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def project_for_user_or_403(
    db: Session,
    project_id: int,
    user: User,
) -> Project:
    """Resolve a project while enforcing current platform membership."""
    project = project_or_404(db, project_id)
    if user.role == "admin":
        return project
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ),
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你不是该项目的有效成员",
        )
    return project


def entity_or_404(db: Session, model: type[ModelType], item_id: int, message: str) -> ModelType:
    entity = db.get(model, item_id)
    if not entity:
        raise HTTPException(status_code=404, detail=message)
    return entity


def audit(db: Session, user: User, action: str, detail: str, project_id: int | None = None, target_type: str | None = None, target_id: int | None = None) -> None:
    db.add(OperationLog(project_id=project_id, operator_id=user.id, action=action, detail=detail, target_type=target_type, target_id=target_id))


def user_connector_view(row: UserConnectorConfig) -> dict[str, Any]:
    """Expose connector metadata without ever returning its credential."""

    return {
        "id": row.id,
        "connector_type": row.connector_type,
        "account_identifier": row.account_identifier,
        "platform_type": row.platform_type,
        "configured": row.configured,
        "has_secret": bool(row.secret_encrypted),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def project_connector_view(row: ProjectConnectorConfig) -> dict[str, Any]:
    """Expose project connector metadata without returning its credential."""

    legacy_wecom_webhook = (
        row.connector_type == "wecom"
        and is_wecom_webhook_url(row.connection_id)
    )
    return {
        "id": row.id,
        "project_id": row.project_id,
        "connector_type": row.connector_type,
        "connection_id": (
            "项目群机器人" if legacy_wecom_webhook else row.connection_id
        ),
        "configured": (
            project_wecom_configured(row)
            if row.connector_type == "wecom"
            else row.configured
        ),
        "has_secret": bool(row.secret_encrypted or legacy_wecom_webhook),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
