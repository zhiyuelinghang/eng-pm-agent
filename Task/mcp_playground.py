#!/usr/bin/env python3.13
"""交互式 MCP 测试程序 —— 手动验证任务引擎。

启动真实的 MCP server 子进程，进入交互式命令行。你输入简短命令，
程序帮你调用对应的 MCP 工具，并把结果以友好的方式打印出来。

用法：
    .venv/bin/python mcp_playground.py              # 用 playground.db，复用已有数据
    .venv/bin/python mcp_playground.py --fresh      # 启动前清空数据
    .venv/bin/python mcp_playground.py --db 自定义.db

进入后输入 `help` 查看全部命令，输入 `demo` 自动跑一遍完整演示。
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SERVER = ROOT / "server.py"
PY = sys.executable

# 让 stdout 在管道/脚本驱动下也逐行输出，而不只在终端下才行缓冲
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# ── 终端颜色 ──────────────────────────────────────────────
def _c(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def title(text: str) -> str:
    return _c(text, "1;36")


def ok(text: str) -> str:
    return _c(text, "32")


def warn(text: str) -> str:
    return _c(text, "33")


def err(text: str) -> str:
    return _c(text, "31")


def dim(text: str) -> str:
    return _c(text, "2")


# ── MCP 客户端 ────────────────────────────────────────────
class MCP:
    """一个极简的 MCP stdio 客户端，只做我们要的三件事。"""

    def __init__(self, db: Path) -> None:
        self.proc = subprocess.Popen(
            [PY, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), text=True, bufsize=1,
            env={"PATH": "/usr/bin:/bin", "TASK_ENGINE_DB": str(db),
                 "TASK_ENGINE_TZ": "Asia/Shanghai", "TASK_ENGINE_AI_KEY": ""},
        )
        self._id = 0
        self._req("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        tools = self._req("tools/list", {})["result"]["tools"]
        self.tool_names = sorted(t["name"] for t in tools)

    def _req(self, method: str, params: dict) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"服务无响应。stderr:\n{self.proc.stderr.read()}")
        return json.loads(line)

    def call(self, tool: str, args: dict | None = None) -> dict:
        """调用工具，返回 (is_error, payload)。"""
        resp = self._req("tools/call", {"name": tool, "arguments": args or {}})
        result = resp.get("result")
        if result is None:
            return True, {"error": json.dumps(resp.get("error"), ensure_ascii=False)}
        return bool(result.get("isError")), result.get("structuredContent", {})

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


# ── 结果格式化 ────────────────────────────────────────────
STATE_COLOR = {
    "待开始": "2", "进行中": "36", "受阻": "33", "待验收": "35",
    "已完成": "32", "已取消": "31", "已逾期": "31",
}


def _short(uid: str) -> str:
    return uid[:16] if uid else ""


def _who(a: dict | None) -> str:
    if not a:
        return dim("待指定")
    return a.get("name") or a.get("ref") or "?"


def _show_task_brief(t: dict) -> None:
    st = t.get("state_label", "")
    color = STATE_COLOR.get(st, "0")
    site = t.get("site") or {}
    confirmer = t.get("confirmer") or {}
    owner = _who(t.get("current_assignee"))
    due = (t.get("due_at") or "")[:10]
    print(
        f"  {_c(f'[{st}]', color):<12} {t['title'][:24]:<26}"
        f" 进度 {t.get('progress', '?'):<6} 当前 {owner:<8}"
        f" 工点 {site.get('name', '-')[:12]:<14} 确认 {confirmer.get('name', '-')[:8]:<10}"
        f" 截止 {due}  {dim(_short(t['id']))}"
    )


def _show_step(s: dict) -> None:
    st = s.get("state_label", "")
    color = STATE_COLOR.get(st, "0")
    owner = _who(s.get("assignee"))
    due = (s.get("due_at") or "")[:10]
    mat = s.get("deliverable") or "-"
    flag = " ⚠需留证" if s.get("requires_attachment") else ""
    redo = _c(" [退回重做]", "35") if s.get("reopened") else ""
    print(
        f"    {s['seq'] + 1}. {_c(f'[{st}]', color):<10} {s['name'][:20]:<22}"
        f" {owner:<8} 截止 {due}  交付物 {mat[:16]}{flag}{redo}"
    )


def _show_task(t: dict) -> None:
    print(title(f"\n任务：{t.get('title')}  {dim(t['id'])}"))
    st = t.get("state_label", "")
    color = STATE_COLOR.get(st, "0")
    print(f"  状态 {_c(st, color)}  进度 {t.get('progress', {}).get('text', '?')}")
    site = t.get("site") or {}
    confirmer = t.get("confirmer") or {}
    print(f"  工点 {site.get('label') or site.get('name') or '-'}")
    print(f"  确认人 {_who(confirmer)}   截止 {(t.get('due_at') or '')[:10]}")
    if t.get("trigger_note"):
        print(f"  来源 {dim(t['trigger_note'][:60])}")
    print("  节点：")
    for s in t.get("steps", []):
        _show_step(s)
    hist = t.get("history")
    if hist:
        print(f"  历史（{len(hist)} 条）：")
        for h in hist[-10:]:
            who = h.get("actor") or "system"
            print(f"    {(h.get('at') or '')[:16].replace('T', ' ')}  "
                  f"{h.get('kind_label', '')}   {h.get('summary', '')[:40]}")
        if len(hist) > 10:
            print(f"    {dim(f'… 省略更早的 {len(hist) - 10} 条')}")


def show(result: dict, *, tool: str) -> None:
    """按工具类型选择展示方式。"""
    # 业务错误
    if result.get("error") and tool not in ("generate_task_flow",):
        print(err(f"\n✗ {result['error']}"))
        return

    if msg := result.get("message"):
        print(ok(f"\n✓ {msg}"))

    if "templates" in result:
        print(title("\n内置模板："))
        for t in result["templates"]:
            print(f"  {t['key']:<24} {t['label']}  "
                  f"({t['step_count']} 节点)  {dim(t['summary'])}")
        return

    if "flow" in result:
        f = result["flow"]
        print(title(f"\n任务流：{f['title']}  {dim(f['id'])}"))
        trig = f.get("trigger", {})
        print(f"  触发 {trig.get('description', '-')}")
        site = f.get("site") or {}
        conf = f.get("confirmer") or {}
        print(f"  工点 {site.get('label') or site.get('name') or '-'}"
              f"   确认人 {_who(conf)}")
        print("  节点：")
        for s in f.get("steps", []):
            owner = _who(s.get("assignee"))
            mat = s.get("deliverable") or "-"
            print(f"    {s['seq'] + 1}. {s['name'][:20]:<22} {owner:<8}"
                  f" 交付物 {mat[:16]}")
        if f.get("origin_note"):
            print(f"  {dim(f['origin_note'][:80])}")
        if result.get("next_step"):
            print(warn(f"  下一步：{result['next_step']}"))
        if missing := result.get("missing_requirements"):
            print(warn("  布置前还缺："))
            for m in missing:
                print(warn(f"    - {m}"))
        return

    if "flows" in result:
        if not result["flows"]:
            print(dim("\n（暂无任务流，用 gen 或 from 创建一个）"))
            return
        print(title(f"\n已保存的任务流（{result['count']} 个）："))
        for f in result["flows"]:
            trig = f.get("trigger", {}).get("description", "")
            print(f"  {f['title'][:24]:<26} {trig[:44]}  {dim(_short(f['id']))}")
        return

    if "tasks" in result:
        if not result["tasks"]:
            print(dim("\n（没有符合条件的任务）"))
            return
        print(title(f"\n任务列表（{result['count']} 个）："))
        for t in result["tasks"]:
            _show_task_brief(t)
        return

    if "task" in result:
        _show_task(result["task"])
        return

    if "schedule" in result:
        s = result["schedule"]
        print(ok(f"\n✓ {result.get('message', '')}"))
        print(f"  计划 {_short(s['id'])}  状态 {s.get('status')}")
        print(f"  触发 {s.get('trigger_description')}")
        print(f"  下次 {s.get('next_fire_at') or '无（已走完）'}"
              f"   已触发 {s.get('fire_count')} 次")
        if result.get("note"):
            print(warn(f"  {result['note']}"))
        return

    if "schedules" in result:
        if not result["schedules"]:
            print(dim("\n（暂无触发计划）"))
            return
        print(title(f"\n触发计划（{result['count']} 个）："))
        for s in result["schedules"]:
            print(f"  [{s.get('status')}] {s['title'][:20]:<22} "
                  f"{s.get('trigger_description', '')[:36]:<38} "
                  f"下次 {s.get('next_fire_at') or '无'}  {dim(_short(s['id']))}")
        return

    if "at" in result and tool == "tick":
        print(ok(f"\n✓ {result['message']}"))
        if result.get("created_tasks"):
            print(f"  新建任务：{', '.join(_short(t) for t in result['created_tasks'])}")
        if result.get("overdue_task_ids"):
            print(warn(f"  标记逾期：{', '.join(_short(t) for t in result['overdue_task_ids'])}"))
        return

    # 兜底：原样打印
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


# ── id 前缀匹配 ───────────────────────────────────────────
def collect_ids(mcp: MCP) -> dict[str, str]:
    """收集所有已知的 flow / task / schedule id，供前缀匹配。"""
    ids: dict[str, str] = {}
    for tool in ("list_flows", "list_tasks", "list_schedules"):
        ok_, payload = mcp.call(tool)
        if ok_:
            continue
        for key in ("flows", "tasks", "schedules"):
            for item in payload.get(key, []):
                ids[item["id"]] = item.get("title", "")
    return ids


def resolve(prefix: str, ids: dict[str, str]) -> str:
    """前缀唯一匹配；完整匹配直接返回；不唯一或匹配不到则原样返回。"""
    if prefix in ids:
        return prefix
    matches = [i for i in ids if i.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    return prefix


# ── 命令实现 ──────────────────────────────────────────────
def cmd_templates(mcp: MCP) -> None:
    _, r = mcp.call("list_templates")
    show(r, tool="list_templates")


def cmd_gen(mcp: MCP, requirement: str, assignees: list, confirmer: str, site: str) -> None:
    args = {"requirement": requirement}
    if assignees:
        args["assignees"] = [{"ref": f"u{i}", "name": n} for i, n in enumerate(assignees, 1)]
    if confirmer:
        args["confirmer"] = {"ref": confirmer, "name": confirmer}
    if site:
        args["site"] = {"ref": site, "name": site}
    _, r = mcp.call("generate_task_flow", args)
    show(r, tool="generate_task_flow")


def cmd_from(mcp: MCP, template: str, flow_title: str, assignees: list,
             confirmer: str, site: str) -> None:
    args = {"template": template, "title": flow_title}
    if assignees:
        args["assignees"] = [{"ref": f"u{i}", "name": n} for i, n in enumerate(assignees, 1)]
    if confirmer:
        args["confirmer"] = {"ref": confirmer, "name": confirmer}
    if site:
        args["site"] = {"ref": site, "name": site}
    _, r = mcp.call("create_flow_from_template", args)
    show(r, tool="create_flow_from_template")


def cmd_flows(mcp: MCP) -> None:
    _, r = mcp.call("list_flows")
    show(r, tool="list_flows")


def cmd_dispatch(mcp: MCP, flow_id: str, actor: str = "operator") -> None:
    _, r = mcp.call("dispatch_task", {"flow_id": flow_id, "actor": actor})
    show(r, tool="dispatch_task")


def cmd_schedule(mcp: MCP, flow_id: str, mode: str, at: str, every: int, unit: str) -> None:
    args = {"flow_id": flow_id, "run_mode": mode, "first_at": at}
    if every:
        args["interval_value"] = every
    if unit:
        args["interval_unit"] = unit
    _, r = mcp.call("create_schedule", args)
    show(r, tool="create_schedule")


def cmd_schedules(mcp: MCP) -> None:
    _, r = mcp.call("list_schedules")
    show(r, tool="list_schedules")


def cmd_pause(mcp: MCP, schedule_id: str, paused: bool) -> None:
    _, r = mcp.call("pause_schedule", {"schedule_id": schedule_id, "paused": paused})
    show(r, tool="pause_schedule")


def cmd_cancel_sched(mcp: MCP, schedule_id: str) -> None:
    _, r = mcp.call("cancel_schedule", {"schedule_id": schedule_id})
    show(r, tool="cancel_schedule")


def cmd_tick(mcp: MCP, now: str | None) -> None:
    args = {"now": now} if now else {}
    _, r = mcp.call("tick", args)
    show(r, tool="tick")


def cmd_tasks(mcp: MCP, assignee: str, state: str, site: str, open_only: bool) -> None:
    args = {}
    if assignee:
        args["assignee"] = assignee
    if state:
        args["state"] = state
    if site:
        args["site"] = site
    if open_only:
        args["open_only"] = True
    args["limit"] = 50
    _, r = mcp.call("list_tasks", args)
    show(r, tool="list_tasks")


def cmd_task(mcp: MCP, task_id: str) -> None:
    _, r = mcp.call("get_task", {"task_id": task_id, "include_history": True})
    show(r, tool="get_task")


def cmd_complete(mcp: MCP, task_id: str, seq: int, actor: str,
                 comment: str, attachments: list) -> None:
    args = {"task_id": task_id, "seq": seq, "actor": actor, "comment": comment}
    if attachments:
        args["attachments"] = attachments
    _, r = mcp.call("complete_step", args)
    show(r, tool="complete_step")


def cmd_forward(mcp: MCP, task_id: str, seq: int, to_ref: str, to_name: str, actor: str) -> None:
    _, r = mcp.call("forward_step", {
        "task_id": task_id, "seq": seq, "to_ref": to_ref,
        "to_name": to_name or to_ref, "actor": actor,
    })
    show(r, tool="forward_step")


def cmd_block(mcp: MCP, task_id: str, seq: int, reason: str) -> None:
    _, r = mcp.call("block_step", {"task_id": task_id, "seq": seq, "reason": reason})
    show(r, tool="block_step")


def cmd_unblock(mcp: MCP, task_id: str, seq: int) -> None:
    _, r = mcp.call("unblock_step", {"task_id": task_id, "seq": seq})
    show(r, tool="unblock_step")


def cmd_note(mcp: MCP, task_id: str, text: str) -> None:
    _, r = mcp.call("add_note", {"task_id": task_id, "note": text})
    show(r, tool="add_note")


def cmd_accept(mcp: MCP, task_id: str, actor: str = "confirmer") -> None:
    _, r = mcp.call("accept_task", {"task_id": task_id, "actor": actor})
    show(r, tool="accept_task")


def cmd_reject(mcp: MCP, task_id: str, reason: str, actor: str = "confirmer") -> None:
    _, r = mcp.call("reject_task", {"task_id": task_id, "reason": reason, "actor": actor})
    show(r, tool="reject_task")


def cmd_cancel(mcp: MCP, task_id: str, reason: str) -> None:
    _, r = mcp.call("cancel_task", {"task_id": task_id, "reason": reason})
    show(r, tool="cancel_task")


def cmd_raw(mcp: MCP, tool: str, args_json: str) -> None:
    args = json.loads(args_json) if args_json else {}
    _, r = mcp.call(tool, args)
    show(r, tool=tool)


HELP = f"""{title('任务引擎 MCP 测试台')}

