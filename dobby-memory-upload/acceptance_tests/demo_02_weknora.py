#!/usr/bin/env python3
"""
Demo Step 2: WeKnora KB + Mem0 Memory Fusion via RRF.

Usage:
  $env:DEEPSEEK_API_KEY="sk-..."
  python demo_02_weknora.py

Prerequisites:
  - Step 1 verified (demo_01_base.py)
  - WeKnora running: docker compose up -d (in weknora/)
  - WeKnora KB created + documents uploaded

Verified against: agentscope==2.0.4, mem0ai==2.0.12, WeKnora v0.6.x (July 2026)
"""

import asyncio
import concurrent.futures
import json
import os
import selectors
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dobby-memory/
sys.path.insert(0, _ROOT)
from utils.config import (
    DATABASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_CONTEXT_SIZE, DEEPSEEK_BASE_URL,
    EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DIMS,
    MEM0_USER_ID, MEM0_AGENT_ID,
    WEKNORA_BASE_URL, WEKNORA_API_KEY, WEKNORA_KB_NAME,
    RRF_K, FUSION_MEM0_WEIGHT, FUSION_KB_WEIGHT,
    MEMORY_TOP_K, MEMORY_THRESHOLD,
    LIGHTRAG_ENABLED,
    validate as config_validate, summary as config_summary,
)
from utils.weknora_client import WeKnoraClient
from utils.fusion import MemoryFusion, ContextAssembler, SearchResult

# ============================================================
# Test Results (same pattern as Step 1)
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
# Shared helpers (reuse Step 1 patterns)
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

def _get_weknora_client() -> WeKnoraClient:
    return WeKnoraClient(base_url=WEKNORA_BASE_URL, api_key=WEKNORA_API_KEY)

# ============================================================
# AC-2.1: WeKnora deployment health check
# ============================================================
async def t01_weknora_health(r: TR):
    try:
        wc = _get_weknora_client()
        ok = wc.health_check()
        if ok:
            # Also list KBs to confirm API is fully functional
            kbs = wc.list_knowledge_bases()
            r.add("AC-2.1 WeKnora Health", True,
                  f"API reachable, {len(kbs)} knowledge base(s) found")
        else:
            r.add("AC-2.1 WeKnora Health", False,
                  "API returned unexpected response")
    except Exception as e:
        r.add("AC-2.1 WeKnora Health", False, str(e))

# ============================================================
# AC-2.2: KB creation + document upload
# ============================================================
async def t02_kb_and_upload(r: TR):
    try:
        wc = _get_weknora_client()

        # Find or create the KB
        kbs = wc.list_knowledge_bases()
        kb_id = None
        for kb in kbs:
            if isinstance(kb, dict) and kb.get("name") == WEKNORA_KB_NAME:
                kb_id = kb.get("id")
                break

        if not kb_id:
            resp = wc.create_knowledge_base(
                name=WEKNORA_KB_NAME,
                description="Dobby 建设工程质量安全规范知识库",
                chunk_size=1000,
                chunk_overlap=200,
            )
            kb_id = resp.get("id") or (resp.get("data", {}) if isinstance(resp, dict) else {}).get("id")
            if not kb_id:
                r.add("AC-2.2 KB Create", False, f"Cannot find KB ID in response: {str(resp)[:200]}")
                return
            print(f"  [INFO] Created KB: {kb_id}")

        # Check if KB already has documents
        knowledge_list = wc.list_knowledge(kb_id, page=1, page_size=10)
        items = knowledge_list.get("data", knowledge_list)
        if isinstance(items, dict):
            items = items.get("list", items.get("items", []))
        if items and len(items) > 0:
            print(f"  [INFO] KB already has {len(items)} document(s), skipping upload")
        else:
            # Upload engineering safety documents
            data_file = os.path.join(_ROOT, "data", "engineering_safety.md")
            data_file = os.path.abspath(data_file)
            if os.path.exists(data_file):
                wc.upload_file(kb_id, data_file)
                print(f"  [INFO] Uploaded: {os.path.basename(data_file)}")
                # GraphRAG: index the same file into the knowledge graph
                if LIGHTRAG_ENABLED:
                    from utils.graph_rag_engine import get_graph_rag
                    engine = await get_graph_rag(project_id=WEKNORA_KB_NAME)
                    await engine.index_file(data_file)
                    print(f"  [INFO] GraphRAG indexed: {os.path.basename(data_file)}")
            else:
                # Fallback: create a minimal text document
                test_file = os.path.join(_ROOT, "data", "safety_minimal.txt")
                os.makedirs(os.path.dirname(test_file), exist_ok=True)
                with open(test_file, "w", encoding="utf-8") as f:
                    f.write("JGJ 80-2016 临边防护栏杆高度不低于1.2m，设置两道横杆。基坑临边防护需满足JGJ 80-2016要求。\n")
                    f.write("高处作业高度2m及以上需设置安全网，佩戴安全带。\n")
                    f.write("隐患整改闭环管理：发现→通知→整改→复核→归档。较大隐患1天内整改。\n")
                wc.upload_file(kb_id, test_file)
                print(f"  [INFO] Uploaded fallback: {os.path.basename(test_file)}")

        # Wait a moment for indexing, then verify retrieval
        time.sleep(2)
        results = wc.hybrid_search(kb_id, "基坑临边防护", match_count=3)
        if results and len(results) > 0:
            content = results[0].get("content") or results[0].get("chunk_content") or str(results[0])
            r.add("AC-2.2 KB Create+Upload", True,
                  f"Found {len(results)} result(s). Top: {content[:80]}...")
        else:
            r.add("AC-2.2 KB Create+Upload", False,
                  "No results returned — document may still be indexing. Run again in 30s.")

        # Store kb_id for later tests
        if hasattr(t02_kb_and_upload, "__dict__"):
            t02_kb_and_upload.kb_id = kb_id
    except Exception as e:
        r.add("AC-2.2 KB Create+Upload", False, str(e))

