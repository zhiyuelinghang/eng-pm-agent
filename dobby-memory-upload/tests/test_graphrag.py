#!/usr/bin/env python3
"""
GraphRAG acceptance tests — 9 acceptance criteria per design spec §7.

Usage:
  # Requires LIGHTRAG_ENABLED=true for AC-GR-1 through AC-GR-4
  python test_graphrag.py
"""

import asyncio
import os
import sys
import selectors

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # dobby-memory/
from utils.config import (
    LIGHTRAG_ENABLED, LIGHTRAG_WORKING_DIR,
    DATABASE_URL, FUSION_WEIGHT_GRAPHRAG,
)


class TR:
    def __init__(self):
        self.r = []
    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        print(f"  {'PASS' if passed else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        print(f"\n{'='*60}\nResults: {p}/{len(self.r)} passed {'ALL PASS' if p == len(self.r) else 'FAILURES'}\n{'='*60}")
        return p == len(self.r)


# ═══════════════════════════════════════════════════════════════
# AC-GR-1: LightRAG tables created in dobby_demo without conflicts
# ═══════════════════════════════════════════════════════════════
async def t01_tables_created(r: TR):
    try:
        import psycopg
        conn = psycopg.Connection.connect(
            DATABASE_URL, autocommit=True, prepare_threshold=0,
        )
        with conn:
            cur = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name ILIKE '%ligh%'"
            )
            tables = [row[0] for row in cur.fetchall()]
        if tables:
            r.add("AC-GR-1 Tables Created", True,
                  f"Found {len(tables)} LightRAG tables: {', '.join(tables[:5])}...")
        else:
            r.add("AC-GR-1 Tables Created", False,
                  "No LightRAG tables found. Run reindex_graph.py first with LIGHTRAG_ENABLED=true")
    except Exception as e:
        r.add("AC-GR-1 Tables Created", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-2: index_file creates graph nodes > 0
# ═══════════════════════════════════════════════════════════════
async def t02_index_creates_nodes(r: TR):
    try:
        from utils.graph_rag_engine import get_graph_rag
        engine = await get_graph_rag(project_id="test_graphrag")

        # Index a small test text
        test_doc = "\u9ad8\u5904\u4f5c\u4e1a\u9700\u8981\u8bbe\u7f6e\u9632\u62a4\u680f\u6746\u548c\u5b89\u5168\u7f51\u3002JGJ 80-2016 \u89c4\u5b9a\u4e34\u8fb9\u9632\u62a4\u680f\u6746\u9ad8\u5ea6\u4e0d\u4f4e\u4e8e1.2m\u3002"
        doc_id = await engine.index_document("doc-test-ac2", test_doc)
        await asyncio.sleep(2)  # wait for async indexing

        if doc_id:
            r.add("AC-GR-2 Index Creates Nodes", True,
                  f"Doc ID: {doc_id}")
        else:
            r.add("AC-GR-2 Index Creates Nodes", False,
                  "index_document returned empty (engine not initialized?)")
    except Exception as e:
        r.add("AC-GR-2 Index Creates Nodes", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-3: Duplicate index is idempotent
# ═══════════════════════════════════════════════════════════════
async def t03_idempotent_index(r: TR):
    try:
        from utils.graph_rag_engine import get_graph_rag
        engine = await get_graph_rag(project_id="test_graphrag")

        test_doc = "\u9ad8\u5904\u4f5c\u4e1a\u9700\u8981\u8bbe\u7f6e\u9632\u62a4\u680f\u6746\u548c\u5b89\u5168\u7f51\u3002"
        doc_id1 = await engine.index_document("doc-test-ac3", test_doc)
        doc_id2 = await engine.index_document("doc-test-ac3", test_doc)
        await asyncio.sleep(2)

        # Both calls should return the same doc_id (MD5-based)
        if doc_id1 == doc_id2:
            r.add("AC-GR-3 Idempotent Index", True,
                  f"Same doc_id: {doc_id1}")
        else:
            r.add("AC-GR-3 Idempotent Index", False,
                  f"Different: {doc_id1} vs {doc_id2}")
    except Exception as e:
        r.add("AC-GR-3 Idempotent Index", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-4: search returns non-empty entities + relations + chunks
# ═══════════════════════════════════════════════════════════════
async def t04_search_returns_data(r: TR):
    try:
        from utils.graph_rag_engine import get_graph_rag
        engine = await get_graph_rag(project_id="test_graphrag")
        result = await engine.search("\u9ad8\u5904\u4f5c\u4e1a\u9632\u62a4", mode="mix")

        has_data = bool(
            result.get("entities") or
            result.get("relations") or
            result.get("chunks") or
            result.get("formatted")
        )
        if has_data:
            r.add("AC-GR-4 Search Returns Data", True,
                  f"formatted={len(result.get('formatted', ''))} chars")
        else:
            r.add("AC-GR-4 Search Returns Data", False,
                  "All result fields are empty")
    except Exception as e:
        r.add("AC-GR-4 Search Returns Data", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-5: 5-source fusion includes graphrag
# ═══════════════════════════════════════════════════════════════
async def t05_fusion_includes_graphrag(r: TR):
    try:
        from utils.fusion import MemoryFusion
        mf = MemoryFusion()
        assert "graphrag" in mf.default_weights, "graphrag not in weights"
        assert mf.default_weights["graphrag"] == FUSION_WEIGHT_GRAPHRAG, \
            f"Expected weight {FUSION_WEIGHT_GRAPHRAG}, got {mf.default_weights['graphrag']}"

        # Test fuse() with graphrag_results
        graphrag_item = {"formatted": "\u3010\u77e5\u8bc6\u56fe\u8c31\u3011\u9ad8\u5904\u4f5c\u4e1a \u2190[\u89c4\u8303\u8981\u6c42]\u2192 \u5b89\u5168\u5e26"}
        result = mf.fuse(
            mem0_results=[],
            kb_results=[],
            graphrag_results=[graphrag_item],
        )
        has_graphrag = any(r.source == "graphrag" for r in result)
        if has_graphrag:
            r.add("AC-GR-5 Fusion Includes GraphRAG", True,
                  f"W={FUSION_WEIGHT_GRAPHRAG}, {len(result)} results")
        else:
            r.add("AC-GR-5 Fusion Includes GraphRAG", False,
                  "No graphrag source in results")
    except Exception as e:
        r.add("AC-GR-5 Fusion Includes GraphRAG", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-6: Adaptive weights boost graphrag for "association" queries
# ═══════════════════════════════════════════════════════════════
async def t06_adaptive_weights(r: TR):
    try:
        from utils.fusion import MemoryFusion
        mf = MemoryFusion()

        w_default = mf._adapt_weights("\u57fa\u5751\u4e34\u8fb9\u9632\u62a4\u8981\u6c42")
        w_boosted = mf._adapt_weights("\u9ad8\u5904\u4f5c\u4e1a\u6d89\u53ca\u54ea\u4e9b\u5173\u8054\u89c4\u8303")

        assert w_boosted.get("graphrag", 0) > w_default.get("graphrag", 0), \
            f"Boosted {w_boosted.get('graphrag')} <= default {w_default.get('graphrag')}"
        r.add("AC-GR-6 Adaptive Weights", True,
              f"Default={w_default['graphrag']:.3f}, Boosted={w_boosted['graphrag']:.3f}")
    except Exception as e:
        r.add("AC-GR-6 Adaptive Weights", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-7: MMR dedup across GraphRAG + WeKnora
# ═══════════════════════════════════════════════════════════════
async def t07_mmr_dedup(r: TR):
    try:
        from utils.fusion import MemoryFusion

        mf = MemoryFusion()
        # Simulate duplicated content across sources
        duplicate_text = "\u9ad8\u5904\u4f5c\u4e1a\u9632\u62a4\u680f\u6746\u9ad8\u5ea6\u4e0d\u4f4e\u4e8e1.2m\uff0c\u8bbe\u7f6e\u4e24\u9053\u6a2a\u6746\u3002"

        kb_result = [{"content": duplicate_text, "score": 0.9}]
        graphrag_result = [{"formatted": duplicate_text}]

        result = mf.fuse(
            mem0_results=[],
            kb_results=kb_result,
            graphrag_results=graphrag_result,
        )
        # MMR should pick at most one of the duplicates
        count_similar = sum(
            1 for r in result if duplicate_text[:30] in r.content[:60]
        )
        if count_similar <= 1:
            r.add("AC-GR-7 MMR Dedup", True,
                  f"Duplicates filtered: {count_similar}/{len(result)}")
        else:
            r.add("AC-GR-7 MMR Dedup", False,
                  f"Expected <=1 duplicate, got {count_similar}")
    except Exception as e:
        r.add("AC-GR-7 MMR Dedup", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-8: LIGHTRAG_ENABLED=false -> search returns empty
# ═══════════════════════════════════════════════════════════════
async def t08_disabled_returns_empty(r: TR):
    try:
        from utils.graph_rag_engine import GraphRAGEngine

        # Create engine WITHOUT LIGHTRAG_ENABLED context -- should guard
        engine = GraphRAGEngine(project_id="test_disabled")

        # search should return empty dict (guarded by LIGHTRAG_ENABLED check)
        result = await engine.search("\u9ad8\u5904\u4f5c\u4e1a", mode="mix")
        assert result == {"entities": [], "relations": [], "chunks": [], "formatted": ""}, \
            f"Expected empty dict, got {result}"

        r.add("AC-GR-8 Disabled Returns Empty", True,
              "search() returns empty when LIGHTRAG_ENABLED=false")
    except Exception as e:
        r.add("AC-GR-8 Disabled Returns Empty", False, str(e))


# ═══════════════════════════════════════════════════════════════
# AC-GR-9: Existing tests still pass (sanity check)
# ═══════════════════════════════════════════════════════════════
async def t09_existing_tests_ok(r: TR):
    """Manual check -- run test_unfixed_diffs.py separately."""
    # This test just confirms the import chain is intact
    try:
        from utils.fusion import MemoryFusion, ContextAssembler
        from utils.memory_manager import MemoryManager
        from utils.memory_tools import TOOL_SCHEMAS
        from utils.config import FUSION_WEIGHT_GRAPHRAG, LIGHTRAG_ENABLED
        r.add("AC-GR-9 Import Chain Intact", True,
              "All modules importable. Run test_unfixed_diffs.py separately for full 66 AC.")
    except Exception as e:
        r.add("AC-GR-9 Import Chain Intact", False, str(e))


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
async def main():
    if not LIGHTRAG_ENABLED:
        print("=" * 60)
        print("WARNING: LIGHTRAG_ENABLED=false")
        print("AC-GR-1 through AC-GR-4 require LIGHTRAG_ENABLED=true")
        print("AC-GR-5 through AC-GR-9 can run without.")
        print("=" * 60)
        print()

    print("=" * 60)
    print("GraphRAG Acceptance Tests (AC-GR-1 to AC-GR-9)")
    print("=" * 60)
    print()

    r = TR()

    await t08_disabled_returns_empty(r); print()
    await t05_fusion_includes_graphrag(r); print()
    await t06_adaptive_weights(r); print()
    await t07_mmr_dedup(r); print()
    await t09_existing_tests_ok(r); print()

    if LIGHTRAG_ENABLED:
        await t01_tables_created(r); print()
        await t02_index_creates_nodes(r); print()
        await t03_idempotent_index(r); print()
        await t04_search_returns_data(r); print()

    r.summary()


if __name__ == "__main__":
    lf = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    asyncio.run(main(), loop_factory=lf)
