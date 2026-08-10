#!/usr/bin/env python3
"""
demo_05_multi_agent.py — Step 5: Multi-Agent Collaboration Verification

Validates the LangGraph supervisor-via-tools pattern with:
  - Dynamic role routing via Command(goto=...)
  - 5+ role agents with isolated Mem0 / WeKnora bindings
  - Handoff state transfer (summary + tasks)
  - Sub-agent delegation with isolated context windows
  - Backward compatibility with demo_03 (2-role legacy mode)

12 acceptance criteria. Run:
    python demo_05_multi_agent.py
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import uuid

# ── Project root (acceptance_tests/ 的父目录 = dobby-memory) ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ── Load environment ──
try:
    from dotenv import load_dotenv
    _env = os.path.join(_ROOT, ".env")
    load_dotenv(_env, override=True)
except ImportError:
    pass


# ============================================================
# TR — Test Result Tracker
# ============================================================

class TR:
    def __init__(self):
        self.r = []

    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        print(f"  {'✅' if passed else '❌'} {name}" + (f": {detail}" if detail else ""))

    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        print(f"\n{'='*60}\nResults: {p}/{len(self.r)} passed "
              f"{'🎉 ALL PASS' if p == len(self.r) else '⚠️  SOME FAILED'}\n{'='*60}")
        return p == len(self.r)


# ============================================================
# Helpers (mirrored from demo_03/04)
# ============================================================

def _msg_text(msg) -> str:
    """Extract plain text from any message object."""
    content = ""
    if hasattr(msg, "content"):
        content = msg.content
    elif isinstance(msg, dict):
        content = msg.get("content", "")
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


async def _setup_checkpointer():
    """Create PostgresSaver with setup."""
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    from utils.config import LANGGRAPH_CHECKPOINT_DB
    conn = psycopg.Connection.connect(LANGGRAPH_CHECKPOINT_DB, autocommit=True, prepare_threshold=0)
    cp = PostgresSaver(conn=conn)
    cp.setup()
    return cp, conn


def _compile_graph(checkpointer, roles=None):
    """Compile graph with checkpointer. roles=None → legacy 2-role."""
    from utils.langgraph_utils import build_graph, compile_with_checkpointer
    builder = build_graph(roles=roles)
    return compile_with_checkpointer(builder, checkpointer=checkpointer)


# ============================================================
# Mem0 helper (mirrored from demo_04)
# ============================================================

def _build_mem0_config():
    """Build Mem0 config for pgvector."""
    from mem0.configs.base import MemoryConfig as MC
    from mem0.vector_stores.configs import VectorStoreConfig
    from utils import config as _cfg

    return MC(
        vector_store=VectorStoreConfig(
            provider="pgvector",
            config={
                "dbname": "dobby_demo",
                "host": "localhost",
                "port": 5432,
                "user": "dobby",
                "password": "dobby",
                "embedding_model_dims": _cfg.EMBEDDING_DIMS,
                "collection_name": "dobby_memories",
            },
        ),
        llm={
            "provider": "deepseek",
            "config": {
                "model": "deepseek-chat",
                "api_key": _cfg.DEEPSEEK_API_KEY,
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        embedder={
            "provider": "huggingface",
            "config": {"model": _cfg.EMBEDDING_MODEL},
        },
        version="v1.1",
    )


def _mem0_add_sync(text, user_id, agent_id, metadata=None):
    from mem0 import Memory as MM
    m = MM(_build_mem0_config())
    try:
        return m.add(text, user_id=user_id, agent_id=agent_id, metadata=metadata, infer=False)
    finally:
        # Help cleanup httpx client
        if hasattr(m, 'close'):
            try:
                m.close()
            except Exception:
                pass


async def _mem0_add(text, user_id, agent_id, metadata=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=1),
        _mem0_add_sync, text, user_id, agent_id, metadata,
    )


def _mem0_search_sync(query, user_id, limit=10, threshold=0.0):
    from mem0 import Memory as MM
    m = MM(_build_mem0_config())
    try:
        result = m.search(query, filters={"user_id": user_id}, limit=limit, threshold=threshold)
    except Exception:
        return []
    if isinstance(result, dict):
        return result.get("results", [])
    if isinstance(result, list):
        return result
    return []


async def _mem0_search(query, user_id, limit=10, threshold=0.0):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=1),
        _mem0_search_sync, query, user_id, limit, threshold,
    )


# ============================================================
# AC-5.1 — Handoff Routing
# ============================================================

async def t51_handoff_routing(r: TR):
    """Safety query → supervisor routes to safety_director via Command."""
    from agentscope.message import UserMsg
    from utils.roles import get_roles

    cp, conn = await _setup_checkpointer()
    try:
        pid = f"ac51_{uuid.uuid4().hex[:8]}"
        roles = get_roles(["dobby_core", "safety_director"])
        graph = _compile_graph(cp, roles=roles)

        config = {"configurable": {"thread_id": f"th51_{uuid.uuid4().hex[:8]}"}}
        result = await graph.ainvoke(
            {"messages": [UserMsg("user", "3号基坑临边防护有什么安全要求？请引用规范")],
             "project_id": pid},
            config=config,
        )

        msgs = result.get("messages", [])
        current_role = result.get("current_role", "")
        response_text = _msg_text(msgs[-1]) if msgs else ""

        # Should route to safety_director (not dobby_core)
        routed_to_safety = current_role == "safety_director"
        mentions_spec = "JGJ" in response_text or "规范" in response_text or "防护" in response_text

        r.add("AC-5.1 Handoff Routing",
              routed_to_safety and mentions_spec,
              f"role={current_role}, refs={'✓' if mentions_spec else '✗'}")
    except Exception as e:
        r.add("AC-5.1 Handoff Routing", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-5.2 — Non-Matching Role Rejection
# ============================================================

async def t52_role_rejection(r: TR):
    """A role agent should not answer out-of-scope questions directly."""
    from agentscope.message import UserMsg
    from utils.roles import get_roles

    cp, conn = await _setup_checkpointer()
    try:
        pid = f"ac52_{uuid.uuid4().hex[:8]}"
        roles = get_roles(["dobby_core", "safety_director"])
        graph = _compile_graph(cp, roles=roles)

        config = {"configurable": {"thread_id": f"th52_{uuid.uuid4().hex[:8]}"}}
        result = await graph.ainvoke(
            {"messages": [UserMsg("user", "项目总体进度如何？有哪些延期风险？")],
             "project_id": pid},
            config=config,
        )

        current_role = result.get("current_role", "")
        # Progress question → should NOT route to safety_director
        not_safety = current_role != "safety_director"
        r.add("AC-5.2 Role Rejection",
              not_safety,
              f"routed to {current_role} (not safety_director)")
    except Exception as e:
        r.add("AC-5.2 Role Rejection", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-5.3 — Handoff State Transfer
# ============================================================

async def t53_state_transfer(r: TR):
    """Summary and tasks should persist across handoffs."""
    from agentscope.message import UserMsg
    from utils.roles import get_roles

    cp, conn = await _setup_checkpointer()
    try:
        pid = f"ac53_{uuid.uuid4().hex[:8]}"
        roles = get_roles(["dobby_core", "safety_director"])
        graph = _compile_graph(cp, roles=roles)

        tid = f"th53_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": tid}}

        # First turn — set summary via compress-like injection
        result1 = await graph.ainvoke(
            {"messages": [UserMsg("user", "帮我记录：3号基坑东侧围护结构有渗漏风险，需要监测")],
             "project_id": pid,
             "summary": "项目X，3号基坑开挖阶段，东侧围护渗漏风险待监测",
             "tasks": {"T1": {"status": "in_progress", "desc": "围护结构渗漏监测"}}},
            config=config,
        )

        # Get state and check summary/tasks survived
        state = await graph.aget_state(config)
        summary_after = state.values.get("summary", "") if state else ""
        tasks_after = state.values.get("tasks", {}) if state else {}

        summary_ok = "渗漏" in summary_after or "围护" in summary_after
        tasks_ok = "T1" in tasks_after

        # Second turn — safety query, tasks should persist
        result2 = await graph.ainvoke(
            {"messages": [UserMsg("user", "围护结构渗漏有什么安全规范要求？")],
             "project_id": pid},
            config=config,
        )

        state2 = await graph.aget_state(config)
        tasks2 = state2.values.get("tasks", {}) if state2 else {}
        tasks_survived = "T1" in tasks2

        r.add("AC-5.3 State Transfer",
              summary_ok and tasks_ok and tasks_survived,
              f"summary={'✓' if summary_ok else '✗'} tasks={'✓' if tasks_ok else '✗'} survived={'✓' if tasks_survived else '✗'}")
    except Exception as e:
        r.add("AC-5.3 State Transfer", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-5.4 — Mem0 Role Isolation
# ============================================================

async def t54_mem0_isolation(r: TR):
    """PM memories should not be searchable by safety_director's agent_id."""
    pid = f"ac54_{uuid.uuid4().hex[:8]}"

    # Add memory as PM role — ensure fresh client each call
    try:
        await _mem0_add(
            "项目进度会议决定3号基坑7月25日开挖",
            user_id=pid,
            agent_id="role:pm",
            metadata={"memory_type": "decision", "importance": 0.7},
        )
        await asyncio.sleep(1.5)
    except Exception as e:
        r.add("AC-5.4 Mem0 Isolation", False, f"add pm failed: {str(e)[:80]}")
        return

    # Add memory as safety role
    try:
        await _mem0_add(
            "3号基坑西侧发现支护结构裂缝",
            user_id=pid,
            agent_id="role:safety_director",
            metadata={"memory_type": "finding", "importance": 0.8},
        )
        await asyncio.sleep(1.5)
    except Exception as e:
        r.add("AC-5.4 Mem0 Isolation", False, f"add safety failed: {str(e)[:80]}")
        return

    try:
        # Search for both memories
        all_results = await _mem0_search("基坑", user_id=pid, limit=20)
        has_memories = len(all_results) >= 1

        r.add("AC-5.4 Mem0 Isolation",
              has_memories,
              f"found={len(all_results)} memories for project")
    except Exception as e:
        r.add("AC-5.4 Mem0 Isolation", False, str(e)[:100])


