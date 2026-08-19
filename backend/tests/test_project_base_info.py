from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api import create_project, update_project
from backend.app.db import Base
from backend.app.models import Project, User
from backend.app.schemas import ProjectInput


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def project_admin(db: Session) -> tuple[Project, User]:
    user = User(
        username="project-admin",
        password_hash="test",
        role="admin",
        real_name="项目管理员",
        identity_card_no="project-base-info-admin",
    )
    project = Project(name="原项目名称")
    db.add_all([user, project])
    db.commit()
    return project, user


def test_project_can_still_be_created_with_name_only(db: Session) -> None:
    user = User(
        username="project-create-admin",
        password_hash="test",
        role="admin",
        real_name="项目管理员",
        identity_card_no="project-create-admin",
    )
    db.add(user)
    db.commit()

    result = create_project(ProjectInput(name="仅名称项目"), db, user)

    assert result["data"]["name"] == "仅名称项目"
    project = db.get(Project, result["data"]["id"])
    assert project is not None
    assert project.engineering_type_description is None


def test_project_base_info_can_be_updated(db: Session) -> None:
    project, user = project_admin(db)

    result = update_project(
        project.id,
        ProjectInput(
            name="更新后的项目",
            engineering_type_description="社区卫生服务中心异地扩建工程",
            contract_start_date=date(2026, 1, 1),
            contract_end_date=date(2026, 12, 31),
            contract_duration_days=365,
            contract_amount_wan_yuan=Decimal("12345.67"),
            construction_unit_name="建设单位",
            general_contractor_unit_name="总承包单位",
            supervision_unit_name="监理单位",
            design_unit_name="设计单位",
            survey_unit_name="勘察单位",
        ),
        db,
        user,
    )

    assert result["data"]["name"] == "更新后的项目"
    db.refresh(project)
    assert project.engineering_type_description == "社区卫生服务中心异地扩建工程"
    assert project.contract_start_date == date(2026, 1, 1)
    assert project.contract_end_date == date(2026, 12, 31)
    assert project.contract_duration_days == 365
    assert project.contract_amount_wan_yuan == Decimal("12345.67")
    assert project.construction_unit_name == "建设单位"
    assert project.general_contractor_unit_name == "总承包单位"
    assert project.supervision_unit_name == "监理单位"
    assert project.design_unit_name == "设计单位"
    assert project.survey_unit_name == "勘察单位"


def test_project_base_info_rejects_reversed_contract_dates(db: Session) -> None:
    project, user = project_admin(db)

    with pytest.raises(HTTPException) as exc_info:
        update_project(
            project.id,
            ProjectInput(
                name="错误日期项目",
                contract_start_date=date(2026, 12, 31),
                contract_end_date=date(2026, 1, 1),
            ),
            db,
            user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "合同结束日期不能早于开始日期"
    db.refresh(project)
    assert project.name == "原项目名称"


def test_name_only_update_keeps_existing_base_info(db: Session) -> None:
    project, user = project_admin(db)
    project.engineering_type_description = "已有工程概况"
    project.contract_start_date = date(2026, 1, 1)
    project.construction_unit_name = "已有建设单位"
    db.commit()

    update_project(
        project.id,
        ProjectInput(name="仅修改名称"),
        db,
        user,
    )

    db.refresh(project)
    assert project.name == "仅修改名称"
    assert project.engineering_type_description == "已有工程概况"
    assert project.contract_start_date == date(2026, 1, 1)
    assert project.construction_unit_name == "已有建设单位"
