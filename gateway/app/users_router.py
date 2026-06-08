"""用户与角色管理（仅管理员可用）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from . import models, schemas, auth

router = APIRouter(prefix="/users", tags=["users"])


def _valid_role_codes(db: Session) -> set[str]:
    """从角色表读取所有合法角色标识。"""
    return {r.code for r in db.query(models.Role).all()}


@router.get("", response_model=list[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    """列出全部用户。"""
    return db.query(models.User).order_by(models.User.id).all()


@router.post("", response_model=schemas.UserOut)
def create_user(
    payload: schemas.UserAdminCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    """新建用户。"""
    if payload.role not in _valid_role_codes(db):
        raise HTTPException(status_code=400, detail="角色不存在，请先在角色管理中创建该角色")
    exists = db.query(models.User).filter(models.User.username == payload.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = models.User(
        username=payload.username,
        password_hash=auth.hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserAdminUpdate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.require_admin),
):
    """更新用户的显示名 / 角色 / 密码。"""
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.role is not None:
        if payload.role not in _valid_role_codes(db):
            raise HTTPException(status_code=400, detail="角色不存在，请先在角色管理中创建该角色")
        # 不允许把自己从 admin 降级，避免误操作锁死后台
        if user.id == current.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="不能撤销自己的管理员权限")
        user.role = payload.role
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.password:
        user.password_hash = auth.hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.require_admin),
):
    """删除用户（不能删自己）。"""
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账户")
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.query(models.ProjectMember).filter(models.ProjectMember.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"ok": True, "deleted": user_id}