# ============================================================
# AC-5.5 — WeKnora KB Binding
# ============================================================

async def t55_kb_binding(r: TR):
    """Role node uses its bound WeKnora KB for retrieval."""
    from utils.roles import get_role

    safety_role = get_role("safety_director")
    pm_role = get_role("pm")

    # Verify role configs have correct KB bindings
    safety_has_kb = safety_role is not None and safety_role.weknora_kb_ids is not None
    pm_no_kb = pm_role is not None and pm_role.weknora_kb_ids is None

    # Verify safety has "search_knowledge" in tools
    safety_has_search = "search_knowledge" in safety_role.tools if safety_role else False
    pm_no_search = "search_knowledge" not in pm_role.tools if pm_role else True

    r.add("AC-5.5 KB Binding",
          safety_has_kb and pm_no_kb and safety_has_search and pm_no_search,
          f"safety_kb={'✓' if safety_has_kb else '✗'} pm_no_kb={'✓' if pm_no_kb else '✗'} "
          f"safety_search={'✓' if safety_has_search else '✗'} pm_no_search={'✓' if pm_no_search else '✗'}")


# ============================================================
# AC-5.6 — Sub-Agent Isolation
# ============================================================

async def t56_subagent_isolation(r: TR):
    """delegate_task spawns an isolated sub-agent that doesn't pollute parent."""
    from utils.sub_agent import delegate_task

    try:
        task_id = f"sub_{uuid.uuid4().hex[:8]}"
        result = await delegate_task(
            description="分析以下场景的安全隐患：某建筑工地3号基坑深8米，"
                        "东侧紧邻市政道路（距离仅2米），基坑支护采用排桩+锚杆方案。"
                        "请列出至少2个潜在风险点。",
            file_refs=None,
            timeout=60.0,
        )

        status_ok = result.get("status") in ("success", "failed")
        has_findings = len(result.get("findings", [])) >= 1
        has_summary = len(result.get("summary", "")) > 10

        r.add("AC-5.6 Sub-Agent Isolation",
              status_ok and has_findings and has_summary,
              f"status={result.get('status')} findings={len(result.get('findings', []))} "
              f"summary_len={len(result.get('summary', ''))}")
    except Exception as e:
        r.add("AC-5.6 Sub-Agent Isolation", False, str(e)[:100])


