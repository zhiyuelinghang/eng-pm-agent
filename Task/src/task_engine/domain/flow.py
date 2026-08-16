"""任务流转引擎：状态机与节点推进。

这是引擎的心脏。所有函数都对传入的 TaskInstance 就地操作并返回它，同时把每次变化
记入 activities——任务的历史不是附带产物，而是流转的一等公民。

设计要点：任务状态（TaskState）由节点状态推导，而不是各自独立维护。调用方推进节点，
整体状态自动跟随，避免两者不一致。
"""
from __future__ import annotations

from datetime import datetime

from .models import (
    Activity,
    ActivityKind,
    Assignee,
    Step,
    StepState,
    TaskFlow,
    TaskInstance,
    TaskState,
)
from .trigger import due_dates_for_steps

# 允许的任务状态跃迁。终态不可再变。
ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.RUNNING, TaskState.CANCELLED, TaskState.OVERDUE}),
    TaskState.RUNNING: frozenset(
        {TaskState.BLOCKED, TaskState.REVIEW, TaskState.CANCELLED, TaskState.OVERDUE, TaskState.DONE},
    ),
    TaskState.BLOCKED: frozenset({TaskState.RUNNING, TaskState.CANCELLED, TaskState.OVERDUE}),
    TaskState.REVIEW: frozenset({TaskState.RUNNING, TaskState.DONE, TaskState.CANCELLED, TaskState.OVERDUE}),
    TaskState.OVERDUE: frozenset({TaskState.RUNNING, TaskState.REVIEW, TaskState.DONE, TaskState.CANCELLED}),
    TaskState.DONE: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class TransitionError(RuntimeError):
    """非法的状态跃迁或节点操作。"""


def instantiate(
    flow: TaskFlow,
    now: datetime,
    *,
    trigger_note: str = "",
    actor: str = "system",
) -> TaskInstance:
    """由任务流定义创建一个运行实例，并激活首个节点。

    布置前强制校验责任制三要素：每个节点都有具体责任人、任务有确认人、关联了工点。
    模板阶段可以留空，但一旦要变成真实待办，这三项必须齐备——否则就会出现
    「有任务没人认领」或「完成了没人验收」的情况。
    """
    flow.require_dispatchable()

    deadlines = due_dates_for_steps(now, [spec.due_offset_days for spec in flow.steps])
    steps = [Step.from_spec(spec, seq=index, due_at=deadlines[index]) for index, spec in enumerate(flow.steps)]

    task = TaskInstance(
        title=flow.title,
        steps=steps,
        flow_id=flow.id,
        priority=flow.priority,
        category=flow.category,
        summary=flow.summary,
        site=flow.site,
        confirmer=flow.confirmer,
        watchers=list(flow.watchers),
        tags=list(flow.tags),
        scope=dict(flow.scope),
        trigger_note=trigger_note or flow.trigger.describe(),
        created_at=now,
        updated_at=now,
    )
    task.log(
        Activity(
            kind=ActivityKind.CREATED,
            at=now,
            actor=actor,
            summary=(
                f"任务「{flow.title}」已创建，共 {len(steps)} 个节点"
                + (f"，工点 {flow.site}" if flow.site else "")
            ),
            detail={
                "flow_id": flow.id,
                "origin": flow.origin,
                "site": flow.site.ref if flow.site else "",
                "confirmer": flow.confirmer.ref if flow.confirmer else "",
            },
        ),
    )
    _activate_next(task, now, actor=actor)
    return task


def _require_in_turn(task: TaskInstance, step: Step) -> None:
    """确保只能操作当前轮到的节点。

    任务流的价值就在于顺序——若能越过前序节点直接完成靠后的，就等于「没整改先归档」，
    流转顺序形同虚设。需要跳过某一节点时应显式调用 skip_step（且该节点须为 optional）。
    """
    current = task.current_step
    if current is not None and step.seq != current.seq:
        raise TransitionError(
            f"当前应处理节点「{current.name}」（第 {current.seq + 1} 个），"
            f"不能跨越到「{step.name}」",
        )


def complete_step(
    task: TaskInstance,
    seq: int,
    *,
    now: datetime,
    actor: str = "",
    comment: str = "",
    attachments: list[str] | None = None,
) -> TaskInstance:
    """完成一个节点，并把流转推进到下一个。

    要求附件的节点在没有附件时会被拒绝——这是工程场景的常见约束（如整改需留照片）。
    """
    _reject_if_terminal(task)
    step = task.step_at(seq)
    if step.is_settled:
        raise TransitionError(f"节点「{step.name}」已经了结，不能重复完成")
    _require_in_turn(task, step)

    files = attachments or []
    if step.requires_attachment and not files:
        # 重做时旧附件不算数：确认人以「材料不合格」退回，若旧材料还能顶用，
        # 退回就形同虚设。首次提交则允许沿用已上传的附件。
        if step.reopened:
            raise TransitionError(
                f"节点「{step.name}」被退回重做，需要重新提交证明材料",
            )
        if not step.attachments:
            raise TransitionError(f"节点「{step.name}」要求提交证明材料")

    step.state = StepState.DONE
    step.finished_at = now
    step.finished_by = actor
    step.comment = comment
    step.attachments.extend(files)
    step.reopened = False

    task.log(
        Activity(
            kind=ActivityKind.STEP_DONE,
            at=now,
            actor=actor,
            step_seq=seq,
            summary=f"节点「{step.name}」已完成",
            detail={"comment": comment, "attachments": files},
        ),
    )
    _activate_next(task, now, actor=actor)
    return task


