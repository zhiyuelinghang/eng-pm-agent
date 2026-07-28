from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agent_tool_gateway import (
    execute_tool_operation,
    resolve_tool_context,
)
from backend.app.db import Base
from backend.app.models import (
    AgentConversation,
    OperationLog,
    Project,
    ProjectMember,
    RiskSource,
    Task,
    User,
    WbsItem,
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
    role: str = "member",
    conversation_type: str = "general",
    session_id: str = "session-1",
) -> tuple[User, Project, AgentConversation]:
    user = User(
        username=f"user-{session_id}",
        password_hash="unused",
        real_name="测试用户",
        role=role,
        status="active",
    )
    project = Project(project_name=f"项目-{session_id}", status="active")
    db.add_all([user, project])
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            member_role="project_member",
            display_name=user.real_name,
            status="active",
        ),
    )
    conversation = AgentConversation(
        project_id=project.id,
        user_id=user.id,
        agent_id="agent-main",
        agent_name="Dobby 全局总控",
        conversation_type=conversation_type,
        title="平台会话",
        agentscope_session_id=session_id,
        status="active",
    )
    db.add(conversation)
    db.commit()
    return user, project, conversation


def test_read_operation_is_strictly_scoped_to_bound_project(db: Session) -> None:
    _, project, conversation = _seed_context(db)
    other = Project(project_name="无权项目", status="active")
    db.add(other)
    db.flush()
    current_task = Task(
        project_id=project.id,
        title="当前项目任务",
        task_type="risk_alert",
        status="pending",
    )
    foreign_task = Task(
        project_id=other.id,
        title="其他项目任务",
        task_type="risk_alert",
        status="pending",
    )
    db.add_all([current_task, foreign_task])
    db.commit()

    context = resolve_tool_context(db, conversation.agentscope_session_id)
    data, _ = execute_tool_operation(
        db,
        context,
        "list_project_items",
        {"resource": "tasks"},
    )

    assert [item["title"] for item in data] == ["当前项目任务"]


def test_revoked_member_cannot_resolve_existing_session(db: Session) -> None:
    user, project, conversation = _seed_context(db)
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        ),
    )
    assert membership is not None
    membership.status = "inactive"
    db.commit()

    with pytest.raises(HTTPException) as error:
        resolve_tool_context(db, conversation.agentscope_session_id)

    assert error.value.status_code == 403


def test_business_agent_session_cannot_write(db: Session) -> None:
    _, _, conversation = _seed_context(
        db,
        conversation_type="business",
    )
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
    foreign_project = Project(project_name="其他项目", status="active")
    db.add(foreign_project)
    db.flush()
    foreign_wbs = WbsItem(
        project_id=foreign_project.id,
        code="OTHER-01",
        name="其他工序",
        progress=0,
        status="not_started",
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
    assert db.scalar(select(Task).where(Task.title == "越权引用")) is None


def test_member_main_can_create_task_but_not_admin_resource(db: Session) -> None:
    _, project, conversation = _seed_context(db)
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    task, _ = execute_tool_operation(
        db,
        context,
        "create_task",
        {"title": "总控创建的任务", "risk_level": "medium"},
    )
    assert task["status"] == "pending"
    assert task["title"] == "总控创建的任务"

    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_risk",
            {"name": "管理员风险"},
        )
    assert error.value.status_code == 403
    assert db.scalar(select(RiskSource).where(RiskSource.project_id == project.id)) is None


def test_admin_main_can_update_wbs_and_writes_audit_log(db: Session) -> None:
    _, project, conversation = _seed_context(db, role="superadmin")
    wbs = WbsItem(
        project_id=project.id,
        code="WBS-01",
        name="基础施工",
        progress=10,
        status="in_progress",
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
            "progress": 35,
            "status": "delayed",
            "note": "根据今日核验结果",
        },
    )

    assert result["progress"] == 35
    assert result["status"] == "delayed"
    log = db.scalar(
        select(OperationLog).where(
            OperationLog.target_type == "wbs",
            OperationLog.target_id == wbs.id,
        ),
    )
    assert log is not None
    assert "Dobby 智能体会话" in log.detail
