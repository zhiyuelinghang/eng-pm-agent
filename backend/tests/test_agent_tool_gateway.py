from pathlib import Path

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agent_tool_gateway import (
    execute_tool_operation,
    get_initialization_file_content,
    resolve_tool_context,
)
from backend.app.db import Base
from backend.app.models import (
    AgentConversation,
    OperationLog,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationFile,
    ProjectMember,
    Task,
    User,
    WbsItem,
)
from backend.app.project_initialization import (
    ApplyInitializationDraftInput,
    PersonnelCredentialInput,
    apply_initialization_draft,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    with session_factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _seed_context(
    db: Session,
    *,
    role: str = "user",
    conversation_type: str = "general",
    session_id: str = "session-1",
) -> tuple[User, Project, AgentConversation]:
    user = User(
        username=f"user-{session_id}",
        password_hash="unused",
        real_name="测试用户",
        identity_card_no=f"CARD-{session_id}",
        role=role,
    )
    project = Project(name=f"项目-{session_id}")
    db.add_all([user, project])
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            serial_no=1,
            position_name="项目经理",
            certificate_no=f"CERT-{session_id}",
            responsibility_description="负责项目管理",
        ),
    )
    conversation = AgentConversation(
        project_id=project.id,
        user_id=user.id,
        agent_id="agent-main",
        agent_name="Dobby 智能体",
        conversation_type=conversation_type,
        title="平台会话",
        agentscope_session_id=session_id,
        status="active",
    )
    db.add(conversation)
    db.commit()
    return user, project, conversation


def _initialization_payload() -> dict:
    return {
        "project": {
            "engineering_type_description": "社区卫生服务中心扩建工程",
            "construction_unit_name": "建设单位",
        },
        "personnel": [
            {
                "serial_no": 1,
                "real_name": "张项目",
                "identity_card_no": "310000000000000001",
                "position_name": "项目经理",
                "certificate_no": "CERT-001",
                "responsibility_description": "负责项目统筹",
            },
        ],
        "wbs": [
            {
                "wbs_code": "1",
                "parent_wbs_code": None,
                "name": "施工阶段",
                "planned_start_at": "2026-07-01T08:00:00",
                "planned_finish_at": "2026-07-31T17:00:00",
                "progress_percent": 0,
                "status_text": None,
                "priority_text": None,
                "level": 1,
                "sort_order": 1,
            },
            {
                "wbs_code": "1.1",
                "parent_wbs_code": "1",
                "name": "基础施工",
                "planned_start_at": "2026-07-01T08:00:00",
                "planned_finish_at": "2026-07-15T17:00:00",
                "progress_percent": 0,
                "status_text": "未开始",
                "priority_text": "中",
                "level": 2,
                "sort_order": 1,
            },
        ],
        "risks": [
            {
                "serial_no": 1,
                "related_wbs_code": "1.1",
                "related_process_name": "基础施工",
                "risk_part": "基坑",
                "risk_level": "较大风险",
                "evaluation_condition": "深度达到风险清单条件",
            },
        ],
        "quality_requirements": [
            {
                "wbs_code": "1.1",
                "quality_acceptance_item": "基础验收",
                "control_indicator": "符合设计要求",
                "inspection_frequency": "每道工序",
                "related_documents": "验收记录",
            },
        ],
    }


def test_read_operation_is_strictly_scoped_to_bound_project(db: Session) -> None:
    _, project, conversation = _seed_context(db)
    other = Project(name="无权项目")
    db.add(other)
    db.flush()
    db.add_all(
        [
            Task(
                project_id=project.id,
                title="当前项目任务",
                task_type="risk_alert",
                status="pending",
            ),
            Task(
                project_id=other.id,
                title="其他项目任务",
                task_type="risk_alert",
                status="pending",
            ),
        ],
    )
    db.commit()

    context = resolve_tool_context(db, conversation.agentscope_session_id)
    data, _ = execute_tool_operation(
        db,
        context,
        "list_project_items",
        {"resource": "tasks"},
    )

    assert [item["title"] for item in data] == ["当前项目任务"]


