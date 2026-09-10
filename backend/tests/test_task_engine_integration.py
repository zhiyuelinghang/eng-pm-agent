import asyncio
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
    BusinessLearningSource,
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
from task_engine.generator.llm import AIFlowGenerationError


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


def test_validation_b_only_current_owner_can_complete_step(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, responsible, confirmer, site = responsibility_context
    reference_engine = TaskEngine(tmp_path / "validation-b-owner.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)
    created = api.create_task(
        project.id,
        _task_payload(responsible, confirmer, site),
        platform_db,
        responsible,
    )["data"]

    with pytest.raises(HTTPException) as error:
        api.update_task_step(
            created["id"],
            0,
            TaskStepUpdate(
                status="completed",
                note="非负责人尝试完成",
                attachments=["现场照片.jpg"],
            ),
            platform_db,
            confirmer,
        )

    assert error.value.status_code == 409
    assert "只有节点负责人" in error.value.detail

    completed = api.update_task_step(
        created["id"],
        0,
        TaskStepUpdate(
            status="completed",
            note="负责人已完成",
            attachments=["现场照片.jpg"],
        ),
        platform_db,
        responsible,
    )["data"]
    assert completed["status"] == "pending_confirm"


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
    learning = list(platform_db.scalars(select(BusinessLearningSource).order_by(BusinessLearningSource.id)))
    assert [row.stage for row in learning] == ['task_published', 'task_accepted']
    assert learning[0].evidence[0]['outcome'] == 'confirmed'
    assert learning[1].evidence[0]['outcome'] == 'accepted'
    assert learning[1].actor_user_id == confirmer.id


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
    source = platform_db.scalar(select(BusinessLearningSource))
    assert source.stage == 'task_plan_confirmed'
    assert source.evidence[0]['outcome'] == 'confirmed'
    assert '尚不能证明任何任务已执行' in source.evidence[0]['text']
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


def test_dobby_project_chat_requirement_still_uses_ai_generator(
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    admin = User(
        username="admin-flow-test",
        password_hash="hash",
        role="admin",
        real_name="系统管理员",
        identity_card_no="ADMIN_FLOW_TEST",
    )

    platform_db.add(admin)
    platform_db.commit()
    fixed_now = datetime(2026, 8, 25, 16, 47, tzinfo=ZoneInfo("Asia/Shanghai"))
    requirement = "今天16:52在当前项目群提醒我补充项目资料"

    class FixedClock:
        @staticmethod
        def now() -> datetime:
            return fixed_now

    class StubAIGenerator:
        received_requirement = ""
        received_options: dict[str, object] = {}

        async def generate_async(
            self,
            supplied_requirement: str,
            **options: object,
        ) -> TaskFlow:
            self.received_requirement = supplied_requirement
            self.received_options = options
            action = {
                "type": "project_chat_message",
                "channel_id": channel.id,
                "sender_agent_id": "dobby-task-engine",
                "sender_agent_name": "Dobby",
                "mention_mode": "users",
                "mentioned_user_ids": [admin.id],
                "content": "请补充项目资料。",
                "created_by_user_id": admin.id,
            }
            return TaskFlow(
                title="AI 生成的群聊协同任务",
                summary="验证群聊需求仍由 AI 解析",
                category="automation",
                priority="normal",
                trigger=Trigger(run_mode=RunMode.ONCE, first_at=fixed_now + timedelta(minutes=5)),
                steps=(
                    StepSpec(
                        name="发送群内提醒",
                        due_offset_days=0,
                        instruction="请补充项目资料。",
                        automated=True,
                    ),
                ),
                origin="ai",
                origin_note="由测试 AI 生成",
                scope={
                    "execution_kind": "automation",
                    "action": action,
                    "step_actions": {"0": action},
                },
            )

    stub_generator = StubAIGenerator()
    monkeypatch.setattr(api, "get_engine", lambda: FixedClock())
    monkeypatch.setattr(api, "get_generator", lambda: stub_generator)
    result = asyncio.run(
        api.generate_task_flow(
            project.id,
            TaskFlowGenerateInput(requirement=requirement),
            platform_db,
            admin,
        ),
    )["data"]

    assert stub_generator.received_requirement == requirement
    context = stub_generator.received_options["context"]
    assert isinstance(context, dict)
    assert context["current_user"]["ref"] == str(admin.id)
    assert context["current_user"]["username"] == "admin-flow-test"
    assert "sender_agents" not in context
    assert any(item.ref == str(admin.id) for item in stub_generator.received_options["assignees"])
    project_channel = next(
        item for item in context["chat_channels"] if item["ref"] == str(channel.id)
    )
    assert str(admin.id) in project_channel["member_refs"]
    assert result["run_mode"] == "once"
    assert result["trigger_date"] == "2026-08-25"
    assert result["trigger_time"] == "16:52"
    assert result["generated_by"] == "ai"
    assert result["task_type"] == "automation"
    assert result["assignee_user_id"] is None
    assert len(result["steps"]) == 1
    assert result["steps"][0]["node_type"] == "project_chat_message"
    assert result["steps"][0]["action"]["channel_id"] == channel.id
    assert result["steps"][0]["action"]["mentioned_user_ids"] == [admin.id]


def test_dobby_generation_exposes_ai_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    fixed_now = datetime(2026, 8, 25, 16, 47, tzinfo=ZoneInfo("Asia/Shanghai"))

    class FixedClock:
        @staticmethod
        def now() -> datetime:
            return fixed_now

    class FailingAIGenerator:
        @staticmethod
        async def generate_async(*_: object, **__: object) -> TaskFlow:
            raise AIFlowGenerationError("Dobby AI 请求或响应解析失败（ReadTimeout）：读取超时")

    monkeypatch.setattr(api, "get_engine", lambda: FixedClock())
    monkeypatch.setattr(api, "get_generator", lambda: FailingAIGenerator())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api.generate_task_flow(
                project.id,
                TaskFlowGenerateInput(requirement="检查现场临边防护并完成复核归档"),
                platform_db,
                creator,
            ),
        )

    assert exc_info.value.status_code == 502
    assert "ReadTimeout" in str(exc_info.value.detail)


def test_dobby_generation_can_be_stopped_by_user(
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    fixed_now = datetime(2026, 8, 25, 16, 47, tzinfo=ZoneInfo("Asia/Shanghai"))
    generation_id = "test-generation-stop"

    class FixedClock:
        @staticmethod
        def now() -> datetime:
            return fixed_now

    async def scenario() -> None:
        started = asyncio.Event()

        class SlowAIGenerator:
            @staticmethod
            async def generate_async(*_: object, **__: object) -> TaskFlow:
                started.set()
                await asyncio.Event().wait()
                raise AssertionError("已停止的模型请求不应继续返回")

        monkeypatch.setattr(api, "get_engine", lambda: FixedClock())
        monkeypatch.setattr(api, "get_generator", lambda: SlowAIGenerator())

        generate_request = asyncio.create_task(
            api.generate_task_flow(
                project.id,
                TaskFlowGenerateInput(
                    requirement="检查现场临边防护并完成复核归档",
                    generation_id=generation_id,
                ),
                platform_db,
                creator,
            ),
        )
        await started.wait()

        stop_result = await api.stop_task_flow_generation(
            project.id,
            generation_id,
            platform_db,
            creator,
        )
        assert stop_result["data"]["stopped"] is True

        with pytest.raises(HTTPException) as exc_info:
            await generate_request
        assert exc_info.value.status_code == 409
        assert "停止" in str(exc_info.value.detail)
        assert (project.id, generation_id) not in api._active_task_flow_generations

    asyncio.run(scenario())


def test_dobby_stop_is_not_lost_when_it_arrives_before_generation(
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    generation_id = "test-stop-before-generation"
    generator_called = False

    class FixedClock:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 8, 25, 16, 47, tzinfo=ZoneInfo("Asia/Shanghai"))

    class UnexpectedAIGenerator:
        @staticmethod
        async def generate_async(*_: object, **__: object) -> TaskFlow:
            nonlocal generator_called
            generator_called = True
            raise AssertionError("提前到达的停止请求必须阻止模型调用")

    monkeypatch.setattr(api, "get_engine", lambda: FixedClock())
    monkeypatch.setattr(api, "get_generator", lambda: UnexpectedAIGenerator())

    async def scenario() -> None:
        stop_result = await api.stop_task_flow_generation(
            project.id,
            generation_id,
            platform_db,
            creator,
        )
        assert stop_result["data"]["stopped"] is True

        with pytest.raises(HTTPException) as exc_info:
            await api.generate_task_flow(
                project.id,
                TaskFlowGenerateInput(
                    requirement="检查现场临边防护并完成复核归档",
                    generation_id=generation_id,
                ),
                platform_db,
                creator,
            )
        assert exc_info.value.status_code == 409
        assert "停止" in str(exc_info.value.detail)

    asyncio.run(scenario())
    assert generator_called is False


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
                        "sender_agent_name": "Dobby",
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


def test_admin_can_schedule_project_group_message_mentioning_self(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    platform_db: Session,
    responsibility_context: tuple[Project, User, User, WbsItem],
) -> None:
    project, creator, _, _ = responsibility_context
    channel = _project_chat_channel(platform_db, project, creator)
    admin = User(
        username="admin-message-test",
        password_hash="hash",
        role="admin",
        real_name="系统管理员",
        identity_card_no="ADMIN_MESSAGE_TEST",
    )
    platform_db.add(admin)
    platform_db.commit()
    reference_engine = TaskEngine(tmp_path / "admin-self-message.db")
    monkeypatch.setattr(api, "get_engine", lambda: reference_engine)

    registered = api.create_task(
        project.id,
        TaskInput(
            title="提醒我补充项目资料",
            task_type="automation",
            action_type="project_chat_message",
            run_mode="once",
            trigger_date="2026-08-25",
            trigger_time="15:35",
            target_channel_id=channel.id,
            mention_mode="users",
            mentioned_user_ids=[admin.id],
            message_content="请补充项目资料。",
        ),
        platform_db,
        admin,
    )["data"]
    plan = reference_engine.get_schedule(registered["schedule_id"])
    assert plan is not None and plan.next_fire_at is not None

    reference_engine.tick(now=plan.next_fire_at)
    results = execute_pending_automation_tasks(platform_db, reference_engine)

    assert len(results) == 1
    assert results[0].ok is True
    message = platform_db.scalar(select(ChatMessage))
    assert message is not None
    assert message.content == "@系统管理员 请补充项目资料。"
    membership = platform_db.scalar(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel.id,
            ChatChannelMember.user_id == admin.id,
            ChatChannelMember.left_at.is_(None),
        ),
    )
    assert membership is not None


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
    assert progressed["workflow_steps"][1]["action"]["sender_agent_id"] == "dobby-task-engine"
    assert progressed["workflow_steps"][1]["action"]["sender_agent_name"] == "Dobby"
    assert progressed["workflow_steps"][2]["owner_user_id"] == str(receiver.id)

    message = platform_db.scalar(select(ChatMessage))
    assert message is not None
    assert message.sender_type == "agent"
    assert message.sender_agent_id == "dobby-task-engine"
    assert message.metadata_json["agent_name"] == "Dobby"
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


def test_generated_task_without_binding_cannot_be_learned_as_manual(tmp_path,monkeypatch,platform_db,responsibility_context):
    project,responsible,confirmer,site=responsibility_context
    reference_engine=TaskEngine(tmp_path/'unknown-origin.db')
    monkeypatch.setattr(api,'get_engine',lambda:reference_engine)
    payload=_task_payload(responsible,confirmer,site).model_copy(update={'generation_id':'missing-generation'})
    result=api.create_task(project.id,payload,platform_db,responsible)
    source=platform_db.scalar(select(BusinessLearningSource))
    assert source.allow_learning is False
    assert reference_engine.get_task(result['data']['id']).scope['learning_policy']['allow_learning'] is False


def test_signed_generation_policy_survives_real_create_route(tmp_path,monkeypatch,platform_db,responsibility_context):
    from backend.app.models import AgentConversation
    from backend.app import business_learning_policy as policy
    project,responsible,confirmer,site=responsibility_context
    conversation=AgentConversation(project_id=project.id,user_id=responsible.id,agent_id='task-assistant',agent_name='任务助手',
        conversation_type='task_editor',generation_id='generated-draft',agentscope_session_id='actual-session',status='completed',title='实际生成')
    platform_db.add(conversation)
    platform_db.commit()
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:[{'tenant_id':'projectcopilot','run_id':'actual-run',
        'root_session_id':'actual-session','root_agent_id':'task-assistant','state':'completed','no_memory':False,'no_learning':True}])
    token=policy.generation_origin_token(conversation)
    reference_engine=TaskEngine(tmp_path/'bound-origin.db')
    monkeypatch.setattr(api,'get_engine',lambda:reference_engine)
    payload=_task_payload(responsible,confirmer,site).model_copy(update={'generation_id':'generated-draft','generation_origin_token':token})
    result=api.create_task(project.id,payload,platform_db,responsible)
    source=platform_db.scalar(select(BusinessLearningSource))
    assert source.allow_learning is False
    assert source.source_run_refs[0]['run_id']=='actual-run'
    assert reference_engine.get_task(result['data']['id']).scope['learning_policy']['source_run_refs']==source.source_run_refs
