from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

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
    project_status_overview,
    save_my_connector,
    save_project_connector,
    update_me,
)
from backend.app.connector_secrets import decrypt_connector_secret
from backend.app.db import Base
from backend.app.models import (
    EngineeringDocumentNode,
    EngineeringDocumentSyncState,
    Project,
    ProjectConnectorConfig,
    ProjectMember,
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
            connection_id="项目管理群",
            secret=(
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
                "?key=connector-test-key"
            ),
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
    assert decrypt_connector_secret(stored.secret_encrypted) == (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
        "?key=connector-test-key"
    )
    assert result["data"]["project_id"] == project.id
    assert result["data"]["connection_id"] == "项目管理群"
    assert "connector-test-key" not in str(result["data"])
    assert "secret_encrypted" not in result["data"]
    assert len(list_project_connectors(project.id, db, user)["data"]) == 1

    delete_project_connector(project.id, "wecom", db, user)
    assert list_project_connectors(project.id, db, user)["data"] == []


def test_dashboard_fallback_uses_canonical_project_fields(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyTaskEngine:
        @staticmethod
        def list_tasks(**_: object) -> list[object]:
            return []

    monkeypatch.setattr("backend.app.api.get_engine", lambda: EmptyTaskEngine())
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


def test_project_status_overview_preserves_unconfigured_states(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyTaskEngine:
        @staticmethod
        def list_tasks(**_: object) -> list[object]:
            return []

    monkeypatch.setattr("backend.app.api.get_engine", lambda: EmptyTaskEngine())
    user, project = _admin_and_project(db)

    result = project_status_overview(project.id, db, user)["data"]

    assert result["base_info"] == {
        "completed_fields": 1,
        "total_fields": 11,
        "missing_fields": [
            "工程类型",
            "合同开工日期",
            "合同竣工日期",
            "合同工期",
            "合同金额",
            "建设单位",
            "施工总承包单位",
            "监理单位",
            "设计单位",
            "勘察单位",
        ],
    }
    assert result["wbs"]["configured"] is False
    assert result["wbs"]["progress_rate"] is None
    assert result["tasks"]["total"] == 0
    assert result["risks"]["configured"] is False
    assert result["documents"] == {
        "total_files": 0,
        "today_count": 0, "today_files": [], "required_count": 0, "missing_materials": [], "complete": None,
        "folder_count": 0,
        "knowledge_base_count": 0,
        "knowledge_bases": [],
        "recent_files": [],
    }


def test_project_status_overview_aggregates_only_backed_sources(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project = _admin_and_project(db)
    project.engineering_type_description = "医疗建筑"
    project.contract_start_date = date(2026, 3, 1)
    project.contract_end_date = date(2027, 8, 31)
    project.contract_duration_days = 548
    project.contract_amount_wan_yuan = Decimal("12800")
    project.construction_unit_name = "建设单位"
    project.general_contractor_unit_name = "施工总承包单位"
    project.supervision_unit_name = "监理单位"
    project.design_unit_name = "设计单位"
    project.survey_unit_name = "勘察单位"
    db.add(ProjectMember(project_id=project.id, user_id=user.id))

    root = WbsItem(
        project_id=project.id,
        sort_order=1,
        wbs_code="1",
        name="土建工程",
        progress_percent=Decimal("20"),
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
        name="基坑支护",
        progress_percent=Decimal("80"),
        status_text="进行中",
        planned_finish_at=datetime(2026, 9, 18, 18, 0),
        level=2,
    )
    db.add(leaf)
    db.flush()
    db.add_all([
        RiskSource(
            project_id=project.id,
            serial_no=1,
            related_process_name="基坑支护",
            risk_part="深基坑",
            risk_level="重大",
            evaluation_condition="按方案监测",
            status="active",
        ),
        RiskSource(
            project_id=project.id,
            serial_no=2,
            related_process_name="临时用电",
            risk_part="配电箱",
            risk_level="一般",
            evaluation_condition="每日巡检",
            status="active",
        ),
        QualityMetric(
            project_id=project.id,
            wbs_code=leaf.wbs_code,
            quality_acceptance_item="支护验收",
            control_indicator="符合设计要求",
            inspection_frequency="每道工序",
            related_documents="验收记录",
        ),
    ])
    knowledge_base = EngineeringDocumentNode(
        project_id=project.id,
        node_type="knowledge_base",
        node_key="kb-1",
        knowledge_base_id="kb-1",
        external_id="kb-1",
        name="项目资料库",
        folder_path="",
    )
    db.add(knowledge_base)
    db.flush()
    document_folder = EngineeringDocumentNode(
        project_id=project.id,
        parent_id=knowledge_base.id,
        node_type="folder",
        node_key="folder-1",
        knowledge_base_id="kb-1",
        external_id="folder-1",
        name="方案资料",
        folder_path="方案资料",
    )
    db.add(document_folder)
    db.flush()
    db.add_all([
        EngineeringDocumentNode(
            project_id=project.id,
            parent_id=document_folder.id,
            node_type="file",
            node_key="doc-1",
            knowledge_base_id="kb-1",
            external_id="doc-1",
            name="施工方案.pdf",
            folder_path="方案资料",
            file_type="pdf",
            file_size=3_145_728,
            external_created_at="2026-08-30T09:00:00",
        ),
        EngineeringDocumentNode(
            project_id=project.id,
            parent_id=document_folder.id,
            node_type="file",
            node_key="doc-2",
            knowledge_base_id="kb-1",
            external_id="doc-2",
            name="总平面图.dwg",
            folder_path="方案资料",
            file_type="dwg",
            file_size=8_388_608,
            external_created_at="2026-08-31T10:30:00",
        ),
        EngineeringDocumentSyncState(project_id=project.id, status="ready"),
    ])
    db.commit()

    def fake_task(
        task_id: str,
        *,
        title: str,
        state: str,
        automation: bool = False,
    ) -> SimpleNamespace:
        timestamp = datetime(2026, 9, 1, 9, 0)
        return SimpleNamespace(
            id=task_id,
            title=title,
            scope={"project_id": project.id, "task_type": "risk_alert"},
            current_step=SimpleNamespace(
                assignee=SimpleNamespace(ref=str(user.id)),
            ),
            confirmer=None,
            due_at=timestamp,
            site=SimpleNamespace(ref=str(leaf.id)),
            trigger_note="测试任务",
            steps=[],
            state=state,
            priority="normal",
            is_automation=automation,
            created_at=timestamp,
            updated_at=timestamp,
            closed_at=None,
        )

    class FakeTaskEngine:
        @staticmethod
        def list_tasks(**_: object) -> list[SimpleNamespace]:
            return [
                fake_task("task-pending", title="待处理责任任务", state="pending"),
                fake_task("task-overdue", title="逾期责任任务", state="overdue"),
                fake_task(
                    "task-automation",
                    title="群聊定时通知",
                    state="overdue",
                    automation=True,
                ),
            ]

    monkeypatch.setattr("backend.app.api.get_engine", lambda: FakeTaskEngine())

    result = project_status_overview(project.id, db, user)["data"]

    assert result["base_info"]["completed_fields"] == 11
    assert result["wbs"]["configured"] is True
    assert result["wbs"]["leaf_items"] == 1
    assert result["wbs"]["progress_rate"] == 80
    assert result["tasks"]["total"] == 2
    assert result["tasks"]["pending"] == 1
    assert result["tasks"]["overdue"] == 1
    assert result["risks"]["total"] == 2
    assert result["risks"]["high_level_count"] == 1
    assert result["quality"] == {"configured": True, "total": 1}
    assert result["documents"] == {
        "total_files": 2,
        "today_count": 0, "today_files": [], "required_count": 1, "missing_materials": ["验收记录"], "complete": False,
        "folder_count": 1,
        "knowledge_base_count": 1,
        "knowledge_bases": [{
            "id": "kb-1",
            "name": "项目资料库",
            "folder_count": 1,
            "total_document_count": 2,
        }],
        "recent_files": [
            {
                "id": "doc-2",
                "name": "总平面图.dwg",
                "file_type": "dwg",
                "file_size": 8_388_608,
                "folder_path": "方案资料",
                "created_at": "2026-08-31T10:30:00",
                "knowledge_base_id": "kb-1",
                "knowledge_base_name": "项目资料库",
            },
            {
                "id": "doc-1",
                "name": "施工方案.pdf",
                "file_type": "pdf",
                "file_size": 3_145_728,
                "folder_path": "方案资料",
                "created_at": "2026-08-30T09:00:00",
                "knowledge_base_id": "kb-1",
                "knowledge_base_name": "项目资料库",
            },
        ],
    }
    assert result["members"]["total"] == 1
