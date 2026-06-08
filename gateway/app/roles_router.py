"""角色管理（仅管理员可用）。code=英文标识，name=中文名称。"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from . import models, schemas, auth

router = APIRouter(prefix="/roles", tags=["roles"])

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


@router.get("", response_model=list[schemas.RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    """列出全部角色。"""
    return db.query(models.Role).order_by(models.Role.id).all()


@router.post("", response_model=schemas.RoleOut)
def create_role(
    payload: schemas.RoleCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    """新建自定义角色。标识必须为英文（小写字母开头，仅含小写字母/数字/下划线）。"""
    code = payload.code.strip()
    if not CODE_PATTERN.match(code):
        raise HTTPException(status_code=400, detail="角色标识非法：须以小写字母开头，仅含小写字母、数字、下划线")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="角色名称不能为空")
    exists = db.query(models.Role).filter(models.Role.code == code).first()
    if exists:
        raise HTTPException(status_code=400, detail="角色标识已存在")
    role = models.Role(
        code=code,
        name=payload.name.strip(),
        description=payload.description,
        builtin=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.patch("/{role_id}", response_model=schemas.RoleOut)
def update_role(
    role_id: int,
    payload: schemas.RoleUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    """更新角色的中文名称 / 描述（标识 code 不可改）。"""
    role = db.get(models.Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="角色名称不能为空")
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description
    db.commit()
    db.refresh(role)
    return role


@router.delete("/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    """删除自定义角色（内置角色与仍被用户使用的角色不可删）。"""
    role = db.get(models.Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.builtin:
        raise HTTPException(status_code=400, detail="内置角色不可删除")
    in_use = db.query(models.User).filter(models.User.role == role.code).count()
    if in_use:
        raise HTTPException(status_code=400, detail=f"该角色下仍有 {in_use} 个用户，请先调整这些用户的角色")
    db.delete(role)
    db.commit()
    return {"ok": True, "deleted": role_id}