def test_removed_member_cannot_resolve_existing_session(db: Session) -> None:
    user, project, conversation = _seed_context(db)
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        ),
    )
    assert membership is not None
    db.delete(membership)
    db.commit()

    with pytest.raises(HTTPException) as error:
        resolve_tool_context(db, conversation.agentscope_session_id)

    assert error.value.status_code == 403


def test_business_agent_session_cannot_write(db: Session) -> None:
    _, _, conversation = _seed_context(db, conversation_type="business")
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_task",
            {"title": "不应创建"},
        )

    assert error.value.status_code == 403
    assert db.scalar(select(Task).where(Task.title == "不应创建")) is None


def test_cross_project_reference_is_hidden_and_rejected(db: Session) -> None:
    _, _, conversation = _seed_context(db)
    foreign_project = Project(name="其他项目")
    db.add(foreign_project)
    db.flush()
    foreign_wbs = WbsItem(
        project_id=foreign_project.id,
        wbs_code="OTHER-01",
        name="其他工序",
        level=1,
        sort_order=1,
    )
    db.add(foreign_wbs)
    db.commit()
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_task",
            {"title": "越权引用", "wbs_item_id": foreign_wbs.id},
        )

    assert error.value.status_code == 404


def test_admin_main_can_update_new_wbs_fields_and_audit(db: Session) -> None:
    _, project, conversation = _seed_context(db, role="admin")
    wbs = WbsItem(
        project_id=project.id,
        wbs_code="WBS-01",
        name="基础施工",
        level=1,
        sort_order=1,
        progress_percent=10,
        status_text="in_progress",
    )
    db.add(wbs)
    db.commit()
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    result, _ = execute_tool_operation(
        db,
        context,
        "update_wbs_progress",
        {
            "wbs_item_id": wbs.id,
            "progress_percent": 35,
            "status_text": "delayed",
            "note": "根据今日核验结果",
        },
    )

    assert result["progress_percent"] == 35
    assert result["status_text"] == "delayed"
    log = db.scalar(
        select(OperationLog).where(
            OperationLog.target_type == "wbs",
            OperationLog.target_id == wbs.id,
        ),
    )
    assert log is not None
    assert "Dobby 智能体会话" in log.detail


def test_initialization_agent_can_only_submit_draft(db: Session) -> None:
    _, project, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    draft, _ = execute_tool_operation(
        db,
        context,
        "submit_project_initialization_draft",
        {
            "payload": _initialization_payload(),
            "source_files": ["人员名单.xlsx", "总进度计划.xlsx"],
        },
    )

    assert draft["status"] == "ready"
    assert draft["summary"]["wbs"] == 2
    assert draft["payload"]["wbs"][0]["progress_percent"] == "0"
    assert draft["payload"]["wbs"][0]["parent_wbs_code"] is None
    assert db.get(Project, project.id).engineering_type_description is None
    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_task",
            {"title": "初始化智能体不能直接写业务表"},
        )
    assert error.value.status_code == 403