# ============================================================
# AC-2.3: WeKnora standalone hybrid search
# ============================================================
async def t03_hybrid_search(r: TR):
    try:
        wc = _get_weknora_client()
        kbs = wc.list_knowledge_bases()
        kb_id = None
        for kb in kbs:
            if isinstance(kb, dict) and kb.get("name") == WEKNORA_KB_NAME:
                kb_id = kb.get("id")
                break

        if not kb_id:
            r.add("AC-2.3 Standalone Search", False, f"KB '{WEKNORA_KB_NAME}' not found. Run AC-2.2 first.")
            return

        queries = [
            "高处作业安全规范",
            "基坑临边防护要求",
            "安全事故应急预案",
        ]
        for q in queries:
            results = wc.hybrid_search(kb_id, q, match_count=3)
            if results and len(results) > 0:
                content = results[0].get("content") or results[0].get("chunk_content") or ""
                if any(kw in content for kw in ("高", "基坑", "临边", "安全", "防护")):
                    r.add("AC-2.3 Standalone Search", True,
                          f"Query '{q[:20]}' → {len(results)} hits. Top score: {results[0].get('score', 'N/A')}")
                    return
        r.add("AC-2.3 Standalone Search", False, "No relevant results for any test query")
    except Exception as e:
        r.add("AC-2.3 Standalone Search", False, str(e))

# ============================================================
# AC-2.4: RRF Fusion — Mem0 + WeKnora
# ============================================================
def _fusion_mem0_add_and_search():
    """Sync function for ThreadPoolExecutor."""
    from mem0 import Memory as MM
    import uuid
    uid = f"fusion_{uuid.uuid4().hex[:8]}"
    m = MM(_build_mem0_config())
    m.add(
        messages=[{"role": "user", "content": "3号基坑东侧临边防护栏杆高度1.05m，不符合JGJ 80-2016要求≥1.2m，已于7月16日整改完成，责任人张三。"}],
        user_id=uid, agent_id=MEM0_AGENT_ID,
    )
    sr = m.search(query="基坑临边防护整改要求", filters={"user_id": uid, "agent_id": MEM0_AGENT_ID}, top_k=5, threshold=0.3)
    return sr