命令（方括号内为可选参数，< > 为必填）：

  {ok('生成与模板')}
    gen <需求描述> [--assignee 张三,李四] [--confirmer 王工] [--site 3号楼]
        自然语言生成任务流，自动识别周期触发
    from <模板名> [标题] [--assignee ...] [--confirmer ...] [--site ...]
        按模板创建，模板名可用中文（如「隐患整改」）或 key（如 hazard_rectification）
    templates            列出内置模板
    flows                列出已保存的任务流

  {ok('布置与调度')}
    dispatch <flow前缀> [--actor 谁]        立即布置任务
    schedule <flow前缀> --at "2026-08-21 09:00" [--mode recurring] [--every 1] [--unit week]
        登记定时计划；--mode 为 once 或 recurring
    schedules / pause <sched前缀> / cancel-sched <sched前缀>

  {ok('推进与查询')}
    tick [--now "2026-08-21 09:00"]          推进引擎（不带 --now 用系统时间）
    tasks [--assignee u1] [--state running] [--site 前缀] [--open]
    task <task前缀>                          任务详情 + 历史

  {ok('办理')}
    complete <task前缀> <节点序号> [--attach a.jpg,b.pdf] [--comment 文字] [--actor u1]
        完成节点并推进（序号从 1 开始）
    forward <task前缀> <节点序号> <新责任人ref> [姓名]
    block <task前缀> <节点序号> [原因]       标记受阻
    unblock <task前缀> <节点序号>            解除受阻
    note <task前缀> <文字>                   添加说明

  {ok('闭环')}
    accept <task前缀>                       验收通过
    reject <task前缀> [原因]                退回重做
    cancel <task前缀> [原因]                取消任务

  {ok('其他')}
    raw <工具名> [json参数]                 直接调用任意 MCP 工具
    demo                                    自动跑一遍完整演示
    fresh                                   清空数据重新开始
    help / quit / exit

