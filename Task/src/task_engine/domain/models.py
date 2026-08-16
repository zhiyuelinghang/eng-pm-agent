"""领域模型：任务流定义、实例与流转记录。

本模块只描述"任务是什么"，不涉及存储、网络与协议。所有类型都是不可变或近乎不可变的
数据载体，便于在纯函数中推演。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Self


def new_id(prefix: str) -> str:
    """生成带前缀的短 id，便于日志里一眼看出类型。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class RunMode(StrEnum):
    """任务流的执行方式。"""

    ONCE = "once"            # 到点执行一次
    RECURRING = "recurring"  # 首次执行后按间隔重复


class IntervalUnit(StrEnum):
    """重复间隔单位。"""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class StepState(StrEnum):
    """单个节点的状态。

    节点是任务流的最小执行单位，同一时刻只有一个节点处于 ACTIVE。
    """

    WAITING = "waiting"    # 尚未轮到
    ACTIVE = "active"      # 当前责任节点
    DONE = "done"          # 已完成
    SKIPPED = "skipped"    # 被跳过（条件不满足或人工跳过）
    BLOCKED = "blocked"    # 受阻，需要外部介入


class TaskState(StrEnum):
    """任务实例的整体状态。

    与节点状态分离：节点描述"走到哪了"，任务状态描述"整体处境"。
    """

    PENDING = "pending"        # 已创建，首个节点尚未开始
    RUNNING = "running"        # 正在流转
    BLOCKED = "blocked"        # 某节点受阻
    REVIEW = "review"          # 所有节点完成，等待验收
    DONE = "done"              # 已闭环
    CANCELLED = "cancelled"    # 已取消
    OVERDUE = "overdue"        # 超过截止时间且未闭环

    @property
    def is_terminal(self) -> bool:
        return self in (TaskState.DONE, TaskState.CANCELLED)


class ActivityKind(StrEnum):
    """流转记录的类型，构成任务的完整审计轨迹。"""

    CREATED = "created"
    STEP_ACTIVATED = "step_activated"
    STEP_DONE = "step_done"
    STEP_SKIPPED = "step_skipped"
    STEP_BLOCKED = "step_blocked"
    FORWARDED = "forwarded"       # 转办：换人不换节点
    STATE_CHANGED = "state_changed"
    NOTE_ADDED = "note_added"
    ATTACHMENT_ADDED = "attachment_added"
    OVERDUE_MARKED = "overdue_marked"
    FIRED = "fired"               # 由触发计划创建


@dataclass(frozen=True, slots=True)
class Assignee:
    """责任人——必须是具体的人，不接受抽象角色。

    工程责任制的底线：提醒和待办要能追到某一个人。若允许「安全员」「资料员」这类
    角色作为责任人，出了事没人认领，任务也无从判断该谁办。角色到人的解析属于宿主
    系统的组织架构职责，必须在进入引擎之前完成。

    `ref` 是宿主系统里的稳定人员标识（用户 id / 工号），不能是岗位名。
    """

    ref: str
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.ref or not self.ref.strip():
            raise ValueError("责任人标识不能为空——任务必须落到具体的人")

    def __str__(self) -> str:
        return self.display_name or self.ref


@dataclass(frozen=True, slots=True)
class Site:
    """工点：任务发生的具体位置。

    工程任务必须能回答「在哪个工点」——同一类隐患在不同工点是不同的任务，
    责任人、验收标准、整改时限都可能不同。做成一等字段而非自由标签，
    是为了支持按工点检索与统计。
    """

    ref: str                      # 宿主系统里的工点标识（WBS id / 部位编号）
    name: str = ""                # 显示名，如「3号楼-地下室」
    code: str = ""                # 编号，如「WBS-03-B1」

    def __post_init__(self) -> None:
        if not self.ref or not self.ref.strip():
            raise ValueError("工点标识不能为空")

    def __str__(self) -> str:
        if self.code and self.name:
            return f"{self.code} {self.name}"
        return self.name or self.ref