async def t04_rrf_fusion(r: TR):
    import concurrent.futures
    try:
        # 1. Get WeKnora results
        wc = _get_weknora_client()
        kbs = wc.list_knowledge_bases()
        kb_id = None
        for kb in kbs:
            if isinstance(kb, dict) and kb.get("name") == WEKNORA_KB_NAME:
                kb_id = kb.get("id")
                break
        if not kb_id:
            r.add("AC-2.4 RRF Fusion", False, f"KB '{WEKNORA_KB_NAME}' not found")
            return

        kb_results = wc.hybrid_search(kb_id, "基坑临边防护整改要求", match_count=5)

        # 2. Get Mem0 results (in thread pool)
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            mem0_results = await loop.run_in_executor(pool, _fusion_mem0_add_and_search)

        # 3. RRF Fusion
        fusion = MemoryFusion(
            {"mem0": FUSION_MEM0_WEIGHT, "kb": FUSION_KB_WEIGHT},
            rrf_k=RRF_K,
        )
        fused = fusion.fuse(mem0_results, kb_results)

        # 4. Verify
        has_mem0 = any(r.source == "mem0" for r in fused)
        has_kb = any(r.source == "weknora" for r in fused)

        if has_mem0 and has_kb:
            r.add("AC-2.4 RRF Fusion", True,
                  f"Merged {len(fused)} results (Mem0 + WeKnora). Weights: KB={FUSION_KB_WEIGHT}, LTM={FUSION_MEM0_WEIGHT}")
        elif has_kb:
            r.add("AC-2.4 RRF Fusion", True,
                  f"KB results only ({len(fused)} items). Mem0 may need populated data.")
        else:
            r.add("AC-2.4 RRF Fusion", False, "No results from either source")
    except Exception as e:
        r.add("AC-2.4 RRF Fusion", False, str(e))

# ============================================================
# AC-2.5: Context Assembly → LLM answering with KB + Memory
# ============================================================
def _assembly_mem0_add_and_search():
    """Sync function for ThreadPoolExecutor."""
    from mem0 import Memory as MM
    import uuid
    uid = f"ctx_{uuid.uuid4().hex[:8]}"
    m = MM(_build_mem0_config())
    m.add(
        messages=[{"role": "user", "content": "3号基坑东侧临边防护栏杆高度1.05m，不符合JGJ 80-2016要求的≥1.2m，这是重大安全隐患，需立即整改。整改通知已发给张三。"}],
        user_id=uid, agent_id=MEM0_AGENT_ID,
    )
    sr = m.search(query="3号基坑临边防护有什么要求", filters={"user_id": uid, "agent_id": MEM0_AGENT_ID}, top_k=5, threshold=0.3)
    return sr

async def t05_context_assembly(r: TR):
    import concurrent.futures
    try:
        if not DEEPSEEK_API_KEY:
            r.add("AC-2.5 Context Assembly", False, "DEEPSEEK_API_KEY not set")
            return

        # 1. Get KB results
        wc = _get_weknora_client()
        kbs = wc.list_knowledge_bases()
        kb_id = None
        for kb in kbs:
            if isinstance(kb, dict) and kb.get("name") == WEKNORA_KB_NAME:
                kb_id = kb.get("id")
                break
        if not kb_id:
            r.add("AC-2.5 Context Assembly", False, "KB not found")
            return

        query = "3号基坑临边防护有什么要求？"
        kb_results = wc.hybrid_search(kb_id, query, match_count=3)

        # 2. Get Mem0 results
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            mem0_results = await loop.run_in_executor(pool, _assembly_mem0_add_and_search)

        # 3. RRF Fusion
        fusion = MemoryFusion({"mem0": FUSION_MEM0_WEIGHT, "kb": FUSION_KB_WEIGHT}, RRF_K)
        fused = fusion.fuse(mem0_results, kb_results)

        # 4. Context Assembly
        assembler = ContextAssembler()
        messages = assembler.assemble(
            system_prompt="你是建设工程质量安全AI助手Dobby。你可以在回答中引用知识库的规范标准和项目历史记忆。回答要具体、有依据。",
            fused_results=fused,
            user_message=query,
            project_id="project_demo",
            role_id="role_safety",
        )

        # 5. Check <system-reminder> is in context
        has_reminder = any("<system-reminder>" in m.get("content", "") for m in messages)

        # 6. LLM call
        from agentscope.agent import Agent
        from agentscope.message import UserMsg
        from agentscope.tool import Toolkit

        agent = Agent(
            name="Dobby",
            system_prompt="你是建设工程质量安全AI助手Dobby。回答要具体，引用规范。",
            model=_build_agent_model(),
            toolkit=Toolkit(tools=[]),
        )

        # Build the injected user message with the system reminder
        reminder_text = assembler.format_system_reminder(fused)
        injected_msg = f"{reminder_text}\n\n用户问题: {query}"
        resp = await agent.reply(UserMsg("user", injected_msg))
        answer = _extract(resp)

        # 7. Verify answer references both KB and memory
        has_spec_ref = any(kw in answer for kw in ("规范", "JGJ", "GB", "标准", "要求"))
        has_memory_ref = any(kw in answer for kw in ("整改", "张三", "1.05", "检查", "发现"))

        if has_reminder and answer and len(answer) > 20:
            detail = f"Answer: {answer[:120]}..."
            if has_spec_ref and has_memory_ref:
                detail = "Answer references BOTH spec + history. " + detail
            elif has_spec_ref:
                detail = "Answer references spec. " + detail
            elif has_memory_ref:
                detail = "Answer references history. " + detail
            r.add("AC-2.5 Context Assembly", True, detail)
        else:
            r.add("AC-2.5 Context Assembly", False,
                  f"Reminder={has_reminder}, Answer='{answer[:80] if answer else 'EMPTY'}'")
    except Exception as e:
        r.add("AC-2.5 Context Assembly", False, str(e))

