from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import task_context_api
from backend.app.db import Base
from backend.app.models import (
    Attachment,
    ChatChannel,
    ChatMessage,
    CollaborationMessage,
    CollaborationSession,
    Project,
    ProjectMember,
    RiskSource,
    User,
    WbsItem,
)
from task_engine.domain.models import Assignee, Site, StepSpec, TaskFlow
from task_engine.engine import TaskEngine


def test_task_context_links_project_records(tmp_path, monkeypatch) -> None:
    orm_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        orm_engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(orm_engine)
    reference_engine = TaskEngine(tmp_path / "task-context.db")
    monkeypatch.setattr(task_context_api, "get_engine", lambda: reference_engine)

    with Session(orm_engine) as db:
        project = Project(name="任务上下文测试项目")
        user = User(
            username="task-context-user",
            password_hash="test",
            role="user",
            real_name="任务上下文用户",
            identity_card_no="TASK_CONTEXT_USER",
        )
        db.add_all([project, user])
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=user.id))
        wbs = WbsItem(
            project_id=project.id,
            sort_order=1,
            wbs_code="WBS-CONTEXT",
            name="上下文工点",
            level=1,
        )
        risk = RiskSource(
            project_id=project.id,
            serial_no=1,
            related_process_name="主体结构",
            risk_part="临边防护",
            risk_level="high",
            evaluation_condition="防护缺失",
            risk_window_start_date=date(2026, 9, 1),
            risk_window_end_date=date(2026, 9, 30),
        )
        db.add_all([wbs, risk])
        db.flush()

        owner = Assignee(ref=str(user.id), display_name=user.real_name)
        task = reference_engine.dispatch(
            TaskFlow(
                title="补齐临边防护资料",
                steps=(
                    StepSpec(
                        name="提交现场资料",
                        assignee=owner,
                        deliverable="现场照片.jpg",
                    ),
                ),
                site=Site(ref=str(wbs.id), name=wbs.name, code=wbs.wbs_code),
                confirmer=owner,
                scope={
                    "project_id": project.id,
                    "task_type": "material_missing",
                    "risk_source_id": risk.id,
                },
            ),
            actor=str(user.id),
            trigger_note="群聊发现资料缺口",
        )

        channel = ChatChannel(
            project_id=project.id,
            created_by_user_id=user.id,
            title="项目群",
            channel_type="project",
        )
        session = CollaborationSession(
            project_id=project.id,
            title="临边防护协同",
            participant_ids=[user.id],
            task_ids=[task.id],
        )
        attachment = Attachment(
            project_id=project.id,
            file_name="现场照片.jpg",
            storage_path="test/现场照片.jpg",
            category="任务处置",
        )
        db.add_all([channel, session, attachment])
        db.flush()
        db.add_all(
            [
                ChatMessage(
                    channel_id=channel.id,
                    sender_type="system",
                    message_type="task_event",
                    content="任务已进入处理队列",
                    task_ids=[task.id],
                ),
                CollaborationMessage(
                    session_id=session.id,
                    role="assistant",
                    content="已生成资料补齐任务",
                    generated_task_ids=[task.id],
                ),
            ],
        )
        db.commit()

        data = task_context_api.task_context(
            project.id,
            task.id,
            db,
            user,
        )["data"]

        assert data["risk"] == {"id": str(risk.id), "name": "临边防护"}
        assert data["wbs"]["id"] == str(wbs.id)
        assert data["chat_messages"][0]["channel_id"] == channel.id
        assert data["collaboration_sessions"][0]["id"] == session.id
        assert data["documents"][0]["file_name"] == "现场照片.jpg"

    orm_engine.dispose()
