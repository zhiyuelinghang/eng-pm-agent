from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import api as _legacy


router = _legacy.router
get_db = _legacy.get_db
get_current_user = _legacy.get_current_user
ok = _legacy.ok
audit = _legacy.audit
serialize = _legacy.serialize
entity_or_404 = _legacy.entity_or_404
user_connector_view = _legacy.user_connector_view
encrypt_connector_secret = _legacy.encrypt_connector_secret
create_access_token = _legacy.create_access_token
hash_password = _legacy.hash_password
verify_password = _legacy.verify_password
reconcile_user_management_role = _legacy.reconcile_user_management_role

from .models import User, UserConnectorConfig
from .schemas import LoginRequest, PasswordChangeInput, ProfileUpdate, UserConnectorConfigInput, UserConnectorType

@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    previous_role = user.role
    reconcile_user_management_role(db, user)
    if user.role != previous_role:
        db.commit()
        db.refresh(user)
    return ok({"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": serialize(user)})


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(serialize(user))


@router.patch("/me")
def update_me(payload: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    user.real_name = payload.real_name.strip()
    user.phone = payload.phone.strip() if payload.phone and payload.phone.strip() else None
    user.email = payload.email.strip() if payload.email and payload.email.strip() else None
    user.title = payload.title.strip() if payload.title and payload.title.strip() else None
    user.org_name = payload.org_name.strip() if payload.org_name and payload.org_name.strip() else None
    audit(db, user, "更新个人资料", "更新姓名、岗位或联系方式", target_type="user", target_id=user.id)
    db.commit()
    db.refresh(user)
    return ok(serialize(user), "个人资料已保存")


@router.post("/me/password")
def change_my_password(payload: PasswordChangeInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    audit(db, user, "修改登录密码", "当前用户修改登录密码", target_type="user", target_id=user.id)
    db.commit()
    return ok(None, "登录密码已更新")


@router.get("/me/connectors")
def list_my_connectors(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = db.scalars(
        select(UserConnectorConfig)
        .where(UserConnectorConfig.user_id == user.id)
        .order_by(UserConnectorConfig.id),
    ).all()
    return ok([user_connector_view(row) for row in rows])


@router.put("/me/connectors/{connector_type}")
def save_my_connector(
    connector_type: UserConnectorType,
    payload: UserConnectorConfigInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not payload.account_identifier.strip():
        raise HTTPException(422, "账号不能为空")
    row = db.scalar(
        select(UserConnectorConfig).where(
            UserConnectorConfig.user_id == user.id,
            UserConnectorConfig.connector_type == connector_type,
        ),
    )
    sending_enabled = payload.sending_enabled
    if connector_type == "mail":
        if sending_enabled is None:
            sending_enabled = bool(payload.secret or (row and row.sending_enabled))
        if sending_enabled and not ((payload.secret and payload.secret.strip()) or (row and row.secret_encrypted)):
            raise HTTPException(422, "开启邮件发送时请填写密码或授权码")
    if row is None:
        row = UserConnectorConfig(
            user_id=user.id,
            connector_type=connector_type,
            account_identifier=payload.account_identifier.strip(),
        )
        db.add(row)
    row.account_identifier = payload.account_identifier.strip()
    row.platform_type = (
        payload.platform_type.strip()
        if payload.platform_type and payload.platform_type.strip()
        else None
    )
    if payload.secret and payload.secret.strip():
        row.secret_encrypted = encrypt_connector_secret(payload.secret)
    if connector_type == "mail":
        row.sending_enabled = bool(sending_enabled)
        if not row.sending_enabled:
            row.secret_encrypted = None
    row.configured = True
    db.flush()
    audit(
        db,
        user,
        "保存个人连接配置",
        f"保存个人{connector_type}连接配置",
        target_type="user_connector_config",
        target_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return ok(user_connector_view(row), "个人连接配置已保存")


@router.delete("/me/connectors/{connector_type}")
def delete_my_connector(
    connector_type: UserConnectorType,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.scalar(
        select(UserConnectorConfig).where(
            UserConnectorConfig.user_id == user.id,
            UserConnectorConfig.connector_type == connector_type,
        ),
    )
    if row is None:
        return ok(None, "个人连接配置已清除")
    row_id = row.id
    db.delete(row)
    audit(
        db,
        user,
        "清除个人连接配置",
        f"清除个人{connector_type}连接配置",
        target_type="user_connector_config",
        target_id=row_id,
    )
    db.commit()
    return ok(None, "个人连接配置已清除")