def skip_step(
    task: TaskInstance,
    seq: int,
    *,
    now: datetime,
    actor: str = "",
    reason: str = "",
) -> TaskInstance:
    """跳过一个节点。只有标记为 optional 的节点才允许跳过。"""
    _reject_if_terminal(task)
    step = task.step_at(seq)
    if step.is_settled:
        raise TransitionError(f"节点「{step.name}」已经了结")
    if not step.optional:
        raise TransitionError(f"节点「{step.name}」是必经节点，不能跳过")
    _require_in_turn(task, step)

    step.state = StepState.SKIPPED
    step.finished_at = now
    step.finished_by = actor
    step.comment = reason

    task.log(
        Activity(
            kind=ActivityKind.STEP_SKIPPED,
            at=now,
            actor=actor,
            step_seq=seq,
            summary=f"节点「{step.name}」已跳过",
            detail={"reason": reason},
        ),
    )
    _activate_next(task, now, actor=actor)
    return task


def block_step(
    task: TaskInstance,
    seq: int,
    *,
    now: datetime,
    actor: str = "",
    reason: str = "",
) -> TaskInstance:
    """把节点标记为受阻，任务整体转入 BLOCKED。"""
    _reject_if_terminal(task)
    step = task.step_at(seq)
    if step.is_settled:
        raise TransitionError(f"节点「{step.name}」已经了结")

    step.state = StepState.BLOCKED
    task.log(
        Activity(
            kind=ActivityKind.STEP_BLOCKED,
            at=now,
            actor=actor,
            step_seq=seq,
            summary=f"节点「{step.name}」受阻",
            detail={"reason": reason},
        ),
    )
    _set_state(task, TaskState.BLOCKED, now, actor=actor, note=reason)
    return task


def unblock_step(
    task: TaskInstance,
    seq: int,
    *,
    now: datetime,
    actor: str = "",
    note: str = "",
) -> TaskInstance:
    """解除受阻，节点回到活跃状态。"""
    step = task.step_at(seq)
    if step.state is not StepState.BLOCKED:
        raise TransitionError(f"节点「{step.name}」当前未受阻")
    step.state = StepState.ACTIVE
    task.log(
        Activity(
            kind=ActivityKind.STEP_ACTIVATED,
            at=now,
            actor=actor,
            step_seq=seq,
            summary=f"节点「{step.name}」已解除阻塞",
            detail={"note": note},
        ),
    )
    _set_state(task, TaskState.RUNNING, now, actor=actor, note=note)
    return task


def forward_step(
    task: TaskInstance,
    seq: int,
    *,
    to: Assignee,
    now: datetime,
    actor: str = "",
    note: str = "",
) -> TaskInstance:
    """转办：换责任人，节点原地不动。

    与「完成并推进」不同，转办不改变流转位置，只改变谁来做。

    允许操作当前节点（转办：我干不了，换人接手）与未来节点（排班：提前安排后续人手），
    但已了结的节点不可改派——历史责任归属是审计轨迹的基础，不允许事后篡改。
    """
    _reject_if_terminal(task)
    step = task.step_at(seq)
    if step.is_settled:
        raise TransitionError(f"节点「{step.name}」已经了结，无法转办")

    previous = step.assignee
    step.assignee = to
    task.log(
        Activity(
            kind=ActivityKind.FORWARDED,
            at=now,
            actor=actor,
            step_seq=seq,
            summary=f"节点「{step.name}」由 {previous or '未指派'} 转办给 {to}",
            detail={"from": previous.ref if previous else "", "to": to.ref, "note": note},
        ),
    )
    return task


def add_note(
    task: TaskInstance,
    *,
    now: datetime,
    actor: str = "",
    note: str,
    seq: int | None = None,
) -> TaskInstance:
    """追加一条处理说明，不改变流转位置。"""
    if not note.strip():
        raise TransitionError("处理说明不能为空")
    task.log(
        Activity(
            kind=ActivityKind.NOTE_ADDED,
            at=now,
            actor=actor,
            step_seq=seq,
            summary=note.strip()[:120],
            detail={"note": note},
        ),
    )
    return task


def accept(task: TaskInstance, *, now: datetime, actor: str = "", note: str = "") -> TaskInstance:
    """验收通过，任务闭环。

    只有任务指定的确认人能验收——「完成后由谁确认」若不强制，验收就退化成
    走过场，谁都能点通过，闭环也就失去了意义。
    """
    if task.state is not TaskState.REVIEW:
        raise TransitionError(f"任务当前为 {task.state}，只有待验收的任务可以通过")
    _require_confirmer(task, actor, action="验收")

    _set_state(task, TaskState.DONE, now, actor=actor, note=note)
    task.closed_at = now
    return task


