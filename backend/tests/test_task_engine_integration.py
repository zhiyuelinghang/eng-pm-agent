from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import api
from backend.app.db import Base
from backend.app.models import (
    ChatChannel,
    ChatChannelMember,
    ChatMessage,
    ChatMessageMentionReceipt,
    ChatRealtimeOutbox,
    Project,
    ProjectMember,
    User,
    WbsItem,
)
from backend.app.schemas import (
    TaskFlowGenerateInput,
    TaskInput,
    TaskStepUpdate,
    TaskTransitionInput,
)
from backend.app.task_action_gateway import (
    execute_pending_automation_tasks,
)
from task_engine.domain.models import (
    Assignee,
    CalendarMode,
    IntervalUnit,
    RunMode,
    Site,
    StepSpec,
    TaskFlow,
    Trigger,
)
from task_engine.engine import TaskEngine


@pytest.fixture()
def platform_db() -> Session:
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
    with Session(orm_engine) as session:
        yield session


@pytest.fixture()
def responsibility_context(
    platform_db: Session,
) -> tuple[Project, User, User, WbsItem]:
    project = Project(name="任务引擎接入测试项目")
    responsible = User(
        username="task-owner",
        password_hash="hash",
        role="user",
        real_name="任务责任人",
        identity_card_no="TASK_OWNER",
    )
    confirmer = User(
        username="task-confirmer",
        password_hash="hash",
        role="user",
        real_name="任务确认人",
        identity_card_no="TASK_CONFIRMER",
    )
    platform_db.add_all([project, responsible, confirmer])
    platform_db.flush()
    platform_db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=responsible.id),
            ProjectMember(project_id=project.id, user_id=confirmer.id),
        ],
    )
    site = WbsItem(
        project_id=project.id,
        sort_order=1,
        wbs_code="WBS-001",
        name="一号工点",
        level=1,
    )
    platform_db.add(site)
    platform_db.commit()
    return project, responsible, confirmer, site


def _task_payload(
    responsible: User,
    confirmer: User,
    site: WbsItem | None,
) -> TaskInput:
    return TaskInput(
        title="检查一号工点",
        task_type="risk_alert",
        risk_level="high",
        confirmer_user_id=confirmer.id,
        wbs_item_id=site.id if site else None,
        trigger_reason="任务引擎接入验证",
        workflow_steps=[
            {
                "name": "现场检查",
                "owner_user_id": str(responsible.id),
                "due_at": "2026-08-21",
                "material": "现场照片",
            },
        ],
    )