@dataclass(frozen=True, slots=True)
class Trigger:
    """触发规则。

    `first_at` 是首次（或唯一一次）触发时刻。RECURRING 模式下，之后按
    interval_value × interval_unit 重复。
    """

    run_mode: RunMode = RunMode.ONCE
    first_at: datetime | None = None
    interval_value: int = 1
    interval_unit: IntervalUnit = IntervalUnit.WEEK
    timezone: str = "Asia/Shanghai"
    # RECURRING 的收敛条件，二者皆空表示无限重复
    until: datetime | None = None
    max_fires: int | None = None

    def __post_init__(self) -> None:
        if self.run_mode is RunMode.RECURRING and self.interval_value < 1:
            raise ValueError("重复间隔必须为正整数")

    @property
    def is_recurring(self) -> bool:
        return self.run_mode is RunMode.RECURRING

    def describe(self) -> str:
        """生成人类可读的触发说明，供 UI 直接展示。"""
        if self.first_at is None:
            return "未设置触发时间"
        stamp = self.first_at.strftime("%Y-%m-%d %H:%M")
        if not self.is_recurring:
            return f"{stamp} 执行一次"
        unit_label = {"hour": "小时", "day": "天", "week": "周", "month": "个月"}[self.interval_unit]
        tail = ""
        if self.max_fires:
            tail = f"，共 {self.max_fires} 次"
        elif self.until:
            tail = f"，直到 {self.until.strftime('%Y-%m-%d')}"
        return f"{stamp} 首次执行，之后每 {self.interval_value} {unit_label}执行一次{tail}"


@dataclass(frozen=True, slots=True)
class StepSpec:
    """任务流定义里的节点模板。

    只描述"这一步该做什么"，不含运行时状态。

    `assignee` 允许为 None——模板可以先留空以便复用，但布置成具体任务时必须已经
    落到人（由 flow.require_assignees() 校验）。这样既保住了责任制，又不牺牲模板的
    通用性。
    """

    name: str
    assignee: Assignee | None = None
    # 相对于上一节点的工期天数；配合触发时间算出实际截止时刻
    due_offset_days: int = 1
    deliverable: str = ""          # 该节点的交付物 / 依据
    instruction: str = ""          # 给执行人的说明
    requires_attachment: bool = False
    optional: bool = False         # 可跳过

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("节点名称不能为空")


@dataclass(frozen=True, slots=True)
class TaskFlow:
    """任务流定义：一张可复用的"流程图"。

    它是模板，不是运行中的任务。一个 TaskFlow 可被触发多次，每次产生一个 TaskInstance。
    """

    title: str
    steps: tuple[StepSpec, ...]
    id: str = field(default_factory=lambda: new_id("flow"))
    summary: str = ""                       # 一句话说明这个流程解决什么
    category: str = "general"               # 业务分类，由宿主定义含义
    priority: str = "normal"                # low | normal | high | urgent
    trigger: Trigger = field(default_factory=Trigger)
    site: Site | None = None                # 工点：任务发生的位置
    confirmer: Assignee | None = None       # 确认人：全部节点完成后由谁验收
    watchers: tuple[Assignee, ...] = ()     # 抄送人
    tags: tuple[str, ...] = ()
    origin: str = "manual"                  # manual | template | ai | imported
    origin_note: str = ""                   # 生成说明，如"由需求描述自动生成"
    scope: dict[str, Any] = field(default_factory=dict)  # 宿主上下文（项目 id 等）

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("任务流标题不能为空")
        if not self.steps:
            raise ValueError("任务流至少需要一个节点")

    def with_trigger(self, trigger: Trigger) -> Self:
        return replace(self, trigger=trigger)

    def unassigned_steps(self) -> list[tuple[int, str]]:
        """列出尚未指定责任人的节点，返回 [(序号, 名称)]。"""
        return [
            (index, spec.name)
            for index, spec in enumerate(self.steps)
            if spec.assignee is None
        ]

    def require_dispatchable(self) -> None:
        """校验这个任务流是否可以布置成真实任务。

        工程责任制要求每一项待办都能追到具体的人、具体的工点、具体的验收责任，
        所以布置前这三项必须齐备。模板阶段可以留空，布置阶段不行。
        """
        missing = self.unassigned_steps()
        if missing:
            detail = "、".join(f"第 {i + 1} 个「{name}」" for i, name in missing)
            raise ValueError(f"以下节点尚未指定责任人，无法布置：{detail}")
        if self.confirmer is None:
            raise ValueError("任务未指定确认人，无法布置——完成后需要有人验收")
        if self.site is None:
            raise ValueError("任务未关联工点，无法布置")