def reject(task: TaskInstance, *, now: datetime, actor: str = "", reason: str = "") -> TaskInstance:
    """验收退回：把最后一个已完成节点重新打开，任务回到流转中。"""
    if task.state is not TaskState.REVIEW:
        raise TransitionError(f"任务当前为 {task.state}，只有待验收的任务可以退回")
    _require_confirmer(task, actor, action="退回")

    for step in reversed(task.steps):
        if step.state is StepState.DONE:
            step.state = StepState.ACTIVE
            step.finished_at = None
            step.finished_by = ""
            # 旧附件保留（审计轨迹不可抹去），但标记为重做——
            # 要求留证的节点必须提交新材料，否则退回等于没退
            step.reopened = True
            task.log(
                Activity(
                    kind=ActivityKind.STEP_ACTIVATED,
                    at=now,
                    actor=actor,
                    step_seq=step.seq,
                    summary=f"节点「{step.name}」被退回重做",
                    detail={"reason": reason},
                ),
            )
            break

    _set_state(task, TaskState.RUNNING, now, actor=actor, note=reason)
    return task


def _require_confirmer(task: TaskInstance, actor: str, *, action: str) -> None:
    """校验操作人是否为任务指定的确认人。

    actor 为空视为系统调用（如自动化脚本），放行——引擎不承担身份认证职责，
    调用方须自行确保 actor 的真实性。
    """
    if task.confirmer is None or not actor:
        return
    if actor != task.confirmer.ref:
        raise TransitionError(
            f"只有确认人 {task.confirmer} 可以{action}该任务",
        )


def cancel(task: TaskInstance, *, now: datetime, actor: str = "", reason: str = "") -> TaskInstance:
    """取消任务。"""
    _reject_if_terminal(task)
    _set_state(task, TaskState.CANCELLED, now, actor=actor, note=reason)
    task.closed_at = now
    return task


def mark_overdue_if_needed(task: TaskInstance, *, now: datetime) -> bool:
    """超过截止时间且未闭环时标记逾期。返回是否发生了变化。

    主动调用即可判定，不依赖任何人打开列表页——这是相对被动扫描的关键改进。
    """
    if task.state.is_terminal or task.state is TaskState.OVERDUE:
        return False
    deadline = task.due_at
    if deadline is None or deadline >= now:
        return False

    _set_state(task, TaskState.OVERDUE, now, actor="system", note="超过截止时间，系统自动标记")
    task.log(
        Activity(
            kind=ActivityKind.OVERDUE_MARKED,
            at=now,
            actor="system",
            summary=f"任务已逾期（截止 {deadline.strftime('%Y-%m-%d %H:%M')}）",
            detail={"due_at": deadline.isoformat()},
        ),
    )
    return True


# ---- 内部辅助 ----


def _activate_next(task: TaskInstance, now: datetime, *, actor: str = "") -> None:
    """激活下一个待办节点；若全部了结则转入待验收。"""
    nxt = task.current_step
    if nxt is None:
        _set_state(task, TaskState.REVIEW, now, actor=actor, note="全部节点已完成，等待验收")
        return

    if nxt.state is StepState.WAITING:
        nxt.state = StepState.ACTIVE
        nxt.started_at = now
        task.log(
            Activity(
                kind=ActivityKind.STEP_ACTIVATED,
                at=now,
                actor=actor,
                step_seq=nxt.seq,
                summary=f"节点「{nxt.name}」开始，责任人 {nxt.assignee or '待指定'}",
                detail={"assignee": nxt.assignee.ref if nxt.assignee else ""},
            ),
        )

    # 有活跃节点就意味着任务在流转。BLOCKED 也要恢复——受阻节点一旦被完成或跳过，
    # 阻塞就已经解除了，否则任务状态会与节点状态脱节（责任人在干活，看板却显示受阻）。
    if task.state in (TaskState.PENDING, TaskState.OVERDUE, TaskState.BLOCKED):
        _set_state(task, TaskState.RUNNING, now, actor=actor, note="")


def _set_state(
    task: TaskInstance,
    target: TaskState,
    now: datetime,
    *,
    actor: str = "",
    note: str = "",
) -> None:
    """校验并执行状态跃迁。同状态视为无操作。"""
    if task.state is target:
        return
    allowed = ALLOWED_TRANSITIONS.get(task.state, frozenset())
    if target not in allowed:
        raise TransitionError(f"任务当前为 {task.state}，不能流转到 {target}")

    previous = task.state
    task.state = target
    task.log(
        Activity(
            kind=ActivityKind.STATE_CHANGED,
            at=now,
            actor=actor or "system",
            summary=f"任务状态由 {previous} 变为 {target}",
            detail={"from": previous, "to": target, "note": note},
        ),
    )


def _reject_if_terminal(task: TaskInstance) -> None:
    if task.state.is_terminal:
        raise TransitionError(f"任务已 {task.state}，不能继续操作")
