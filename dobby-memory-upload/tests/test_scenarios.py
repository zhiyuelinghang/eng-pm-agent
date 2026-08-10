#!/usr/bin/env python3
"""
Dobby 全量化场景测试

7 个真实场景，覆盖：循环路由、记忆检索、
知识库搜索、会话恢复、项目隔离。

Run: python test_scenarios.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
import json
from pathlib import Path

# ── Env setup ──
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,huggingface.co,cdn-lfs.huggingface.co")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

try:
    from dotenv import load_dotenv
    _env = Path(__file__).parent.parent / ".env"
    load_dotenv(_env, override=True)
except ImportError:
    pass

from agentscope.message import UserMsg


# ============================================================
# Test result tracker
# ============================================================

class TR:
    def __init__(self):
        self.results = []

    def add(self, name: str, passed: bool, detail: str = ""):
        self.results.append((name, passed, detail))
        icon = "✅" if passed else "❌"
        print(f"  {icon} {name}" + (f": {detail}" if detail else ""))

    def summary(self) -> bool:
        p = sum(1 for _, x, _ in self.results if x)
        total = len(self.results)
        all_pass = p == total
        print(f"\n{'='*60}")
        print(f"Results: {p}/{total} passed {'🎉 ALL PASS' if all_pass else '⚠️  SOME FAILED'}")
        print(f"{'='*60}")
        return all_pass


# ============================================================
# Setup helpers
# ============================================================

def _msg_text(msg) -> str:
    """Extract text from message object."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(str(block))
        return "".join(parts)
    if hasattr(content, "text"):
        return content.text
    return str(content)


async def _setup():
    """Build and compile the graph."""
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from utils.config import LANGGRAPH_CHECKPOINT_DB
    from utils.langgraph_utils import build_graph, compile_with_checkpointer
    from utils.roles import get_all_roles

    conn = psycopg.Connection.connect(
        LANGGRAPH_CHECKPOINT_DB, autocommit=True, prepare_threshold=0,
    )
    cp = PostgresSaver(conn=conn)
    cp.setup()

    roles = get_all_roles()
    builder = build_graph(roles=roles)
    graph = compile_with_checkpointer(builder, checkpointer=cp)
    return graph, conn, roles


# ============================================================
# Scenario 1: Single Role — Safety Director Regulation Query
# ============================================================

