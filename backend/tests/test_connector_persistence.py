from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api import (
    delete_my_connector,
    delete_project_connector,
    list_my_connectors,
    list_project_connectors,
    project_dashboard,
    save_my_connector,
    save_project_connector,
    update_me,
)
from backend.app.connector_secrets import decrypt_connector_secret
from backend.app.db import Base
from backend.app.models import (
    Project,
    ProjectConnectorConfig,
    QualityMetric,
    RiskSource,
    User,
    UserConnectorConfig,
    WbsItem,
)
from backend.app.schemas import (
    ProfileUpdate,
    ProjectConnectorConfigInput,
    UserConnectorConfigInput,
)


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


def _admin_and_project(db: Session) -> tuple[User, Project]:
    user = User(
        username="connector-admin",
        password_hash="hash",
        role="admin",
        real_name="连接配置管理员",
        identity_card_no="CONNECTOR_ADMIN",
    )
    project = Project(name="连接配置测试项目")
    db.add_all([user, project])
    db.commit()
    return user, project


def test_profile_optional_fields_are_real_mapped_columns(db: Session) -> None:
    user, _ = _admin_and_project(db)

    result = update_me(
        ProfileUpdate(
            real_name="更新后的管理员",
            phone="13800138000",
            email="admin@example.com",
            title="项目负责人",
            org_name="测试建设单位",
        ),
        db,
        user,
    )

    db.expire_all()
    stored = db.get(User, user.id)
    assert stored is not None
    assert result["data"]["phone"] == "13800138000"
    assert stored.email == "admin@example.com"
    assert stored.title == "项目负责人"
    assert stored.org_name == "测试建设单位"


def test_personal_connector_is_encrypted_and_never_echoed(db: Session) -> None:
    user, _ = _admin_and_project(db)

    result = save_my_connector(
        "mail",
        UserConnectorConfigInput(
            account_identifier="admin@example.com",
            secret="mail-password",
        ),
        db,
        user,
    )

    stored = db.scalar(
        select(UserConnectorConfig).where(
            UserConnectorConfig.user_id == user.id,
            UserConnectorConfig.connector_type == "mail",
        ),
    )
    assert stored is not None
    assert stored.secret_encrypted != "mail-password"
    assert decrypt_connector_secret(stored.secret_encrypted) == "mail-password"
    assert result["data"]["has_secret"] is True
    assert "secret_encrypted" not in result["data"]
    assert len(list_my_connectors(db, user)["data"]) == 1

    delete_my_connector("mail", db, user)
    assert list_my_connectors(db, user)["data"] == []


def test_project_connector_is_project_scoped(db: Session) -> None:
    user, project = _admin_and_project(db)

    result = save_project_connector(
        project.id,
        "wecom",
        ProjectConnectorConfigInput(
            connection_id="https://example.com/project-webhook",
            secret="signing-secret",
        ),
        db,
        user,
    )

    stored = db.scalar(
        select(ProjectConnectorConfig).where(
            ProjectConnectorConfig.project_id == project.id,
            ProjectConnectorConfig.connector_type == "wecom",
        ),
    )
    assert stored is not None
    assert decrypt_connector_secret(stored.secret_encrypted) == "signing-secret"
    assert result["data"]["project_id"] == project.id
    assert "secret_encrypted" not in result["data"]
    assert len(list_project_connectors(project.id, db, user)["data"]) == 1

    delete_project_connector(project.id, "wecom", db, user)
    assert list_project_connectors(project.id, db, user)["data"] == []


def test_dashboard_fallback_uses_canonical_project_fields(db: Session) -> None:
    user, project = _admin_and_project(db)
    root = WbsItem(
        project_id=project.id,
        sort_order=1,
        wbs_code="1",
        name="总进度",
        progress_percent=Decimal("10"),
        status_text="进行中",
        level=1,
    )
    db.add(root)
    db.flush()
    leaf = WbsItem(
        project_id=project.id,
        parent_id=root.id,
        sort_order=2,
        wbs_code="1.1",
        name="基坑施工",
        progress_percent=Decimal("80"),
        status_text="进行中",
        level=2,
    )
    risk = RiskSource(
        project_id=project.id,
        serial_no=1,
        related_process_name="基坑安全检查",
        risk_part="深基坑临边防护",
        risk_level="重大",
        evaluation_condition="每日检查",
        material_requirements=["验收记录"],
        status="active",
    )
    db.add_all([leaf, risk])
    db.flush()
    db.add(
        QualityMetric(
            project_id=project.id,
            wbs_code=leaf.wbs_code,
            quality_acceptance_item="基坑验收",
            control_indicator="符合设计要求",
            inspection_frequency="每道工序",
            related_documents="验收记录",
        ),
    )
    db.commit()

    result = project_dashboard(project.id, db, user)["data"]

    assert result["progress_rate"] == 80
    assert result["risk_warnings"] == 1
    assert result["safety_issues"] == 1
    assert result["quality_issues"] == 1
    assert result["main_risk"] == "深基坑临边防护"
    assert result["main_quality"] == "基坑验收"