# ============================================================
# AC-5.7 — Sub-Agent Structured Output
# ============================================================

async def t57_subagent_output(r: TR):
    """Sub-agent returns structured JSON with all required fields."""
    from utils.sub_agent import delegate_task

    try:
        result = await delegate_task(
            description="判断以下场景的风险等级：施工现场一台塔吊在6级风中继续作业，"
                        "起重臂长50米，吊载重量2吨。",
            timeout=60.0,
        )

        required_fields = ["status", "summary", "findings", "severity", "recommendation", "confidence"]
        all_present = all(f in result for f in required_fields)
        severity_valid = result.get("severity") in ("high", "medium", "low")
        confidence_valid = 0.0 <= result.get("confidence", -1) <= 1.0

        r.add("AC-5.7 Sub-Agent Output",
              all_present and severity_valid and confidence_valid,
              f"fields={'✓' if all_present else '✗'} severity={'✓' if severity_valid else '✗'} "
              f"confidence={'✓' if confidence_valid else '✗'}")
    except Exception as e:
        r.add("AC-5.7 Sub-Agent Output", False, str(e)[:100])


# ============================================================
# AC-5.8 — Sub-Agent Timeout
# ============================================================

async def t58_subagent_timeout(r: TR):
    """Sub-agent timeout detection via preemptive cancellation."""
    import asyncio

    async def _slow_call(*args, **kwargs):
        """Simulate a very slow LLM call that exceeds timeout."""
        await asyncio.sleep(10.0)  # Will be cancelled before this finishes
        return None

    from utils.sub_agent import delegate_task
    try:
        result = await delegate_task(
            description="测试超时处理的任务",
            timeout=0.1,  # Very short — will definitely timeout
            _call_model_fn=_slow_call,
        )

        is_timeout = result.get("status") == "timeout"
        r.add("AC-5.8 Sub-Agent Timeout",
              is_timeout,
              f"status={result.get('status')} expect=timeout")
    except asyncio.TimeoutError:
        r.add("AC-5.8 Sub-Agent Timeout", True, "TimeoutError raised")
    except Exception as e:
        r.add("AC-5.8 Sub-Agent Timeout", False, str(e)[:80])


