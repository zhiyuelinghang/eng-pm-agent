#!/usr/bin/env python3
"""
Demo Step 3: LangGraph PostgresSaver as session state source of truth.

Usage:
  $env:DEEPSEEK_API_KEY="sk-..."
  $env:HF_HUB_OFFLINE="1"                # skip HuggingFace online checks
  $env:WEKNORA_API_KEY="<jwt-token>"     # optional, for AC-3.5
  python demo_03_postgres_saver.py

Prerequisites:
  - Step 1 verified (demo_01_base.py)  — PG + pgvector alive
  - Step 2 verified (demo_02_weknora.py) — WeKnora optional for AC-3.5

Verified against: langgraph==1.1.6, langgraph-checkpoint-postgres==3.1.0 (July 2026)
"""

import asyncio
import concurrent.futures
import json
import os
import selectors
import sys
import time
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dobby-memory/
sys.path.insert(0, _ROOT)
from utils.config import (
    DATABASE_URL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_CONTEXT_SIZE,
    DEEPSEEK_BASE_URL,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    EMBEDDING_DIMS,
    MEM0_USER_ID,
    MEM0_AGENT_ID,
    WEKNORA_BASE_URL,
    WEKNORA_API_KEY,
    WEKNORA_KB_NAME,
    LANGGRAPH_CHECKPOINT_DB,
    COMPRESSION_TRIGGER_TOKENS,
    COMPRESSION_KEEP_MESSAGES,
    validate as config_validate,
    summary as config_summary,
)


# ============================================================
# Test Results
# ============================================================
class TR:
    def __init__(self):
        self.r = []

    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        print(f"  {'✅' if passed else '❌'} {name}" + (f": {detail}" if detail else ""))

    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        print(f"\n{'='*60}\nResults: {p}/{len(self.r)} passed {'🎉 ALL PASS' if p == len(self.r) else '⚠️  FAILURES'}\n{'='*60}")
        return p == len(self.r)


def _extract(resp) -> str:
    if hasattr(resp, "content"):
        return resp.content if isinstance(resp.content, str) else str(resp.content)
    if hasattr(resp, "get_text_content"):
        return resp.get_text_content()
    return str(resp)


def _msg_text(msg) -> str:
    """Extract plain text from any message object (AgentScope Msg, dict, etc.)."""
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


# ============================================================
# Shared helpers
# ============================================================
def _build_model():
    from agentscope.model import DeepSeekChatModel
    from agentscope.credential import DeepSeekCredential
    return DeepSeekChatModel(
        credential=DeepSeekCredential(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL),
        model=DEEPSEEK_MODEL,
        context_size=DEEPSEEK_CONTEXT_SIZE,
    )


def _build_mem0_config():
    from mem0.configs.base import MemoryConfig as MC
    from mem0.vector_stores.configs import VectorStoreConfig
    return MC(
        vector_store=VectorStoreConfig(provider="pgvector", config={
            "dbname": "dobby_demo", "host": "localhost", "port": 5432,
            "user": "dobby", "password": "dobby",
            "embedding_model_dims": EMBEDDING_DIMS,
            "collection_name": "dobby_memories",
        }),
        llm={"provider": "deepseek", "config": {
            "model": "deepseek-chat", "api_key": DEEPSEEK_API_KEY,
            "temperature": 0.1, "max_tokens": 2000,
        }},
        embedder={"provider": "huggingface", "config": {"model": EMBEDDING_MODEL}},
        version="v1.1",
    )


async def _setup_checkpointer():
    """Create PostgresSaver with persistent connection. Returns (cp, conn)."""
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.Connection.connect(
        LANGGRAPH_CHECKPOINT_DB,
        autocommit=True,
        prepare_threshold=0,
    )
    cp = PostgresSaver(conn=conn)
    cp.setup()  # synchronous, creates tables
    return cp, conn


def _compile_graph(checkpointer):
    """Compile the Dobby StateGraph with the given checkpointer."""
    from utils.langgraph_utils import build_graph, compile_with_checkpointer
    builder = build_graph()
    return compile_with_checkpointer(builder, checkpointer=checkpointer)


