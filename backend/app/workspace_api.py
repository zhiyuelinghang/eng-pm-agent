from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_common import audit, get_current_user, ok, project_for_user_or_403, require_admin, serialize
from .connector_secrets import encrypt_connector_secret
from .db import get_db
from .models import User, UserConnectorConfig
from .workspace_models import ProjectAnnouncement, ProjectPlatform, UserPlatformAccount
from .project_status_details import project_status_tasks
from .task_engine_gateway import get_engine, to_api_task

router = APIRouter(prefix="/api", tags=["workspace"])


@router.get("/projects/{project_id}/my-task-counts")
def my_task_counts(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    rows = [to_api_task(task) for task in project_status_tasks(get_engine(), project_id)]
    mine = [row for row in rows if row["status"] not in {"completed", "cancelled"} and (
        str(row["assignee_user_id"]) == str(user.id) or (row["status"] == "pending_confirm" and str(row["confirmer_user_id"]) == str(user.id)))]
    return ok({"tasks": len(mine), "home_todo": sum(row["status"] != "processing" for row in mine)})


class PlatformInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform_type: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=4000)

    @field_validator("name", "platform_type", "url", mode="before")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return value.strip()

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("请填写不含账号密码的 HTTP 或 HTTPS 平台地址")
        return value


class PlatformAccountInput(BaseModel):
    account_identifier: str = Field(min_length=1, max_length=500)
    secret: str | None = Field(default=None, max_length=4000)
    use_legacy_account: bool = False

    @field_validator("account_identifier", mode="before")
    @classmethod
    def strip_account(cls, value: str) -> str:
        return value.strip()


class AnnouncementInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


def platform_for_user(db: Session, project_id: int, platform_id: int, user: User) -> ProjectPlatform:
    project_for_user_or_403(db, project_id, user)
    row = db.get(ProjectPlatform, platform_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "工程平台不存在")
    return row


@router.get("/projects/{project_id}/platforms")
def list_platforms(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    return ok([serialize(row) for row in db.scalars(select(ProjectPlatform).where(ProjectPlatform.project_id == project_id).order_by(ProjectPlatform.id)).all()])


@router.post("/projects/{project_id}/platforms", status_code=201)
def create_platform(project_id: int, payload: PlatformInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    require_admin(user)
    project_for_user_or_403(db, project_id, user)
    row = ProjectPlatform(project_id=project_id, **payload.model_dump())
    db.add(row)
    return save_platform_row(db, user, row)


@router.put("/projects/{project_id}/platforms/{platform_id}")
def update_platform(project_id: int, platform_id: int, payload: PlatformInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    require_admin(user)
    row = platform_for_user(db, project_id, platform_id, user)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    return save_platform_row(db, user, row)


def save_platform_row(db: Session, user: User, row: ProjectPlatform) -> dict[str, Any]:
    try:
        db.flush()
        audit(db, user, "保存工程平台", f"保存平台「{row.name}」", row.project_id, "project_platform", row.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "当前工程已存在同名平台") from exc
    db.refresh(row)
    return ok(serialize(row), "工程平台已保存")


def account_view(row: UserPlatformAccount) -> dict[str, Any]:
    return {"platform_id": row.platform_id, "account_identifier": row.account_identifier,
            "has_secret": bool(row.secret_encrypted), "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get("/projects/{project_id}/my-platform-accounts")
def list_platform_accounts(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    rows = db.scalars(select(UserPlatformAccount).join(ProjectPlatform).where(ProjectPlatform.project_id == project_id, UserPlatformAccount.user_id == user.id)).all()
    return ok([account_view(row) for row in rows])


@router.put("/projects/{project_id}/my-platform-accounts/{platform_id}")
def save_platform_account(project_id: int, platform_id: int, payload: PlatformAccountInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    platform_for_user(db, project_id, platform_id, user)
    row = db.scalar(select(UserPlatformAccount).where(UserPlatformAccount.user_id == user.id, UserPlatformAccount.platform_id == platform_id))
    if row is None:
        row = UserPlatformAccount(user_id=user.id, platform_id=platform_id, account_identifier=payload.account_identifier)
        db.add(row)
    row.account_identifier = payload.account_identifier
    if payload.use_legacy_account:
        legacy = db.scalar(select(UserConnectorConfig).where(UserConnectorConfig.user_id == user.id, UserConnectorConfig.connector_type == "platform"))
        if legacy is None:
            raise HTTPException(409, "历史平台账号已不存在，请重新填写")
        row.secret_encrypted = legacy.secret_encrypted
    if payload.secret:
        row.secret_encrypted = encrypt_connector_secret(payload.secret)
    db.flush()
    audit(db, user, "保存个人平台账号", "更新本人平台账号与凭据", project_id, "user_platform_account", row.id)
    db.commit()
    db.refresh(row)
    return ok(account_view(row), "个人平台账号已保存")


@router.delete("/projects/{project_id}/my-platform-accounts/{platform_id}")
def delete_platform_account(project_id: int, platform_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    platform_for_user(db, project_id, platform_id, user)
    row = db.scalar(select(UserPlatformAccount).where(UserPlatformAccount.user_id == user.id, UserPlatformAccount.platform_id == platform_id))
    if row:
        db.delete(row)
        audit(db, user, "清除个人平台账号", "清除本人平台账号与凭据", project_id)
        db.commit()
    return ok(None, "个人平台账号已清除")


@router.get("/projects/{project_id}/announcements")
def list_announcements(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    rows = db.execute(select(ProjectAnnouncement, User.real_name).join(User, User.id == ProjectAnnouncement.author_user_id).where(ProjectAnnouncement.project_id == project_id, ProjectAnnouncement.published.is_(True)).order_by(ProjectAnnouncement.created_at.desc(), ProjectAnnouncement.id.desc())).all()
    return ok([{**serialize(row), "author_name": name} for row, name in rows])


@router.post("/projects/{project_id}/announcements", status_code=201)
def publish_announcement(project_id: int, payload: AnnouncementInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    require_admin(user)
    project_for_user_or_403(db, project_id, user)
    row = ProjectAnnouncement(project_id=project_id, author_user_id=user.id, **payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, user, "发布项目公告", row.title, project_id, "project_announcement", row.id)
    db.commit()
    db.refresh(row)
    return ok({**serialize(row), "author_name": user.real_name}, "公告已发布")


@router.delete("/projects/{project_id}/announcements/{announcement_id}")
def withdraw_announcement(project_id: int, announcement_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    require_admin(user)
    project_for_user_or_403(db, project_id, user)
    row = db.get(ProjectAnnouncement, announcement_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "公告不存在")
    row.published = False
    audit(db, user, "撤回项目公告", row.title, project_id, "project_announcement", row.id)
    db.commit()
    return ok(None, "公告已撤回")
