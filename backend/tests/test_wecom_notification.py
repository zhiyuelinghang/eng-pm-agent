from datetime import UTC, datetime
import json

import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.connector_secrets import encrypt_connector_secret
from backend.app.db import Base
from backend.app.agent_context_gateway import WeComRelayInput, relay_wecom_message
from backend.app.models import (
    AgentConversation,
    OperationLog,
    OutboundNotification,
    Project,
    ProjectConnectorConfig,
    ProjectMember,
    User,
    UserConnectorConfig,
)
from backend.app.wecom_notification_gateway import (
    deliver_due_notifications,
    enqueue_task_notification,
    send_project_wecom_test,
    validate_wecom_webhook_url,
)
from task_engine.domain.models import (
    Activity,
    ActivityKind,
    Assignee,
    Site,
    Step,
    StepState,
    TaskInstance,
    TaskState,
)


WEBHOOK = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    "?key=notification-test-key"
)


@pytest.fixture
def database():
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
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db, factory


def _configured_task(db: Session) -> tuple[Project, User, TaskInstance]:
    project = Project(name="企业微信通知测试项目")
    user = User(
        username="wecom-owner",
        password_hash="hash",
        role="user",
        real_name="王芳",
        identity_card_no="WECOM_OWNER",
        phone="13800138000",
    )
    db.add_all([project, user])
    db.flush()
    db.add_all(
        [
            ProjectConnectorConfig(
                project_id=project.id,
                connector_type="wecom",
                connection_id="项目管理群",
                secret_encrypted=encrypt_connector_secret(WEBHOOK),
                configured=True,
            ),
            UserConnectorConfig(
                user_id=user.id,
                connector_type="wecom",
                account_identifier="wangfang",
                configured=True,
            ),
        ],
    )
    db.flush()
    assignee = Assignee(ref=str(user.id), display_name=user.real_name)
    task = TaskInstance(
        id="task_wecom_001",
        title="深基坑风险草稿审核",
        state=TaskState.RUNNING,
        steps=[
            Step(
                seq=0,
                name="审核风险草稿",
                state=StepState.ACTIVE,
                assignee=assignee,
                due_at=datetime(2026, 8, 21, 10, 0, tzinfo=UTC),
                deliverable="审核意见",
            ),
        ],
        site=Site(ref="12", code="WBS-12", name="深基坑"),
        confirmer=assignee,
        scope={"project_id": project.id},
        trigger_note="风险草稿已生成，请确认关键结论。",
        activities=[
            Activity(
                id="act_wecom_001",
                kind=ActivityKind.STEP_ACTIVATED,
                at=datetime.now(UTC),
            ),
        ],
    )
    return project, user, task


def test_webhook_validation_only_accepts_official_group_robot_url() -> None:
    assert validate_wecom_webhook_url(WEBHOOK) == WEBHOOK
    with pytest.raises(ValueError):
        validate_wecom_webhook_url("https://example.com/?key=secret")
    with pytest.raises(ValueError):
        validate_wecom_webhook_url(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
        )


def test_task_event_is_enqueued_once_with_current_owner_mention(database) -> None:
    db, _ = database
    project, user, task = _configured_task(db)

    first = enqueue_task_notification(db, task, "task_created")
    second = enqueue_task_notification(db, task, "task_created")
    db.commit()

    assert first is second
    assert first is not None
    assert first.project_id == project.id
    assert first.recipient_user_id == user.id
    assert first.mentioned_user_id is None
    assert first.mentioned_mobile == "13800138000"
    assert first.status == "pending"
    assert "深基坑风险草稿审核" in first.content
    assert "WBS-12 深基坑" in first.content
    assert len(db.scalars(select(OutboundNotification)).all()) == 1


def test_unconfigured_project_does_not_create_outbox_record(database) -> None:
    db, _ = database
    project = Project(name="未配置通知的项目")
    db.add(project)
    db.flush()
    assignee = Assignee(ref="999", display_name="测试人员")
    task = TaskInstance(
        id="task_without_connector",
        title="不应发送",
        state=TaskState.RUNNING,
        steps=[Step(seq=0, name="处理", assignee=assignee, state=StepState.ACTIVE)],
        site=Site(ref="1", name="测试工点"),
        confirmer=assignee,
        scope={"project_id": project.id},
    )

    assert enqueue_task_notification(db, task, "task_created") is None
    assert db.scalars(select(OutboundNotification)).all() == []


def test_due_notification_is_delivered_and_marked_sent(database) -> None:
    db, factory = database
    _, _, task = _configured_task(db)
    notification = enqueue_task_notification(db, task, "task_created")
    assert notification is not None
    db.commit()
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = deliver_due_notifications(
            session_factory=factory,
            client=client,
        )

    db.expire_all()
    stored = db.get(OutboundNotification, notification.id)
    assert report.sent == 1
    assert report.retrying == 0
    assert stored is not None
    assert stored.status == "sent"
    assert stored.attempt_count == 1
    assert stored.sent_at is not None
    assert "mentioned_list" not in payloads[0]["text"]
    assert payloads[0]["text"]["mentioned_mobile_list"] == ["13800138000"]


def test_wecom_business_error_is_retried_without_leaking_webhook(database) -> None:
    db, factory = database
    _, _, task = _configured_task(db)
    notification = enqueue_task_notification(db, task, "task_created")
    assert notification is not None
    db.commit()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = deliver_due_notifications(
            session_factory=factory,
            client=client,
        )

    db.expire_all()
    stored = db.get(OutboundNotification, notification.id)
    assert report.retrying == 1
    assert stored is not None
    assert stored.status == "retrying"
    assert stored.next_attempt_at is not None
    assert "notification-test-key" not in (stored.last_error or "")


def test_explicit_project_connection_test_uses_stored_secret(database) -> None:
    db, _ = database
    project, _, _ = _configured_task(db)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = send_project_wecom_test(db, project.id, client=client)

    assert result == {"status": "ok", "response_code": "0"}
    assert requests[0].url.params["key"] == "notification-test-key"


def test_internal_mcp_relay_is_bound_to_conversation_project(
    database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _ = database
    project, user, _ = _configured_task(db)
    db.add(ProjectMember(project_id=project.id, user_id=user.id))
    conversation = AgentConversation(
        project_id=project.id,
        user_id=user.id,
        agent_id="global-main",
        agent_name="Dobby",
        conversation_type="general",
        title="企业微信通知测试会话",
        agentscope_session_id="platform-session-wecom",
        status="active",
    )
    db.add(conversation)
    db.commit()
    captured: dict = {}

    def fake_send(session: Session, project_id: int, payload: dict):
        captured.update(
            session=session,
            project_id=project_id,
            payload=payload,
        )
        return {
            "status": "ok",
            "response_code": "0",
            "message_type": "text",
        }

    monkeypatch.setattr(
        "backend.app.agent_context_gateway.send_project_wecom_payload",
        fake_send,
    )
    result = relay_wecom_message(
        WeComRelayInput(
            payload={"msgtype": "text", "text": {"content": "任务已下发"}},
        ),
        conversation.agentscope_session_id,
        db,
    )

    assert result["success"] is True
    assert captured["project_id"] == project.id
    assert captured["payload"]["text"]["content"] == "任务已下发"
    log = db.scalar(
        select(OperationLog).where(
            OperationLog.action == "Dobby发送企业微信消息",
        ),
    )
    assert log is not None
    assert log.project_id == project.id