@dataclass(slots=True)
class Step:
    """运行中的节点。

    由 StepSpec 实例化而来，携带状态与实际经办信息。可变——流转会就地更新。
    """

    seq: int
    name: str
    assignee: Assignee | None = None
    state: StepState = StepState.WAITING
    due_at: datetime | None = None
    deliverable: str = ""
    instruction: str = ""
    requires_attachment: bool = False
    optional: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    finished_by: str = ""
    comment: str = ""
    attachments: list[str] = field(default_factory=list)
    # 被退回重做时置为 True。此时旧附件仍保留（审计需要），但要求留证的节点
    # 必须提交新材料才能再次完成——否则"照片不清晰，重拍"的退回会被旧照片蒙混过关。
    reopened: bool = False

    @property
    def is_settled(self) -> bool:
        """节点是否已了结（完成或跳过），不再占用流转。"""
        return self.state in (StepState.DONE, StepState.SKIPPED)

    @classmethod
    def from_spec(cls, spec: StepSpec, seq: int, due_at: datetime | None = None) -> Step:
        return cls(
            seq=seq,
            name=spec.name,
            assignee=spec.assignee,
            due_at=due_at,
            deliverable=spec.deliverable,
            instruction=spec.instruction,
            requires_attachment=spec.requires_attachment,
            optional=spec.optional,
        )


@dataclass(frozen=True, slots=True)
class Activity:
    """一条流转记录。

    任务的历史即 Activity 的有序集合——每次状态变化都留痕，可完整回溯。
    """

    kind: ActivityKind
    at: datetime
    id: str = field(default_factory=lambda: new_id("act"))
    actor: str = ""            # 操作人 ref，系统触发时为 "system"
    step_seq: int | None = None
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskInstance:
    """运行中的任务：任务流的一次具体执行。"""

    title: str
    steps: list[Step]
    id: str = field(default_factory=lambda: new_id("task"))
    flow_id: str = ""
    state: TaskState = TaskState.PENDING
    priority: str = "normal"
    category: str = "general"
    summary: str = ""
    site: Site | None = None                # 工点
    confirmer: Assignee | None = None       # 确认人
    watchers: list[Assignee] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)
    trigger_note: str = ""      # 本次因何而起（定时触发 / 手动布置）
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    activities: list[Activity] = field(default_factory=list)

    @property
    def current_step(self) -> Step | None:
        """当前责任节点：第一个未了结的节点。"""
        for step in self.steps:
            if not step.is_settled:
                return step
        return None

    @property
    def current_assignee(self) -> Assignee | None:
        step = self.current_step
        return step.assignee if step else None

    @property
    def due_at(self) -> datetime | None:
        """任务整体截止时间 = 最后一个节点的截止时间。"""
        deadlines = [step.due_at for step in self.steps if step.due_at]
        return max(deadlines) if deadlines else None

    @property
    def progress(self) -> tuple[int, int]:
        """(已了结节点数, 总节点数)"""
        return sum(1 for step in self.steps if step.is_settled), len(self.steps)

    def step_at(self, seq: int) -> Step:
        for step in self.steps:
            if step.seq == seq:
                return step
        raise KeyError(f"节点 {seq} 不存在")

    def log(self, activity: Activity) -> None:
        self.activities.append(activity)
        self.updated_at = activity.at


@dataclass(slots=True)
class Schedule:
    """触发计划：把任务流与时间绑定起来。

    这是引擎相对宿主系统的核心增量——宿主往往能存任务，却没有"到点自动布置"的能力。
    """

    flow: TaskFlow
    id: str = field(default_factory=lambda: new_id("sched"))
    next_fire_at: datetime | None = None
    last_fire_at: datetime | None = None
    fire_count: int = 0
    active: bool = True
    paused: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str = ""

    @property
    def is_exhausted(self) -> bool:
        """计划是否已走完（不会再触发）。"""
        return not self.active or self.next_fire_at is None

    @property
    def is_due(self) -> bool:
        return self.active and not self.paused and self.next_fire_at is not None
