from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from . import models, schemas
from .auth import get_current_user, visible_project_ids

router = APIRouter()


def _require_project_access(db: Session, user: models.User, project_id: int):
    """校验当前用户能否访问该项目，不能则 403/404。"""
    project = db.get(models.Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if user.role != "admin" and project_id not in visible_project_ids(db, user):
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return project


# ---- B5 项目接口 ----
@router.post("/projects", response_model=schemas.ProjectOut, tags=["projects"])
def create_project(
    payload: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    project = models.Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    # 创建者自动成为项目成员（owner）
    db.add(
        models.ProjectMember(
            project_id=project.id, user_id=current.id, role="owner"
        )
    )
    db.commit()
    return project


@router.get("/projects", response_model=list[schemas.ProjectOut], tags=["projects"])
def list_projects(
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    ids = visible_project_ids(db, current)
    return (
        db.query(models.Project)
        .filter(models.Project.id.in_(ids))
        .order_by(models.Project.id)
        .all()
    )


# ---- B6 信息写入接口（C 写摘要进来）----
@router.post("/messages", response_model=schemas.MessageOut, tags=["messages"])
def create_message(
    payload: schemas.MessageCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    _require_project_access(db, current, payload.project_id)

    message = models.Message(
        project_id=payload.project_id,
        source=payload.source,
        source_ref=payload.source_ref,
        raw_text=payload.raw_text,
        summary=payload.summary,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


@router.get(
    "/projects/{project_id}/messages",
    response_model=list[schemas.MessageOut],
    tags=["messages"],
)
def list_messages(
    project_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    _require_project_access(db, current, project_id)
    return (
        db.query(models.Message)
        .filter(models.Message.project_id == project_id)
        .order_by(models.Message.created_at.desc())
        .all()
    )


# ---- B8 技能调用日志（最小版，复用 tool_call_logs 表）----
@router.post("/skill-logs", response_model=schemas.SkillLogOut, tags=["skill-logs"])
def create_skill_log(
    payload: schemas.SkillLogCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    if payload.project_id is not None:
        _require_project_access(db, current, payload.project_id)

    log = models.ToolCallLog(
        project_id=payload.project_id,
        tool_name=payload.tool_name,
        input_args=payload.input_args,
        output_result=payload.output_result,
        status=payload.status,
        error_message=payload.error_message,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get(
    "/skill-logs",
    response_model=list[schemas.SkillLogOut],
    tags=["skill-logs"],
)
def list_skill_logs(
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    return (
        db.query(models.ToolCallLog)
        .order_by(models.ToolCallLog.created_at.desc())
        .limit(100)
        .all()
    )
