"""触发时间计算的测试。

重点覆盖月末溢出与漂移——这是日程类逻辑最常见的错误来源。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from task_engine.domain.models import IntervalUnit, RunMode, Trigger
from task_engine.domain.trigger import (
    add_interval,
    add_months,
    due_dates_for_steps,
    next_fire_after,
    nth_fire_at,
)

TZ = ZoneInfo("Asia/Shanghai")


def dt(year: int, month: int, day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class TestAddMonths:
    def test_normal_month(self):
        assert add_months(dt(2026, 3, 15), 1) == dt(2026, 4, 15)

    def test_month_end_clamps_to_february(self):
        # 1月31日 + 1个月 应落在 2月28日，而不是滑到 3月3日
        assert add_months(dt(2026, 1, 31), 1) == dt(2026, 2, 28)

    def test_leap_year_february(self):
        assert add_months(dt(2028, 1, 31), 1) == dt(2028, 2, 29)

    def test_crosses_year_boundary(self):
        assert add_months(dt(2026, 11, 30), 3) == dt(2027, 2, 28)

    def test_thirty_one_to_thirty_day_month(self):
        assert add_months(dt(2026, 5, 31), 1) == dt(2026, 6, 30)

    def test_preserves_time_of_day(self):
        result = add_months(dt(2026, 1, 31, 14, 30), 1)
        assert (result.hour, result.minute) == (14, 30)


class TestAddInterval:
    @pytest.mark.parametrize(
        ("unit", "value", "expected"),
        [
            (IntervalUnit.HOUR, 5, dt(2026, 3, 15, 14)),
            (IntervalUnit.DAY, 3, dt(2026, 3, 18)),
            (IntervalUnit.WEEK, 2, dt(2026, 3, 29)),
            (IntervalUnit.MONTH, 1, dt(2026, 4, 15)),
        ],
    )
    def test_each_unit(self, unit, value, expected):
        assert add_interval(dt(2026, 3, 15), value, unit) == expected


class TestNoMonthlyDrift:
    """按月重复时，日期必须锚定首次触发日，不能逐月漂移。"""

    def test_month_end_series_recovers(self):
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=dt(2026, 1, 31),
            interval_value=1,
            interval_unit=IntervalUnit.MONTH,
        )
        # 2月被夹到28日，但3月必须回到31日——若在上次结果上迭代就会一直停在28日
        assert nth_fire_at(trigger, 0) == dt(2026, 1, 31)
        assert nth_fire_at(trigger, 1) == dt(2026, 2, 28)
        assert nth_fire_at(trigger, 2) == dt(2026, 3, 31)
        assert nth_fire_at(trigger, 3) == dt(2026, 4, 30)
        assert nth_fire_at(trigger, 4) == dt(2026, 5, 31)


class TestNextFireAfter:
    def test_once_before_firing(self):
        trigger = Trigger(run_mode=RunMode.ONCE, first_at=dt(2026, 3, 15))
        assert next_fire_after(trigger, after=None, fire_count=0) == dt(2026, 3, 15)

    def test_once_after_firing_is_exhausted(self):
        trigger = Trigger(run_mode=RunMode.ONCE, first_at=dt(2026, 3, 15))
        assert next_fire_after(trigger, after=dt(2026, 3, 15), fire_count=1) is None

    def test_recurring_advances(self):
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=dt(2026, 3, 2),
            interval_value=1,
            interval_unit=IntervalUnit.WEEK,
        )
        assert next_fire_after(trigger, after=dt(2026, 3, 2), fire_count=1) == dt(2026, 3, 9)

    def test_recovers_after_long_downtime(self):
        # 停机数月后重启，应跳到当前之后的下一次，而不是补跑历史
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=dt(2026, 1, 5),
            interval_value=1,
            interval_unit=IntervalUnit.WEEK,
        )
        result = next_fire_after(trigger, after=dt(2026, 3, 20), fire_count=1)
        assert result is not None
        assert result > dt(2026, 3, 20)
        assert result == dt(2026, 3, 23)  # 1/5 起每周一，3/20 之后是 3/23

    def test_max_fires_exhausts(self):
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=dt(2026, 3, 2),
            interval_value=1,
            interval_unit=IntervalUnit.DAY,
            max_fires=3,
        )
        assert next_fire_after(trigger, after=dt(2026, 3, 3), fire_count=3) is None

    def test_until_bound_stops_series(self):
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=dt(2026, 3, 2),
            interval_value=1,
            interval_unit=IntervalUnit.WEEK,
            until=dt(2026, 3, 10),
        )
        # 3/9 在界内
        assert next_fire_after(trigger, after=dt(2026, 3, 2), fire_count=1) == dt(2026, 3, 9)
        # 3/16 越界
        assert next_fire_after(trigger, after=dt(2026, 3, 9), fire_count=2) is None

    def test_missing_first_at_yields_none(self):
        assert next_fire_after(Trigger(), after=None, fire_count=0) is None


class TestTriggerValidation:
    def test_recurring_rejects_non_positive_interval(self):
        with pytest.raises(ValueError, match="正整数"):
            Trigger(run_mode=RunMode.RECURRING, first_at=dt(2026, 3, 2), interval_value=0)

    def test_describe_once(self):
        trigger = Trigger(run_mode=RunMode.ONCE, first_at=dt(2026, 3, 15, 9, 0))
        assert trigger.describe() == "2026-03-15 09:00 执行一次"

    def test_describe_recurring(self):
        trigger = Trigger(
            run_mode=RunMode.RECURRING,
            first_at=dt(2026, 3, 15, 9, 0),
            interval_value=2,
            interval_unit=IntervalUnit.WEEK,
        )
        assert "每 2 周执行一次" in trigger.describe()


class TestStepDeadlines:
    def test_offsets_accumulate(self):
        result = due_dates_for_steps(dt(2026, 3, 2), [1, 2, 1])
        assert result == [dt(2026, 3, 3), dt(2026, 3, 5), dt(2026, 3, 6)]

    def test_zero_offset_keeps_same_moment(self):
        result = due_dates_for_steps(dt(2026, 3, 2), [0, 1])
        assert result == [dt(2026, 3, 2), dt(2026, 3, 3)]

    def test_negative_offset_treated_as_zero(self):
        result = due_dates_for_steps(dt(2026, 3, 2), [-5, 1])
        assert result == [dt(2026, 3, 2), dt(2026, 3, 3)]
