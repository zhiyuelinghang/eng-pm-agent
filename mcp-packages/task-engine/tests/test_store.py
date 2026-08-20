"""存储层测试：领域对象与数据库之间的往返必须无损。"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from task_engine.domain.flow import complete_step, forward_step, instantiate
from task_engine.domain.models import (
    Assignee,
    IntervalUnit,
    RunMode,
    Schedule,
    Site,
    StepSpec,
    StepState,
    TaskFlow,
    TaskState,
    Trigger,
)
from task_engine.store.sqlite import Store

TZ = ZoneInfo("Asia/Shanghai")
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=TZ)

ZHANG = Assignee(ref="u1", display_name="张三")
LI = Assignee(ref="u2", display_name="李四")
BOSS = Assignee(ref="boss", display_name="项目经理")
SITE = Site(ref="wbs-3", name="3号楼-地下室", code="WBS-03-B1")


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def make_flow(**overrides) -> TaskFlow:
    defaults = dict(
        title="基坑监测复核",
        summary="每周核查监测数据",
        category="monitoring",
        steps=(
            StepSpec(name="采集数据", assignee=ZHANG, due_offset_days=1, deliverable="监测记录"),
            StepSpec(name="复核", assignee=LI, due_offset_days=2, requires_attachment=True),
        ),
        site=SITE,
        confirmer=BOSS,
        watchers=(Assignee(ref="u9", display_name="项目经理"),),
        tags=("监测", "周期"),
        scope={"project_id": "p1"},
    )
    defaults.update(overrides)
    return TaskFlow(**defaults)


class TestFlowRoundTrip:
    def test_saves_and_reads_back(self, store):
        flow = make_flow()
        store.save_flow(flow, T0)
        loaded = store.get_flow(flow.id)

        assert loaded is not None
        assert loaded.title == flow.title
        assert loaded.summary == flow.summary
        assert loaded.category == flow.category
        assert len(loaded.steps) == 2

    def test_step_details_survive(self, store):
        flow = make_flow()
        store.save_flow(flow, T0)
        loaded = store.get_flow(flow.id)

        assert loaded.steps[0].assignee == ZHANG
        assert loaded.steps[0].deliverable == "监测记录"
        assert loaded.steps[1].requires_attachment is True

    def test_trigger_survives(self, store):
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=T0,
            interval_value=2,
            interval_unit=IntervalUnit.WEEK,
            max_fires=10,
        )
        flow = make_flow(trigger=trigger)
        store.save_flow(flow, T0)
        loaded = store.get_flow(flow.id)

        assert loaded.trigger.run_mode is RunMode.RECURRING
        assert loaded.trigger.first_at == T0
        assert loaded.trigger.interval_value == 2
        assert loaded.trigger.interval_unit is IntervalUnit.WEEK
        assert loaded.trigger.max_fires == 10

    def test_watchers_and_tags_survive(self, store):
        flow = make_flow()
        store.save_flow(flow, T0)
        loaded = store.get_flow(flow.id)

        assert len(loaded.watchers) == 1
        assert loaded.watchers[0].display_name == "项目经理"
        assert loaded.tags == ("监测", "周期")
        assert loaded.scope == {"project_id": "p1"}

    def test_save_is_idempotent(self, store):
        flow = make_flow()
        store.save_flow(flow, T0)
        store.save_flow(flow, T0)
        assert len(store.list_flows()) == 1

    def test_list_filters_by_category(self, store):
        store.save_flow(make_flow(), T0)
        store.save_flow(make_flow(title="别的流程", category="safety"), T0)

        assert len(store.list_flows(category="monitoring")) == 1
        assert len(store.list_flows()) == 2

    def test_missing_flow_returns_none(self, store):
        assert store.get_flow("flow_nonexistent") is None


class TestTaskRoundTrip:
    def test_saves_and_reads_back(self, store):
        task = instantiate(make_flow(), T0)
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert loaded is not None
        assert loaded.title == task.title
        assert loaded.state is TaskState.RUNNING
        assert len(loaded.steps) == 2

    def test_step_state_survives(self, store):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0, actor="u1", comment="已采集")
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert loaded.steps[0].state is StepState.DONE
        assert loaded.steps[0].comment == "已采集"
        assert loaded.steps[0].finished_by == "u1"
        assert loaded.steps[1].state is StepState.ACTIVE

    def test_attachments_survive(self, store):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0, attachments=["a.jpg", "b.pdf"])
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert loaded.steps[0].attachments == ["a.jpg", "b.pdf"]

    def test_activities_survive_in_order(self, store):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0 + timedelta(hours=1))
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert len(loaded.activities) == len(task.activities)
        assert [a.kind for a in loaded.activities] == [a.kind for a in task.activities]

    def test_repeated_save_does_not_duplicate_activities(self, store):
        task = instantiate(make_flow(), T0)
        store.save_task(task)
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert len(loaded.activities) == len(task.activities)

    def test_current_step_after_reload(self, store):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0)
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert loaded.current_step.seq == 1
        assert loaded.current_assignee == LI

    def test_forward_survives(self, store):
        task = instantiate(make_flow(), T0)
        forward_step(task, 0, to=LI, now=T0)
        store.save_task(task)
        loaded = store.get_task(task.id)

        assert loaded.steps[0].assignee == LI


class TestTaskQueries:
    def test_filters_by_assignee(self, store):
        task_a = instantiate(make_flow(), T0)
        task_b = instantiate(
            make_flow(steps=(StepSpec(name="别的活", assignee=LI),)), T0,
        )
        store.save_task(task_a)
        store.save_task(task_b)

        mine = store.list_tasks(assignee="u1")
        assert [t.id for t in mine] == [task_a.id]

    def test_assignee_follows_active_step(self, store):
        """完成首节点后，任务应从张三的列表移到李四的列表。"""
        task = instantiate(make_flow(), T0)
        store.save_task(task)
        assert len(store.list_tasks(assignee="u1")) == 1

        complete_step(task, 0, now=T0)
        store.save_task(task)

        assert len(store.list_tasks(assignee="u1")) == 0
        assert len(store.list_tasks(assignee="u2")) == 1

    def test_filters_by_state(self, store):
        task = instantiate(make_flow(), T0)
        store.save_task(task)
        assert len(store.list_tasks(state="running")) == 1
        assert len(store.list_tasks(state="done")) == 0

    def test_open_only_excludes_closed(self, store):
        from task_engine.domain.flow import cancel

        task = instantiate(make_flow(), T0)
        cancel(task, now=T0)
        store.save_task(task)

        assert len(store.list_tasks(open_only=True)) == 0
        assert len(store.list_tasks()) == 1

    def test_pagination(self, store):
        for index in range(5):
            store.save_task(instantiate(make_flow(title=f"任务{index}"), T0))

        page1 = store.list_tasks(limit=2, offset=0)
        page2 = store.list_tasks(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {t.id for t in page1}.isdisjoint({t.id for t in page2})

    def test_count(self, store):
        store.save_task(instantiate(make_flow(), T0))
        store.save_task(instantiate(make_flow(), T0))
        assert store.count_tasks() == 2
        assert store.count_tasks(open_only=True) == 2

    def test_overdue_candidates(self, store):
        task = instantiate(make_flow(), T0)
        store.save_task(task)

        assert store.overdue_candidates(T0 + timedelta(hours=1)) == []
        candidates = store.overdue_candidates(T0 + timedelta(days=30))
        assert len(candidates) == 1

    def test_delete(self, store):
        task = instantiate(make_flow(), T0)
        store.save_task(task)
        assert store.delete_task(task.id) is True
        assert store.get_task(task.id) is None


class TestScheduleRoundTrip:
    def test_saves_and_reads_back(self, store):
        flow = make_flow(
            trigger=Trigger(run_mode=RunMode.RECURRING, first_at=T0, interval_unit=IntervalUnit.WEEK),
        )
        schedule = Schedule(flow=flow, next_fire_at=T0, created_at=T0)
        store.save_schedule(schedule, T0)
        loaded = store.get_schedule(schedule.id)

        assert loaded is not None
        assert loaded.next_fire_at == T0
        assert loaded.flow.id == flow.id
        assert loaded.active is True

    def test_due_schedules_respects_time(self, store):
        flow = make_flow()
        schedule = Schedule(flow=flow, next_fire_at=T0 + timedelta(days=1), created_at=T0)
        store.save_schedule(schedule, T0)

        assert store.due_schedules(T0) == []
        assert len(store.due_schedules(T0 + timedelta(days=2))) == 1

    def test_paused_schedule_is_not_due(self, store):
        schedule = Schedule(flow=make_flow(), next_fire_at=T0, paused=True, created_at=T0)
        store.save_schedule(schedule, T0)
        assert store.due_schedules(T0 + timedelta(days=1)) == []

    def test_inactive_schedule_is_not_due(self, store):
        schedule = Schedule(flow=make_flow(), next_fire_at=T0, active=False, created_at=T0)
        store.save_schedule(schedule, T0)
        assert store.due_schedules(T0 + timedelta(days=1)) == []

    def test_delete_cascades_nothing_unexpected(self, store):
        schedule = Schedule(flow=make_flow(), next_fire_at=T0, created_at=T0)
        store.save_schedule(schedule, T0)
        assert store.delete_schedule(schedule.id) is True
        assert store.get_schedule(schedule.id) is None
        # 流程定义应当保留，可被其他计划复用
        assert store.get_flow(schedule.flow.id) is not None


class TestFireIdempotency:
    def test_first_claim_succeeds(self, store):
        assert store.claim_fire("sched_1", T0, T0) is True

    def test_second_claim_for_same_moment_fails(self, store):
        store.claim_fire("sched_1", T0, T0)
        assert store.claim_fire("sched_1", T0, T0) is False

    def test_different_moment_can_be_claimed(self, store):
        store.claim_fire("sched_1", T0, T0)
        assert store.claim_fire("sched_1", T0 + timedelta(days=7), T0) is True

    def test_release_allows_retry(self, store):
        store.claim_fire("sched_1", T0, T0)
        store.release_fire("sched_1", T0)
        assert store.claim_fire("sched_1", T0, T0) is True


class TestPersistenceAcrossConnections:
    def test_data_survives_reopen(self, tmp_path):
        db = tmp_path / "persist.db"
        with Store(db) as store:
            task = instantiate(make_flow(), T0)
            store.save_task(task)
            task_id = task.id

        with Store(db) as store:
            loaded = store.get_task(task_id)
            assert loaded is not None
            assert loaded.title == "基坑监测复核"