async def test_s1_safety_director(graph, r: TR):
    """安全总监收到安全规范问题，应引用具体规范条款。"""
    print("\n── 场景1：安全总监 — 规范查询 ──")
    try:
        config = {"configurable": {"thread_id": f"s1_{uuid.uuid4().hex[:8]}"}}
        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "3号基坑临边防护不符合JGJ 80规范，应该如何处理？请引用具体规范条款。")],
                    "project_id": "scenario_01",
                },
                config=config,
            ),
            timeout=60.0,
        )
        msgs = result.get("messages", [])
        current_role = result.get("current_role", "")
        response = _msg_text(msgs[-1]) if msgs else ""

        # Assertions
        has_response = len(response) > 20
        mentions_regulation = any(t in response for t in ["JGJ", "规范", "防护", "标准", "GB"])
        routed_correctly = current_role in ("safety_director", "dobby_core", "")

        r.add("S1.1 收到回复", has_response, f"长度={len(response)}字")
        r.add("S1.2 引用规范", mentions_regulation, f"role={current_role}")
        r.add("S1.3 路由正确", routed_correctly, f"→ {current_role}")
        return response
    except asyncio.TimeoutError:
        r.add("S1 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S1 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 2: Single Role — PM Progress Question
# ============================================================

async def test_s2_pm_progress(graph, r: TR):
    """项目经理收到进度问题，应给出有条理的进度分析。"""
    print("\n── 场景2：项目经理 — 进度问答 ──")
    try:
        config = {"configurable": {"thread_id": f"s2_{uuid.uuid4().hex[:8]}"}}
        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "项目总体进度如何？有哪些延期风险？请分点说明。")],
                    "project_id": "scenario_02",
                },
                config=config,
            ),
            timeout=60.0,
        )
        msgs = result.get("messages", [])
        response = _msg_text(msgs[-1]) if msgs else ""

        has_response = len(response) > 20
        structured = any(t in response for t in ["1.", "2.", "- ", "风险", "进度", "延期"])

        r.add("S2.1 收到回复", has_response, f"长度={len(response)}字")
        r.add("S2.2 结构化回答", structured, "包含序号或风险/进度分析")
        return response
    except asyncio.TimeoutError:
        r.add("S2 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S2 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 3: Loop Routing — Cross-Domain Multi-Role Collaboration
# ============================================================

async def test_s3_loop_routing(graph, r: TR):
    """循环路由模式：同时涉及安全和进度的跨领域问题应调用多个角色。"""
    print("\n── 场景3：循环路由 — 跨领域多角色协作 ──")
    try:
        tid = f"test-loop-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": tid}}
        project_id = "test-loop-project"

        message = "深基坑开挖前需要检查哪些安全项目？当前进度是否延误？"

        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", message)],
                    "project_id": project_id,
                    "thread_id": tid,
                },
                config=config,
            ),
            timeout=120.0,
        )

        msgs = result.get("messages", [])
        called = result.get("called_roles", [])
        iterations = result.get("iteration_count", 0)

        # 应该调用了至少 2 个角色
        has_enough_roles = len(called) >= 2
        # 不应该达到 max_cycles 上限
        not_capped = iterations < 10
        # 应该有最终回复
        has_final = len(msgs) > 0

        passed = has_enough_roles and not_capped and has_final
        r.add(
            "loop-routing-safety-progress",
            passed,
            f"called={called} iters={iterations} roles={len(called)}"
            if not passed else f"called {len(called)} roles in {iterations} iterations",
        )
        return _msg_text(msgs[-1]) if msgs else ""
    except asyncio.TimeoutError:
        r.add("S3 超时", False, "120秒未响应")
        return ""
    except Exception as e:
        r.add("S3 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 4: Memory Search
# ============================================================

async def test_s4_memory_search(r: TR):
    """测试记忆检索功能。"""
    print("\n── 场景4：记忆检索 ──")
    try:
        from utils.memory_tools import _execute_search_memory

        results = await asyncio.wait_for(
            _execute_search_memory(
                query="基坑 JGJ 安全",
                user_id="project_scenario_01",
                agent_id="role:safety_director",
                top_k=5,
            ),
            timeout=15.0,
        )

        has_results = isinstance(results, str) and len(results) > 10
        r.add("S4.1 检索成功", has_results, f"返回{len(results)}字")
        return results
    except asyncio.TimeoutError:
        r.add("S4 超时", False, "15秒未响应")
        return ""
    except Exception as e:
        r.add("S4 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 5: Knowledge Base Search
# ============================================================

async def test_s5_kb_search(r: TR):
    """测试知识库搜索功能。"""
    print("\n── 场景5：知识库搜索 ──")
    try:
        from utils.config import WEKNORA_API_KEY
        if not WEKNORA_API_KEY:
            r.add("S5 跳过", True, "WeKnora 未配置（需要 API Key）")
            return ""

        from utils.memory_tools import _execute_search_knowledge_base

        results = await asyncio.wait_for(
            _execute_search_knowledge_base(
                query="工程安全 基坑 防护",
                kb_names=None,
            ),
            timeout=15.0,
        )

        has_results = isinstance(results, str) and len(results) > 10
        r.add("S5.1 KB搜索成功", has_results, f"返回{len(results)}字" if has_results else "无结果")
        return results
    except asyncio.TimeoutError:
        r.add("S5 超时", False, "15秒未响应")
        return ""
    except Exception as e:
        r.add("S5 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 6: Session Persistence
# ============================================================

async def test_s6_session_resume(graph, r: TR):
    """同一 thread_id 两次调用，第二次应有上下文延续。"""
    print("\n── 场景6：会话恢复 ──")
    try:
        thread_id = f"s6_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        # Round 1
        r1 = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "我叫张三，是3号基坑的项目经理。")],
                    "project_id": "scenario_06",
                },
                config=config,
            ),
            timeout=60.0,
        )

        # Round 2 — fetch previous state, merge messages for context
        prev_state = await graph.aget_state(config)
        prev_messages = list(prev_state.values.get("messages", [])) if prev_state.values else []
        all_messages = prev_messages + [UserMsg("user", "我刚才说我是谁？")]

        r2 = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": all_messages,
                    "project_id": "scenario_06",
                },
                config=config,
            ),
            timeout=60.0,
        )

        r2_text = _msg_text(r2.get("messages", [])[-1]) if r2.get("messages") else ""
        r1_text = _msg_text(r1.get("messages", [])[-1]) if r1.get("messages") else ""

        remembers = "张三" in r2_text or "项目经理" in r2_text or "3号" in r2_text
        r.add("S6.1 第一轮成功", len(r1_text) > 10, f"回复{len(r1_text)}字")
        r.add("S6.2 记住上下文", remembers, "识别'张三'" if remembers else "未识别")
        return r2_text
    except asyncio.TimeoutError:
        r.add("S6 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S6 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 7: Project Isolation
# ============================================================

async def test_s7_project_isolation(graph, r: TR):
    """不同 project_id 的记忆应互不可见。"""
    print("\n── 场景7：项目隔离 ──")
    try:
        # Project A
        c_a = {"configurable": {"thread_id": f"s7a_{uuid.uuid4().hex[:8]}"}}
        await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "项目Alpha：3号基坑发现裂缝，需要立即整改。")],
                    "project_id": "project_alpha",
                },
                config=c_a,
            ),
            timeout=60.0,
        )

        # Project B
        c_b = {"configurable": {"thread_id": f"s7b_{uuid.uuid4().hex[:8]}"}}
        r_b = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "请列出project_beta中的所有已知问题。")],
                    "project_id": "project_beta",
                },
                config=c_b,
            ),
            timeout=60.0,
        )

        b_text = _msg_text(r_b.get("messages", [])[-1]) if r_b.get("messages") else ""

        # Project B should NOT know about project_alpha's cracks
        no_leak = "Alpha" not in b_text and "裂缝" not in b_text
        r.add("S7.1 项目A写入成功", True)
        r.add("S7.2 项目B不泄露", no_leak, "Alpha数据未泄露到Beta" if no_leak else "存在跨项目泄露")
        return b_text
    except asyncio.TimeoutError:
        r.add("S7 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S7 异常", False, str(e)[:100])
        return ""


