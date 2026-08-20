"""MCP 工具的实现与分发。

与协议解析分离：本模块只管「工具名 + 参数 → 结果字典」，不关心 JSON-RPC。
这样同一套工具可以同时被 MCP server 与 CLI 复用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .domain.models import Assignee, IntervalUnit, RunMode, Site, Trigger
from .engine import TaskEngine
from .generator.llm import FlowGenerator
from .generator.templates import build_from_template, list_templates
from .serialize import (
    flow_json,
    schedule_json,
    task_brief,
    task_json,
)


class ToolError(Exception):
    """工具调用失败，消息会原样回给调用方。"""


def parse_moment(value: Any, *, timezone: str) -> datetime | None:
    """宽松解析时间字符串——调用方可能来自模型，格式未必规整。"""
    if not value:
        return None
    text = str(value).strip().replace("/", "-")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ToolError(f"无法解析时间：{value}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed


def parse_people(raw: Any) -> list[Assignee]:
    """把 [{ref, name}] 转成 Assignee 列表，忽略缺 ref 的条目。"""
    if not isinstance(raw, list):
        return []
    people = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("ref") or "").strip():
            people.append(
                Assignee(
                    ref=str(item["ref"]).strip(),
                    display_name=str(item.get("name") or ""),
                ),
            )
    return people


def parse_person(raw: Any, *, field: str) -> Assignee | None:
    """解析单个责任人。

    只接受具体的人——工程责任制不允许「安全员」这类抽象角色，
    角色到人的解析属于宿主系统的组织架构职责。
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        ref = raw.strip()
        return Assignee(ref=ref) if ref else None
    if isinstance(raw, dict):
        ref = str(raw.get("ref") or "").strip()
        if not ref:
            return None
        return Assignee(ref=ref, display_name=str(raw.get("name") or ""))
    raise ToolError(f"{field} 格式不正确，应为 {{ref, name}} 对象")


def parse_site(raw: Any) -> Site | None:
    """解析工点。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        ref = raw.strip()
        return Site(ref=ref) if ref else None
    if isinstance(raw, dict):
        ref = str(raw.get("ref") or "").strip()
        if not ref:
            return None
        return Site(
            ref=ref,
            name=str(raw.get("name") or ""),
            code=str(raw.get("code") or ""),
        )
    raise ToolError("site 格式不正确，应为 {ref, name, code} 对象")


def parse_int(value: Any, *, field: str, default: int | None = None,
              low: int | None = None, high: int | None = None) -> int | None:
    """解析整数参数：类型错误拒绝，数值越界夹回合法区间。

    这两类问题的处置不同是有意的——
    类型错误（"很多"、"0"）说明调用方误解了 schema，静默转换会让问题延后到更难排查的
    地方暴露，所以直接拒绝；bool 也要挡，因为 isinstance(True, int) 为真，
    不挡的话 seq=True 会静默变成 seq=1。
    数值越界（limit=0、offset=-1）意图是清楚的，夹回边界即可，没必要为此打断调用方。
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{field} 必须是整数，收到 {type(value).__name__}：{value!r}")
    if low is not None and value < low:
        return low
    if high is not None and value > high:
        return high
    return value