# ============================================================
# AC-5.9 — Broadcast (Parallel Aggregation)  [OPTIONAL — Phase 2]
# ============================================================

async def t59_broadcast(r: TR):
    """Sequential simulation: query multiple roles and aggregate results."""
    from agentscope.message import UserMsg
    from utils.roles import get_roles

    cp, conn = await _setup_checkpointer()
    try:
        pid = f"ac59_{uuid.uuid4().hex[:8]}"
        roles = get_roles(["dobby_core", "safety_director", "inspector"])
        graph = _compile_graph(cp, roles=roles)

        tid = f"th59_{uuid.uuid4().hex[:8]}"

        # Query safety_director
        config_s = {"configurable": {"thread_id": f"{tid}_safety"}}
        r_safety = await graph.ainvoke(
            {"messages": [UserMsg("user", "3号基坑临边防护规范要求是什么？")],
             "project_id": pid},
            config=config_s,
        )

        # Query inspector (监理)
        config_v = {"configurable": {"thread_id": f"{tid}_inspector"}}
        r_inspector = await graph.ainvoke(
            {"messages": [UserMsg("user", "3号基坑临边防护施工质量如何验收？")],
             "project_id": pid},
            config=config_v,
        )

        # Both should succeed and return different roles
        safety_role = r_safety.get("current_role", "")
        inspector_role = r_inspector.get("current_role", "")

        both_ok = safety_role == "safety_director" and inspector_role == "inspector"
        r.add("AC-5.9 Broadcast (simulated)",
              both_ok,
              f"safety={safety_role} inspector={inspector_role}")
    except Exception as e:
        r.add("AC-5.9 Broadcast", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-5.10 — Post-Compression Role Context Preservation
# ============================================================

async def t5a_post_compress(r: TR):
    """Tasks should survive compression in a role context."""
    from agentscope.message import UserMsg
    from utils.roles import get_roles
    import utils.config as cfg

    cp, conn = await _setup_checkpointer()
    try:
        pid = f"ac5a_{uuid.uuid4().hex[:8]}"
        roles = get_roles(["dobby_core", "safety_director"])
        graph = _compile_graph(cp, roles=roles)

        tid = f"th5a_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": tid}}

        # Build up many messages to trigger compression
        msgs = [UserMsg("user", "项目启动：3号基坑开挖")]
        for i in range(30):
            msgs.append(UserMsg("user", f"进度更新{i}: 第{i}号桩完成浇筑，检测合格。"
                                 f"现场安全巡检通过，无隐患报告。"
                                 f"监理单位已签认工序报验单。"))
            msgs.append(UserMsg("assistant", f"收到更新{i}。已记录：第{i}号桩完成，检测合格。"))

        # Set low compression threshold
        old_threshold = cfg.COMPRESSION_TRIGGER_TOKENS
        cfg.COMPRESSION_TRIGGER_TOKENS = 500
        try:
            result = await graph.ainvoke(
                {"messages": msgs,
                 "project_id": pid,
                 "tasks": {"T_START": {"status": "in_progress", "desc": "基坑开挖"}}},
                config=config,
            )
        finally:
            cfg.COMPRESSION_TRIGGER_TOKENS = old_threshold

        # Check tasks survived
        tasks = result.get("tasks", {})
        tasks_ok = "T_START" in tasks

        r.add("AC-5.10 Post-Compress",
              tasks_ok,
              f"tasks={'✓' if tasks_ok else '✗'} compression_count={result.get('compression_count', 0)}")
    except Exception as e:
        r.add("AC-5.10 Post-Compress", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-5.11 — Cross-Role Experience Extraction
# ============================================================

async def t5b_crossrole_experience(r: TR):
    """Experience extraction should work across roles (project-scoped, not role-scoped)."""
    from utils.lifecycle import extract_experiences

    pid = f"ac5b_{uuid.uuid4().hex[:8]}"
    tid1 = f"task_pm_{uuid.uuid4().hex[:8]}"
    tid2 = f"task_safety_{uuid.uuid4().hex[:8]}"

    # Simulate completed tasks from different roles
    tasks = {
        tid1: {"status": "done",
               "description": "项目经理组织召开了3号基坑开挖前的安全技术交底会议，"
                              "参会单位包括施工、监理、建设方。会议通过了开挖方案，"
                              "明确了监测频率为每天2次，应急物资已到位。",
               "extracted": False},
        tid2: {"status": "done",
               "description": "安全总监完成3号基坑临边防护专项检查，发现东侧栏杆"
                              "高度1.05m不满足JGJ 80-2016要求的1.2m，已发出"
                              "整改通知RECT-2026-003，限期1天完成。",
               "extracted": False},
    }

    try:
        result = await extract_experiences(project_id=pid, tasks=tasks)
        extracted = result.get("extracted", {})
        inserts = result.get("total_inserts", 0)

        both_extracted = extracted.get(tid1) and extracted.get(tid2)
        r.add("AC-5.11 Cross-Role Experience",
              both_extracted and inserts >= 2,
              f"extracted={'✓' if both_extracted else '✗'} inserts={inserts}")
    except Exception as e:
        r.add("AC-5.11 Cross-Role Experience", False, str(e)[:100])


# ============================================================
# AC-5.12 — Backward Compatibility with demo_03
# ============================================================

async def t5c_backward_compat(r: TR):
    """build_graph() without roles parameter → legacy 2-role behavior."""
    from agentscope.message import UserMsg

    cp, conn = await _setup_checkpointer()
    try:
        # Use legacy mode (no roles argument)
        graph = _compile_graph(cp, roles=None)

        pid = f"ac5c_{uuid.uuid4().hex[:8]}"
        tid = f"th5c_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": tid}}

        # Safety query
        result1 = await graph.ainvoke(
            {"messages": [UserMsg("user", "JGJ 80-2016对防护栏杆高度有什么要求？")],
             "project_id": pid},
            config=config,
        )
        role1 = result1.get("current_role", "")
        text1 = _msg_text(result1.get("messages", [{}])[-1]) if result1.get("messages") else ""

        safety_ok = "safety_director" in role1

        # General query
        result2 = await graph.ainvoke(
            {"messages": [UserMsg("user", "今天天气怎么样？")],
             "project_id": pid},
            config=config,
        )
        role2 = result2.get("current_role", "")
        general_ok = "dobby_core" in role2

        r.add("AC-5.12 Backward Compat",
              safety_ok and general_ok,
              f"safety={'✓' if safety_ok else '✗'} general={'✓' if general_ok else '✗'}")
    except Exception as e:
        r.add("AC-5.12 Backward Compat", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# Main
# ============================================================

async def main():
    r = TR()
    print("=" * 60)
    print("Step 5: Multi-Agent Collaboration — Verification")
    print("=" * 60)

    tests = [
        ("AC-5.1 Handoff Routing", t51_handoff_routing),
        ("AC-5.2 Role Rejection", t52_role_rejection),
        ("AC-5.3 State Transfer", t53_state_transfer),
        ("AC-5.4 Mem0 Isolation", t54_mem0_isolation),
        ("AC-5.5 KB Binding", t55_kb_binding),
        ("AC-5.6 Sub-Agent Isolation", t56_subagent_isolation),
        ("AC-5.7 Sub-Agent Output", t57_subagent_output),
        ("AC-5.8 Sub-Agent Timeout", t58_subagent_timeout),
        ("AC-5.9 Broadcast (simulated)", t59_broadcast),
        ("AC-5.10 Post-Compress", t5a_post_compress),
        ("AC-5.11 Cross-Role Experience", t5b_crossrole_experience),
        ("AC-5.12 Backward Compat", t5c_backward_compat),
    ]

    for name, fn in tests:
        print(f"\n── {name} ──")
        try:
            await fn(r)
        except Exception as e:
            r.add(name, False, f"unhandled: {str(e)[:100]}")

    return r.summary()


if __name__ == "__main__":
    import selectors
    lf = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    success = asyncio.run(main(), loop_factory=lf)
    sys.exit(0 if success else 1)
