"""MCP 协议契约测试：通过真实的 stdio 子进程验证 server 行为。

这些测试启动实际的 server.py 并按 JSON-RPC 对话，因此能抓到只在真实运行时才出现的
问题——比如日志误写进 stdout 污染协议帧。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server.py"


class ServerSession:
    """驱动一个 MCP server 子进程。"""

    def __init__(self, db_path: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
            text=True,
            bufsize=1,
            env={
                "PATH": "/usr/bin:/bin",
                "TASK_ENGINE_DB": str(db_path),
                "TASK_ENGINE_TZ": "Asia/Shanghai",
                "TASK_ENGINE_AI_KEY": "",  # 强制走规则路径，测试不依赖网络
            },
        )
        self._next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params

        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

        line = self.proc.stdout.readline()
        if not line:
            stderr = self.proc.stderr.read()
            raise RuntimeError(f"server 无响应。stderr:\n{stderr}")
        return json.loads(line)

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """调用工具并返回解析后的结构化结果。"""
        response = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        assert "result" in response, response
        return response["result"]

    def payload(self, name: str, arguments: dict | None = None) -> dict:
        return self.call_tool(name, arguments)["structuredContent"]

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


@pytest.fixture
def session(tmp_path):
    sess = ServerSession(tmp_path / "mcp.db")
    sess.request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    })
    yield sess
    sess.close()


# 责任制三要素：布置任务前必须齐备
PEOPLE = [{"ref": "u1", "name": "张三"}, {"ref": "u2", "name": "李四"}]
CONFIRMER = {"ref": "boss", "name": "项目经理"}
SITE = {"ref": "wbs-3", "name": "3号楼-地下室", "code": "WBS-03-B1"}


def ready_flow(session, template: str = "generic", **extra) -> dict:
    """建一个责任人、确认人、工点都齐备的任务流，可直接布置。"""
    args = {
        "template": template,
        "assignees": PEOPLE,
        "confirmer": CONFIRMER,
        "site": SITE,
    }
    args.update(extra)
    return session.payload("create_flow_from_template", args)["flow"]


class TestProtocol:
    def test_initialize(self, tmp_path):
        sess = ServerSession(tmp_path / "init.db")
        try:
            response = sess.request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            })
            assert response["result"]["serverInfo"]["name"] == "task-engine"
            assert "tools" in response["result"]["capabilities"]
        finally:
            sess.close()

    def test_tools_list(self, session):
        tools = session.request("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}

        assert "generate_task_flow" in names
        assert "create_schedule" in names
        assert "tick" in names
        assert "complete_step" in names

    def test_every_tool_has_schema_and_description(self, session):
        for tool in session.request("tools/list")["result"]["tools"]:
            assert tool["description"], tool["name"]
            assert tool["inputSchema"]["type"] == "object", tool["name"]

    def test_ping(self, session):
        assert "result" in session.request("ping")

    def test_unknown_method_errors(self, session):
        response = session.request("nonexistent/method")
        assert response["error"]["code"] == -32601

    def test_unknown_tool_returns_tool_error(self, session):
        result = session.call_tool("no_such_tool")
        assert result["isError"] is True
        assert "未知工具" in result["structuredContent"]["error"]

    def test_notification_gets_no_response(self, tmp_path):
        """通知不应产生响应——多发一条响应会打乱客户端的请求配对。"""
        sess = ServerSession(tmp_path / "notif.db")
        try:
            sess.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
            sess.proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n",
            )
            sess.proc.stdin.flush()
            # 紧接着发一个正常请求，若通知产生了响应，这里会读到错位的消息
            response = sess.request("ping")
            assert response["id"] == 2
        finally:
            sess.close()

    def test_malformed_json_does_not_crash(self, session):
        session.proc.stdin.write("这不是 JSON\n")
        session.proc.stdin.flush()
        error_line = json.loads(session.proc.stdout.readline())
        assert error_line["error"]["code"] == -32700

        # 服务应当继续工作
        assert "result" in session.request("ping")


class TestGenerationTools:
    def test_list_templates(self, session):
        payload = session.payload("list_templates")
        assert len(payload["templates"]) >= 5
        assert all("key" in t for t in payload["templates"])

    def test_generate_from_requirement(self, session):
        payload = session.payload("generate_task_flow", {
            "requirement": "每周五检查基坑监测数据，异常时由监测员复核并归档",
        })
        flow = payload["flow"]

        assert flow["trigger"]["run_mode"] == "recurring"
        assert flow["trigger"]["interval_unit"] == "week"
        assert len(flow["steps"]) >= 2
        assert flow["origin"] == "rules"  # 未配 key，走规则路径

    def test_generate_assigns_people(self, session):
        payload = session.payload("generate_task_flow", {
            "requirement": "整改现场临边防护缺失问题并闭环",
            "assignees": [{"ref": "u1", "name": "张三"}, {"ref": "u2", "name": "李四"}],
        })
        steps = payload["flow"]["steps"]
        assert steps[0]["assignee"]["ref"] == "u1"

    def test_generate_rejects_short_input(self, session):
        result = session.call_tool("generate_task_flow", {"requirement": "改"})
        assert result["isError"] is True

    def test_create_from_template(self, session):
        payload = session.payload("create_flow_from_template", {
            "template": "隐患整改",
            "title": "3号楼临边防护整改",
        })
        assert payload["flow"]["title"] == "3号楼临边防护整改"
        assert len(payload["flow"]["steps"]) >= 4

    def test_unknown_template_errors_helpfully(self, session):
        result = session.call_tool("create_flow_from_template", {"template": "不存在"})
        assert result["isError"] is True
        assert "可用模板" in result["structuredContent"]["error"]


class TestEndToEndWorkflow:
    """完整走一遍：生成 → 布置 → 办理 → 验收。"""

    def test_full_lifecycle(self, session):
        # 1. 生成任务流——责任制三要素一并给全
        flow = session.payload("generate_task_flow", {
            "requirement": "整改现场临边防护缺失并复核闭环",
            "assignees": PEOPLE,
            "confirmer": CONFIRMER,
            "site": SITE,
        })["flow"]

        # 2. 立即布置
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        assert task["state"] == "running"
        assert task["current_assignee"]["ref"] == "u1"

        # 3. 张三能在「我的任务」看到
        mine = session.payload("list_tasks", {"assignee": "u1"})
        assert mine["count"] == 1

        # 4. 逐个完成节点
        total = len(task["steps"])
        for seq in range(total):
            detail = session.payload("get_task", {"task_id": task["id"]})["task"]
            step = detail["steps"][seq]
            args = {"task_id": task["id"], "seq": seq, "actor": "u1", "comment": "已处理"}
            if step["requires_attachment"]:
                args["attachments"] = ["evidence.jpg"]
            session.payload("complete_step", args)

        # 5. 全部完成后进入待验收
        detail = session.payload("get_task", {"task_id": task["id"]})["task"]
        assert detail["state"] == "review"

        # 6. 验收通过
        accepted = session.payload("accept_task", {"task_id": task["id"], "actor": "boss"})
        assert accepted["task"]["state"] == "done"

        # 7. 历史完整留痕
        history = session.payload("get_task", {"task_id": task["id"]})["task"]["history"]
        kinds = {item["kind"] for item in history}
        assert "created" in kinds
        assert "step_done" in kinds
        assert "state_changed" in kinds

    def test_attachment_requirement_blocks_completion(self, session):
        flow = ready_flow(session, "隐患整改")
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]

        # 首节点要求留证，不带附件应被拒
        assert task["steps"][0]["requires_attachment"] is True
        result = session.call_tool("complete_step", {"task_id": task["id"], "seq": 0})
        assert result["isError"] is True
        assert "证明材料" in result["structuredContent"]["error"]

    def test_forward_moves_ownership(self, session):
        flow = ready_flow(session, assignees=[{"ref": "u1", "name": "张三"}])
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]

        session.payload("forward_step", {
            "task_id": task["id"], "seq": 0,
            "to_ref": "u2", "to_name": "李四", "actor": "u1",
        })

        assert session.payload("list_tasks", {"assignee": "u1"})["count"] == 0
        assert session.payload("list_tasks", {"assignee": "u2"})["count"] == 1

    def test_reject_reopens_task(self, session):
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]

        for seq in range(len(task["steps"])):
            detail = session.payload("get_task", {"task_id": task["id"]})["task"]
            args = {"task_id": task["id"], "seq": seq}
            if detail["steps"][seq]["requires_attachment"]:
                args["attachments"] = ["x.jpg"]
            session.payload("complete_step", args)

        rejected = session.payload("reject_task", {"task_id": task["id"], "reason": "材料不全"})
        assert rejected["task"]["state"] == "running"


class TestSchedulingTools:
    def test_schedule_and_tick(self, session):
        flow = session.payload("generate_task_flow", {
            "requirement": "每周一巡检施工现场安全状况",
            "assignees": PEOPLE,
            "confirmer": CONFIRMER,
            "site": SITE,
        })["flow"]

        plan = session.payload("create_schedule", {
            "flow_id": flow["id"],
            "run_mode": "recurring",
            "first_at": "2026-03-02 09:00",
            "interval_value": 1,
            "interval_unit": "week",
        })["schedule"]
        assert plan["next_fire_at"].startswith("2026-03-02")

        # 未到点不触发
        assert session.payload("tick", {"now": "2026-03-01 08:00"})["created_count"] == 0

        # 到点触发
        report = session.payload("tick", {"now": "2026-03-02 09:00"})
        assert report["created_count"] == 1

        # 重复 tick 不重复创建——最重要的不变量
        again = session.payload("tick", {"now": "2026-03-02 09:00"})
        assert again["created_count"] == 0
        assert session.payload("list_tasks")["count"] == 1

        # 下一周期照常触发
        session.payload("tick", {"now": "2026-03-09 09:00"})
        assert session.payload("list_tasks")["count"] == 2

    def test_pause_stops_firing(self, session):
        flow = ready_flow(session)
        plan = session.payload("create_schedule", {
            "flow_id": flow["id"], "run_mode": "recurring",
            "first_at": "2026-03-02 09:00", "interval_unit": "day",
        })["schedule"]

        session.payload("pause_schedule", {"schedule_id": plan["id"]})
        assert session.payload("tick", {"now": "2026-03-03 09:00"})["created_count"] == 0

        session.payload("pause_schedule", {"schedule_id": plan["id"], "paused": False})
        assert session.payload("tick", {"now": "2026-03-03 09:00"})["created_count"] >= 1

    def test_cancel_schedule(self, session):
        flow = ready_flow(session)
        plan = session.payload("create_schedule", {
            "flow_id": flow["id"], "run_mode": "recurring",
            "first_at": "2026-03-02 09:00", "interval_unit": "day",
        })["schedule"]

        session.payload("cancel_schedule", {"schedule_id": plan["id"]})
        assert session.payload("tick", {"now": "2026-03-05 09:00"})["created_count"] == 0

    def test_tick_marks_overdue(self, session):
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]

        report = session.payload("tick", {"now": "2030-01-01 09:00"})
        assert task["id"] in report["overdue_task_ids"]

    def test_schedule_requires_existing_flow(self, session):
        result = session.call_tool("create_schedule", {"flow_id": "flow_nope"})
        assert result["isError"] is True
        assert "不存在" in result["structuredContent"]["error"]


class TestAccountability:
    """工程责任制：谁负责、在哪个工点、由谁确认——三者缺一不可布置。"""

    def test_dispatch_rejects_missing_assignee(self, session):
        flow = session.payload("create_flow_from_template", {
            "template": "generic", "confirmer": CONFIRMER, "site": SITE,
        })["flow"]
        result = session.call_tool("dispatch_task", {"flow_id": flow["id"]})
        assert result["isError"] is True
        assert "责任人" in result["structuredContent"]["error"]

    def test_dispatch_rejects_missing_confirmer(self, session):
        flow = session.payload("create_flow_from_template", {
            "template": "generic", "assignees": PEOPLE, "site": SITE,
        })["flow"]
        result = session.call_tool("dispatch_task", {"flow_id": flow["id"]})
        assert result["isError"] is True
        assert "确认人" in result["structuredContent"]["error"]

    def test_dispatch_rejects_missing_site(self, session):
        flow = session.payload("create_flow_from_template", {
            "template": "generic", "assignees": PEOPLE, "confirmer": CONFIRMER,
        })["flow"]
        result = session.call_tool("dispatch_task", {"flow_id": flow["id"]})
        assert result["isError"] is True
        assert "工点" in result["structuredContent"]["error"]

    def test_missing_requirements_are_listed(self, session):
        """生成时就告诉调用方还缺什么，不必等到布置失败。"""
        payload = session.payload("create_flow_from_template", {"template": "generic"})
        missing = payload["missing_requirements"]
        assert len(missing) == 3
        assert any("责任人" in m for m in missing)
        assert any("确认人" in m for m in missing)
        assert any("工点" in m for m in missing)

    def test_complete_flow_has_no_missing(self, session):
        payload = session.payload("create_flow_from_template", {
            "template": "generic", "assignees": PEOPLE,
            "confirmer": CONFIRMER, "site": SITE,
        })
        assert payload["missing_requirements"] == []

    def test_schedule_rejects_incomplete_flow(self, session):
        """定时任务到点自动布置，缺责任人会静默失败在后台——登记时就要挡住。"""
        flow = session.payload("create_flow_from_template", {"template": "generic"})["flow"]
        result = session.call_tool("create_schedule", {
            "flow_id": flow["id"], "run_mode": "recurring",
            "first_at": "2026-03-02 09:00", "interval_unit": "week",
        })
        assert result["isError"] is True
        assert "自动布置" in result["structuredContent"]["error"]

    def test_site_and_confirmer_survive_dispatch(self, session):
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]

        assert task["site"]["ref"] == "wbs-3"
        assert task["site"]["code"] == "WBS-03-B1"
        assert task["confirmer"]["ref"] == "boss"

    def test_every_step_has_a_named_person(self, session):
        """每个节点都必须能追到具体的人。"""
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]

        for step in task["steps"]:
            assert step["assignee"] is not None, step["name"]
            assert step["assignee"]["ref"], step["name"]

    def test_task_answers_all_six_questions(self, session):
        """一项任务应能回答：谁负责、做什么、何时截止、哪个工点、交什么材料、谁确认。"""
        flow = ready_flow(session, "隐患整改")
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        step = task["steps"][0]

        assert step["assignee"]["name"]           # 1. 谁负责
        assert step["name"]                       # 2. 要做什么
        assert step["due_at"]                     # 3. 截止时间
        assert task["site"]["name"]               # 4. 关联哪个工点
        assert step["deliverable"]                # 5. 需要提交什么材料
        assert task["confirmer"]["name"]          # 6. 完成后由谁确认


class TestConfirmerAuthority:
    """只有指定的确认人能验收——否则验收就退化成走过场。"""

    def _finish_all(self, session):
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        for seq in range(len(task["steps"])):
            detail = session.payload("get_task", {"task_id": task["id"]})["task"]
            args = {"task_id": task["id"], "seq": seq, "actor": "u1"}
            if detail["steps"][seq]["requires_attachment"]:
                args["attachments"] = ["proof.jpg"]
            session.payload("complete_step", args)
        return task["id"]

    def test_non_confirmer_cannot_accept(self, session):
        task_id = self._finish_all(session)
        result = session.call_tool("accept_task", {"task_id": task_id, "actor": "u1"})
        assert result["isError"] is True
        assert "确认人" in result["structuredContent"]["error"]

    def test_confirmer_can_accept(self, session):
        task_id = self._finish_all(session)
        payload = session.payload("accept_task", {"task_id": task_id, "actor": "boss"})
        assert payload["task"]["state"] == "done"

    def test_non_confirmer_cannot_reject(self, session):
        task_id = self._finish_all(session)
        result = session.call_tool("reject_task", {
            "task_id": task_id, "actor": "u2", "reason": "不合格",
        })
        assert result["isError"] is True


class TestSiteQueries:
    """按工点检索——工程管理的常见需求。"""

    def test_filter_by_site(self, session):
        flow_a = ready_flow(session)
        session.payload("dispatch_task", {"flow_id": flow_a["id"]})

        other_site = {"ref": "wbs-9", "name": "9号楼-屋面"}
        flow_b = session.payload("create_flow_from_template", {
            "template": "generic", "assignees": PEOPLE,
            "confirmer": CONFIRMER, "site": other_site,
        })["flow"]
        session.payload("dispatch_task", {"flow_id": flow_b["id"]})

        assert session.payload("list_tasks", {"site": "wbs-3"})["count"] == 1
        assert session.payload("list_tasks", {"site": "wbs-9"})["count"] == 1
        assert session.payload("list_tasks")["count"] == 2

    def test_filter_by_confirmer(self, session):
        flow = ready_flow(session)
        session.payload("dispatch_task", {"flow_id": flow["id"]})

        assert session.payload("list_tasks", {"confirmer": "boss"})["count"] == 1
        assert session.payload("list_tasks", {"confirmer": "u1"})["count"] == 0


class TestErrorHandling:
    def test_missing_task_id(self, session):
        result = session.call_tool("complete_step", {"seq": 0})
        assert result["isError"] is True

    def test_nonexistent_task(self, session):
        result = session.call_tool("get_task", {"task_id": "task_nope"})
        assert result["isError"] is True

    def test_invalid_seq_type(self, session):
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        result = session.call_tool("complete_step", {"task_id": task["id"], "seq": "第一个"})
        assert result["isError"] is True

    def test_numeric_string_seq_rejected(self, session):
        """字符串形式的数字也要拒绝——宽松转换会掩盖调用方对 schema 的误解。"""
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        result = session.call_tool("complete_step", {"task_id": task["id"], "seq": "0"})
        assert result["isError"] is True
        assert "整数" in result["structuredContent"]["error"]

    def test_bool_seq_rejected(self, session):
        """bool 是 int 的子类，不挡的话 seq=True 会静默变成 seq=1。"""
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        result = session.call_tool("complete_step", {"task_id": task["id"], "seq": True})
        assert result["isError"] is True

    def test_invalid_limit_type_reports_error(self, session):
        """非法 limit 应返回工具错误，而非冒出未处理异常。"""
        result = session.call_tool("list_tasks", {"limit": "很多"})
        assert result["isError"] is True
        assert "整数" in result["structuredContent"]["error"]

    def test_illegal_transition_is_reported(self, session):
        flow = ready_flow(session)
        task = session.payload("dispatch_task", {"flow_id": flow["id"]})["task"]
        # 尚未完成所有节点就验收
        result = session.call_tool("accept_task", {"task_id": task["id"]})
        assert result["isError"] is True
        assert "待验收" in result["structuredContent"]["error"]

    def test_errors_do_not_kill_server(self, session):
        session.call_tool("get_task", {"task_id": "nope"})
        session.call_tool("no_such_tool")
        # 服务仍然可用
        assert session.payload("list_templates")["templates"]