# ============================================================
# AC-3.1: PostgresSaver deployment
# ============================================================
async def t31_saver_setup(r: TR):
    """Verify PostgresSaver.setup() creates checkpoint tables in dobby_demo."""
    try:
        cp, conn = await _setup_checkpointer()

        # Verify checkpoints table exists
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            min_size=1, max_size=2, open=False,
        )
        await pool.open()
        async with pool.connection() as c:
            async with c.cursor() as cur:
                await cur.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='checkpoints')"
                )
                exists = (await cur.fetchone())[0]
        await pool.close()

        conn.close()
        r.add("AC-3.1 PostgresSaver Setup", exists, "checkpoints table exists" if exists else "table missing")
    except Exception as e:
        r.add("AC-3.1 PostgresSaver Setup", False, str(e)[:100])


# ============================================================
# AC-3.2: Single-turn persistence
# ============================================================
async def t32_single_turn(r: TR):
    """Send one message → verify checkpoint saved in PG."""
    cp, conn = await _setup_checkpointer()
    try:
        graph = _compile_graph(cp)
        thread_id = f"ac32_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        from agentscope.message import UserMsg
        result = await graph.ainvoke(
            {"messages": [UserMsg("user", "你好，我是项目经理")]},
            config=config,
        )

        msgs = result.get("messages", [])
        has_response = len(msgs) >= 2

        # Verify checkpoint in PG
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            min_size=1, max_size=2, open=False,
        )
        await pool.open()
        async with pool.connection() as c:
            async with c.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM checkpoints WHERE thread_id=%s",
                    (thread_id,),
                )
                count = (await cur.fetchone())[0]
        await pool.close()

        ok = has_response and count > 0
        r.add("AC-3.2 Single-Turn Persist", ok,
              f"msgs={len(msgs)}, checkpoints={count}" if ok else f"msgs={len(msgs)}, checkpoints={count}")
    except Exception as e:
        r.add("AC-3.2 Single-Turn Persist", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.3: Session resume
# ============================================================
async def t33_session_resume(r: TR):
    """Resume with same thread_id → state has history."""
    cp, conn = await _setup_checkpointer()
    try:
        graph = _compile_graph(cp)
        thread_id = f"ac33_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        from agentscope.message import UserMsg

        # First turn
        await graph.ainvoke(
            {"messages": [UserMsg("user", "我叫张三，负责3号基坑项目")]},
            config=config,
        )

        # Get current state to preserve messages for second turn
        state = await graph.aget_state(config)
        existing = state.values.get("messages", []) if state else []

        # Second turn — append user message to existing
        result2 = await graph.ainvoke(
            {"messages": existing + [UserMsg("user", "我叫什么名字？负责哪个项目？")]},
            config=config,
        )

        msgs = result2.get("messages", [])
        last_content = ""
        for m in reversed(msgs):
            c = _msg_text(m)
            if "张三" in c or "3号" in c or "基坑" in c:
                last_content = c[:200]
                break

        has_history = len(msgs) >= 4 and ("张三" in last_content or "3号" in last_content)
        r.add("AC-3.3 Session Resume", has_history,
              f"msgs={len(msgs)}, recall={'✓' if has_history else '✗'}")
    except Exception as e:
        r.add("AC-3.3 Session Resume", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.4: Supervisor routing
# ============================================================
async def t34_supervisor_routing(r: TR):
    """Safety query → safety_director, general query → dobby_core."""
    cp, conn = await _setup_checkpointer()
    try:
        graph = _compile_graph(cp)
        from agentscope.message import UserMsg

        # Test 1: safety query
        thread_s = f"ac34s_{uuid.uuid4().hex[:8]}"
        result_s = await graph.ainvoke(
            {"messages": [UserMsg("user", "基坑临边防护栏杆的高度要求是多少？")]},
            config={"configurable": {"thread_id": thread_s}},
        )
        role_s = result_s.get("current_role", "")

        # Test 2: general query
        thread_g = f"ac34g_{uuid.uuid4().hex[:8]}"
        result_g = await graph.ainvoke(
            {"messages": [UserMsg("user", "帮我查一下3号项目的整改进度")]},
            config={"configurable": {"thread_id": thread_g}},
        )
        role_g = result_g.get("current_role", "")

        safety_ok = role_s == "safety_director"
        general_ok = role_g == "dobby_core"

        r.add("AC-3.4 Supervisor Routing", safety_ok and general_ok,
              f"safety→{role_s}, general→{role_g}")
    except Exception as e:
        r.add("AC-3.4 Supervisor Routing", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.5: Safety node WeKnora retrieval
# ============================================================
async def t35_safety_weknora(r: TR):
    """safety_director calls WeKnora → answer contains standard reference."""
    cp, conn = await _setup_checkpointer()
    try:
        from utils.weknora_client import WeKnoraClient

        # Check WeKnora availability
        try:
            wc = WeKnoraClient(base_url=WEKNORA_BASE_URL, api_key=WEKNORA_API_KEY)
            kb_list = wc.list_knowledge_bases()
            kb_id = None
            for kb in kb_list:
                if kb.get("name") == WEKNORA_KB_NAME:
                    kb_id = kb["id"]
                    break
        except Exception as we:
            r.add("AC-3.5 Safety WeKnora", False, f"WeKnora unavailable: {str(we)[:80]}")
            return

        if not kb_id:
            r.add("AC-3.5 Safety WeKnora", False, f"KB '{WEKNORA_KB_NAME}' not found")
            return

        graph = _compile_graph(cp)
        from agentscope.message import UserMsg

        thread_id = f"ac35_{uuid.uuid4().hex[:8]}"
        result = await graph.ainvoke(
            {"messages": [UserMsg("user", "JGJ 80-2016对临边防护有什么具体要求？")]},
            config={"configurable": {"thread_id": thread_id}},
        )

        msgs = result.get("messages", [])
        last = ""
        for m in reversed(msgs):
            c = _msg_text(m)
            if len(c) > 10:
                last = c
                break

        has_ref = any(kw in last for kw in ["JGJ", "80", "临边", "防护", "栏杆", "1.2", "规范"])
        role = result.get("current_role", "")

        r.add("AC-3.5 Safety WeKnora", has_ref and role == "safety_director",
              f"role={role}, refs={'✓' if has_ref else '✗'} | {last[:120]}")
    except Exception as e:
        r.add("AC-3.5 Safety WeKnora", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.6: Core node Mem0 memory
# ============================================================
async def t36_core_memory(r: TR):
    """dobby_core calls Mem0 search/add → answer references history."""
    cp, conn = await _setup_checkpointer()
    try:
        from agentscope.message import UserMsg

        # Add a memory first
        def _add_memory():
            from mem0 import Memory as MM
            m = MM(_build_mem0_config())
            m.add(
                "3号基坑东侧栏杆整改完成，高度达到1.25m，超过JGJ 80-2016要求的1.2m",
                user_id=MEM0_USER_ID,
                agent_id=MEM0_AGENT_ID,
            )

        await asyncio.get_event_loop().run_in_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1),
            _add_memory,
        )
        await asyncio.sleep(1)  # wait for Mem0 to process

        # Now query
        graph = _compile_graph(cp)
        thread_id = f"ac36_{uuid.uuid4().hex[:8]}"
        result = await graph.ainvoke(
            {"messages": [UserMsg("user", "3号基坑东侧栏杆的整改情况怎么样？")]},
            config={"configurable": {"thread_id": thread_id}},
        )

        msgs = result.get("messages", [])
        last = ""
        for m in reversed(msgs):
            c = _msg_text(m)
            if len(c) > 10:
                last = c
                break

        has_mem = any(kw in last for kw in ["3号", "基坑", "栏杆", "整改", "1.25", "1.2"])
        role = result.get("current_role", "")

        r.add("AC-3.6 Core Memory", has_mem and role == "dobby_core",
              f"role={role}, mem={'✓' if has_mem else '✗'} | {last[:120]}")
    except Exception as e:
        r.add("AC-3.6 Core Memory", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.7: Compression trigger
# ============================================================
async def t37_compression(r: TR):
    """Inject excess tokens → compress_node triggered → summary + trim."""
    cp, conn = await _setup_checkpointer()
    try:
        from agentscope.message import UserMsg, AssistantMsg

        # Temporarily lower compression threshold
        import utils.config as cfg
        old_threshold = cfg.COMPRESSION_TRIGGER_TOKENS
        cfg.COMPRESSION_TRIGGER_TOKENS = 2000  # very low for test
        cfg.TOKEN_ESTIMATION_CHARS_PER_TOKEN = 3.0  # more conservative

        try:
            graph = _compile_graph(cp)
            thread_id = f"ac37_{uuid.uuid4().hex[:8]}"
            config = {"configurable": {"thread_id": thread_id}}

            # Inject a long conversation
            long_messages = [
                UserMsg("user", "你好，开始今天的项目检查"),
                AssistantMsg("assistant", "好的，开始检查。"),
            ]

            filler = (
                "关于工程安全管理的详细讨论记录。本次检查涉及多个施工区域的安全隐患排查。"
                "包括但不限于：高处作业、临边防护、基坑支护、临时用电、起重机械、脚手架工程等。"
                "各项检查均按照国家现行标准执行，检查人员对发现的问题进行了详细记录并下发了整改通知单。"
                "整改内容包括：补充临边防护栏杆、加固脚手架连墙件、更换破损安全网、规范配电箱接线等。"
                "整改完成后由监理单位组织验收，验收合格后方可继续施工。本次检查还涉及以下具体内容："
                "一、高处作业安全防护措施落实情况；二、临边洞口防护设施完好情况；三、基坑支护结构稳定性监测；"
                "四、临时用电系统接地保护检测；五、起重机械限位装置有效性验证；六、脚手架搭设质量专项检查。"
            )
            for i in range(60):
                long_messages.append(UserMsg("user", f"[第{i+1}项检查] {filler[:300]}"))
                long_messages.append(AssistantMsg("assistant", f"收到第{i+1}项检查记录。{filler[100:400]}"))

            result = await graph.ainvoke(
                {"messages": long_messages},
                config=config,
            )

            summary = result.get("summary", "")
            msgs_after = result.get("messages", [])
            compression_count = result.get("compression_count", 0)

            has_summary = len(summary) > 50
            was_trimmed = len(msgs_after) < len(long_messages)
            compress_triggered = compression_count > 0

            ok = has_summary and was_trimmed and compress_triggered
            r.add("AC-3.7 Compression", ok,
                  f"summary={len(summary)}c, msgs {len(long_messages)}→{len(msgs_after)}, compressions={compression_count}")
        finally:
            cfg.COMPRESSION_TRIGGER_TOKENS = old_threshold
    except Exception as e:
        r.add("AC-3.7 Compression", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.8: Tasks preserved after compression
# ============================================================
async def t38_tasks_preserved(r: TR):
    """Set tasks before compression → tasks survive compression."""
    cp, conn = await _setup_checkpointer()
    try:
        from agentscope.message import UserMsg, AssistantMsg

        import utils.config as cfg
        old_threshold = cfg.COMPRESSION_TRIGGER_TOKENS
        cfg.COMPRESSION_TRIGGER_TOKENS = 8000

        try:
            graph = _compile_graph(cp)
            thread_id = f"ac38_{uuid.uuid4().hex[:8]}"
            config = {"configurable": {"thread_id": thread_id}}

            # Set tasks
            initial = {
                "messages": [UserMsg("user", "建立任务清单")],
                "tasks": {
                    "T1": {"status": "in_progress", "desc": "整改3号基坑东侧栏杆"},
                    "T2": {"status": "pending", "desc": "检查5号楼脚手架"},
                },
            }
            await graph.ainvoke(initial, config=config)

            # Inject lots of messages to trigger compression
            filler = "工程安全检查记录。本项检查依据JGJ 80-2016和GB 50656-2011进行。检查内容涵盖了施工现场的各个方面包括高处作业、临边防护、临时用电等。"
            long_msgs = []
            for i in range(50):
                long_msgs.append(UserMsg("user", f"[检查{i}] {filler}"))
                long_msgs.append(AssistantMsg("assistant", f"记录第{i}项。{filler[50:]}"))
            result = await graph.ainvoke(
                {"messages": long_msgs},
                config=config,
            )

            tasks = result.get("tasks", {})
            has_t1 = "T1" in tasks
            has_t2 = "T2" in tasks
            t1_desc = str(tasks.get("T1", {}).get("desc", "")) if isinstance(tasks.get("T1"), dict) else str(tasks.get("T1", ""))
            t2_desc = str(tasks.get("T2", {}).get("desc", "")) if isinstance(tasks.get("T2"), dict) else str(tasks.get("T2", ""))
            t1_ok = has_t1 and ("基坑" in t1_desc or "栏杆" in t1_desc or "整改" in t1_desc)
            t2_ok = has_t2 and ("脚手架" in t2_desc or "5号" in t2_desc)

            r.add("AC-3.8 Tasks Preserved", t1_ok and t2_ok,
                  f"T1={'✓' if t1_ok else '✗'}, T2={'✓' if t2_ok else '✗'}")
        finally:
            cfg.COMPRESSION_TRIGGER_TOKENS = old_threshold
    except Exception as e:
        r.add("AC-3.8 Tasks Preserved", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# AC-3.9: Multi-project isolation
# ============================================================
async def t39_isolation(r: TR):
    """Different thread_ids → states not visible to each other."""
    cp, conn = await _setup_checkpointer()
    try:
        graph = _compile_graph(cp)
        from agentscope.message import UserMsg

        # Project A
        config_a = {"configurable": {"thread_id": f"ac39a_{uuid.uuid4().hex[:8]}"}}
        await graph.ainvoke(
            {"messages": [UserMsg("user", "项目A：3号基坑需要做地基加固")], "project_id": "project_A"},
            config=config_a,
        )

        # Project B
        config_b = {"configurable": {"thread_id": f"ac39b_{uuid.uuid4().hex[:8]}"}}
        await graph.ainvoke(
            {"messages": [UserMsg("user", "项目B：1号楼外墙粉刷")], "project_id": "project_B"},
            config=config_b,
        )

        # Resume Project A — append to existing messages
        state_a = await graph.aget_state(config_a)
        existing_a = state_a.values.get("messages", []) if state_a else []
        result_a = await graph.ainvoke(
            {"messages": existing_a + [UserMsg("user", "我刚才说的项目A要做什么？")]},
            config=config_a,
        )

        msgs_a = result_a.get("messages", [])
        last_a = ""
        for m in reversed(msgs_a):
            c = _msg_text(m)
            if c and len(c) > 10:
                last_a = c
                break

        has_a = any(kw in last_a for kw in ["3号", "基坑", "地基"])
        no_b = "外墙" not in last_a and "粉刷" not in last_a

        r.add("AC-3.9 Project Isolation", has_a and no_b,
              f"refs_A={'✓' if has_a else '✗'}, leaks_B={'✗' if no_b else '⚠️'} | {last_a[:120]}")
    except Exception as e:
        r.add("AC-3.9 Project Isolation", False, str(e)[:100])
    finally:
        conn.close()


# ============================================================
# Main
# ============================================================
async def main():
    print("=" * 60)
    print("Step 3: LangGraph PostgresSaver — Session State Source of Truth")
    print("=" * 60)

    # Validate config
    issues = config_validate()
    if issues:
        for i in issues:
            print(f"  ⚠️  {i}")
        if any("API_KEY" in i or "api key" in i.lower() for i in issues):
            print("\n  Set DEEPSEEK_API_KEY and re-run.")
            return

    print(f"\n{config_summary()}\n")

    r = TR()

    # Run ACs
    print("── AC-3.1 PostgresSaver Setup ──")
    await t31_saver_setup(r)

    print("\n── AC-3.2 Single-Turn Persistence ──")
    await t32_single_turn(r)

    print("\n── AC-3.3 Session Resume ──")
    await t33_session_resume(r)

    print("\n── AC-3.4 Supervisor Routing ──")
    await t34_supervisor_routing(r)

    print("\n── AC-3.5 Safety WeKnora Retrieval ──")
    await t35_safety_weknora(r)

    print("\n── AC-3.6 Core Memory (Mem0) ──")
    await t36_core_memory(r)

    print("\n── AC-3.7 Compression Trigger ──")
    await t37_compression(r)

    print("\n── AC-3.8 Tasks Preserved ──")
    await t38_tasks_preserved(r)

    print("\n── AC-3.9 Project Isolation ──")
    await t39_isolation(r)

    r.summary()


if __name__ == "__main__":
    lf = (
        (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
        if sys.platform == "win32"
        else None
    )
    asyncio.run(main(), loop_factory=lf)
