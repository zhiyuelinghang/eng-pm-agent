"""触发时间计算。

全部是纯函数：给定触发规则与当前时刻，算出下一次该在什么时候执行。不读时钟、不碰
存储，因此可以完全用测试锁死行为——尤其是月末与夏令时这类边界。
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import IntervalUnit, Trigger


def add_months(moment: datetime, months: int) -> datetime:
    """按"月"推进，并把溢出的日期夹到当月最后一天。

    日历上的"一个月后"没有统一定义。这里采用与人的直觉一致的做法：
    1月31日 + 1个月 = 2月28日（闰年为 29 日），而不是滑到 3月 3日。

    注意这个操作不可逆：1/31 前进一个月到 2/28，再退回来是 1/28。重复触发时始终从
    首次触发时间累加计算，而非在上次结果上迭代，以免日期逐月漂移。
    """
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def add_interval(moment: datetime, value: int, unit: IntervalUnit) -> datetime:
    """在给定时刻上加 value 个 unit。"""
    match unit:
        case IntervalUnit.HOUR:
            return moment + timedelta(hours=value)
        case IntervalUnit.DAY:
            return moment + timedelta(days=value)
        case IntervalUnit.WEEK:
            return moment + timedelta(weeks=value)
        case IntervalUnit.MONTH:
            return add_months(moment, value)
    raise ValueError(f"不支持的间隔单位：{unit}")


def nth_fire_at(trigger: Trigger, n: int) -> datetime | None:
    """第 n 次触发的时刻（n 从 0 开始）。

    始终以 first_at 为基准累加，避免逐次迭代带来的日期漂移：
    1/31 按月重复，得到的是 2/28、3/31、4/30，而不是 2/28、3/28、4/28。
    """
    if trigger.first_at is None:
        return None
    if n == 0:
        return trigger.first_at
    if not trigger.is_recurring:
        return None
    return add_interval(trigger.first_at, trigger.interval_value * n, trigger.interval_unit)


def next_fire_after(
    trigger: Trigger,
    after: datetime | None = None,
    fire_count: int = 0,
) -> datetime | None:
    """算出严格晚于 `after` 的下一次触发时刻。

    返回 None 表示计划已终结——一次性任务已触发过，或重复任务已达 max_fires / until。

    `fire_count` 是已经触发的次数，用于判断 max_fires 是否耗尽。当 `after` 为 None 时，
    直接返回第 fire_count 次的时刻（即"还没开始，下一次就是首次"）。
    """
    if trigger.first_at is None:
        return None

    # 次数已用尽
    if trigger.max_fires is not None and fire_count >= trigger.max_fires:
        return None

    if after is None:
        candidate = nth_fire_at(trigger, fire_count)
        return _within_bounds(trigger, candidate)

    # 一次性任务：触发过就结束
    if not trigger.is_recurring:
        return None if trigger.first_at <= after else trigger.first_at

    # 重复任务：从 fire_count 往后找第一个晚于 after 的时刻。
    # 正常情况下一两步就能命中；补偿长时间停机时才会多走几步。
    n = fire_count
    while True:
        candidate = nth_fire_at(trigger, n)
        if candidate is None:
            return None
        if candidate > after:
            return _within_bounds(trigger, candidate)
        n += 1
        if trigger.max_fires is not None and n >= trigger.max_fires:
            return None
        # 防御：间隔异常导致时间不前进时兜底退出
        if n > 100_000:
            raise RuntimeError("触发时间计算未收敛，请检查间隔配置")


def _within_bounds(trigger: Trigger, candidate: datetime | None) -> datetime | None:
    """检查候选时刻是否越过了 until 边界。"""
    if candidate is None:
        return None
    if trigger.until is not None and candidate > trigger.until:
        return None
    return candidate


def due_dates_for_steps(
    start: datetime,
    offsets: list[int],
) -> list[datetime]:
    """由任务开始时刻与各节点的偏移天数，算出每个节点的截止时刻。

    偏移是累进的：节点按顺序执行，后一个节点的截止时间不会早于前一个。
    """
    deadlines: list[datetime] = []
    cursor = start
    for offset in offsets:
        cursor = max(cursor + timedelta(days=max(offset, 0)), cursor)
        deadlines.append(cursor)
    return deadlines


def localize(moment: datetime, timezone: str) -> datetime:
    """给 naive 时间挂上时区；已带时区的原样返回。

    引擎内部统一用带时区的时间，避免跨时区部署时的隐性错误。
    """
    if moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=ZoneInfo(timezone))


def ensure_aware(moment: datetime | None, timezone: str = "Asia/Shanghai") -> datetime | None:
    if moment is None:
        return None
    return localize(moment, timezone)