def test_initialization_agent_reads_and_incrementally_updates_draft(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    created, _ = execute_tool_operation(
        db,
        context,
        "submit_project_initialization_draft",
        {
            "payload": _initialization_payload(),
            "source_files": ["总进度计划.xlsx"],
        },
    )

    wbs_page, _ = execute_tool_operation(
        db,
        context,
        "get_project_initialization_draft",
        {"section": "wbs", "start": 1, "limit": 1},
    )
    assert wbs_page["draft"]["id"] == created["id"]
    assert wbs_page["draft"]["revision"] == 1
    assert wbs_page["total"] == 2
    assert wbs_page["next_start"] == 2
    assert [item["wbs_code"] for item in wbs_page["data"]] == ["1"]

    updated, _ = execute_tool_operation(
        db,
        context,
        "update_project_initialization_draft",
        {
            "draft_id": created["id"],
            "expected_revision": 1,
            "source_files": ["工程风险清单.xlsx"],
            "patch": {
                "project": {
                    "contract_amount_wan_yuan": 1234.5,
                },
                "risks": [
                    {
                        "serial_no": 2,
                        "related_wbs_code": "1.1",
                        "related_process_name": "基础施工",
                        "risk_part": "临边防护",
                        "risk_level": "一般风险",
                        "evaluation_condition": "临边防护缺失",
                    },
                ],
            },
        },
    )
    assert updated["revision"] == 2
    assert updated["updated_sections"] == ["project", "risks"]
    assert updated["summary"]["wbs"] == 2
    assert updated["summary"]["risks"] == 1
    assert updated["source_files"] == [
        "总进度计划.xlsx",
        "工程风险清单.xlsx",
    ]

    draft = db.get(ProjectInitializationDraft, created["id"])
    assert draft is not None
    assert len(draft.payload["wbs"]) == 2
    assert len(draft.payload["personnel"]) == 1
    assert draft.payload["project"]["engineering_type_description"] == (
        "社区卫生服务中心扩建工程"
    )
    assert draft.payload["project"]["contract_amount_wan_yuan"] == "1234.5"
    assert draft.payload["risks"][0]["serial_no"] == 2
    assert len(draft.payload["quality_requirements"]) == 1

    with pytest.raises(HTTPException) as stale:
        execute_tool_operation(
            db,
            context,
            "update_project_initialization_draft",
            {
                "draft_id": created["id"],
                "expected_revision": 1,
                "patch": {"risks": []},
            },
        )
    assert stale.value.status_code == 409
    assert "重新读取草稿" in stale.value.detail


def test_initialization_file_is_bound_to_its_agent_session(
    db: Session,
    tmp_path,
) -> None:
    user, project, conversation = _seed_context(
        db,
        conversation_type="initialization",
    )
    file_path = tmp_path / "人员名单.xlsx"
    file_path.write_bytes(b"raw-xlsx-content")
    row = ProjectInitializationFile(
        project_id=project.id,
        conversation_id=conversation.id,
        uploaded_by_user_id=user.id,
        file_name=file_path.name,
        storage_path=str(file_path),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        file_size=file_path.stat().st_size,
        file_hash="hash-1",
    )
    db.add(row)
    db.commit()

    response = get_initialization_file_content(
        row.id,
        conversation.agentscope_session_id,
        db,
    )
    assert Path(response.path) == file_path
    assert response.headers["x-dobby-file-extension"] == ".xlsx"

    _, _, other_conversation = _seed_context(
        db,
        conversation_type="initialization",
        session_id="other-session",
    )
    with pytest.raises(HTTPException) as error:
        get_initialization_file_content(
            row.id,
            other_conversation.agentscope_session_id,
            db,
        )
    assert error.value.status_code == 404


def test_confirmed_draft_is_applied_in_one_transaction(db: Session) -> None:
    _, project, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    result, _ = execute_tool_operation(
        db,
        context,
        "submit_project_initialization_draft",
        {"payload": _initialization_payload()},
    )
    draft = db.get(ProjectInitializationDraft, result["id"])
    assert draft is not None

    applied = apply_initialization_draft(
        db,
        draft,
        ApplyInitializationDraftInput(
            allow_partial=True,
            personnel_credentials=[
                PersonnelCredentialInput(
                    identity_card_no="310000000000000001",
                    username="zhangxiangmu",
                    initial_password="TempPass123!",
                ),
            ],
        ),
    )
    db.commit()

    assert applied["counts"] == {
        "personnel": 1,
        "wbs": 2,
        "risks": 1,
        "quality_requirements": 1,
    }
    assert db.get(Project, project.id).engineering_type_description == (
        "社区卫生服务中心扩建工程"
    )
    assert db.scalar(
        select(User).where(User.username == "zhangxiangmu"),
    ) is not None
