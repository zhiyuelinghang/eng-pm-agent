from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import ChatChannel, Project


def default_group_title(db: Session, project: Project) -> str:
    base = f"{project.name}项目群"
    title, suffix = base, 1
    while db.scalar(select(ChatChannel.id).where(ChatChannel.project_id == project.id,
            ChatChannel.archived_at.is_(None), func.lower(func.trim(ChatChannel.title)) == title.lower())) is not None:
        title = f"{base}（全体{suffix if suffix > 1 else ''}）"
        suffix += 1
    return title