class ToolRegistry:
    """工具注册表：把 MCP 工具名映射到引擎调用。"""

    def __init__(self, engine: TaskEngine, generator: FlowGenerator | None = None) -> None:
        self.engine = engine
        self.generator = generator or FlowGenerator()
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "generate_task_flow": self.generate_task_flow,
            "list_templates": self.list_templates,
            "create_flow_from_template": self.create_flow_from_template,
            "list_flows": self.list_flows,
            "dispatch_task": self.dispatch_task,
            "create_schedule": self.create_schedule,
            "list_schedules": self.list_schedules,
            "pause_schedule": self.pause_schedule,
            "cancel_schedule": self.cancel_schedule,
            "tick": self.tick,
            "list_tasks": self.list_tasks,
            "get_task": self.get_task,
            "complete_step": self.complete_step,
            "forward_step": self.forward_step,
            "skip_step": self.skip_step,
            "block_step": self.block_step,
            "unblock_step": self.unblock_step,
            "add_note": self.add_note,
            "accept_task": self.accept_task,
            "reject_task": self.reject_task,
            "cancel_task": self.cancel_task,
        }

    @property
    def tool_names(self) -> list[str]:
        return list(self._handlers)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolError(f"未知工具：{name}")
        return handler(arguments or {})

    # ---- 生成 ----

    def generate_task_flow(self, args: dict[str, Any]) -> dict[str, Any]:
        requirement = str(args.get("requirement") or "")
        flow = self.generator.generate(
            requirement,
            now=self.engine.now(),
            assignees=parse_people(args.get("assignees")),
            confirmer=parse_person(args.get("confirmer"), field="confirmer"),
            site=parse_site(args.get("site")),
            watchers=parse_people(args.get("watchers")),
            context=args.get("context") if isinstance(args.get("context"), dict) else None,
        )
        if args.get("save", True):
            self.engine.save_flow(flow)

        missing = self._missing_requirements(flow)
        return {
            "flow": flow_json(flow),
            "saved": bool(args.get("save", True)),
            "message": (
                f"已生成任务流「{flow.title}」，共 {len(flow.steps)} 个节点。"
                f"{flow.trigger.describe()}。{flow.origin_note}"
            ),
            "missing_requirements": missing,
            "next_step": (
                f"布置前需补齐：{'；'.join(missing)}"
                if missing
                else (
                    "调用 create_schedule 登记定时触发"
                    if flow.trigger.is_recurring
                    else "调用 dispatch_task 立即布置，或 create_schedule 定时布置"
                )
            ),
        }

    @staticmethod
    def _missing_requirements(flow) -> list[str]:
        """列出布置前还缺什么，让调用方（含模型）知道下一步该补哪些信息。"""
        missing: list[str] = []
        unassigned = flow.unassigned_steps()
        if unassigned:
            detail = "、".join(f"第 {i + 1} 个「{name}」" for i, name in unassigned)
            missing.append(f"以下节点的责任人：{detail}")
        if flow.confirmer is None:
            missing.append("确认人（完成后由谁验收）")
        if flow.site is None:
            missing.append("工点（任务发生在哪）")
        return missing

    def list_templates(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"templates": list_templates()}

    def create_flow_from_template(self, args: dict[str, Any]) -> dict[str, Any]:
        template = str(args.get("template") or "")
        try:
            flow = build_from_template(
                template,
                title=str(args.get("title") or ""),
                assignees=parse_people(args.get("assignees")),
                confirmer=parse_person(args.get("confirmer"), field="confirmer"),
                site=parse_site(args.get("site")),
                watchers=parse_people(args.get("watchers")),
            )
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

        if args.get("save", True):
            self.engine.save_flow(flow)

        missing = self._missing_requirements(flow)
        return {
            "flow": flow_json(flow),
            "missing_requirements": missing,
            "message": (
                f"已按模板生成任务流「{flow.title}」，共 {len(flow.steps)} 个节点"
                + (f"。布置前需补齐：{'；'.join(missing)}" if missing else "")
            ),
        }

    def list_flows(self, args: dict[str, Any]) -> dict[str, Any]:
        flows = self.engine.list_flows(
            category=args.get("category"),
            limit=parse_int(args.get("limit"), field="limit", default=50, low=1, high=200),
        )
        return {"flows": [flow_json(f) for f in flows], "count": len(flows)}

    # ---- 布置与调度 ----

    def dispatch_task(self, args: dict[str, Any]) -> dict[str, Any]:
        flow = self._require_flow(args.get("flow_id"))
        try:
            task = self.engine.dispatch(
                flow,
                actor=str(args.get("actor") or "system"),
                trigger_note=str(args.get("trigger_note") or "手动布置"),
            )
        except ValueError as exc:
            # 责任制校验失败——责任人/确认人/工点缺失
            raise ToolError(str(exc)) from exc

        current = task.current_step
        return {
            "task": task_json(task),
            "message": (
                f"任务「{task.title}」已布置"
                + (f"，工点 {task.site}" if task.site else "")
                + (
                    f"，当前节点「{current.name}」责任人 {current.assignee}"
                    if current and current.assignee else ""
                )
            ),
        }

    def create_schedule(self, args: dict[str, Any]) -> dict[str, Any]:
        flow = self._require_flow(args.get("flow_id"))
        trigger = self._build_trigger(args, base=flow.trigger)

        # 提前校验：定时任务到点会自动布置，若此时才发现缺责任人，
        # 失败会静默发生在后台 tick 里，没人看得到。登记时就挡住。
        try:
            flow.require_dispatchable()
        except ValueError as exc:
            raise ToolError(f"{exc}。定时任务到点会自动布置，必须先补齐") from exc

        try:
            plan = self.engine.schedule(flow, trigger=trigger)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        return {
            "schedule": schedule_json(plan),
            "message": (
                f"触发计划已登记：{trigger.describe()}。"
                f"下次触发 {plan.next_fire_at.strftime('%Y-%m-%d %H:%M') if plan.next_fire_at else '无'}"
            ),
            "note": "需由外部定时调用 tick 工具来驱动触发",
        }

    def _build_trigger(self, args: dict[str, Any], *, base: Trigger) -> Trigger:
        """从参数构造触发规则，未提供的字段沿用任务流自带的设置。"""
        timezone = self.engine.timezone
        mode_raw = str(args.get("run_mode") or "").lower()
        run_mode = RunMode(mode_raw) if mode_raw in {"once", "recurring"} else base.run_mode

        first_at = parse_moment(args.get("first_at"), timezone=timezone) or base.first_at

        unit_raw = str(args.get("interval_unit") or "").lower()
        unit = IntervalUnit(unit_raw) if unit_raw in {u.value for u in IntervalUnit} else base.interval_unit

        interval_value = args.get("interval_value")
        try:
            value = max(1, int(interval_value)) if interval_value is not None else base.interval_value
        except (TypeError, ValueError):
            value = base.interval_value

        max_fires = args.get("max_fires")
        try:
            fires = max(1, int(max_fires)) if max_fires is not None else base.max_fires
        except (TypeError, ValueError):
            fires = base.max_fires

        return Trigger(
            run_mode=run_mode,
            first_at=first_at,
            interval_value=value,
            interval_unit=unit,
            timezone=timezone,
            until=parse_moment(args.get("until"), timezone=timezone) or base.until,
            max_fires=fires,
        )

    def list_schedules(self, args: dict[str, Any]) -> dict[str, Any]:
        plans = self.engine.list_schedules(active_only=bool(args.get("active_only")))
        return {"schedules": [schedule_json(p) for p in plans], "count": len(plans)}

    def pause_schedule(self, args: dict[str, Any]) -> dict[str, Any]:
        paused = bool(args.get("paused", True))
        plan = self.engine.pause_schedule(str(args.get("schedule_id") or ""), paused=paused)
        if plan is None:
            raise ToolError(f"触发计划 {args.get('schedule_id')} 不存在")
        return {
            "schedule": schedule_json(plan),
            "message": f"触发计划已{'暂停' if paused else '恢复'}",
        }

    def cancel_schedule(self, args: dict[str, Any]) -> dict[str, Any]:
        schedule_id = str(args.get("schedule_id") or "")
        if not self.engine.cancel_schedule(schedule_id):
            raise ToolError(f"触发计划 {schedule_id} 不存在")
        return {"schedule_id": schedule_id, "message": "触发计划已停用，不再触发"}

    def tick(self, args: dict[str, Any]) -> dict[str, Any]:
        now = parse_moment(args.get("now"), timezone=self.engine.timezone)
        report = self.engine.tick(now=now)
        return {
            "at": report.at.isoformat(),
            "created_tasks": [item.task_id for item in report.fired if item.ok],
            "created_count": report.created_count,
            "failed": [
                {"schedule_id": item.schedule_id, "error": item.error}
                for item in report.fired if not item.ok
            ],
            "overdue_task_ids": report.overdue_task_ids,
            "skipped_duplicates": report.skipped,
            "message": report.describe(),
        }

    # ---- 任务查询 ----

    def list_tasks(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = parse_int(args.get("limit"), field="limit", default=20, low=1, high=100)
        offset = parse_int(args.get("offset"), field="offset", default=0, low=0)
        tasks = self.engine.list_tasks(
            assignee=args.get("assignee"),
            confirmer=args.get("confirmer"),
            site=args.get("site"),
            state=args.get("state"),
            category=args.get("category"),
            open_only=bool(args.get("open_only")),
            limit=limit,
            offset=offset,
        )
        return {
            "tasks": [task_brief(t) for t in tasks],
            "count": len(tasks),
            "message": f"共 {len(tasks)} 个任务" if tasks else "没有符合条件的任务",
        }

    def get_task(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self.engine.get_task(str(args.get("task_id") or ""))
        if task is None:
            raise ToolError(f"任务 {args.get('task_id')} 不存在")
        return {"task": task_json(task, include_history=bool(args.get("include_history", True)))}

    # ---- 任务操作 ----

    def complete_step(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.complete_step,
            args,
            seq_required=True,
            comment=str(args.get("comment") or ""),
            attachments=list(args.get("attachments") or []),
        )
        current = task.current_step
        done, total = task.progress
        return {
            "task": task_json(task),
            "message": (
                f"节点已完成（{done}/{total}）。"
                + (
                    f"下一节点「{current.name}」责任人 {current.assignee or '待指定'}"
                    if current else "全部节点完成，任务进入待验收"
                )
            ),
        }

    def forward_step(self, args: dict[str, Any]) -> dict[str, Any]:
        to = Assignee(
            ref=str(args.get("to_ref") or ""),
            display_name=str(args.get("to_name") or ""),
        )
        if not to.ref:
            raise ToolError("必须指定接收人 to_ref")
        task = self._operate(
            self.engine.forward_step, args, seq_required=True,
            to=to, note=str(args.get("note") or ""),
        )
        return {"task": task_json(task), "message": f"节点已转办给 {to}"}

    def skip_step(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.skip_step, args, seq_required=True,
            reason=str(args.get("reason") or ""),
        )
        return {"task": task_json(task), "message": "节点已跳过"}

    def block_step(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.block_step, args, seq_required=True,
            reason=str(args.get("reason") or ""),
        )
        return {"task": task_json(task), "message": "节点已标记为受阻"}

    def unblock_step(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.unblock_step, args, seq_required=True,
            note=str(args.get("note") or ""),
        )
        return {"task": task_json(task), "message": "节点已恢复流转"}

    def add_note(self, args: dict[str, Any]) -> dict[str, Any]:
        note = str(args.get("note") or "")
        seq = args.get("seq")
        parsed_seq = parse_int(seq, field="节点序号 seq")
        if parsed_seq is not None and parsed_seq < 0:
            raise ToolError(f"节点序号不能为负数：{parsed_seq}")
        task = self._operate(
            self.engine.add_note, args, seq_required=False,
            note=note, seq=parsed_seq,
        )
        return {"task_id": task.id, "message": "处理说明已记录"}

    def accept_task(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.accept, args, seq_required=False, note=str(args.get("note") or ""),
        )
        return {"task": task_json(task), "message": f"任务「{task.title}」已验收通过并闭环"}

    def reject_task(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.reject, args, seq_required=False, reason=str(args.get("reason") or ""),
        )
        current = task.current_step
        return {
            "task": task_json(task),
            "message": f"任务已退回，重做节点「{current.name}」" if current else "任务已退回",
        }

    def cancel_task(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._operate(
            self.engine.cancel_task, args, seq_required=False, reason=str(args.get("reason") or ""),
        )
        return {"task": task_json(task), "message": f"任务「{task.title}」已取消"}

    # ---- 内部辅助 ----

    def _operate(self, method: Callable, args: dict[str, Any], *, seq_required: bool, **extra: Any):
        """统一处理 task_id / seq / actor 三个通用参数并转换异常。"""
        task_id = str(args.get("task_id") or "")
        if not task_id:
            raise ToolError("必须提供 task_id")

        call_args: list[Any] = [task_id]
        if seq_required:
            seq = args.get("seq")
            if seq is None:
                raise ToolError("必须提供节点序号 seq")
            # 序号不能夹回边界——seq=-1 若被夹成 0，就会误操作到另一个节点
            parsed_seq = parse_int(seq, field="节点序号 seq")
            if parsed_seq < 0:
                raise ToolError(f"节点序号不能为负数：{parsed_seq}")
            call_args.append(parsed_seq)

        try:
            return method(*call_args, actor=str(args.get("actor") or ""), **extra)
        except KeyError as exc:
            raise ToolError(str(exc).strip("'")) from exc
        except Exception as exc:
            # 领域层的 TransitionError 等，消息已经是给人看的中文
            raise ToolError(str(exc)) from exc

    def _require_flow(self, flow_id: Any):
        flow = self.engine.get_flow(str(flow_id or ""))
        if flow is None:
            raise ToolError(f"任务流 {flow_id} 不存在，请先用 generate_task_flow 或 create_flow_from_template 创建")
        return flow
