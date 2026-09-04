"""Fixed project-position catalogue and platform account role policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProjectMember, ProjectMemberPosition, ProjectPosition, User


PROJECT_MANAGER_POSITION_NAME = "项目经理"
DEFAULT_ENGINEERING_KNOWLEDGE_BASE_NAME = "B_工程知识库"
INITIAL_MANAGEMENT_USERNAME = "admin"


@dataclass(frozen=True, slots=True)
class ProjectPositionDefinition:
    name: str
    code: str
    category: str


PROJECT_POSITION_DEFINITIONS: tuple[ProjectPositionDefinition, ...] = (
    ProjectPositionDefinition("项目经理", "role_pm", "决策与总体管理"),
    ProjectPositionDefinition("项目常务副经理", "role_deputy_pm", "决策与总体管理"),
    ProjectPositionDefinition("项目商务副经理", "role_biz", "决策与总体管理"),
    ProjectPositionDefinition("项目总工", "role_chief_eng", "技术与方案"),
    ProjectPositionDefinition("项目技术员", "role_tech", "技术与方案"),
    ProjectPositionDefinition("安全员", "role_safety", "安全"),
    ProjectPositionDefinition("质量员", "role_qa", "质量与试验"),
    ProjectPositionDefinition("施工员", "role_site", "现场施工组织"),
    ProjectPositionDefinition("劳务员", "role_labor", "专业职能支持"),
    ProjectPositionDefinition("材料员", "role_material", "专业职能支持"),
    ProjectPositionDefinition("机械员", "role_mech", "专业职能支持"),
    ProjectPositionDefinition("测量员", "role_survey", "专业职能支持"),
    ProjectPositionDefinition("资料员", "role_doc", "专业职能支持"),
    ProjectPositionDefinition("标准员", "role_std", "专业职能支持"),
    ProjectPositionDefinition("取样员", "role_sample", "质量与试验"),
)
PROJECT_POSITION_NAMES = tuple(item.name for item in PROJECT_POSITION_DEFINITIONS)
PROJECT_POSITION_NAME_SET = frozenset(PROJECT_POSITION_NAMES)
PROJECT_POSITION_BY_NAME = {
    item.name: item for item in PROJECT_POSITION_DEFINITIONS
}


class UnsupportedProjectPositionError(ValueError):
    """Raised when imported or manually entered personnel use another title."""


def normalize_project_position_name(value: str) -> str:
    return str(value or "").strip()


def require_supported_project_position(value: str) -> str:
    """Return the canonical fixed position name or raise a readable error."""

    position_name = normalize_project_position_name(value)
    if position_name not in PROJECT_POSITION_NAME_SET:
        allowed = "、".join(PROJECT_POSITION_NAMES)
        shown = position_name or "空白岗位"
        raise UnsupportedProjectPositionError(
            f"岗位「{shown}」不在固定岗位范围内。可选岗位：{allowed}",
        )
    return position_name


def project_position_definition(value: str) -> ProjectPositionDefinition | None:
    return PROJECT_POSITION_BY_NAME.get(normalize_project_position_name(value))


def reconcile_user_management_role(db: Session, user: User) -> str:
    """Derive the global account role from the fixed personnel policy.

    The built-in ``admin`` account always remains a management account. Any
    person holding the 项目经理 position in at least one project is also a
    management account; every other imported project account is ordinary.
    """

    is_initial_admin = user.username.strip().casefold() == (
        INITIAL_MANAGEMENT_USERNAME.casefold()
    )
    is_project_manager = db.scalar(
        select(ProjectMemberPosition.id)
        .join(
            ProjectMember,
            ProjectMember.id == ProjectMemberPosition.project_member_id,
        )
        .join(
            ProjectPosition,
            ProjectPosition.id == ProjectMemberPosition.position_id,
        )
        .where(
            ProjectMember.user_id == user.id,
            ProjectPosition.position_name == PROJECT_MANAGER_POSITION_NAME,
        )
        .limit(1),
    ) is not None
    user.role = "admin" if is_initial_admin or is_project_manager else "user"
    return user.role


def reconcile_user_management_roles(
    db: Session,
    user_ids: Iterable[int],
) -> dict[int, str]:
    """Recalculate account roles after project personnel assignments change."""

    result: dict[int, str] = {}
    for user_id in dict.fromkeys(int(item) for item in user_ids):
        user = db.get(User, user_id)
        if user is not None:
            result[user.id] = reconcile_user_management_role(db, user)
    return result
