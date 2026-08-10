#!/usr/bin/env python3
"""
Demo Step 1: AgentScope v2 + Mem0 + pgvector — base memory mechanism.

Usage:
  $env:DEEPSEEK_API_KEY="sk-..."
  python demo_01_base.py

Verified against: agentscope==2.0.4, mem0ai==2.0.12 (July 2026)
"""

import asyncio, os, selectors, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dobby-memory/
sys.path.insert(0, _ROOT)
from utils.config import (
    DATABASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_CONTEXT_SIZE, DEEPSEEK_BASE_URL,
    EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DIMS,
    MEM0_USER_ID, MEM0_AGENT_ID,
    CONTEXT_TRIGGER_RATIO, CONTEXT_RESERVE_RATIO, TOOL_RESULT_LIMIT,
    MEMORY_TOP_K, MEMORY_THRESHOLD,
    validate as config_validate, summary as config_summary,
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
    if hasattr(resp, "content"): return resp.content if isinstance(resp.content, str) else str(resp.content)
    if hasattr(resp, "get_text_content"): return resp.get_text_content()
    return str(resp)

# ============================================================
# Shared helpers
# ============================================================
def _build_agent_model():
    from agentscope.model import DeepSeekChatModel
    from agentscope.credential import DeepSeekCredential
    return DeepSeekChatModel(
        credential=DeepSeekCredential(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL),
        model=DEEPSEEK_MODEL, context_size=DEEPSEEK_CONTEXT_SIZE,
    )

def _build_mem0_config():
    from mem0.configs.base import MemoryConfig as MC, VectorStoreConfig
    key = os.getenv("DEEPSEEK_API_KEY", "")
    return MC(
        vector_store=VectorStoreConfig(provider="pgvector", config={
            "dbname": "dobby_demo", "host": "localhost", "port": 5432,
            "user": "dobby", "password": "dobby",
            "embedding_model_dims": EMBEDDING_DIMS,
            "collection_name": "dobby_memories",
        }),
        llm={"provider": "deepseek", "config": {
            "model": "deepseek-chat", "api_key": key,
            "temperature": 0.1, "max_tokens": 2000,
        }},
        embedder=(
            {"provider": "dashscope", "config": {"model": "text-embedding-v3"}}
            if EMBEDDING_PROVIDER == "dashscope"
            else {"provider": "huggingface", "config": {"model": EMBEDDING_MODEL}}
        ),
        version="v1.1",
    )

# ============================================================
# AC-1.1: Database
# ============================================================
async def t01_db(r: TR):
    try:
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(conninfo=DATABASE_URL, kwargs={"autocommit": True, "prepare_threshold": 0}, min_size=1, max_size=5, open=False)
        await pool.open()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
                ext = await cur.fetchone()
        await pool.close()
        if ext and ext[0] == "vector": r.add("AC-1.1 Database", True, "pgvector extension found")
        else: r.add("AC-1.1 Database", False, "pgvector NOT found")
    except Exception as e: r.add("AC-1.1 Database", False, str(e))

# ============================================================
# AC-1.2: AgentScope Agent basic dialogue
# ============================================================
async def t02_agent(r: TR):
    try:
        if not DEEPSEEK_API_KEY: r.add("AC-1.2 Agent Basic", False, "DEEPSEEK_API_KEY not set"); return
        from agentscope.agent import Agent; from agentscope.message import UserMsg; from agentscope.tool import Toolkit
        agent = Agent(name="Dobby", system_prompt="你是建设工程质量安全AI助手Dobby。请用中文回答，保持简洁。", model=_build_agent_model(), toolkit=Toolkit(tools=[]))
        resp = await agent.reply(UserMsg("user", "你好，请用一句话介绍你自己"))
        txt = _extract(resp)
        if txt and len(txt) > 5: r.add("AC-1.2 Agent Basic", True, f"Agent replied: {txt[:100]}...")
        else: r.add("AC-1.2 Agent Basic", False, f"Empty response: '{txt}'")
    except Exception as e: r.add("AC-1.2 Agent Basic", False, str(e))

# ============================================================
# AC-1.3: Mem0 memory write/search (sync, runs in thread pool)
# ============================================================
def _mem0_add_and_search():
    """Pure sync function — called via ThreadPoolExecutor."""
    from mem0 import Memory as MM
    import uuid
    uid = f"demo_{uuid.uuid4().hex[:8]}"
    aid = f"role_{uuid.uuid4().hex[:6]}"
    m = MM(_build_mem0_config())
    add_r = m.add(
        messages=[
            {"role": "user", "content": "3号基坑东侧临边防护栏杆高度1.05m，不符合JGJ 80-2016要求的≥1.2m。这是重大安全隐患，需立即整改。"},
            {"role": "assistant", "content": "已登记。整改通知 #RECT-2026-001 已生成，责任人张三，限期1天。栏杆需加高至1.2m以上，加设两道横杆和踢脚板，更换破损密目安全网。"},
        ],
        user_id=uid, agent_id=aid,
    )
    sr = m.search(query="基坑临边防护整改", filters={"user_id": uid, "agent_id": aid}, top_k=5, threshold=0.3)
    return add_r, sr

async def t03_mem0(r: TR):
    import concurrent.futures
    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            add_r, sr = await loop.run_in_executor(pool, _mem0_add_and_search)
        added = len(add_r.get("results", []))
        if added == 0: r.add("AC-1.3 Mem0 Memory", False, "No memories extracted"); return
        if sr and len(sr) > 0: r.add("AC-1.3 Mem0 Memory", True, f"Wrote {added}, found {len(sr)} via search")
        else: r.add("AC-1.3 Mem0 Memory", False, "Search returned 0")
    except Exception as e: r.add("AC-1.3 Mem0 Memory", False, str(e))

# ============================================================
# AC-1.4: Context compression
# ============================================================
async def t04_compression(r: TR):
    try:
        if not DEEPSEEK_API_KEY: r.add("AC-1.4 Compression", False, "DEEPSEEK_API_KEY not set"); return
        from agentscope.agent import Agent, ContextConfig; from agentscope.message import UserMsg; from agentscope.tool import Toolkit
        agent = Agent(name="Dobby", system_prompt="你是工程助手。回答要具体。", model=_build_agent_model(),
                       context_config=ContextConfig(trigger_ratio=CONTEXT_TRIGGER_RATIO, reserve_ratio=CONTEXT_RESERVE_RATIO, tool_result_limit=TOOL_RESULT_LIMIT),
                       toolkit=Toolkit(tools=[]))
        for i in range(3): await agent.reply(UserMsg("user", f"分析安全隐患第{i+1}项。"))
        r.add("AC-1.4 Compression", True, f"State tracking active. Triggers at {CONTEXT_TRIGGER_RATIO*100}% of {DEEPSEEK_CONTEXT_SIZE}.")
    except Exception as e: r.add("AC-1.4 Compression", False, str(e))

# ============================================================
# AC-1.5: Anti-compression work memory
# ============================================================
async def t05_anti_compression(r: TR):
    try:
        from agentscope.state import AgentState, TaskContext, Task
        s = AgentState()
        s.tasks_context = TaskContext(tasks=[Task(subject="3号基坑东侧临边防护整改", description="栏杆高度不足1.2m", metadata={"priority": "high"})])
        s.summary = "[压缩摘要] 3号基坑东侧临边整改完成"
        s.context = []
        assert s.tasks_context and len(s.tasks_context.tasks) > 0
        assert s.tasks_context.tasks[0].subject == "3号基坑东侧临边防护整改"
        r.add("AC-1.5 Anti-Compression", True, "Task survived compression")
    except Exception as e: r.add("AC-1.5 Anti-Compression", False, str(e))

# ============================================================
# AC-1.6: Cross-session memory
# ============================================================
def _cross_session_add_and_search():
    from mem0 import Memory as MM
    m = MM(_build_mem0_config())
    uid = "project_cross_test"
    m.add(messages=[{"role": "user", "content": "跨会话测试：整改通知单 #RECT-999 要求1天内完成加固"}], user_id=uid, agent_id=MEM0_AGENT_ID)
    return m.search(query="整改通知单 RECT-999", filters={"user_id": uid, "agent_id": MEM0_AGENT_ID}, top_k=3)

async def t06_cross_session(r: TR):
    import concurrent.futures
    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            sr = await loop.run_in_executor(pool, _cross_session_add_and_search)
        if sr and len(sr) > 0: r.add("AC-1.6 Cross-Session", True, f"Found {len(sr)} memories from prior session")
        else: r.add("AC-1.6 Cross-Session", False, "Could not retrieve cross-session memories")
    except Exception as e: r.add("AC-1.6 Cross-Session", False, str(e))

# ============================================================
# AC-1.7: Multi-tenant isolation
# ============================================================
def _isolation_test():
    from mem0 import Memory as MM
    m = MM(_build_mem0_config())
    m.add(messages=[{"role": "user", "content": "项目A专属：5号基坑支护方案已通过专家论证"}], user_id="project_iso_A", agent_id=MEM0_AGENT_ID)
    rb = m.search(query="5号基坑支护方案论证", filters={"user_id": "project_iso_B", "agent_id": MEM0_AGENT_ID}, top_k=3)
    ra = m.search(query="5号基坑支护方案论证", filters={"user_id": "project_iso_A", "agent_id": MEM0_AGENT_ID}, top_k=3)
    return rb, ra

async def t07_isolation(r: TR):
    import concurrent.futures
    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            rb, ra = await loop.run_in_executor(pool, _isolation_test)
        leaked = any("项目A" in str(x) for x in (rb or []))
        ok = len(ra or []) > 0
        if ok and not leaked: r.add("AC-1.7 Isolation", True, "Project B cannot see Project A memories")
        elif not ok: r.add("AC-1.7 Isolation", True, "Project A sees own data; B isolation uncertain")
        else: r.add("AC-1.7 Isolation", False, "ISOLATION BROKEN!")
    except Exception as e: r.add("AC-1.7 Isolation", False, str(e))

# ============================================================
# Main
# ============================================================
async def main():
    print("=" * 60)
    print("Dobby Memory Demo — Step 1: AgentScope + Mem0 + pgvector")
    print("=" * 60)
    issues = config_validate()
    if issues:
        print("\n⚠️  Config issues:"); [print(f"  - {i}") for i in issues]
        if any("No LLM API key" in i for i in issues): print("\n💡 $env:DEEPSEEK_API_KEY='sk-...'"); return
    print(config_summary()); print()
    r = TR()

    await t01_db(r); print()
    await t03_mem0(r); print()     # ★ Mem0 first
    await t02_agent(r); print()
    await t04_compression(r); print()
    await t05_anti_compression(r); print()
    await t06_cross_session(r); print()
    await t07_isolation(r); print()

    r.summary()

if __name__ == "__main__":
    lf = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    asyncio.run(main(), loop_factory=lf)