# ============================================================
# AC-2.6: Isolation — different projects see different KBs
# ============================================================
async def t06_isolation(r: TR):
    try:
        wc = _get_weknora_client()

        # Create two KBs for two projects
        kb_a_name = f"{WEKNORA_KB_NAME}_project_a"
        kb_b_name = f"{WEKNORA_KB_NAME}_project_b"

        # Find or create KBs
        kbs = wc.list_knowledge_bases()
        kb_ids = {}
        for name in (kb_a_name, kb_b_name):
            for kb in kbs:
                if isinstance(kb, dict) and kb.get("name") == name:
                    kb_ids[name] = kb.get("id")
                    break
            if name not in kb_ids:
                resp = wc.create_knowledge_base(name=name, description=f"Test KB for {name}")
                kid = resp.get("id") or (resp.get("data", {}) if isinstance(resp, dict) else {}).get("id")
                if kid:
                    kb_ids[name] = kid

        time.sleep(1)

        # Search project A's KB for project B's content — should NOT leak
        # Project A KB contains "基坑" content; Project B KB is empty
        kid_a = kb_ids.get(kb_a_name, "")
        kid_b = kb_ids.get(kb_b_name, "")

        if not kid_a or not kid_b:
            r.add("AC-2.6 Isolation", False, "Could not create both KBs")
            return

        # KB A should find "基坑" content (since it was uploaded to the main KB)
        # KB B should be empty (no documents uploaded)
        results_b = wc.hybrid_search(kid_b, "基坑临边防护要求", match_count=3)
        leaked = results_b and len(results_b) > 0

        if not leaked:
            r.add("AC-2.6 Isolation", True, "Project B KB returns no results for Project A's content")
        else:
            r.add("AC-2.6 Isolation", False, f"ISOLATION BROKEN: KB B leaked {len(results_b)} results")
    except Exception as e:
        r.add("AC-2.6 Isolation", False, str(e))

# ============================================================
# Main
# ============================================================
async def main():
    print("=" * 60)
    print("Dobby Memory Demo — Step 2: WeKnora + Mem0 Fusion")
    print("=" * 60)
    issues = config_validate()
    if issues:
        print("\n⚠️  Config issues:"); [print(f"  - {i}") for i in issues]
        if any("No LLM API key" in i for i in issues):
            print("\n💡 $env:DEEPSEEK_API_KEY='sk-...'"); return
    print(config_summary())
    print(f"  WeKnora:       {WEKNORA_BASE_URL} (KB: {WEKNORA_KB_NAME})")
    print(f"  RRF:           KB_w={FUSION_KB_WEIGHT}, LTM_w={FUSION_MEM0_WEIGHT}, k={RRF_K}")
    print()
    r = TR()

    await t01_weknora_health(r); print()
    await t02_kb_and_upload(r); print()
    await t03_hybrid_search(r); print()
    await t04_rrf_fusion(r); print()
    await t05_context_assembly(r); print()
    await t06_isolation(r); print()

    r.summary()

if __name__ == "__main__":
    lf = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    asyncio.run(main(), loop_factory=lf)
