from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import api
from backend.app.db import Base
from backend.app.models import Project, ProjectMember, User, WbsItem
from backend.app.schemas import TaskInput, TaskStepUpdate, TaskTransitionInput
from task_engine.domain.models import (
    Assignee,
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