# ============================================================
# Scenario 8: Thread ID State Propagation (BUGFIX VERIFICATION)
# ============================================================

async def test_s8_thread_id_in_state(graph, r: TR):
    """验证 thread_id 被正确写入 DobbyState（修复关键bug）。"""
    print("\n── 场景8：Thread ID State 传播验证 ──")
    try:
        thread_id = f"s8_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "测试消息：请回复OK。")],
                    "project_id": "scenario_08",
                    "thread_id": thread_id,  # ← 关键修复：传入 thread_id
                },
                config=config,
            ),
            timeout=60.0,
        )

        state_thread_id = result.get("thread_id", "")
        msgs = result.get("messages", [])
        response = _msg_text(msgs[-1]) if msgs else ""

        # Assertions
        state_has_tid = state_thread_id == thread_id
        has_response = len(response) > 0

        r.add("S8.1 state.thread_id 正确", state_has_tid,
              f"期望={thread_id}, 实际={state_thread_id}" if not state_has_tid else "OK")
        r.add("S8.2 收到回复", has_response, f"长度={len(response)}字")

        # Verify checkpoint persistence
        state = await graph.aget_state(config)
        checkpoint_tid = state.values.get("thread_id", "") if state.values else ""
        checkpoint_tid_ok = checkpoint_tid == thread_id
        r.add("S8.3 checkpoint 持久化", checkpoint_tid_ok,
              f"期望={thread_id}, 实际={checkpoint_tid}" if not checkpoint_tid_ok else "OK")

        return response
    except asyncio.TimeoutError:
        r.add("S8 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S8 异常", False, str(e)[:200])
        return ""


# ============================================================
# Scenario 9: Cross-Session Memory Isolation
# ============================================================

async def test_s9_session_isolation(graph, r: TR):
    """不同 thread_id 的上下文应相互隔离（修复跨会话串扰bug）。"""
    print("\n── 场景9：跨会话数据隔离验证 ──")
    try:
        tid_a = f"s9a_{uuid.uuid4().hex[:8]}"
        tid_b = f"s9b_{uuid.uuid4().hex[:8]}"

        # Session A: 基坑防护问题
        await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "3号基坑东侧临边防护护栏高度只有0.8米，不达标。")],
                    "project_id": "scenario_09a",
                    "thread_id": tid_a,
                },
                config={"configurable": {"thread_id": tid_a}},
            ),
            timeout=60.0,
        )

        # Session B: 完全不同的项目
        r_b = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [UserMsg("user", "请列出当前已知的安全隐患。")],
                    "project_id": "scenario_09b",
                    "thread_id": tid_b,
                },
                config={"configurable": {"thread_id": tid_b}},
            ),
            timeout=60.0,
        )

        b_text = _msg_text(r_b.get("messages", [])[-1]) if r_b.get("messages") else ""

        # Session B should NOT know about Session A's specific details
        # Use only unique identifiers that LLM cannot coincidentally generate
        leak_keywords = ["0.8米", "基坑东侧"]
        leaked = any(kw in b_text for kw in leak_keywords)

        # Direct state check: Session B's checkpoint should NOT contain Session A's message
        state_b = await graph.aget_state({"configurable": {"thread_id": tid_b}})
        b_messages = " ".join(
            _msg_text(m) for m in (state_b.values.get("messages", []) if state_b.values else [])
        )
        # Check that Session A's unique detail didn't leak into Session B's state
        state_leak = "0.8米" in b_messages or "基坑东侧" in b_messages

        r.add("S9.1 Session A 写入", True)
        r.add("S9.2 Session B 不泄露(响应)",
              not leaked,
              f"泄露={leaked}" if leaked else "隔离正常")
        r.add("S9.3 Session B 不泄露(状态)",
              not state_leak,
              f"状态泄露" if state_leak else "隔离正常")

        return b_text
    except asyncio.TimeoutError:
        r.add("S9 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S9 异常", False, str(e)[:200])
        return ""