def test_validation_a_rejects_task_without_site(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, responsible, confirmer, _ = responsibility_context
    reference_engine = TaskEngine(tmp_path / "validation-a.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)

    with pytest.raises(HTTPException) as error:
        api.create_task(
            project.id,
            _task_payload(responsible, confirmer, None),
            platform_db,
            responsible,
        )

    assert error.value.status_code == 422
    assert error.value.detail == "任务未关联工点，无法布置"


def test_validation_c_only_confirmer_can_accept(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, responsible, confirmer, site = responsibility_context
    reference_engine = TaskEngine(tmp_path / "validation-c.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)

    created = api.create_task(
        project.id,
        _task_payload(responsible, confirmer, site),
        platform_db,
        responsible,
    )["data"]
    api.update_task_step(
        created["id"],
        0,
        TaskStepUpdate(
            status="completed",
            note="已完成现场检查",
            attachments=["现场照片.jpg"],
        ),
        platform_db,
        responsible,
    )

    with pytest.raises(HTTPException) as error:
        api.transition_task(
            created["id"],
            TaskTransitionInput(status="completed"),
            platform_db,
            responsible,
        )

    assert error.value.status_code == 409
    assert error.value.detail == "只有确认人 任务确认人 可以验收该任务"

    accepted = api.transition_task(
        created["id"],
        TaskTransitionInput(status="completed"),
        platform_db,
        confirmer,
    )["data"]
    assert accepted["status"] == "completed"


def test_recurring_tick_is_idempotent_and_creates_two_tasks(tmp_path) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    first_at = datetime(2026, 8, 21, 9, 0, tzinfo=timezone)
    reference_engine = TaskEngine(tmp_path / "validation-b.db")
    person = Assignee(ref="1", display_name="任务责任人")
    flow = TaskFlow(
        title="周期检查一号工点",
        steps=(StepSpec(name="现场检查", assignee=person),),
        site=Site(ref="1", name="一号工点", code="WBS-001"),
        confirmer=person,
        trigger=Trigger(
            run_mode=RunMode.RECURRING,
            first_at=first_at,
            interval_value=1,
            interval_unit=IntervalUnit.HOUR,
            timezone="Asia/Shanghai",
        ),
        scope={"project_id": 1, "task_type": "risk_alert"},
    )
    reference_engine.schedule(flow, now=first_at - timedelta(minutes=1))

    first = reference_engine.tick(now=first_at)
    duplicate = reference_engine.tick(now=first_at)
    second = reference_engine.tick(now=first_at + timedelta(hours=1))

    assert first.created_count == 1
    assert duplicate.created_count == 0
    assert duplicate.skipped == 0
    assert second.created_count == 1
    assert len(reference_engine.list_tasks()) == 2


def test_timed_once_registers_schedule_before_creating_task(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, responsible, confirmer, site = responsibility_context
    reference_engine = TaskEngine(tmp_path / "timed-once.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = _task_payload(responsible, confirmer, site).model_copy(
        update={
            "run_mode": "once",
            "trigger_date": "2026-08-21",
            "trigger_time": "09:30",
        },
    )

    registered = api.create_task(
        project.id,
        payload,
        platform_db,
        responsible,
    )["data"]

    assert registered["schedule_id"].startswith("sched_")
    assert reference_engine.list_tasks() == []
    plan = reference_engine.get_schedule(registered["schedule_id"])
    assert plan is not None
    assert plan.flow.trigger.run_mode is RunMode.ONCE
    assert plan.next_fire_at == datetime(
        2026,
        8,
        21,
        9,
        30,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )


@pytest.mark.parametrize(
    ("end_mode", "until_date", "max_fires"),
    [
        ("until", "2026-09-30", None),
        ("count", None, 6),
    ],
)
def test_recurring_schedule_exposes_engine_native_end_conditions(
    end_mode: str,
    until_date: str | None,
    max_fires: int | None,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, responsible, confirmer, site = responsibility_context
    reference_engine = TaskEngine(tmp_path / f"recurring-{end_mode}.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = _task_payload(responsible, confirmer, site).model_copy(
        update={
            "run_mode": "recurring",
            "trigger_date": "2026-08-21",
            "trigger_time": "09:00",
            "trigger_interval_value": 2,
            "trigger_interval_unit": "week",
            "trigger_end_mode": end_mode,
            "trigger_until_date": until_date,
            "trigger_max_fires": max_fires,
        },
    )

    registered = api.create_task(
        project.id,
        payload,
        platform_db,
        responsible,
    )["data"]
    plan = reference_engine.get_schedule(registered["schedule_id"])

    assert plan is not None
    assert plan.flow.trigger.run_mode is RunMode.RECURRING
    assert plan.flow.trigger.interval_value == 2
    assert plan.flow.trigger.interval_unit is IntervalUnit.WEEK
    if end_mode == "until":
        assert plan.flow.trigger.until == datetime(
            2026,
            9,
            30,
            9,
            0,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        assert plan.flow.trigger.max_fires is None
    else:
        assert plan.flow.trigger.until is None
        assert plan.flow.trigger.max_fires == 6


def _project_chat_channel(
    db: Session,
    project: Project,
    creator: User,
) -> ChatChannel:
    channel = ChatChannel(
        project_id=project.id,
        created_by_user_id=creator.id,
        title="任务自动化测试群",
        summary="验证任务引擎触发群聊消息",
        channel_type="project",
    )
    db.add(channel)
    db.commit()
    return channel


def test_dobby_generates_one_timed_project_chat_message_node(
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    fixed_now = datetime(2026, 8, 25, 16, 47, tzinfo=ZoneInfo("Asia/Shanghai"))

    class FixedClock:
        @staticmethod
        def now() -> datetime:
            return fixed_now

    monkeypatch.setattr(api, "get_engine", lambda: FixedClock())
    result = api.generate_task_flow(
        project.id,
        TaskFlowGenerateInput(
            requirement=(
                "创建一个定时单次群发任务：今天16:52由任务智能体在当前项目群"
                "@全体成员发送“Dobby定时群发测试：看到这条消息说明任务引擎"
                "触发和群聊发送正常。”"
            ),
        ),
        platform_db,
        creator,
    )["data"]

    assert result["run_mode"] == "once"
    assert result["trigger_date"] == "2026-08-25"
    assert result["trigger_time"] == "16:52"
    assert result["generated_by"] == "rules"
    assert len(result["steps"]) == 1
    step = result["steps"][0]
    assert step["node_type"] == "project_chat_message"
    assert step["action"] == {
        "type": "project_chat_message",
        "channel_id": channel.id,
        "sender_agent_id": "dobby-task-engine",
        "sender_agent_name": "Dobby（任务引擎）",
        "mention_mode": "all",
        "mentioned_user_ids": [],
        "content": "Dobby定时群发测试：看到这条消息说明任务引擎触发和群聊发送正常。",
    }


def test_message_automation_registers_minute_schedule_without_wbs(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    reference_engine = TaskEngine(tmp_path / "message-minute.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = TaskInput(
        title="每五分钟提醒提交记录",
        task_type="automation",
        action_type="project_chat_message",
        run_mode="recurring",
        trigger_date="2026-08-25",
        trigger_time="09:00",
        trigger_interval_value=5,
        trigger_interval_unit="minute",
        target_channel_id=channel.id,
        mention_mode="all",
        message_content="请提交最新现场记录。",
    )

    registered = api.create_task(
        project.id,
        payload,
        platform_db,
        creator,
    )["data"]
    plan = reference_engine.get_schedule(registered["schedule_id"])

    assert plan is not None
    assert plan.flow.is_automation is True
    assert plan.flow.site is None
    assert plan.flow.confirmer is None
    assert plan.flow.steps[0].assignee is None
    assert plan.flow.trigger.interval_value == 5
    assert plan.flow.trigger.interval_unit is IntervalUnit.MINUTE
    assert plan.flow.scope["action"]["channel_id"] == channel.id


def test_message_automation_supports_calendar_trigger(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    reference_engine = TaskEngine(tmp_path / "message-calendar.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = TaskInput(
        title="每周安全例会提醒",
        task_type="automation",
        action_type="project_chat_message",
        run_mode="calendar",
        trigger_date="2026-08-25",
        trigger_time="08:30",
        trigger_calendar_mode="weekly",
        trigger_weekdays=[1, 3, 5],
        target_channel_id=channel.id,
        mention_mode="all",
        message_content="请准备安全例会材料。",
    )

    registered = api.create_task(
        project.id,
        payload,
        platform_db,
        creator,
    )["data"]
    plan = reference_engine.get_schedule(registered["schedule_id"])

    assert plan is not None
    assert plan.flow.trigger.run_mode is RunMode.CALENDAR
    assert plan.flow.trigger.calendar_mode is CalendarMode.WEEKLY
    assert plan.flow.trigger.calendar_weekdays == (1, 3, 5)


def test_message_node_only_flow_is_classified_as_automation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    reference_engine = TaskEngine(tmp_path / "message-node-only.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)

    registered = api.create_task(
        project.id,
        TaskInput(
            title="群聊定时通知",
            task_type="daily_confirm",
            run_mode="once",
            trigger_date="2026-08-25",
            trigger_time="17:25",
            workflow_steps=[
                {
                    "name": "发送群聊消息",
                    "node_type": "project_chat_message",
                    "action": {
                        "type": "project_chat_message",
                        "channel_id": channel.id,
                        "sender_agent_id": "dobby-task-engine",
                        "sender_agent_name": "Dobby（任务引擎）",
                        "mention_mode": "all",
                        "mentioned_user_ids": [],
                        "content": "任务引擎联调测试。",
                    },
                },
            ],
        ),
        platform_db,
        creator,
    )["data"]

    plan = reference_engine.get_schedule(registered["schedule_id"])
    assert plan is not None
    assert plan.flow.execution_kind == "automation"
    assert plan.flow.scope["task_type"] == "automation"
    listed = api.list_task_schedules(project.id, platform_db, creator)["data"]
    assert listed[0]["execution_kind"] == "automation"
    assert listed[0]["action"]["type"] == "project_chat_message"


def test_message_schedule_can_be_listed_paused_resumed_and_cancelled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    reference_engine = TaskEngine(tmp_path / "message-manage.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    registered = api.create_task(
        project.id,
        TaskInput(
            title="可管理的消息计划",
            task_type="automation",
            action_type="project_chat_message",
            run_mode="recurring",
            trigger_date="2026-08-25",
            trigger_time="09:00",
            trigger_interval_value=30,
            trigger_interval_unit="minute",
            target_channel_id=channel.id,
            mention_mode="all",
            message_content="半小时进度提醒。",
        ),
        platform_db,
        creator,
    )["data"]
    schedule_id = registered["schedule_id"]

    listed = api.list_task_schedules(
        project.id,
        platform_db,
        creator,
    )["data"]
    assert [item["id"] for item in listed] == [schedule_id]

    paused = api.pause_task_schedule(
        schedule_id,
        True,
        platform_db,
        creator,
    )["data"]
    assert paused["paused"] is True
    assert paused["status"] == "已暂停"

    resumed = api.pause_task_schedule(
        schedule_id,
        False,
        platform_db,
        creator,
    )["data"]
    assert resumed["paused"] is False
    assert resumed["status"] == "生效中"

    api.cancel_task_schedule(schedule_id, platform_db, creator)
    cancelled = reference_engine.get_schedule(schedule_id)
    assert cancelled is not None
    assert cancelled.active is False
    assert cancelled.next_fire_at is None


def test_due_message_automation_posts_all_mention_once(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, receiver, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    reference_engine = TaskEngine(tmp_path / "message-execute.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = TaskInput(
        title="定时群通知",
        task_type="automation",
        action_type="project_chat_message",
        run_mode="once",
        trigger_date="2026-08-25",
        trigger_time="10:00",
        target_channel_id=channel.id,
        mention_mode="all",
        message_content="请全体成员十点前提交日报。",
    )
    registered = api.create_task(
        project.id,
        payload,
        platform_db,
        creator,
    )["data"]
    plan = reference_engine.get_schedule(registered["schedule_id"])
    assert plan is not None and plan.next_fire_at is not None

    report = reference_engine.tick(now=plan.next_fire_at)
    results = execute_pending_automation_tasks(platform_db, reference_engine)

    assert report.created_count == 1
    assert len(results) == 1
    assert results[0].ok is True
    message = platform_db.scalar(select(ChatMessage))
    assert message is not None
    assert message.sender_type == "agent"
    assert message.sender_agent_id == "dobby-task-engine"
    assert message.message_type == "task_event"
    assert message.content == "@全体成员 请全体成员十点前提交日报。"
    assert message.metadata_json["mention_all"] is True
    assert message.task_ids == [report.fired[0].task_id]
    receipt_user_ids = set(
        platform_db.scalars(select(ChatMessageMentionReceipt.user_id)).all(),
    )
    assert receipt_user_ids == {creator.id, receiver.id}
    assert platform_db.scalar(select(func.count(ChatRealtimeOutbox.id))) == 3

    ledger = api.list_archived_tasks(project.id, platform_db, creator)["data"]
    assert len(ledger) == 1
    assert ledger[0]["closed_at"]
    assert ledger[0]["updated_at"]
    assert ledger[0]["workflow_steps"][0]["node_type"] == "project_chat_message"
    assert ledger[0]["workflow_steps"][0]["action"]["sender_agent_id"] == (
        "dobby-task-engine"
    )
    plans = api.list_task_schedules(project.id, platform_db, creator)["data"]
    assert plans[0]["status"] == "已结束"

    repeated = execute_pending_automation_tasks(platform_db, reference_engine)

    assert repeated == []
    assert platform_db.scalar(select(func.count(ChatMessage.id))) == 1
    assert reference_engine.get_task(report.fired[0].task_id).state.value == "done"


def test_message_is_a_node_inside_the_original_task_flow(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, receiver, site = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    reference_engine = TaskEngine(tmp_path / "message-node.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = TaskInput(
        title="检查后在项目群提醒复核",
        task_type="risk_alert",
        confirmer_user_id=receiver.id,
        wbs_item_id=site.id,
        workflow_steps=[
            {
                "name": "现场检查",
                "node_type": "manual",
                "owner_user_id": str(creator.id),
            },
            {
                "name": "发送复核提醒",
                "node_type": "project_chat_message",
                "action": {
                    "type": "project_chat_message",
                    "channel_id": channel.id,
                    "sender_agent_id": "task-agent",
                    "sender_agent_name": "任务智能体",
                    "mention_mode": "users",
                    "mentioned_user_ids": [receiver.id],
                    "content": "请复核刚完成的现场检查。",
                },
            },
            {
                "name": "负责人复核",
                "node_type": "manual",
                "owner_user_id": str(receiver.id),
            },
        ],
    )

    created = api.create_task(
        project.id,
        payload,
        platform_db,
        creator,
    )["data"]

    assert platform_db.scalar(select(func.count(ChatMessage.id))) == 0
    progressed = api.update_task_step(
        created["id"],
        0,
        TaskStepUpdate(status="completed", note="现场检查完成"),
        platform_db,
        creator,
    )["data"]

    assert [step["status"] for step in progressed["workflow_steps"]] == [
        "completed",
        "completed",
        "processing",
    ]
    assert progressed["workflow_steps"][1]["node_type"] == "project_chat_message"
    assert progressed["workflow_steps"][1]["action"]["sender_agent_id"] == "task-agent"
    assert progressed["workflow_steps"][2]["owner_user_id"] == str(receiver.id)

    message = platform_db.scalar(select(ChatMessage))
    assert message is not None
    assert message.sender_type == "agent"
    assert message.sender_agent_id == "task-agent"
    assert message.metadata_json["agent_name"] == "任务智能体"
    assert message.metadata_json["task_engine_step_seq"] == 1
    assert message.content == f"@{receiver.real_name} 请复核刚完成的现场检查。"

    task = reference_engine.get_task(created["id"])
    assert task is not None
    assert task.current_step is not None
    assert task.current_step.seq == 2
    assert task.current_step.assignee == Assignee(
        ref=str(receiver.id),
        display_name=receiver.real_name,
    )


def test_private_message_automation_respects_channel_membership(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, non_member, _ = responsibility_context
    channel = ChatChannel(
        project_id=project.id,
        created_by_user_id=creator.id,
        title="仅创建人可见的私聊",
        channel_type="private",
    )
    platform_db.add(channel)
    platform_db.flush()
    platform_db.add(
        ChatChannelMember(
            channel_id=channel.id,
            user_id=creator.id,
            member_role="owner",
        ),
    )
    platform_db.commit()
    reference_engine = TaskEngine(tmp_path / "message-private.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    payload = TaskInput(
        title="私聊提醒",
        task_type="automation",
        action_type="project_chat_message",
        run_mode="once",
        trigger_date="2026-08-25",
        trigger_time="10:00",
        target_channel_id=channel.id,
        mention_mode="none",
        message_content="仅私聊成员可见。",
    )

    with pytest.raises(HTTPException) as invisible_error:
        api.create_task(
            project.id,
            payload,
            platform_db,
            non_member,
        )
    assert invisible_error.value.status_code == 422
    assert invisible_error.value.detail == "目标私聊对当前用户不可见"

    with pytest.raises(HTTPException) as recipient_error:
        api.create_task(
            project.id,
            payload.model_copy(
                update={
                    "mention_mode": "users",
                    "mentioned_user_ids": [non_member.id],
                },
            ),
            platform_db,
            creator,
        )
    assert recipient_error.value.status_code == 422
    assert recipient_error.value.detail == "消息接收人必须是目标群聊的当前成员"
