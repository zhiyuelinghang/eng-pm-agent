"""服务门面：把领域逻辑、存储与调度编织成可调用的用例。

MCP 层与 CLI 层都只依赖这里，不直接碰 domain 或 store。这样协议层可以随意替换，
业务语义只有一份。

时间的处理：所有用例都接受可选的 `now`，缺省时取系统时钟。测试因此可以完全控制时间，
无需 mock。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .domain import flow as flow_ops
from .domain.models import (
    Assignee,
    Schedule,
    TaskFlow,
    TaskInstance,
    Trigger,
)
from .domain.trigger import next_fire_after
from .store.sqlite import Store

DEFAULT_TZ = "Asia/Shanghai"


@dataclass(slots=True)
class FireOutcome:
    """一次触发的结果。"""

    schedule_id: str
    fired_at: datetime
    task_id: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass(slots=True)
class TickReport:
    """一次 tick 的完整结果，供调用方展示或记录。"""

    at: datetime
    fired: list[FireOutcome] = field(default_factory=list)
    overdue_task_ids: list[str] = field(default_factory=list)
    skipped: int = 0  # 因幂等而跳过的重复触发

    @property
    def created_count(self) -> int:
        return sum(1 for item in self.fired if item.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.fired if not item.ok)

    def describe(self) -> str:
        parts = [f"触发 {self.created_count} 个任务"]
        if self.failed_count:
            parts.append(f"{self.failed_count} 个失败")
        if self.overdue_task_ids:
            parts.append(f"{len(self.overdue_task_ids)} 个标记逾期")
        if self.skipped:
            parts.append(f"{self.skipped} 个重复触发已跳过")
        return "，".join(parts)


class TaskEngine:
    """任务引擎的服务门面。"""

    def __init__(self, db_path: str | Path = "task_engine.db", *, timezone: str = DEFAULT_TZ) -> None:
        self.store = Store(db_path)
        self.timezone = timezone

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> TaskEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    # ---- 任务流定义 ----

    def save_flow(self, flow: TaskFlow, *, now: datetime | None = None) -> TaskFlow:
        self.store.save_flow(flow, now or self.now())
        return flow

    def get_flow(self, flow_id: str) -> TaskFlow | None:
        return self.store.get_flow(flow_id)

    def list_flows(self, *, category: str | None = None, limit: int = 100) -> list[TaskFlow]:
        return self.store.list_flows(category=category, limit=limit)

    # ---- 布置任务 ----

    def dispatch(
        self,
        flow: TaskFlow,
        *,
        now: datetime | None = None,
        actor: str = "system",
        trigger_note: str = "",
    ) -> TaskInstance:
        """立即布置一个任务：由任务流创建实例并激活首节点。"""
        moment = now or self.now()
        self.store.save_flow(flow, moment)
        task = flow_ops.instantiate(flow, moment, actor=actor, trigger_note=trigger_note)
        self.store.save_task(task)
        return task

    def schedule(
        self,
        flow: TaskFlow,
        *,
        trigger: Trigger | None = None,
        now: datetime | None = None,
    ) -> Schedule:
        """登记一个触发计划。

        这是引擎相对多数系统的关键增量——把「什么时候自动布置」变成可持久化的状态，
        而不是散落在提示文本里的一句话。
        """
        moment = now or self.now()
        if trigger is not None:
            flow = flow.with_trigger(trigger)

        if flow.trigger.first_at is None:
            raise ValueError("触发计划必须设置首次执行时间")

        plan = Schedule(
            flow=flow,
            next_fire_at=next_fire_after(flow.trigger, after=None, fire_count=0),
            created_at=moment,
            updated_at=moment,
        )
        self.store.save_schedule(plan, moment)
        return plan

    def list_schedules(self, *, active_only: bool = False) -> list[Schedule]:
        return self.store.list_schedules(active_only=active_only)

    def get_schedule(self, schedule_id: str) -> Schedule | None:
        return self.store.get_schedule(schedule_id)

    def pause_schedule(self, schedule_id: str, *, paused: bool = True) -> Schedule | None:
        plan = self.store.get_schedule(schedule_id)
        if plan is None:
            return None
        plan.paused = paused
        self.store.save_schedule(plan, self.now())
        return plan

    def cancel_schedule(self, schedule_id: str) -> bool:
        plan = self.store.get_schedule(schedule_id)
        if plan is None:
            return False
        plan.active = False
        plan.next_fire_at = None
        self.store.save_schedule(plan, self.now())
        return True

    # ---- 推进 ----

    def tick(self, *, now: datetime | None = None) -> TickReport:
        """推进引擎一步：触发到期计划，并扫描逾期任务。

        设计为拉模式——由外部定时调用（cron / 宿主定时器 / MCP 客户端），引擎自身不
        常驻。这让引擎无状态可重启，且触发时机对调用方完全透明。

        幂等：同一计划的同一触发时刻只会创建一次任务，重复调用安全。
        """
        moment = now or self.now()
        report = TickReport(at=moment)

        for plan in self.store.due_schedules(moment):
            fire_at = plan.next_fire_at
            if fire_at is None:
                continue

            # 抢占，防止重复触发
            if not self.store.claim_fire(plan.id, fire_at, moment):
                report.skipped += 1
                continue

            outcome = FireOutcome(schedule_id=plan.id, fired_at=fire_at)
            try:
                task = flow_ops.instantiate(
                    plan.flow,
                    fire_at,
                    actor="system",
                    trigger_note=f"由触发计划自动布置（{plan.flow.trigger.describe()}）",
                )
                self.store.save_task(task)
                outcome.task_id = task.id

                plan.fire_count += 1
                plan.last_fire_at = fire_at
                plan.last_error = ""
                # 以「当前时刻」而非「本次触发时刻」为基准推进，确保下次触发落在未来。
                # 若用 fire_at 作基准，停机期间错过的每一次触发都会在重启后被逐个补跑出来——
                # 停机 200 天就是 200 条通知轰炸责任人。错过的周期直接跳过，只对齐到下一次。
                plan.next_fire_at = next_fire_after(
                    plan.flow.trigger, after=max(fire_at, moment), fire_count=plan.fire_count,
                )
                if plan.next_fire_at is None:
                    plan.active = False
                self.store.save_schedule(plan, moment)
                self.store.record_fire_result(plan.id, fire_at, task_id=task.id)

            except Exception as exc:  # 单个计划失败不应中断整轮 tick
                outcome.error = str(exc)[:300]
                plan.last_error = outcome.error
                self.store.save_schedule(plan, moment)
                self.store.record_fire_result(plan.id, fire_at, error=outcome.error)
                # 释放抢占，下次 tick 可重试
                self.store.release_fire(plan.id, fire_at)

            report.fired.append(outcome)

        # 主动扫描逾期，不依赖任何人打开列表页
        for task in self.store.overdue_candidates(moment):
            if flow_ops.mark_overdue_if_needed(task, now=moment):
                self.store.save_task(task)
                report.overdue_task_ids.append(task.id)

        return report

    # ---- 任务操作 ----

    def get_task(self, task_id: str) -> TaskInstance | None:
        return self.store.get_task(task_id)

    def list_tasks(
        self,
        *,
        assignee: str | None = None,
        confirmer: str | None = None,
        site: str | None = None,
        state: str | None = None,
        category: str | None = None,
        open_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskInstance]:
        return self.store.list_tasks(
            assignee=assignee, confirmer=confirmer, site=site,
            state=state, category=category,
            open_only=open_only, limit=limit, offset=offset,
        )

    def complete_step(
        self,
        task_id: str,
        seq: int,
        *,
        actor: str = "",
        comment: str = "",
        attachments: list[str] | None = None,
        now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.complete_step(
            task, seq, now=now or self.now(), actor=actor,
            comment=comment, attachments=attachments,
        )
        self.store.save_task(task)
        return task

    def skip_step(
        self, task_id: str, seq: int, *, actor: str = "", reason: str = "",
        now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.skip_step(task, seq, now=now or self.now(), actor=actor, reason=reason)
        self.store.save_task(task)
        return task

    def forward_step(
        self, task_id: str, seq: int, *, to: Assignee, actor: str = "", note: str = "",
        now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.forward_step(task, seq, to=to, now=now or self.now(), actor=actor, note=note)
        self.store.save_task(task)
        return task

    def block_step(
        self, task_id: str, seq: int, *, actor: str = "", reason: str = "",
        now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.block_step(task, seq, now=now or self.now(), actor=actor, reason=reason)
        self.store.save_task(task)
        return task

    def unblock_step(
        self, task_id: str, seq: int, *, actor: str = "", note: str = "",
        now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.unblock_step(task, seq, now=now or self.now(), actor=actor, note=note)
        self.store.save_task(task)
        return task

    def add_note(
        self, task_id: str, *, note: str, actor: str = "", seq: int | None = None,
        now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.add_note(task, now=now or self.now(), actor=actor, note=note, seq=seq)
        self.store.save_task(task)
        return task

    def accept(
        self, task_id: str, *, actor: str = "", note: str = "", now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.accept(task, now=now or self.now(), actor=actor, note=note)
        self.store.save_task(task)
        return task

    def reject(
        self, task_id: str, *, actor: str = "", reason: str = "", now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.reject(task, now=now or self.now(), actor=actor, reason=reason)
        self.store.save_task(task)
        return task

    def cancel_task(
        self, task_id: str, *, actor: str = "", reason: str = "", now: datetime | None = None,
    ) -> TaskInstance:
        task = self._require_task(task_id)
        flow_ops.cancel(task, now=now or self.now(), actor=actor, reason=reason)
        self.store.save_task(task)
        return task

    def _require_task(self, task_id: str) -> TaskInstance:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"任务 {task_id} 不存在")
        return task