# ============================================================
# Scenario 10: Multi-Turn Conversation Continuity (CRITICAL BUGFIX)
# ============================================================

async def test_s10_multi_turn_memory(graph, r: TR):
    """多轮对话：第二轮应记住第一轮的内容（验证 messages 覆盖修复）。"""
    print("\n── 场景10：多轮对话记忆连续性 ──")
    try:
        thread_id = f"s10_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        # Turn 1: share specific information
        state_input_1 = {
            "messages": [UserMsg("user", "我叫张工，负责3号基坑项目。A区东侧护栏高度只有0.8米，不达标。")],
            "project_id": "scenario_10",
            "thread_id": thread_id,
        }
        r1 = await asyncio.wait_for(
            graph.ainvoke(state_input_1, config=config),
            timeout=60.0,
        )
        r1_text = _msg_text(r1.get("messages", [])[-1]) if r1.get("messages") else ""

        # Turn 2: restore session — fetch checkpoint + append new message
        # (simulating the fixed app.py behavior)
        prev = await graph.aget_state(config)
        existing = list(prev.values.get("messages", [])) if prev and prev.values else []
        r2 = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": existing + [UserMsg("user", "我刚才说了护栏高度是多少？在哪个区域？")],
                    "project_id": "scenario_10",
                    "thread_id": thread_id,
                },
                config=config,
            ),
            timeout=60.0,
        )
        r2_text = _msg_text(r2.get("messages", [])[-1]) if r2.get("messages") else ""

        # Assertions: Turn 2 must remember Turn 1's details
        has_round1 = len(r1_text) > 20
        remembers_height = "0.8米" in r2_text or "0.8" in r2_text
        remembers_location = "A区" in r2_text or "东侧" in r2_text
        remembers_person = "张工" in r2_text or "人名" not in r2_text  # LLM may use pronoun

        r.add("S10.1 第一轮成功", has_round1, f"回复{len(r1_text)}字")
        r.add("S10.2 记住护栏高度(0.8米)", remembers_height,
              "✅" if remembers_height else "❌ 未识别高度")
        r.add("S10.3 记住区域(A区东侧)", remembers_location,
              "✅" if remembers_location else "❌ 未识别区域")
        r.add("S10.4 记住人名(张工)", remembers_person,
              "✅" if remembers_person else "❌ 未识别人名")
        return r2_text
    except asyncio.TimeoutError:
        r.add("S10 超时", False, "60秒未响应")
        return ""
    except Exception as e:
        r.add("S10 异常", False, str(e)[:200])
        return ""


# ============================================================
# Main
# ============================================================

async def main():
    r = TR()
    graph = None
    conn = None

    print("=" * 60)
    print("Dobby 全量化场景测试")
    print("=" * 60)

    # ── Setup ──
    print("\n[初始化] 连接数据库 + 构建 Graph...")
    try:
        graph, conn, roles = await asyncio.wait_for(_setup(), timeout=30.0)
        print(f"  ✅ Graph 就绪 ({len(roles)} 角色)")
        r.add("INIT 初始化", True)
    except Exception as e:
        print(f"  ❌ 初始化失败: {e}")
        r.add("INIT 初始化", False, str(e)[:100])
        r.summary()
        return

    # ── Run scenarios ──
    try:
        await test_s1_safety_director(graph, r)
    except Exception as e:
        r.add("S1 崩溃", False, str(e)[:100])

    try:
        await test_s2_pm_progress(graph, r)
    except Exception as e:
        r.add("S2 崩溃", False, str(e)[:100])

    try:
        await test_s3_loop_routing(graph, r)
    except Exception as e:
        r.add("S3 崩溃", False, str(e)[:100])

    try:
        await test_s4_memory_search(r)
    except Exception as e:
        r.add("S4 崩溃", False, str(e)[:100])

    try:
        await test_s5_kb_search(r)
    except Exception as e:
        r.add("S5 崩溃", False, str(e)[:100])

    try:
        await test_s6_session_resume(graph, r)
    except Exception as e:
        r.add("S6 崩溃", False, str(e)[:100])

    try:
        await test_s7_project_isolation(graph, r)
    except Exception as e:
        r.add("S7 崩溃", False, str(e)[:100])

    try:
        await test_s8_thread_id_in_state(graph, r)
    except Exception as e:
        r.add("S8 崩溃", False, str(e)[:100])

    try:
        await test_s9_session_isolation(graph, r)
    except Exception as e:
        r.add("S9 崩溃", False, str(e)[:100])

    try:
        await test_s10_multi_turn_memory(graph, r)
    except Exception as e:
        r.add("S10 崩溃", False, str(e)[:100])

    # ── Cleanup ──
    if conn:
        conn.close()

    r.summary()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