提示：flow/task/schedule 的 id 可以只输入前几位（如 {dim('task_ab12')}），
程序会自动前缀匹配完整 id。节点序号按展示的 1-based 序号填写。
"""


def cmd_help() -> None:
    print(HELP)


def cmd_demo(mcp: MCP) -> None:
    """自动跑一遍完整演示，展示核心能力。"""
    print(title("\n=== 演示开始 ==="))

    print(title("\n[1/8] 按模板创建任务流（三要素齐备）"))
    _, flow = mcp.call("create_flow_from_template", {
        "template": "隐患整改", "title": "3号楼临边防护整改",
        "assignees": [{"ref": "u1", "name": "张三"}, {"ref": "u2", "name": "李四"}],
        "confirmer": {"ref": "boss", "name": "王工"},
        "site": {"ref": "wbs-3", "name": "3号楼-地下室", "code": "WBS-03-B1"},
    })
    show(flow, tool="create_flow_from_template")
    flow_id = flow["flow"]["id"]

    print(title("\n[2/8] 立即布置任务"))
    _, task = mcp.call("dispatch_task", {"flow_id": flow_id, "actor": "demo"})
    show(task, tool="dispatch_task")
    task_id = task["task"]["id"]

    print(title("\n[3/8] 张三的待办（按责任人过滤）"))
    _, mine = mcp.call("list_tasks", {"assignee": "u1", "limit": 20})
    show(mine, tool="list_tasks")

    print(title("\n[4/8] 逐个完成节点（留证节点自动带附件）"))
    for _ in range(20):
        _, d = mcp.call("get_task", {"task_id": task_id})
        cur = d.get("task", {}).get("current_step")
        if cur is None:
            break
        seq = cur["seq"]
        need_attach = d["task"]["steps"][seq].get("requires_attachment")
        args = {"task_id": task_id, "seq": seq, "actor": "u1", "comment": "已完成"}
        if need_attach:
            args["attachments"] = [f"证据-{seq + 1}.jpg"]
        _, r = mcp.call("complete_step", args)
        show(r, tool="complete_step")

    print(title("\n[5/8] 确认人退回重做"))
    _, r = mcp.call("reject_task", {"task_id": task_id, "reason": "归档材料不完整，重做", "actor": "boss"})
    show(r, tool="reject_task")

    print(title("\n[6/8] 重新完成被退回的节点"))
    _, d = mcp.call("get_task", {"task_id": task_id})
    cur = d["task"].get("current_step")
    if cur is None:
        print(warn("（没有待重做的节点）"))
    else:
        seq = cur["seq"]
        step = d["task"]["steps"][seq]
        print(dim(f"  被退回的节点：{step['name']}"
                  f"{'（要求留证）' if step.get('requires_attachment') else '（不强制留证，可直接重做）'}"))
        args = {"task_id": task_id, "seq": seq, "actor": "u1", "comment": "已补充"}
        if step.get("requires_attachment"):
            # 留证节点：先演示不带附件被拒
            _, denied = mcp.call("complete_step", {"task_id": task_id, "seq": seq, "actor": "u1"})
            print(err(f"  ✗ 不带附件 → {denied.get('error', '被拒绝')}"))
            args["attachments"] = ["补充后的新材料.jpg"]
        _, r = mcp.call("complete_step", args)
        show(r, tool="complete_step")

    print(title("\n[7/8] 确认人验收 → 闭环"))
    _, r = mcp.call("accept_task", {"task_id": task_id, "actor": "boss"})
    show(r, tool="accept_task")

    print(title("\n[8/8] 查看完整历史"))
    _, r = mcp.call("get_task", {"task_id": task_id, "include_history": True})
    _show_task(r["task"])

    print(title("\n=== 演示结束 ==="))
    print(dim(f"任务 id：{task_id}，可用 `task {task_id[:12]}` 随时查看"))


# ── 交互循环 ──────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="任务引擎 MCP 交互式测试台")
    parser.add_argument("--db", default=str(ROOT / "playground.db"))
    parser.add_argument("--fresh", action="store_true", help="启动前清空数据")
    args = parser.parse_args()

    db = Path(args.db)
    if args.fresh:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)

    mcp = MCP(db)
    print(HELP)
    print(dim(f"已连接 server，暴露 {len(mcp.tool_names)} 个 MCP 工具。数据库：{db.name}"))
    print(dim(f"数据{'已清空' if args.fresh else '复用已有' }。输入命令开始，help 查看命令。"))

    try:
        while True:
            try:
                line = input(f"\n{title('任务引擎')} > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue

            parts = shlex.split(line)
            cmd, rest = parts[0], parts[1:]

            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help" or cmd == "?":
                cmd_help()
            elif cmd == "fresh":
                for suffix in ("", "-wal", "-shm"):
                    Path(str(db) + suffix).unlink(missing_ok=True)
                print(ok("数据已清空。"))
                mcp.close()
                mcp = MCP(db)
            elif cmd == "demo":
                cmd_demo(mcp)
            elif cmd == "templates":
                cmd_templates(mcp)
            elif cmd == "flows":
                cmd_flows(mcp)
            elif cmd == "schedules":
                cmd_schedules(mcp)
            elif cmd == "tick":
                now = _opt(rest, "--now")
                cmd_tick(mcp, now)
            elif cmd == "tasks":
                cmd_tasks(mcp, _opt(rest, "--assignee"), _opt(rest, "--state"),
                          _opt(rest, "--site"), _has(rest, "--open"))
            elif cmd == "gen":
                if not rest:
                    print(err("用法：gen <需求描述> [--assignee 张三,李四] ..."))
                    continue
                req = rest[0] if not rest[0].startswith("--") else ""
                cmd_gen(mcp, req, _csv(_opt(rest, "--assignee")),
                        _opt(rest, "--confirmer"), _opt(rest, "--site"))
            elif cmd == "from":
                if not rest:
                    print(err("用法：from <模板名> [标题] [--assignee ...] ..."))
                    continue
                tpl = rest[0]
                ttl = rest[1] if len(rest) > 1 and not rest[1].startswith("--") else ""
                cmd_from(mcp, tpl, ttl, _csv(_opt(rest, "--assignee")),
                         _opt(rest, "--confirmer"), _opt(rest, "--site"))
            elif cmd == "dispatch":
                if not rest:
                    print(err("用法：dispatch <flow前缀> [--actor 谁]"))
                    continue
                cmd_dispatch(mcp, resolve(rest[0], collect_ids(mcp)),
                             _opt(rest, "--actor") or "operator")
            elif cmd == "schedule":
                if not rest:
                    print(err('用法：schedule <flow前缀> --at "时刻" [--mode recurring] [--every N] [--unit week]'))
                    continue
                at = _opt(rest, "--at")
                if not at:
                    print(err("必须用 --at 指定首次触发时刻，如 --at \"2026-08-21 09:00\""))
                    continue
                every = _opt(rest, "--every")
                cmd_schedule(mcp, resolve(rest[0], collect_ids(mcp)),
                             _opt(rest, "--mode") or "once", at,
                             int(every) if every else 0, _opt(rest, "--unit"))
            elif cmd == "pause":
                if not rest:
                    print(err("用法：pause <schedule前缀>"))
                    continue
                cmd_pause(mcp, resolve(rest[0], collect_ids(mcp)), True)
            elif cmd == "cancel-sched":
                if not rest:
                    print(err("用法：cancel-sched <schedule前缀>"))
                    continue
                cmd_cancel_sched(mcp, resolve(rest[0], collect_ids(mcp)))
            elif cmd == "task":
                if not rest:
                    print(err("用法：task <task前缀>"))
                    continue
                cmd_task(mcp, resolve(rest[0], collect_ids(mcp)))
            elif cmd == "complete":
                if len(rest) < 2:
                    print(err("用法：complete <task前缀> <节点序号(1开始)> [--attach a.jpg] [--comment 文字]"))
                    continue
                seq = _int(rest[1])
                if seq is None:
                    print(err("节点序号必须是数字"))
                    continue
                cmd_complete(mcp, resolve(rest[0], collect_ids(mcp)), seq - 1,
                             _opt(rest, "--actor") or "u1",
                             _opt(rest, "--comment") or "",
                             _csv(_opt(rest, "--attach")))
            elif cmd == "forward":
                if len(rest) < 3:
                    print(err("用法：forward <task前缀> <节点序号> <新责任人ref> [姓名]"))
                    continue
                seq = _int(rest[1])
                if seq is None:
                    print(err("节点序号必须是数字"))
                    continue
                name = rest[3] if len(rest) > 3 else ""
                cmd_forward(mcp, resolve(rest[0], collect_ids(mcp)), seq - 1,
                            rest[2], name, _opt(rest, "--actor") or "u1")
            elif cmd == "block":
                if len(rest) < 2:
                    print(err("用法：block <task前缀> <节点序号> [原因]"))
                    continue
                seq = _int(rest[1])
                if seq is None:
                    print(err("节点序号必须是数字"))
                    continue
                cmd_block(mcp, resolve(rest[0], collect_ids(mcp)), seq - 1,
                          " ".join(rest[2:]) or "等待条件")
            elif cmd == "unblock":
                if len(rest) < 2:
                    print(err("用法：unblock <task前缀> <节点序号>"))
                    continue
                seq = _int(rest[1])
                if seq is None:
                    print(err("节点序号必须是数字"))
                    continue
                cmd_unblock(mcp, resolve(rest[0], collect_ids(mcp)), seq - 1)
            elif cmd == "note":
                if len(rest) < 2:
                    print(err("用法：note <task前缀> <文字>"))
                    continue
                cmd_note(mcp, resolve(rest[0], collect_ids(mcp)), " ".join(rest[1:]))
            elif cmd == "accept":
                if not rest:
                    print(err("用法：accept <task前缀>"))
                    continue
                cmd_accept(mcp, resolve(rest[0], collect_ids(mcp)), _opt(rest, "--actor") or "confirmer")
            elif cmd == "reject":
                if not rest:
                    print(err("用法：reject <task前缀> [原因]"))
                    continue
                cmd_reject(mcp, resolve(rest[0], collect_ids(mcp)), " ".join(rest[1:]) or "不合格")
            elif cmd == "cancel":
                if not rest:
                    print(err("用法：cancel <task前缀> [原因]"))
                    continue
                cmd_cancel(mcp, resolve(rest[0], collect_ids(mcp)), " ".join(rest[1:]) or "不需要了")
            elif cmd == "raw":
                if not rest:
                    print(err("用法：raw <工具名> [json参数]"))
                    continue
                cmd_raw(mcp, rest[0], " ".join(rest[1:]))
            else:
                print(err(f"未知命令：{cmd}（输入 help 查看命令）"))
    finally:
        mcp.close()
        print(dim("\n已断开，再见。"))


def _opt(args: list, key: str) -> str | None:
    for i, a in enumerate(args):
        if a == key and i + 1 < len(args):
            return args[i + 1]
    return None


def _has(args: list, key: str) -> bool:
    return key in args


def _csv(s: str | None) -> list:
    if not s:
        return []
    return [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]


def _int(s: str) -> int | None:
    try:
        return int(s)
    except ValueError:
        return None


if __name__ == "__main__":
    main()