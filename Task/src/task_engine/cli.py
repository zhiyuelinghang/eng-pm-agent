"""命令行入口：不经 MCP 也能驱动引擎。

用途有二：一是本地调试与演示，二是让 tick 能挂到 cron —— MCP 是拉模式，
总得有个东西定期来拉。

    # 每 5 分钟推进一次引擎
    */5 * * * * cd /path/to/task-engine && python3 -m task_engine.cli tick
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .engine import TaskEngine
from .generator.llm import FlowGenerator, LLMConfig
from .tools import ToolError, ToolRegistry


def build_registry(db_path: str, timezone: str) -> tuple[TaskEngine, ToolRegistry]:
    engine = TaskEngine(db_path, timezone=timezone)
    return engine, ToolRegistry(engine, FlowGenerator(LLMConfig.from_env()))


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    # 人看的输出：优先展示 message，再列关键内容
    if message := payload.get("message"):
        print(message)
    for key in ("templates", "tasks", "schedules", "flows"):
        for item in payload.get(key, []):
            print(f"  · {_line(item)}")


def _line(item: dict[str, Any]) -> str:
    if "state_label" in item:
        owner = item.get("current_assignee")
        owner_name = owner.get("name") or owner.get("ref") if owner else "待指定"
        return (
            f"{item['id']}  {item['title']}  [{item['state_label']}]  "
            f"{item.get('progress', '')}  {owner_name}"
        )
    if "next_fire_at" in item:
        return f"{item['id']}  {item['title']}  [{item['status']}]  下次 {item.get('next_fire_at') or '无'}"
    if "key" in item:
        return f"{item['key']}  {item['label']}  ({item['step_count']} 节点)  {item['summary']}"
    return str(item.get("id", item))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="task-engine",
        description="通用任务引擎：任务流编排、多级流转与定时触发",
    )
    parser.add_argument("--db", default=os.getenv("TASK_ENGINE_DB", "task_engine.db"))
    parser.add_argument("--tz", default=os.getenv("TASK_ENGINE_TZ", "Asia/Shanghai"))
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="由自然语言需求生成任务流")
    p.add_argument("requirement")

    sub.add_parser("templates", help="列出内置模板")

    p = sub.add_parser("from-template", help="按模板创建任务流")
    p.add_argument("template")
    p.add_argument("--title", default="")

    sub.add_parser("flows", help="列出已保存的任务流")

    p = sub.add_parser("dispatch", help="立即布置任务")
    p.add_argument("flow_id")

    p = sub.add_parser("schedule", help="登记触发计划")
    p.add_argument("flow_id")
    p.add_argument("--mode", choices=["once", "recurring"], default=None)
    p.add_argument("--at", dest="first_at", default=None, help="首次触发，如 '2026-03-02 09:00'")
    p.add_argument("--every", type=int, default=None, help="重复间隔数值")
    p.add_argument("--unit", choices=["hour", "day", "week", "month"], default=None)

    sub.add_parser("schedules", help="查看触发计划")

    p = sub.add_parser("tick", help="推进引擎：触发到期计划并扫描逾期")
    p.add_argument("--now", default=None, help="指定时刻，用于测试或补偿")

    p = sub.add_parser("tasks", help="查询任务")
    p.add_argument("--assignee", default=None)
    p.add_argument("--state", default=None)
    p.add_argument("--open", dest="open_only", action="store_true")

    p = sub.add_parser("task", help="任务详情")
    p.add_argument("task_id")

    p = sub.add_parser("complete", help="完成节点")
    p.add_argument("task_id")
    p.add_argument("seq", type=int)
    p.add_argument("--actor", default="")
    p.add_argument("--comment", default="")
    p.add_argument("--attach", action="append", default=[])

    p = sub.add_parser("forward", help="转办节点")
    p.add_argument("task_id")
    p.add_argument("seq", type=int)
    p.add_argument("to_ref")
    p.add_argument("--name", dest="to_name", default="")

    p = sub.add_parser("accept", help="验收通过")
    p.add_argument("task_id")
    p.add_argument("--actor", default="")

    p = sub.add_parser("reject", help="验收退回")
    p.add_argument("task_id")
    p.add_argument("--reason", default="")

    args = parser.parse_args(argv)

    engine, registry = build_registry(args.db, args.tz)
    try:
        tool, params = _map_command(args)
        payload = registry.call(tool, params)
        emit(payload, as_json=args.json)
        return 0
    except ToolError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 2
    finally:
        engine.close()


def _map_command(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    """把子命令映射到工具调用——CLI 与 MCP 共用同一套实现。"""
    match args.command:
        case "generate":
            return "generate_task_flow", {"requirement": args.requirement}
        case "templates":
            return "list_templates", {}
        case "from-template":
            return "create_flow_from_template", {"template": args.template, "title": args.title}
        case "flows":
            return "list_flows", {}
        case "dispatch":
            return "dispatch_task", {"flow_id": args.flow_id}
        case "schedule":
            params: dict[str, Any] = {"flow_id": args.flow_id}
            if args.mode:
                params["run_mode"] = args.mode
            if args.first_at:
                params["first_at"] = args.first_at
            if args.every:
                params["interval_value"] = args.every
            if args.unit:
                params["interval_unit"] = args.unit
            return "create_schedule", params
        case "schedules":
            return "list_schedules", {}
        case "tick":
            return "tick", {"now": args.now} if args.now else {}
        case "tasks":
            return "list_tasks", {
                "assignee": args.assignee, "state": args.state, "open_only": args.open_only,
            }
        case "task":
            return "get_task", {"task_id": args.task_id}
        case "complete":
            return "complete_step", {
                "task_id": args.task_id, "seq": args.seq, "actor": args.actor,
                "comment": args.comment, "attachments": args.attach,
            }
        case "forward":
            return "forward_step", {
                "task_id": args.task_id, "seq": args.seq,
                "to_ref": args.to_ref, "to_name": args.to_name,
            }
        case "accept":
            return "accept_task", {"task_id": args.task_id, "actor": args.actor}
        case "reject":
            return "reject_task", {"task_id": args.task_id, "reason": args.reason}
    raise ToolError(f"未知命令：{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
