"""调度与服务门面的测试。

重点是 tick 的幂等性：重复调用绝不能重复创建任务。这是整个引擎最容易出错、
后果也最严重的地方——重复布置任务会直接骚扰到真实的人。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from task_engine.domain.models import (
    Assignee,
    IntervalUnit,
    RunMode,
    Site,
    StepSpec,
    TaskFlow,
    TaskState,
    Trigger,
)
from task_engine.engine import TaskEngine

TZ = ZoneInfo("Asia/Shanghai")
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=TZ)

ZHANG = Assignee(ref="u1", display_name="张三")
LI = Assignee(ref="u2", display_name="李四")
BOSS = Assignee(ref="boss", display_name="项目经理")
SITE = Site(ref="wbs-3", name="3号楼-地下室", code="WBS-03-B1")


@pytest.fixture
def engine(tmp_path):
    with TaskEngine(tmp_path / "engine.db") as eng:
        yield eng


def make_flow(**overrides) -> TaskFlow:
    defaults = dict(
        title="每周监测复核",
        steps=(
            StepSpec(name="采集", assignee=ZHANG, due_offset_days=1),
            StepSpec(name="复核", assignee=LI, due_offset_days=1),
        ),
        site=SITE,
        confirmer=BOSS,
    )
    defaults.update(overrides)
    return TaskFlow(**defaults)


def weekly(first_at=T0) -> Trigger:
    return Trigger(
        run_mode=RunMode.RECURRING,
        first_at=first_at,
        interval_value=1,
        interval_unit=IntervalUnit.WEEK,
    )


class TestDispatch:
    def test_creates_running_task(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        assert task.state is TaskState.RUNNING
        assert engine.get_task(task.id) is not None

    def test_flow_is_persisted_too(self, engine):
        flow = make_flow()
        engine.dispatch(flow, now=T0)
        assert engine.get_flow(flow.id) is not None


class TestScheduleRegistration:
    def test_next_fire_is_first_at(self, engine):
        plan = engine.schedule(make_flow(), trigger=weekly(), now=T0)
        assert plan.next_fire_at == T0

    def test_requires_first_at(self, engine):
        with pytest.raises(ValueError, match="首次执行时间"):
            engine.schedule(make_flow(), trigger=Trigger(), now=T0)

    def test_pause_and_resume(self, engine):
        plan = engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.pause_schedule(plan.id)
        assert engine.get_schedule(plan.id).paused is True

        engine.pause_schedule(plan.id, paused=False)
        assert engine.get_schedule(plan.id).paused is False

    def test_cancel_deactivates(self, engine):
        plan = engine.schedule(make_flow(), trigger=weekly(), now=T0)
        assert engine.cancel_schedule(plan.id) is True
        reloaded = engine.get_schedule(plan.id)
        assert reloaded.active is False
        assert reloaded.next_fire_at is None


class TestTickFiring:
    def test_fires_due_schedule(self, engine):
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        report = engine.tick(now=T0)

        assert report.created_count == 1
        assert len(engine.list_tasks()) == 1

    def test_does_not_fire_before_time(self, engine):
        engine.schedule(make_flow(), trigger=weekly(first_at=T0 + timedelta(days=5)), now=T0)
        report = engine.tick(now=T0)

        assert report.created_count == 0
        assert engine.list_tasks() == []

    def test_advances_to_next_occurrence(self, engine):
        plan = engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.tick(now=T0)

        reloaded = engine.get_schedule(plan.id)
        assert reloaded.fire_count == 1
        assert reloaded.next_fire_at == T0 + timedelta(weeks=1)

    def test_fires_again_next_week(self, engine):
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.tick(now=T0)
        engine.tick(now=T0 + timedelta(weeks=1))

        assert len(engine.list_tasks()) == 2

    def test_once_schedule_deactivates_after_firing(self, engine):
        trigger = Trigger(run_mode=RunMode.ONCE, first_at=T0)
        plan = engine.schedule(make_flow(), trigger=trigger, now=T0)
        engine.tick(now=T0)

        reloaded = engine.get_schedule(plan.id)
        assert reloaded.active is False
        assert reloaded.next_fire_at is None

    def test_paused_schedule_does_not_fire(self, engine):
        plan = engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.pause_schedule(plan.id)
        report = engine.tick(now=T0 + timedelta(days=1))

        assert report.created_count == 0

    def test_task_carries_trigger_note(self, engine):
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.tick(now=T0)
        task = engine.list_tasks()[0]
        assert "自动布置" in task.trigger_note


class TestTickIdempotency:
    """重复 tick 绝不能重复创建任务——这是最重要的不变量。"""

    def test_repeated_tick_same_moment(self, engine):
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.tick(now=T0)
        report = engine.tick(now=T0)

        assert report.created_count == 0
        assert len(engine.list_tasks()) == 1

    def test_many_ticks_between_occurrences(self, engine):
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        for hours in range(0, 24 * 6, 6):  # 每 6 小时 tick 一次，持续 6 天
            engine.tick(now=T0 + timedelta(hours=hours))

        # 一周内只应产生一个任务
        assert len(engine.list_tasks()) == 1

    def test_downtime_does_not_backfill(self, engine):
        """停机数周后重启，不应补跑所有错过的触发。"""
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        engine.tick(now=T0 + timedelta(weeks=5))

        # 只触发一次，然后跳到未来
        assert len(engine.list_tasks()) == 1

    def test_downtime_does_not_storm_on_repeated_ticks(self, engine):
        """停机后连续 tick 不应逐次补跑历史触发。

        曾经的缺陷：推进下次触发时以「本次触发时刻」为基准，导致 next_fire_at 仍在过去，
        于是每次 tick 都补一个历史触发——停机 200 天就是 200 条通知轰炸责任人。
        """
        trigger = Trigger(
            run_mode=RunMode.RECURRING, first_at=T0,
            interval_value=1, interval_unit=IntervalUnit.DAY,
        )
        plan = engine.schedule(make_flow(), trigger=trigger, now=T0)

        restart = T0 + timedelta(days=200)
        for _ in range(60):
            engine.tick(now=restart)

        assert len(engine.list_tasks()) == 1, "停机期间错过的触发应跳过，而非逐个补发"
        reloaded = engine.get_schedule(plan.id)
        assert reloaded.next_fire_at > restart, "下次触发必须落在未来"

    def test_clock_going_backwards_does_not_duplicate(self, engine):
        """系统时钟回拨（如 NTP 校时）不应重复创建任务。"""
        trigger = Trigger(
            run_mode=RunMode.RECURRING, first_at=T0,
            interval_value=1, interval_unit=IntervalUnit.DAY,
        )
        engine.schedule(make_flow(), trigger=trigger, now=T0)

        engine.tick(now=T0 + timedelta(days=4))
        before = len(engine.list_tasks())
        engine.tick(now=T0 + timedelta(days=1))  # 时间倒流
        assert len(engine.list_tasks()) == before

    def test_max_fires_respected(self, engine):
        trigger = Trigger(
            run_mode=RunMode.RECURRING, first_at=T0,
            interval_value=1, interval_unit=IntervalUnit.DAY, max_fires=3,
        )
        engine.schedule(make_flow(), trigger=trigger, now=T0)
        for day in range(10):
            engine.tick(now=T0 + timedelta(days=day))

        assert len(engine.list_tasks()) == 3


class TestTickOverdue:
    def test_marks_overdue_tasks(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        report = engine.tick(now=T0 + timedelta(days=10))

        assert task.id in report.overdue_task_ids
        assert engine.get_task(task.id).state is TaskState.OVERDUE

    def test_does_not_remark(self, engine):
        engine.dispatch(make_flow(), now=T0)
        engine.tick(now=T0 + timedelta(days=10))
        report = engine.tick(now=T0 + timedelta(days=11))

        assert report.overdue_task_ids == []

    def test_closed_tasks_untouched(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        engine.cancel_task(task.id, now=T0)
        report = engine.tick(now=T0 + timedelta(days=30))

        assert report.overdue_task_ids == []


class TestTaskOperations:
    def test_complete_advances(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        updated = engine.complete_step(task.id, 0, actor="u1", now=T0)
        assert updated.current_step.seq == 1

    def test_full_lifecycle(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        engine.complete_step(task.id, 0, actor="u1", now=T0)
        engine.complete_step(task.id, 1, actor="u2", now=T0)

        assert engine.get_task(task.id).state is TaskState.REVIEW
        engine.accept(task.id, actor="boss", now=T0)
        assert engine.get_task(task.id).state is TaskState.DONE

    def test_forward_changes_assignee(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        updated = engine.forward_step(task.id, 0, to=LI, actor="u1", now=T0)
        assert updated.steps[0].assignee == LI

    def test_reject_reopens(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        engine.complete_step(task.id, 0, now=T0)
        engine.complete_step(task.id, 1, now=T0)
        updated = engine.reject(task.id, reason="材料不全", now=T0)

        assert updated.state is TaskState.RUNNING

    def test_block_and_unblock(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        engine.block_step(task.id, 0, reason="等材料", now=T0)
        assert engine.get_task(task.id).state is TaskState.BLOCKED

        engine.unblock_step(task.id, 0, now=T0)
        assert engine.get_task(task.id).state is TaskState.RUNNING

    def test_note_recorded(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        updated = engine.add_note(task.id, note="现场已确认", actor="u1", now=T0)
        assert any("现场已确认" in act.summary for act in updated.activities)

    def test_missing_task_raises(self, engine):
        with pytest.raises(KeyError, match="不存在"):
            engine.complete_step("task_missing", 0, now=T0)


class TestMyTasks:
    def test_lists_by_current_assignee(self, engine):
        engine.dispatch(make_flow(), now=T0)
        assert len(engine.list_tasks(assignee="u1")) == 1
        assert len(engine.list_tasks(assignee="u2")) == 0

    def test_moves_to_next_person_on_completion(self, engine):
        task = engine.dispatch(make_flow(), now=T0)
        engine.complete_step(task.id, 0, now=T0)

        assert len(engine.list_tasks(assignee="u1")) == 0
        assert len(engine.list_tasks(assignee="u2")) == 1


class TestTickReport:
    def test_describes_results(self, engine):
        engine.schedule(make_flow(), trigger=weekly(), now=T0)
        report = engine.tick(now=T0)
        assert "触发 1 个任务" in report.describe()

    def test_empty_tick_is_harmless(self, engine):
        report = engine.tick(now=T0)
        assert report.created_count == 0
        assert report.overdue_task_ids == []
