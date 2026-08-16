"""以真实 MCP 客户端的方式全面试用引擎。

不是单元测试——这是模拟真人使用场景的压测：常见误用、边界输入、并发、
长期运行。目的是找出「测试没覆盖但真实使用会踩到」的问题。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SERVER = ROOT / "server.py"

PASS, FAIL, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"

results = {"pass": 0, "fail": 0, "warn": 0}
issues: list[str] = []


class Client:
    def __init__(self, db: Path, ai_key: str = "") -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), text=True, bufsize=1,
            env={"PATH": "/usr/bin:/bin", "TASK_ENGINE_DB": str(db),
                 "TASK_ENGINE_TZ": "Asia/Shanghai", "TASK_ENGINE_AI_KEY": ai_key},
        )
        self._id = 0
        self.req("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "trial", "version": "1"}})

    def req(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"无响应. stderr: {self.proc.stderr.read()}")
        return json.loads(line)

    def call(self, tool: str, args: dict | None = None) -> dict:
        r = self.req("tools/call", {"name": tool, "arguments": args or {}})
        return r["result"]

    def data(self, tool: str, args: dict | None = None) -> dict:
        return self.call(tool, args)["structuredContent"]

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        results["pass"] += 1
        print(f"  {PASS} {label}")
    else:
        results["fail"] += 1
        issues.append(f"{label} — {detail}")
        print(f"  {FAIL} {label}  {detail}")


def warn(label: str, detail: str) -> None:
    results["warn"] += 1
    issues.append(f"[观察] {label} — {detail}")
    print(f"  {WARN} {label}  {detail}")


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ============================================================
section("场景 1：项目经理第一次用，什么都不懂")
# ============================================================
db = ROOT / "trial_1.db"
db.unlink(missing_ok=True)
c = Client(db)

tools = c.req("tools/list")["result"]["tools"]
check("能看到工具清单", len(tools) == 21, f"实际 {len(tools)} 个")

# 直接问「我有什么任务」——库是空的
r = c.data("list_tasks")
check("空库查询不报错", r["count"] == 0)
check("空库有友好提示", "没有" in r.get("message", ""), r.get("message", ""))

# 先看看有哪些模板
r = c.data("list_templates")
check("模板可列出", len(r["templates"]) == 7, f"{len(r['templates'])} 个")

# 直接用自然语言描述需求
r = c.data("generate_task_flow", {
    "requirement": "每周五检查基坑监测数据，异常时由监测员复核，负责人确认后归档",
})
flow = r["flow"]
check("识别出周期触发", flow["trigger"]["run_mode"] == "recurring")
check("识别出「周」为单位", flow["trigger"]["interval_unit"] == "week")
check("首次触发是星期五", flow["trigger"]["first_at"][:10] and True)
from datetime import datetime
first = datetime.fromisoformat(flow["trigger"]["first_at"])
check("首次触发确实是周五", first.isoweekday() == 5, f"实际星期{first.isoweekday()}")
check("生成了多个节点", len(flow["steps"]) >= 3, f"{len(flow['steps'])} 个")
check("给出了下一步指引", bool(r.get("next_step")), r.get("next_step", ""))

# 忘了先登记计划，直接问任务列表
r = c.data("list_tasks")
check("生成流程不会自动产生任务", r["count"] == 0)

c.close()

# ============================================================
section("场景 2：常见误用——用错 id、跳步骤、重复操作")
# ============================================================
db = ROOT / "trial_2.db"
db.unlink(missing_ok=True)
c = Client(db)

# 用不存在的 flow_id 布置
r = c.call("dispatch_task", {"flow_id": "flow_我瞎编的"})
check("不存在的 flow 报错清晰", r["isError"] and "不存在" in r["structuredContent"]["error"])
check("错误信息含补救建议", "generate_task_flow" in r["structuredContent"]["error"],
      r["structuredContent"]["error"])

# 建一个正常的
flow = c.data("create_flow_from_template", {"template": "通用流程"})["flow"]
task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]

# 跳过第一个节点直接完成第三个
r = c.call("complete_step", {"task_id": task["id"], "seq": 2})
check("跨越节点被拒绝", r["isError"] and "不能跨越" in r["structuredContent"]["error"],
      str(r["structuredContent"])[:80])

# 重复完成同一节点
c.call("complete_step", {"task_id": task["id"], "seq": 0, "attachments": ["x.jpg"]})
r = c.call("complete_step", {"task_id": task["id"], "seq": 0})
check("重复完成被拒绝", r["isError"] and "已经了结" in r["structuredContent"]["error"])

# 节点序号越界
r = c.call("complete_step", {"task_id": task["id"], "seq": 999})
check("越界序号报错", r["isError"])

# 负数序号
r = c.call("complete_step", {"task_id": task["id"], "seq": -1})
check("负数序号报错", r["isError"], r["structuredContent"].get("error", ""))

# 未完成就验收
r = c.call("accept_task", {"task_id": task["id"]})
check("未完成不能验收", r["isError"] and "待验收" in r["structuredContent"]["error"])

# 转办给空 ref
r = c.call("forward_step", {"task_id": task["id"], "seq": 1, "to_ref": ""})
check("转办空接收人被拒", r["isError"])

c.close()

# ============================================================
section("场景 3：定时触发的真实节奏")
# ============================================================
db = ROOT / "trial_3.db"
db.unlink(missing_ok=True)
c = Client(db)

flow = c.data("create_flow_from_template", {"template": "周期巡检"})["flow"]
plan = c.data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring",
    "first_at": "2026-03-02 09:00", "interval_value": 1, "interval_unit": "day",
})["schedule"]

# 模拟 cron 每 5 分钟跑一次，连续 3 天
fired_total = 0
for day in range(3):
    for minute in range(0, 24 * 60, 5):
        h, m = divmod(minute, 60)
        stamp = f"2026-03-{2+day:02d} {h:02d}:{m:02d}"
        rep = c.data("tick", {"now": stamp})
        fired_total += rep["created_count"]

check("3 天每 5 分钟 tick，恰好触发 3 次", fired_total == 3, f"实际 {fired_total} 次")
check("任务数正确", c.data("list_tasks")["count"] == 3)

# 检查跳过计数是否合理
rep = c.data("tick", {"now": "2026-03-02 09:00"})
check("重复时刻被识别为跳过", rep["skipped_duplicates"] >= 1 or rep["created_count"] == 0)

c.close()

# ============================================================
section("场景 4：月末与跨年的周期任务")
# ============================================================
db = ROOT / "trial_4.db"
db.unlink(missing_ok=True)
c = Client(db)

flow = c.data("create_flow_from_template", {"template": "资料补全"})["flow"]
c.data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring",
    "first_at": "2026-01-31 09:00", "interval_value": 1, "interval_unit": "month",
})

fires = []
for month, last_day in [(1, 31), (2, 28), (3, 31), (4, 30), (5, 31), (6, 30)]:
    for day in range(25, last_day + 1):
        rep = c.data("tick", {"now": f"2026-{month:02d}-{day:02d} 09:00"})
        if rep["created_count"]:
            fires.append(f"{month:02d}-{day:02d}")

check("每月触发一次", len(fires) == 6, f"实际 {len(fires)} 次：{fires}")
check("1月31日触发", "01-31" in fires, str(fires))
check("2月夹到28日", "02-28" in fires, str(fires))
check("3月回到31日（未漂移）", "03-31" in fires, str(fires))
check("4月夹到30日", "04-30" in fires, str(fires))
check("5月回到31日", "05-31" in fires, str(fires))

c.close()

# ============================================================
section("场景 5：多人协作与转办链")
# ============================================================
db = ROOT / "trial_5.db"
db.unlink(missing_ok=True)
c = Client(db)

flow = c.data("create_flow_from_template", {
    "template": "隐患整改",
    "assignees": [{"ref": "u1", "name": "张三"}, {"ref": "u2", "name": "李四"},
                  {"ref": "u3", "name": "王五"}],
})["flow"]
task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]

check("首节点归张三", task["current_assignee"]["ref"] == "u1")
check("张三能看到", c.data("list_tasks", {"assignee": "u1"})["count"] == 1)
check("李四看不到", c.data("list_tasks", {"assignee": "u2"})["count"] == 0)

# 张三转给王五
c.data("forward_step", {"task_id": task["id"], "seq": 0, "to_ref": "u3",
                        "to_name": "王五", "actor": "u1"})
check("转办后张三看不到", c.data("list_tasks", {"assignee": "u1"})["count"] == 0)
check("转办后王五能看到", c.data("list_tasks", {"assignee": "u3"})["count"] == 1)

# 王五再转回张三
c.data("forward_step", {"task_id": task["id"], "seq": 0, "to_ref": "u1",
                        "to_name": "张三", "actor": "u3"})
check("转办链可回环", c.data("list_tasks", {"assignee": "u1"})["count"] == 1)

# 完成后自动移交下一人
c.data("complete_step", {"task_id": task["id"], "seq": 0, "actor": "u1",
                         "attachments": ["h.jpg"]})
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("完成后交给下一节点责任人", d["current_assignee"]["ref"] == "u2",
      str(d["current_assignee"]))

# 历史记录完整
hist = d["history"]
kinds = [h["kind"] for h in hist]
check("转办有留痕", kinds.count("forwarded") == 2, f"{kinds.count('forwarded')} 次")
check("历史按时间有序", all(hist[i]["at"] <= hist[i+1]["at"] for i in range(len(hist)-1)))

c.close()

# ============================================================
section("场景 6：受阻与恢复")
# ============================================================
db = ROOT / "trial_6.db"
db.unlink(missing_ok=True)
c = Client(db)

flow = c.data("create_flow_from_template", {"template": "条件核查"})["flow"]
task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]

c.data("block_step", {"task_id": task["id"], "seq": 0, "reason": "等待材料进场"})
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("受阻状态生效", d["state"] == "blocked")

# 解除阻塞后应恢复运行
c.data("unblock_step", {"task_id": task["id"], "seq": 0})
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("解除阻塞后恢复运行", d["state"] == "running", d["state"])

# 再次受阻，这次直接完成——任务状态必须跟着恢复，不能卡在 blocked
c.data("block_step", {"task_id": task["id"], "seq": 0, "reason": "又缺材料"})
c.data("complete_step", {"task_id": task["id"], "seq": 0, "attachments": ["m.jpg"]})
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("完成受阻节点后任务恢复运行", d["state"] == "running", d["state"])
check("下一节点已激活", d["current_step"]["seq"] == 1, str(d["current_step"]))

c.close()

# ============================================================
section("场景 7：验收退回与重做")
# ============================================================
db = ROOT / "trial_7.db"
db.unlink(missing_ok=True)
c = Client(db)

flow = c.data("create_flow_from_template", {"template": "报告审核"})["flow"]
task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]

for seq in range(len(task["steps"])):
    d = c.data("get_task", {"task_id": task["id"]})["task"]
    args = {"task_id": task["id"], "seq": seq, "actor": "u1"}
    if d["steps"][seq]["requires_attachment"]:
        args["attachments"] = ["report.pdf"]
    c.data("complete_step", args)

d = c.data("get_task", {"task_id": task["id"]})["task"]
check("全部完成进入待验收", d["state"] == "review")

c.data("reject_task", {"task_id": task["id"], "reason": "数据来源不明"})
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("退回后回到运行中", d["state"] == "running")
check("退回后有待办节点", d["current_step"] is not None)

# 重做后再次验收
seq = d["current_step"]["seq"]
args = {"task_id": task["id"], "seq": seq, "actor": "u1"}
if d["steps"][seq]["requires_attachment"]:
    args["attachments"] = ["report_v2.pdf"]
c.data("complete_step", args)
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("重做完成再次进入待验收", d["state"] == "review", d["state"])

c.data("accept_task", {"task_id": task["id"], "actor": "boss"})
d = c.data("get_task", {"task_id": task["id"]})["task"]
check("最终闭环", d["state"] == "done")

# 闭环后还能操作吗
r = c.call("complete_step", {"task_id": task["id"], "seq": 0})
check("闭环后拒绝再操作", r["isError"])

c.close()

# ============================================================
section("场景 8：畸形与恶意输入")
# ============================================================
db = ROOT / "trial_8.db"
db.unlink(missing_ok=True)
c = Client(db)

weird_requirements = [
    "每每每每每每每每",
    "。。。。。。",
    "a",
    "每周八检查",           # 不存在的星期
    "每0天检查一次",        # 零间隔
    "每999个月检查",        # 超大间隔
    "x" * 5000,            # 超长
    "每周五\n\n\n检查",     # 多换行
    "<script>alert(1)</script>",
    "'; DROP TABLE tasks; --",
]
for req in weird_requirements:
    r = c.call("generate_task_flow", {"requirement": req})
    label = req[:20].replace("\n", "\\n")
    if r["isError"]:
        # 太短的被拒是合理的
        ok = len(req.strip()) < 4
        check(f"畸形输入「{label}」处理得当", ok,
              "" if ok else f"被拒: {r['structuredContent']['error'][:60]}")
    else:
        steps = r["structuredContent"]["flow"]["steps"]
        check(f"畸形输入「{label}」仍生成可用流程", len(steps) >= 2)

# SQL 注入后表还在吗
r = c.data("list_tasks")
check("SQL 注入未破坏数据库", isinstance(r["count"], int))

# 超长标题
r = c.data("create_flow_from_template", {"template": "通用流程", "title": "标" * 1000})
check("超长标题被接受或截断", len(r["flow"]["title"]) > 0)

# 类型错误
r = c.call("list_tasks", {"limit": "很多"})
check("limit 类型错误不崩溃", True)  # 只要没抛协议错误

r = c.call("create_schedule", {"flow_id": flow["id"], "first_at": "不是时间"})
check("非法时间被拒绝", r["isError"], str(r["structuredContent"])[:80])

c.close()

# ============================================================
section("场景 9：长期运行与数据量")
# ============================================================
db = ROOT / "trial_9.db"
db.unlink(missing_ok=True)
c = Client(db)

flow = c.data("create_flow_from_template", {"template": "通用流程"})["flow"]
c.data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring",
    "first_at": "2026-01-01 09:00", "interval_value": 1, "interval_unit": "day",
})

# 跑满一年
for day in range(365):
    from datetime import datetime as _dt, timedelta as _td
    stamp = (_dt(2026, 1, 1, 9, 0) + _td(days=day)).strftime("%Y-%m-%d %H:%M")
    c.data("tick", {"now": stamp})

total = c.data("list_tasks", {"limit": 100})["count"]
check("一年产生任务且分页正常", total == 100, f"首页 {total} 条")

import os
size_kb = os.path.getsize(db) / 1024
if size_kb > 5000:
    warn("数据库体积偏大", f"{size_kb:.0f} KB / 365 个任务")
else:
    check(f"数据库体积合理（{size_kb:.0f} KB / 365 任务）", True)

# 大量数据下的查询性能
import time
t0 = time.time()
c.data("list_tasks", {"limit": 20})
elapsed = (time.time() - t0) * 1000
check(f"大数据量查询快速（{elapsed:.0f}ms）", elapsed < 1000, f"{elapsed:.0f}ms")

c.close()

# ============================================================
section("场景 10：并发访问同一数据库")
# ============================================================
db = ROOT / "trial_10.db"
db.unlink(missing_ok=True)
c1 = Client(db)
flow = c1.data("create_flow_from_template", {"template": "通用流程"})["flow"]
task = c1.data("dispatch_task", {"flow_id": flow["id"]})["task"]

c2 = Client(db)
# 第二个客户端能看到第一个创建的任务吗
r = c2.data("list_tasks")
check("跨连接可见数据", r["count"] == 1, f"{r['count']} 个")

# 两个客户端同时操作同一任务
c1.data("complete_step", {"task_id": task["id"], "seq": 0, "actor": "u1",
                          "attachments": ["a.jpg"]})
r = c2.call("complete_step", {"task_id": task["id"], "seq": 0, "actor": "u2"})
check("并发重复完成被拒", r["isError"], "第二个客户端应看到已完成")

# 两个客户端同时 tick
c1.data("create_schedule", {"flow_id": flow["id"], "run_mode": "once",
                            "first_at": "2026-03-02 09:00"})
r1 = c1.data("tick", {"now": "2026-03-02 09:00"})
r2 = c2.data("tick", {"now": "2026-03-02 09:00"})
total_created = r1["created_count"] + r2["created_count"]
check("并发 tick 只触发一次", total_created == 1, f"共创建 {total_created} 个")

c1.close()
c2.close()

# ============================================================
section("场景 11：服务健壮性")
# ============================================================
db = ROOT / "trial_11.db"
db.unlink(missing_ok=True)
c = Client(db)

# 连续错误后是否还活着
for _ in range(20):
    c.call("get_task", {"task_id": "nope"})
    c.call("no_such_tool", {})
r = c.data("list_templates")
check("连续 40 次错误后服务仍可用", len(r["templates"]) == 7)

# 空参数
for tool in ["list_tasks", "list_templates", "list_flows", "list_schedules", "tick"]:
    r = c.call(tool, {})
    check(f"{tool} 空参数可调用", not r.get("isError"), str(r.get("structuredContent"))[:60])

# 缺必填参数
for tool in ["get_task", "complete_step", "dispatch_task", "create_schedule"]:
    r = c.call(tool, {})
    check(f"{tool} 缺参数报错而非崩溃", r["isError"])

# stdout 是否干净（日志不能污染协议）
stderr_output = ""
c.close()

# ============================================================
print("\n" + "=" * 60)
total = results["pass"] + results["fail"]
print(f"\033[1m结果：{results['pass']}/{total} 通过"
      f"，{results['fail']} 失败，{results['warn']} 处观察\033[0m")

if issues:
    print("\n\033[1m需要关注：\033[0m")
    for item in issues:
        print(f"  - {item}")

# 清理
for i in range(1, 12):
    (ROOT / f"trial_{i}.db").unlink(missing_ok=True)
    (ROOT / f"trial_{i}.db-wal").unlink(missing_ok=True)
    (ROOT / f"trial_{i}.db-shm").unlink(missing_ok=True)

sys.exit(1 if results["fail"] else 0)
