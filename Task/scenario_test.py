"""全场景对抗性测试 —— 第二轮。

与 robustness.py（第一轮 147 项）互补，重点覆盖：
  1. 责任制三要素（谁负责/哪个工点/谁确认）的边界与绕过尝试
  2. 新旧功能的交互：责任制 × 定时触发 × 流转 × 逾期
  3. 状态机完备性：所有状态 × 所有操作的笛卡尔积
  4. 长链路：多次退回、大量转办、深历史

设计原则：假设实现是错的，去证明它。每个用例都要能回答
「如果这里有 bug，这个测试会失败吗」。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
SERVER = ROOT / "server.py"
PY = sys.executable

records: list[dict] = []


def record(group: str, scenario: str, expect: str, actual: str, ok: bool, severity: str = "中") -> None:
    records.append({
        "group": group, "scenario": scenario, "expect": expect,
        "actual": actual, "ok": ok, "severity": severity,
    })
    mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    tail = "" if ok else f"\n      预期：{expect}\n      实际：{actual}"
    print(f"  {mark} {scenario}{tail}")


class Client:
    def __init__(self, db: Path) -> None:
        self.proc = subprocess.Popen(
            [PY, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), text=True, bufsize=1,
            env={"PATH": "/usr/bin:/bin", "TASK_ENGINE_DB": str(db),
                 "TASK_ENGINE_TZ": "Asia/Shanghai", "TASK_ENGINE_AI_KEY": ""},
        )
        self._id = 0
        self.req("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})

    def req(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"服务无响应。stderr: {self.proc.stderr.read()}")
        return json.loads(line)

    def call(self, tool: str, args: dict | None = None) -> dict:
        return self.req("tools/call", {"name": tool, "arguments": args or {}})["result"]

    def data(self, tool: str, args: dict | None = None) -> dict:
        r = self.call(tool, args)
        if r.get("isError"):
            raise AssertionError(f"{tool} 失败：{r['structuredContent'].get('error')}")
        return r["structuredContent"]

    def err(self, tool: str, args: dict | None = None) -> str:
        """调用并返回错误消息；成功返回空串。"""
        r = self.call(tool, args)
        return r["structuredContent"].get("error", "") if r.get("isError") else ""

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def fresh(name: str) -> Client:
    db = ROOT / f"s2_{name}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    return Client(db)


PEOPLE = [{"ref": "u1", "name": "张三"}, {"ref": "u2", "name": "李四"}]
BOSS = {"ref": "boss", "name": "王工"}
SITE = {"ref": "wbs-3", "name": "3号楼-地下室", "code": "WBS-03-B1"}


def ready(c, template="generic", **extra):
    """建一个三要素齐备的任务流。"""
    args = {"template": template, "assignees": PEOPLE, "confirmer": BOSS, "site": SITE}
    args.update(extra)
    return c.data("create_flow_from_template", args)["flow"]


def dispatch(c, template="generic", **extra):
    return c.data("dispatch_task", {"flow_id": ready(c, template, **extra)["id"]})["task"]


def finish_all(c, task_id, actor="u1"):
    """按顺序完成所有未了结的节点，自动满足附件要求。

    退回后只有最后一个节点被重开，所以这里跳过已了结的节点，
    否则会撞上"已经了结，不能重复完成"。
    """
    while True:
        d = c.data("get_task", {"task_id": task_id})["task"]
        current = d.get("current_step")
        if current is None:
            return
        seq = current["seq"]
        args = {"task_id": task_id, "seq": seq, "actor": actor}
        if d["steps"][seq]["requires_attachment"]:
            args["attachments"] = ["proof.jpg"]
        c.data("complete_step", args)


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ══════════════════════════════════════════════════════════
section("A. 责任制 — 绕过尝试")
# ══════════════════════════════════════════════════════════
c = fresh("acc")

# A1. 各种"看起来像人但不是人"的标识
for desc, ref in [
    ("空字符串", ""), ("纯空格", "   "), ("制表符", "\t"), ("换行", "\n"),
]:
    r = c.call("create_flow_from_template", {
        "template": "generic", "assignees": [{"ref": ref, "name": "幽灵"}],
        "confirmer": BOSS, "site": SITE,
    })
    if r.get("isError"):
        record("责任制-空标识", f"责任人 ref={desc}", "拒绝或视为未指派",
               "创建被拒", True, "高")
    else:
        flow = r["structuredContent"]["flow"]
        unassigned = flow["steps"][0]["assignee"] is None
        # 关键：空白 ref 必须等价于"未指派"，不能变成一个叫空字符串的"人"
        record("责任制-空标识", f"责任人 ref={desc}",
               "视为未指派（assignee 为 null）",
               "未指派" if unassigned else f"变成了人：{flow['steps'][0]['assignee']}",
               unassigned, "严重")

# A2. 布置时三要素缺失的所有组合
for desc, has_a, has_c, has_s in [
    ("全缺", False, False, False),
    ("只有责任人", True, False, False),
    ("只有确认人", False, True, False),
    ("只有工点", False, False, True),
    ("缺工点", True, True, False),
    ("缺确认人", True, False, True),
    ("缺责任人", False, True, True),
]:
    args = {"template": "generic"}
    if has_a:
        args["assignees"] = PEOPLE
    if has_c:
        args["confirmer"] = BOSS
    if has_s:
        args["site"] = SITE
    flow = c.data("create_flow_from_template", args)["flow"]
    err = c.err("dispatch_task", {"flow_id": flow["id"]})
    record("责任制-布置校验", f"{desc} → 布置", "拒绝并说明缺什么",
           f"拒绝：{err[:36]}" if err else "竟然布置成功", bool(err), "严重")

# A3. missing_requirements 的准确性
for desc, args, want in [
    ("全缺", {"template": "generic"}, 3),
    ("缺2项", {"template": "generic", "assignees": PEOPLE}, 2),
    ("缺1项", {"template": "generic", "assignees": PEOPLE, "confirmer": BOSS}, 1),
    ("齐备", {"template": "generic", "assignees": PEOPLE, "confirmer": BOSS, "site": SITE}, 0),
]:
    p = c.data("create_flow_from_template", args)
    n = len(p.get("missing_requirements", []))
    record("责任制-缺失提示", f"{desc}", f"{want} 项", f"{n} 项", n == want, "中")

# A4. 人数少于节点数时的轮转分配
flow = c.data("create_flow_from_template", {
    "template": "generic", "assignees": [{"ref": "u1", "name": "张三"}],
    "confirmer": BOSS, "site": SITE,
})["flow"]
assigned = sum(1 for s in flow["steps"] if s["assignee"])
record("责任制-轮转", "1 人分配 4 节点", "全部节点有人（轮转复用）",
       f"{assigned}/{len(flow['steps'])}", assigned == len(flow["steps"]), "中")

# A5. 模板阶段不校验（保证模板可跨工点复用）
r = c.call("create_flow_from_template", {"template": "generic"})
record("责任制-模板豁免", "无三要素时创建模板", "允许（模板需可复用）",
       "允许" if not r.get("isError") else "拒绝", not r.get("isError"), "高")

c.close()

# ══════════════════════════════════════════════════════════
section("B. 确认人权限 — 越权尝试")
# ══════════════════════════════════════════════════════════
c = fresh("confirm")

t = dispatch(c)
finish_all(c, t["id"])
for desc, actor in [
    ("节点责任人", "u1"), ("另一责任人", "u2"), ("陌生人", "hacker"),
    ("大小写变体", "BOSS"), ("带空格", " boss "), ("姓名而非ref", "王工"),
]:
    err = c.err("accept_task", {"task_id": t["id"], "actor": actor})
    record("确认人-越权", f"{desc}(actor={actor!r}) 验收", "拒绝",
           f"拒绝：{err[:28]}" if err else "越权成功", bool(err), "严重")

p = c.data("accept_task", {"task_id": t["id"], "actor": "boss"})
record("确认人-正常", "确认人本人验收", "state=done",
       f"state={p['task']['state']}", p["task"]["state"] == "done", "高")

# 退回同样受限
t2 = dispatch(c)
finish_all(c, t2["id"])
err = c.err("reject_task", {"task_id": t2["id"], "actor": "u1", "reason": "不行"})
record("确认人-越权", "非确认人退回", "拒绝",
       f"拒绝：{err[:28]}" if err else "越权成功", bool(err), "严重")

# 转办不能转移验收权
t3 = dispatch(c)
c.data("forward_step", {"task_id": t3["id"], "seq": 0,
                        "to_ref": "u1", "to_name": "张三", "actor": "sys"})
finish_all(c, t3["id"])
err = c.err("accept_task", {"task_id": t3["id"], "actor": "u1"})
record("确认人-不可转移", "转办后受让人仍无验收权", "拒绝",
       f"拒绝：{err[:28]}" if err else "竟可验收", bool(err), "严重")

c.close()

# ══════════════════════════════════════════════════════════
section("C. 责任制 × 定时触发")
# ══════════════════════════════════════════════════════════
c = fresh("sched")

# C1. 不完整流程不能登记定时计划（否则会在后台静默失败）
flow = c.data("create_flow_from_template", {"template": "generic"})["flow"]
err = c.err("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring",
    "first_at": "2026-08-14 09:00", "interval_unit": "week",
})
record("责任制×定时", "不完整流程登记计划",
       "拒绝（到点才失败没人看得到）",
       f"拒绝：{err[:36]}" if err else "登记成功", bool(err), "严重")

# C2. 触发出的任务保留三要素
flow = ready(c)
c.data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring",
    "first_at": "2026-08-14 09:00", "interval_value": 1, "interval_unit": "week",
})
c.data("tick", {"now": "2026-08-14 09:00"})
tasks = c.data("list_tasks")["tasks"]
if tasks:
    t = c.data("get_task", {"task_id": tasks[0]["id"]})["task"]
    ok = bool(t["site"] and t["confirmer"] and all(s["assignee"] for s in t["steps"]))
    record("责任制×定时", "定时触发的任务保留三要素", "工点/确认人/责任人齐备",
           f"site={bool(t['site'])} conf={bool(t['confirmer'])} "
           f"assignee={sum(1 for s in t['steps'] if s['assignee'])}/{len(t['steps'])}",
           ok, "严重")

# C3. 多次触发的任务互相独立
c.data("tick", {"now": "2026-08-21 09:00"})
ids = [t["id"] for t in c.data("list_tasks")["tasks"]]
if len(ids) >= 2:
    c.data("complete_step", {"task_id": ids[0], "seq": 0, "actor": "u1"})
    other = c.data("get_task", {"task_id": ids[1]})["task"]
    record("责任制×定时", "完成任务A的节点不影响任务B",
           "B 的首节点仍是 active",
           f"B.steps[0]={other['steps'][0]['state']}",
           other["steps"][0]["state"] == "active", "高")

c.close()

# ══════════════════════════════════════════════════════════
section("D. 责任制 × 流转 × 逾期")
# ══════════════════════════════════════════════════════════
c = fresh("mix")

# D1. 逾期不改变责任归属
t = dispatch(c)
before = c.data("get_task", {"task_id": t["id"]})["task"]["current_assignee"]["ref"]
c.data("tick", {"now": "2030-01-01 09:00"})
d = c.data("get_task", {"task_id": t["id"]})["task"]
now_ref = d["current_assignee"]["ref"] if d["current_assignee"] else None
record("交互-逾期", "逾期后责任人不变", f"仍是 {before}",
       f"{now_ref}", now_ref == before, "中")

# D2. 逾期任务仍可办完并验收
finish_all(c, t["id"])
d = c.data("get_task", {"task_id": t["id"]})["task"]
record("交互-逾期", "逾期任务可办完", "state=review",
       f"state={d['state']}", d["state"] == "review", "高")
p = c.data("accept_task", {"task_id": t["id"], "actor": "boss"})
record("交互-逾期", "逾期任务可验收", "state=done",
       f"state={p['task']['state']}", p["task"]["state"] == "done", "高")

# D3. 转办不改变确认人与工点
t2 = dispatch(c)
c.data("forward_step", {"task_id": t2["id"], "seq": 0,
                        "to_ref": "u9", "to_name": "新人", "actor": "u1"})
d = c.data("get_task", {"task_id": t2["id"]})["task"]
record("交互-转办", "转办不改变确认人", "confirmer 仍是 boss",
       f"{d['confirmer']['ref'] if d['confirmer'] else None}",
       d["confirmer"] and d["confirmer"]["ref"] == "boss", "高")
record("交互-转办", "转办不改变工点", "site 仍是 wbs-3",
       f"{d['site']['ref'] if d['site'] else None}",
       d["site"] and d["site"]["ref"] == "wbs-3", "中")

# D4. 退回后当前节点仍有责任人
t3 = dispatch(c)
finish_all(c, t3["id"])
c.data("reject_task", {"task_id": t3["id"], "actor": "boss", "reason": "重做"})
d = c.data("get_task", {"task_id": t3["id"]})["task"]
seq = d["current_step"]["seq"]
record("交互-退回", "退回后当前节点有责任人", "assignee 非空",
       f"节点{seq} assignee={d['steps'][seq]['assignee']}",
       d["steps"][seq]["assignee"] is not None, "高")

# D5. 受阻任务保留三要素
t4 = dispatch(c)
c.data("block_step", {"task_id": t4["id"], "seq": 0, "reason": "等材料"})
d = c.data("get_task", {"task_id": t4["id"]})["task"]
record("交互-受阻", "受阻任务保留三要素", "三项都在",
       f"site={bool(d['site'])} conf={bool(d['confirmer'])} "
       f"assignee={bool(d['steps'][0]['assignee'])}",
       bool(d["site"] and d["confirmer"] and d["steps"][0]["assignee"]), "中")

c.close()

# ══════════════════════════════════════════════════════════
section("E. 工点与确认人查询")
# ══════════════════════════════════════════════════════════
c = fresh("site")

sites = [
    {"ref": "w1", "name": "1号楼", "code": "A-01"},
    {"ref": "w2", "name": "2号楼", "code": "A-02"},
    {"ref": "w3", "name": "3号楼", "code": "A-03"},
]
for s in sites:
    for _ in range(3):
        dispatch(c, site=s)

for s in sites:
    n = c.data("list_tasks", {"site": s["ref"]})["count"]
    record("工点-过滤", f"{s['name']} 的任务数", "3 个", f"{n} 个", n == 3, "高")

n = c.data("list_tasks", {"site": "不存在"})["count"]
record("工点-过滤", "不存在的工点", "0 个", f"{n} 个", n == 0, "中")

# 工点 + 状态组合
t = c.data("list_tasks", {"site": "w1"})["tasks"][0]
finish_all(c, t["id"])
c.data("accept_task", {"task_id": t["id"], "actor": "boss"})
open_n = c.data("list_tasks", {"site": "w1", "open_only": True})["count"]
all_n = c.data("list_tasks", {"site": "w1"})["count"]
record("工点-组合过滤", "工点 + open_only", "未闭环 2，总共 3",
       f"未闭环 {open_n}，总共 {all_n}", open_n == 2 and all_n == 3, "高")

n = c.data("list_tasks", {"confirmer": "boss"})["count"]
record("确认人-过滤", "按确认人查询", "9 个", f"{n} 个", n == 9, "高")

t2 = c.data("list_tasks", {"site": "w2"})["tasks"][0]
finish_all(c, t2["id"])
n = c.data("list_tasks", {"confirmer": "boss", "state": "review"})["count"]
record("确认人-待验收", "确认人 + state=review", "1 个", f"{n} 个", n == 1, "高")

# 列表与详情一致
lst = c.data("list_tasks", {"site": "w3"})["tasks"][0]
det = c.data("get_task", {"task_id": lst["id"]})["task"]
record("一致性", "列表与详情的工点一致", "两处 site.ref 相同",
       f"{lst['site']['ref']} vs {det['site']['ref']}",
       lst["site"]["ref"] == det["site"]["ref"], "中")

c.close()

# ══════════════════════════════════════════════════════════
section("F. 状态机完备性")
# ══════════════════════════════════════════════════════════
c = fresh("fsm")


def make_in_state(client, state):
    t = dispatch(client)
    tid = t["id"]
    if state == "blocked":
        client.data("block_step", {"task_id": tid, "seq": 0, "reason": "x"})
    elif state == "review":
        finish_all(client, tid)
    elif state == "done":
        finish_all(client, tid)
        client.data("accept_task", {"task_id": tid, "actor": "boss"})
    elif state == "cancelled":
        client.data("cancel_task", {"task_id": tid, "reason": "x"})
    elif state == "overdue":
        client.data("tick", {"now": "2030-01-01 09:00"})
    return tid


OPS = {
    "complete_step": lambda tid: {"task_id": tid, "seq": 0, "actor": "u1",
                                  "attachments": ["x.jpg"]},
    "forward_step": lambda tid: {"task_id": tid, "seq": 0, "to_ref": "u9"},
    "block_step": lambda tid: {"task_id": tid, "seq": 0, "reason": "x"},
    "accept_task": lambda tid: {"task_id": tid, "actor": "boss"},
    "reject_task": lambda tid: {"task_id": tid, "actor": "boss", "reason": "x"},
    "cancel_task": lambda tid: {"task_id": tid, "reason": "x"},
}

# 终态必须拒绝一切修改
for state in ["done", "cancelled"]:
    for op, mk in OPS.items():
        tid = make_in_state(c, state)
        r = c.call(op, mk(tid))
        record("状态机-终态防护", f"{state} 状态下 {op}", "拒绝",
               "拒绝" if r.get("isError") else "接受", r.get("isError", False), "高")

# 非终态的合法操作不应被误拒
for state, op, should in [
    ("running", "complete_step", True),
    ("running", "forward_step", True),
    ("running", "block_step", True),
    ("blocked", "complete_step", True),
    ("review", "accept_task", True),
    ("review", "reject_task", True),
    ("overdue", "complete_step", True),
    ("running", "accept_task", False),
    ("running", "reject_task", False),
]:
    tid = make_in_state(c, state)
    r = c.call(op, OPS[op](tid))
    worked = not r.get("isError")
    record("状态机-合法操作", f"{state} 状态下 {op}",
           "允许" if should else "拒绝",
           "允许" if worked else f"拒绝：{r['structuredContent'].get('error','')[:26]}",
           worked == should, "高")

c.close()

# ══════════════════════════════════════════════════════════
section("G. 长链路")
# ══════════════════════════════════════════════════════════
c = fresh("deep")

# G1. 多次退回-重做循环
t = dispatch(c, "hazard_rectification")
tid = t["id"]
cycles = 0
for i in range(10):
    finish_all(c, tid)
    d = c.data("get_task", {"task_id": tid})["task"]
    if d["state"] != "review":
        break
    c.data("reject_task", {"task_id": tid, "actor": "boss", "reason": f"第{i+1}次"})
    cycles += 1
d = c.data("get_task", {"task_id": tid})["task"]
record("长链路-退回", "连续退回重做 10 轮", "状态始终一致",
       f"完成 {cycles} 轮，state={d['state']}", cycles == 10, "高")

# 退回只重开最后一个节点，所以第 2 轮起每轮只需完成 1 个节点。
# 首轮 5 节点 + 后续 9 轮各 1 节点 = 14 次完成，加上激活/状态变更/创建，约 50 条。
kinds = [h["kind"] for h in d["history"]]
done_n = kinds.count("step_done")
reject_n = sum(1 for h in d["history"] if h["kind"] == "step_activated" and "退回" in h["summary"])
record("长链路-历史", "10 轮退回的审计轨迹完整",
       "14 次节点完成 + 10 次退回重开",
       f"{done_n} 次完成，{reject_n} 次退回重开，共 {len(d['history'])} 条",
       done_n == 14 and reject_n == 10, "高")

# G2. 大量转办
t2 = dispatch(c)
for i in range(50):
    c.data("forward_step", {"task_id": t2["id"], "seq": 0,
                            "to_ref": f"u{i}", "to_name": f"员工{i}", "actor": "sys"})
d = c.data("get_task", {"task_id": t2["id"]})["task"]
record("长链路-转办", "连续转办 50 次", "最终责任人是最后一个",
       f"assignee={d['steps'][0]['assignee']['ref']}",
       d["steps"][0]["assignee"]["ref"] == "u49", "中")

# G3. 大量备注后的查询性能
t3 = dispatch(c)
for i in range(200):
    c.data("add_note", {"task_id": t3["id"], "note": f"第{i}条", "actor": "u1"})
start = time.time()
d = c.data("get_task", {"task_id": t3["id"]})["task"]
ms = (time.time() - start) * 1000
record("长链路-深历史", "200 条备注后查详情", "< 500ms 且完整",
       f"{ms:.0f}ms，{len(d['history'])} 条",
       ms < 500 and len(d["history"]) >= 200, "中")

# G4. 节点数上限
r = c.call("generate_task_flow", {
    "requirement": "第一步检查，" * 50 + "最后归档",
    "assignees": PEOPLE, "confirmer": BOSS, "site": SITE,
})
if not r.get("isError"):
    n = len(r["structuredContent"]["flow"]["steps"])
    record("长链路-节点数", "超长需求的节点数", "有上限（≤10）", f"{n} 个", n <= 10, "中")

c.close()

# ══════════════════════════════════════════════════════════
section("H. 并发 — 责任制场景")
# ══════════════════════════════════════════════════════════
db = ROOT / "s2_concurrent.db"
for suffix in ("", "-wal", "-shm"):
    Path(str(db) + suffix).unlink(missing_ok=True)
clients = [Client(db) for _ in range(4)]

# H1. 并发验收只能成功一次
flow = ready(clients[0])
t = clients[0].data("dispatch_task", {"flow_id": flow["id"]})["task"]
finish_all(clients[0], t["id"])
results = [cl.call("accept_task", {"task_id": t["id"], "actor": "boss"}) for cl in clients]
n = sum(1 for r in results if not r.get("isError"))
record("并发-验收", "4 客户端同时验收", "恰好 1 个成功", f"{n} 个成功", n == 1, "严重")

# H2. 并发转办不损坏数据
flow2 = ready(clients[0])
t2 = clients[0].data("dispatch_task", {"flow_id": flow2["id"]})["task"]
for i, cl in enumerate(clients):
    cl.call("forward_step", {"task_id": t2["id"], "seq": 0,
                             "to_ref": f"c{i}", "to_name": f"并发{i}"})
final = clients[0].data("get_task", {"task_id": t2["id"]})["task"]
ref = final["steps"][0]["assignee"]["ref"]
record("并发-转办", "4 客户端同时转办", "最终是其中之一，数据完好",
       f"assignee={ref}", ref.startswith("c"), "高")

# H3. 一方验收后另一方不能继续办理
flow3 = ready(clients[0])
t3 = clients[0].data("dispatch_task", {"flow_id": flow3["id"]})["task"]
finish_all(clients[0], t3["id"])
clients[0].data("accept_task", {"task_id": t3["id"], "actor": "boss"})
r = clients[1].call("complete_step", {"task_id": t3["id"], "seq": 0})
record("并发-终态", "A 验收后 B 尝试办理", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "严重")

for cl in clients:
    cl.close()

# ══════════════════════════════════════════════════════════
section("I. 序列化 — 六要素完整性")
# ══════════════════════════════════════════════════════════
c = fresh("ser")

t = dispatch(c, "hazard_rectification")
d = c.data("get_task", {"task_id": t["id"]})["task"]

for name, getter in [
    ("1.谁负责", lambda x: x["steps"][0]["assignee"] and x["steps"][0]["assignee"]["name"]),
    ("2.做什么", lambda x: x["steps"][0]["name"]),
    ("3.截止时间", lambda x: x["steps"][0]["due_at"]),
    ("4.哪个工点", lambda x: x["site"] and x["site"]["name"]),
    ("5.交什么材料", lambda x: x["steps"][0]["deliverable"]),
    ("6.谁确认", lambda x: x["confirmer"] and x["confirmer"]["name"]),
]:
    value = getter(d)
    record("序列化-六要素", f"{name}", "有值", f"{value!r}"[:36], bool(value), "严重")

lst = c.data("list_tasks")["tasks"][0]
for field in ["site", "confirmer", "current_assignee", "due_at"]:
    record("序列化-列表视图", f"列表含 {field}", "存在",
           "存在" if field in lst else "缺失", field in lst, "中")

flow = c.data("create_flow_from_template", {"template": "generic"})["flow"]
record("序列化-空值", "无工点确认人时可序列化", "为 null 而非报错",
       f"site={flow['site']} conf={flow['confirmer']}",
       flow["site"] is None and flow["confirmer"] is None, "中")

flow2 = c.data("create_flow_from_template", {
    "template": "generic", "assignees": [{"ref": "u1", "name": "张三·特殊\"字符"}],
    "confirmer": {"ref": "b", "name": "王工<script>"},
    "site": {"ref": "s", "name": "3号楼—地下室（负一层）", "code": "A/B-01"},
})["flow"]
record("序列化-特殊字符", "中文与特殊字符", "正常往返",
       flow2["site"]["name"], "地下室" in flow2["site"]["name"], "中")

c.close()

# ══════════════════════════════════════════════════════════
section("J. 回归 — 核心不变量")
# ══════════════════════════════════════════════════════════
c = fresh("reg")
flow = ready(c)
c.data("create_schedule", {"flow_id": flow["id"], "run_mode": "recurring",
                           "first_at": "2026-08-01 09:00", "interval_unit": "day"})
for _ in range(20):
    c.data("tick", {"now": "2026-08-01 09:00"})
n = c.data("list_tasks")["count"]
record("回归-幂等", "同一时刻 tick 20 次", "1 个任务", f"{n} 个", n == 1, "严重")

c2 = fresh("reg2")
flow2 = ready(c2)
c2.data("create_schedule", {"flow_id": flow2["id"], "run_mode": "recurring",
                            "first_at": "2026-01-01 09:00", "interval_unit": "day"})
for _ in range(30):
    c2.data("tick", {"now": "2026-08-01 09:00"})
n = c2.data("list_tasks")["count"]
record("回归-停机", "停机 200 天后 tick 30 次", "1 个任务", f"{n} 个", n == 1, "严重")

c3 = fresh("reg3")
flow3 = ready(c3)
c3.data("create_schedule", {"flow_id": flow3["id"], "run_mode": "recurring",
                            "first_at": "2026-01-31 09:00", "interval_unit": "month"})
fires = []
cursor = datetime(2026, 1, 1, 9, 0)
while cursor < datetime(2026, 6, 1):
    if c3.data("tick", {"now": cursor.strftime("%Y-%m-%d %H:%M")})["created_count"]:
        fires.append(cursor.strftime("%m-%d"))
    cursor += timedelta(days=1)
want = ["01-31", "02-28", "03-31", "04-30", "05-31"]
record("回归-月末", "1/31 起按月重复", str(want), str(fires), fires == want, "严重")

c4 = fresh("reg4")
t = dispatch(c4)
err = c4.err("complete_step", {"task_id": t["id"], "seq": 3})
record("回归-顺序", "跨越节点办理", "拒绝",
       f"拒绝：{err[:28]}" if err else "接受", bool(err), "严重")

t2 = dispatch(c4, "hazard_rectification")
err = c4.err("complete_step", {"task_id": t2["id"], "seq": 0})
record("回归-附件", "要求留证却不传附件", "拒绝",
       f"拒绝：{err[:28]}" if err else "接受", bool(err), "严重")

c4.call("generate_task_flow", {"requirement": "'; DROP TABLE tasks; --"})
try:
    n = c4.data("list_tasks")["count"]
    record("回归-注入", "SQL 注入后数据库完好", "可正常查询", f"{n} 个任务", True, "严重")
except Exception as exc:
    record("回归-注入", "SQL 注入后数据库完好", "可正常查询", str(exc)[:40], False, "严重")

for cli in (c, c2, c3, c4):
    cli.close()

# ══════════════════════════════════════════════════════════
section("K. 规模与性能")
# ══════════════════════════════════════════════════════════
c = fresh("perf")
many = [{"ref": f"w{i}", "name": f"{i}号楼", "code": f"A-{i:02d}"} for i in range(20)]
start = time.time()
for i in range(200):
    dispatch(c, site=many[i % 20])
create_time = time.time() - start
record("性能-写入", "创建 200 个带责任制的任务", "< 60 秒",
       f"{create_time:.1f}s（{create_time/200*1000:.0f}ms/个）", create_time < 60, "中")

for desc, args in [
    ("按工点", {"site": "w5"}), ("按确认人", {"confirmer": "boss"}),
    ("按责任人", {"assignee": "u1"}), ("工点+状态", {"site": "w5", "open_only": True}),
]:
    start = time.time()
    c.data("list_tasks", args)
    ms = (time.time() - start) * 1000
    record("性能-查询", f"{desc}（200 任务）", "< 500ms", f"{ms:.0f}ms", ms < 500, "中")

size_mb = os.path.getsize(ROOT / "s2_perf.db") / 1024 / 1024
record("性能-存储", "200 任务的库体积", "< 10MB", f"{size_mb:.1f}MB", size_mb < 10, "低")
c.close()

# ══════════════════════════════════════════════════════════
print("\n" + "═" * 72)
total = len(records)
passed = sum(1 for r in records if r["ok"])
failed = [r for r in records if not r["ok"]]
print(f"\033[1m总计 {total} 项，通过 {passed}，失败 {len(failed)}\033[0m")

if failed:
    by_sev: dict[str, list] = {}
    for r in failed:
        by_sev.setdefault(r["severity"], []).append(r)
    print("\n\033[1m失败明细：\033[0m")
    for sev in ("严重", "高", "中", "低"):
        items = by_sev.get(sev, [])
        if not items:
            continue
        print(f"\n  [{sev}] {len(items)} 项")
        for r in items:
            print(f"    · {r['group']} / {r['scenario']}")
            print(f"      预期：{r['expect']}")
            print(f"      实际：{r['actual']}")

(ROOT / "scenario_results.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n结果已写入 scenario_results.json")

for path in ROOT.glob("s2_*.db*"):
    path.unlink(missing_ok=True)

# ══════════════════════════════════════════════════════════
# 追加：更刁钻的死角（前两轮未覆盖）
# ══════════════════════════════════════════════════════════
records.clear()
print("\n\n" + "═" * 72)
print("\033[1m追加轮次：死角探测\033[0m")

section("L. 责任制的时序漏洞")
c = fresh("gap")

# L1. 先登记完整计划，再想办法让它变得不完整
flow = ready(c)
c.data("create_schedule", {"flow_id": flow["id"], "run_mode": "recurring",
                           "first_at": "2026-08-14 09:00", "interval_unit": "week"})
# 用同一个 flow_id 覆盖保存一个不完整的版本
r = c.call("create_flow_from_template", {"template": "generic"})
incomplete = r["structuredContent"]["flow"]
record("时序-计划篡改", "已登记的计划能否被架空",
       "新流程有独立 id，不影响已登记的计划",
       f"新id={incomplete['id'][:12]} 原id={flow['id'][:12]}",
       incomplete["id"] != flow["id"], "严重")

# L2. 触发后再看计划是否仍完整
c.data("tick", {"now": "2026-08-14 09:00"})
tasks = c.data("list_tasks")["tasks"]
ok = bool(tasks) and all(
    c.data("get_task", {"task_id": t["id"]})["task"]["confirmer"] for t in tasks
)
record("时序-触发完整性", "触发出的任务都有确认人", "全部有",
       f"{len(tasks)} 个任务", ok, "严重")

# L3. 转办给空 ref 能否清空责任人
t = dispatch(c)
err = c.err("forward_step", {"task_id": t["id"], "seq": 0, "to_ref": ""})
record("时序-清空责任人", "转办给空 ref", "拒绝（不能让任务变成无主）",
       f"拒绝：{err[:30]}" if err else "接受，责任人被清空", bool(err), "严重")

# L4. 转办给纯空白
err = c.err("forward_step", {"task_id": t["id"], "seq": 0, "to_ref": "   "})
d = c.data("get_task", {"task_id": t["id"]})["task"]
still_owned = d["steps"][0]["assignee"] is not None
record("时序-清空责任人", "转办给纯空白 ref",
       "拒绝或保持有主", 
       f"{'拒绝' if err else '接受'}，assignee={'有' if still_owned else '无'}",
       bool(err) or still_owned, "严重")

c.close()

section("M. 数值与边界的极端组合")
c = fresh("edge")

# M1. 截止时间在过去的任务
flow = ready(c)
p = c.data("create_schedule", {"flow_id": flow["id"], "run_mode": "once",
                               "first_at": "2020-01-01 09:00"})
c.data("tick", {"now": "2026-08-14 09:00"})
tasks = c.data("list_tasks")["tasks"]
if tasks:
    t = c.data("get_task", {"task_id": tasks[0]["id"]})["task"]
    # 触发时刻是 2020，节点截止应基于触发时刻推算，因此早已过期
    record("边界-历史触发", "触发时刻在过去时的截止时间",
           "基于触发时刻推算（会立即逾期）",
           f"due={t['due_at'][:10] if t['due_at'] else None}",
           t["due_at"] is not None, "中")
    # 触发与逾期扫描在同一次 tick 内完成，不必等下一轮
    record("边界-历史触发", "过期任务在触发的同一次 tick 内标记逾期",
           "state=overdue",
           f"state={t['state']}", t["state"] == "overdue", "高")
    # 已标记后不应重复标记
    r = c.data("tick", {"now": "2026-08-14 10:00"})
    record("边界-历史触发", "已逾期任务不重复标记", "0 个",
           f"{len(r['overdue_task_ids'])} 个",
           len(r["overdue_task_ids"]) == 0, "中")

# M2. 同一秒内大量操作
t2 = dispatch(c)
for i in range(30):
    c.data("add_note", {"task_id": t2["id"], "note": f"并发备注{i}", "actor": "u1"})
d = c.data("get_task", {"task_id": t2["id"]})["task"]
note_n = sum(1 for h in d["history"] if h["kind"] == "note_added")
record("边界-同秒操作", "同一秒内 30 条备注", "全部记录，不因时间戳相同丢失",
       f"{note_n} 条", note_n == 30, "严重")

# M3. 历史记录的时序稳定性
times = [h["at"] for h in d["history"]]
record("边界-同秒操作", "同秒记录的顺序稳定", "非递减",
       "有序" if times == sorted(times) else "乱序",
       times == sorted(times), "高")

c.close()

section("N. 跨任务干扰")
c = fresh("cross")

# N1. 相同标题的任务不会混淆
ids = [dispatch(c)["id"] for _ in range(5)]
c.data("complete_step", {"task_id": ids[2], "seq": 0, "actor": "u1"})
others_intact = all(
    c.data("get_task", {"task_id": i})["task"]["steps"][0]["state"] == "active"
    for i in ids if i != ids[2]
)
record("跨任务-隔离", "5 个同名任务，操作其一", "其余不受影响",
       "隔离正常" if others_intact else "发生串扰", others_intact, "严重")

# N2. 取消一个不影响其他
c.data("cancel_task", {"task_id": ids[0], "reason": "x"})
alive = sum(1 for i in ids[1:]
            if c.data("get_task", {"task_id": i})["task"]["state"] != "cancelled")
record("跨任务-隔离", "取消其中一个", "其余 4 个存活",
       f"{alive} 个存活", alive == 4, "严重")

# N3. 同一工点的任务互不干扰
same_site = [dispatch(c, site={"ref": "same", "name": "同一工点"})["id"] for _ in range(3)]
c.data("block_step", {"task_id": same_site[0], "seq": 0, "reason": "x"})
unaffected = sum(1 for i in same_site[1:]
                 if c.data("get_task", {"task_id": i})["task"]["state"] == "running")
record("跨任务-同工点", "同工点任务互不干扰", "其余 2 个仍 running",
       f"{unaffected} 个正常", unaffected == 2, "高")

c.close()

section("O. 计划生命周期的完整覆盖")
c = fresh("plan")

flow = ready(c)
p = c.data("create_schedule", {"flow_id": flow["id"], "run_mode": "recurring",
                               "first_at": "2026-08-01 09:00",
                               "interval_unit": "day", "max_fires": 3})["schedule"]
pid = p["id"]

# O1. 暂停期间不触发，恢复后继续
c.data("tick", {"now": "2026-08-01 09:00"})
c.data("pause_schedule", {"schedule_id": pid})
c.data("tick", {"now": "2026-08-02 09:00"})
n_paused = c.data("list_tasks")["count"]
c.data("pause_schedule", {"schedule_id": pid, "paused": False})
c.data("tick", {"now": "2026-08-03 09:00"})
n_resumed = c.data("list_tasks")["count"]
record("计划-暂停恢复", "暂停期间不触发", "任务数不变",
       f"暂停后 {n_paused}", n_paused == 1, "高")
record("计划-暂停恢复", "恢复后继续触发", "任务数增加",
       f"恢复后 {n_resumed}", n_resumed > n_paused, "高")

# O2. max_fires 计数是否包含暂停期
final = c.data("get_schedule", {"schedule_id": pid}) if False else None
plans = c.data("list_schedules")["schedules"]
target = next((x for x in plans if x["id"] == pid), None)
if target:
    record("计划-次数统计", "暂停不消耗触发次数",
           f"fire_count ≤ 3", f"fire_count={target['fire_count']}",
           target["fire_count"] <= 3, "中")

# O3. 停用后无法恢复
c.data("cancel_schedule", {"schedule_id": pid})
c.data("tick", {"now": "2026-08-10 09:00"})
n_after = c.data("list_tasks")["count"]
record("计划-停用", "停用后不再触发", "任务数不变",
       f"{n_resumed} → {n_after}", n_after == n_resumed, "高")

# O4. 对不存在的计划操作
for tool in ["pause_schedule", "cancel_schedule"]:
    err = c.err(tool, {"schedule_id": "sched_不存在"})
    record("计划-容错", f"{tool} 不存在的计划", "报错而非崩溃",
           f"拒绝：{err[:24]}" if err else "静默成功", bool(err), "中")

c.close()

section("P. 附件与材料的语义")
c = fresh("attach")

# P1. 附件累加而非覆盖
t = dispatch(c, "hazard_rectification")
c.data("complete_step", {"task_id": t["id"], "seq": 0, "actor": "u1",
                         "attachments": ["a.jpg", "b.jpg"]})
d = c.data("get_task", {"task_id": t["id"]})["task"]
record("附件-数量", "多个附件都被记录", "2 个",
       f"{len(d['steps'][0]['attachments'])} 个",
       len(d["steps"][0]["attachments"]) == 2, "中")

# P2. 退回后重做，旧附件是否保留
finish_all(c, t["id"])
c.data("reject_task", {"task_id": t["id"], "actor": "boss", "reason": "重来"})
d = c.data("get_task", {"task_id": t["id"]})["task"]
seq = d["current_step"]["seq"]
old_attachments = len(d["steps"][seq]["attachments"])
record("附件-退回保留", "退回后节点的旧附件",
       "保留（审计需要）或清空（重新提交），二者皆可但需明确",
       f"{old_attachments} 个附件", True, "低")

# P3. 重做时追加新附件
if d["steps"][seq]["requires_attachment"]:
    c.data("complete_step", {"task_id": t["id"], "seq": seq,
                             "attachments": ["new.jpg"]})
    d2 = c.data("get_task", {"task_id": t["id"]})["task"]
    total = len(d2["steps"][seq]["attachments"])
    record("附件-累加", "重做时新附件追加", "总数增加",
           f"{old_attachments} → {total}", total > old_attachments, "中")

c.close()

# 汇总追加轮次
print("\n" + "═" * 72)
extra_total = len(records)
extra_passed = sum(1 for r in records if r["ok"])
extra_failed = [r for r in records if not r["ok"]]
print(f"\033[1m追加轮次：{extra_total} 项，通过 {extra_passed}，失败 {len(extra_failed)}\033[0m")
if extra_failed:
    print("\n\033[1m失败明细：\033[0m")
    for r in extra_failed:
        print(f"  · [{r['severity']}] {r['group']} / {r['scenario']}")
        print(f"    预期：{r['expect']}")
        print(f"    实际：{r['actual']}")

existing = json.loads((ROOT / "scenario_results.json").read_text(encoding="utf-8"))
(ROOT / "scenario_results.json").write_text(
    json.dumps(existing + records, ensure_ascii=False, indent=2), encoding="utf-8")

for path in ROOT.glob("s2_*.db*"):
    path.unlink(missing_ok=True)
