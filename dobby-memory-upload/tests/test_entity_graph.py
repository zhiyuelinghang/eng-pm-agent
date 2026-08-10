#!/usr/bin/env python3
"""
Test suite for utils.entity_graph.EntityExtractor.

Covers:
- T1-02 English proper-noun extraction
- Date sentences must not yield month names or "Q1"
- T3-02 acronyms without "AUC 0" false positives
- Chinese connector-split + number/unit merge ("3号基坑", "地下连续墙")
- Deduplication preserving order

Run:
    python test_entity_graph.py
"""

import sys
from pathlib import Path

# Add parent to path (tests/ 的父目录 = dobby-memory)
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.entity_graph import EntityExtractor, EntityGraph

# ── Test Result Tracker ──


class TR:
    def __init__(self):
        self.r = []

    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        status = "✅" if passed else "❌"
        suffix = f": {detail}" if detail else ""
        print(f"  {status} {name}{suffix}")

    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        total = len(self.r)
        all_pass = p == total
        print(f"\n{'='*60}")
        print(f"Results: {p}/{total} passed "
              f"{'🎉 ALL PASS' if all_pass else '⚠️  SOME FAILED'}")
        print(f"{'='*60}")
        return all_pass


tr = TR()

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")

# ============================================================
# 1 — T1-02 English proper nouns
# ============================================================

print("\n" + "="*60)
print("1. T1-02 — English Proper Nouns")
print("="*60)


def test_t1_02_english():
    """Alice and Phoenix should both be extracted."""
    ents = EntityExtractor.extract(
        "Alice is the new project manager for the Phoenix initiative.")
    tr.add("contains 'Alice'", "Alice" in ents, f"got {ents}")
    tr.add("contains 'Phoenix'", "Phoenix" in ents, f"got {ents}")


test_t1_02_english()


def test_leading_stop_word_strip():
    """'The Phoenix ...' must yield 'Phoenix' — leading stop word stripped,
    otherwise 'The Phoenix' vs 'Phoenix' would never match in retrieval."""
    ents = EntityExtractor.extract(
        "The Phoenix initiative office is on the 3rd floor")
    tr.add("contains 'Phoenix' (leading stop word stripped)",
           "Phoenix" in ents, f"got {ents}")
    tr.add("no 'The Phoenix' multi-word run",
           "The Phoenix" not in ents, f"got {ents}")


test_leading_stop_word_strip()

# ============================================================
# 2 — Date sentences: no month names, no "Q1"
# ============================================================

print("\n" + "="*60)
print("2. Date Sentence — No Month / No Q1")
print("="*60)


def test_date_sentence():
    """'March 15' should not produce a 'March' entity, nor 'Q1'."""
    ents = EntityExtractor.extract("The Q1 release deadline is March 15.")
    tr.add("no 'March'", "March" not in ents, f"got {ents}")
    no_month = [m for m in _MONTHS if m in ents]
    tr.add("no single month name", not no_month, f"got {ents} ({no_month})")
    tr.add("no 'Q1' false entity", "Q1" not in ents, f"got {ents}")


test_date_sentence()

# ============================================================
# 3 — T3-02 Acronyms: XGBoost/AUC, no "AUC 0"
# ============================================================

print("\n" + "="*60)
print("3. T3-02 — Acronyms and Metrics")
print("="*60)


def test_t3_02_acronyms():
    """XGBoost and AUC extracted; 'AUC 0.89' must not yield 'AUC 0'."""
    ents = EntityExtractor.extract("The churn model uses XGBoost with AUC 0.89.")
    tr.add("contains 'XGBoost'", "XGBoost" in ents, f"got {ents}")
    tr.add("contains 'AUC'", "AUC" in ents, f"got {ents}")
    tr.add("no 'AUC 0'", "AUC 0" not in ents, f"got {ents}")


test_t3_02_acronyms()

# ============================================================
# 4 — Chinese segmentation + number/unit merge
# ============================================================

print("\n" + "="*60)
print("4. Chinese — Connector Split, Merge, Windows")
print("="*60)


def test_cn_merge_and_windows():
    """'3号基坑', '地下连续墙' (window) and 'JGJ 120-2012' must appear;
    no single-char garbage or >12-char sentence fragments."""
    ents = EntityExtractor.extract(
        "3号基坑需要进行地下连续墙支护，根据JGJ 120-2012规范。")
    tr.add("contains '3号基坑' (number+unit merge)",
           "3号基坑" in ents, f"got {ents}")
    tr.add("contains '地下连续墙' (5-char window)",
           "地下连续墙" in ents, f"got {ents}")
    tr.add("contains 'JGJ 120-2012' (standard)",
           "JGJ 120-2012" in ents, f"got {ents}")
    ents_std = EntityExtractor.extract("根据GB 50016规范")
    tr.add("contains 'GB 50016' (standard)",
           "GB 50016" in ents_std, f"got {ents_std}")
    tr.add("no single-char entity",
           all(len(e) >= 2 for e in ents), f"got {ents}")
    tr.add("no >12-char entity (no sentence fragments)",
           all(len(e) <= 12 for e in ents), f"got {ents}")


test_cn_merge_and_windows()

# ============================================================
# 5 — Deduplication
# ============================================================

print("\n" + "="*60)
print("5. Dedup — Duplicate Entities")
print("="*60)


def test_dedup():
    """Repeated 'Alice' should appear exactly once."""
    ents = EntityExtractor.extract("Alice and Bob; Alice again")
    tr.add("'Alice' appears once", ents.count("Alice") == 1, f"got {ents}")


test_dedup()

# ============================================================
# 6 — EntityGraph: co-occurrence edges
# ============================================================

print("\n" + "="*60)
print("6. EntityGraph — Co-occurrence Edges")
print("="*60)


def test_cooccurrence_edges():
    """Entities in one memory are pairwise linked (case-insensitive)."""
    g = EntityGraph()
    g.add_memory("m1", "content", ["A", "B", "C"])
    cooc = g._cooccurrence
    tr.add("'a' co-occurs with 'b'", "b" in cooc["a"], f"got {sorted(cooc['a'])}")
    tr.add("'a' co-occurs with 'c'", "c" in cooc["a"], f"got {sorted(cooc['a'])}")
    tr.add("'b' co-occurs with 'a'", "a" in cooc["b"], f"got {sorted(cooc['b'])}")
    tr.add("index maps 'a' -> mem", "m1" in g._entity_to_mems["a"],
           f"got {g._entity_to_mems['a']}")


test_cooccurrence_edges()

# ============================================================
# 7 — EntityGraph: depth limit
# ============================================================

print("\n" + "="*60)
print("7. EntityGraph — Spreading Activation Depth Limit")
print("="*60)


def test_depth_limit():
    """max_depth=0 activates only direct entity→memory links."""
    g = EntityGraph()
    g.add_memory("mem1", "content", ["Alice", "Phoenix"])
    g.add_memory("mem2", "content", ["Phoenix"])
    result = g.spreading_activation(["Alice"], max_depth=0)
    tr.add("direct link mem1 activated @1.0",
           result.get("mem1") == 1.0, f"got {result}")
    tr.add("indirect mem2 NOT activated at depth 0",
           "mem2" not in result, f"got {result}")
    # control: with max_depth=1 the co-occurrence hop reaches mem2 @0.5
    result1 = g.spreading_activation(["Alice"], max_depth=1)
    tr.add("control: mem2 activated @~0.5 at depth 1",
           abs(result1.get("mem2", 0.0) - 0.5) < 1e-9, f"got {result1}")


test_depth_limit()

# ============================================================
# 8 — EntityGraph: T1-02 three-session spread
# ============================================================

print("\n" + "="*60)
print("8. EntityGraph — T1-02 Three-Session Spread")
print("="*60)


def test_t1_02_spread():
    """Seed 'Alice': mem1 (Alice) @1.0; mem2 (Phoenix co-occurrence) @~0.5;
    mem3 (PM memory) has no link from Alice."""
    g = EntityGraph()
    ext = EntityExtractor()
    mem1 = "Alice is the new project manager for the Phoenix initiative."
    mem2 = "The Phoenix initiative office is on the 3rd floor, room 302."
    mem3 = "All PMs have admin access to the build server."
    g.add_memory("mem1", mem1, ext.extract(mem1))
    g.add_memory("mem2", mem2, ext.extract(mem2))
    g.add_memory("mem3", mem3, ext.extract(mem3))
    result = g.spreading_activation(["Alice"])
    tr.add("mem1 activated @1.0", result.get("mem1") == 1.0, f"got {result}")
    tr.add("mem2 activated @~0.5 (Phoenix co-occurrence)",
           abs(result.get("mem2", 0.0) - 0.5) < 1e-9, f"got {result}")
    tr.add("mem3 not activated (no link from Alice)",
           "mem3" not in result, f"got {result}")


test_t1_02_spread()

# ============================================================
# 9 — P0-1 Adapter: temporal sort / temporal MMR / vector (BGE)
# ============================================================

print("\n" + "="*60)
print("9. P0-1 Adapter — Temporal Cluster Sort / MMR / Vector Retrieval")
print("="*60)

import asyncio

# Project root + benchmark on path so we can drive the real DemoAdapter.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'benchmark'))
from benchmark.adapters.demo_adapter import DemoAdapter
from benchmark.data import Session


def _session(sid: str, date: str, text: str) -> Session:
    """Minimal single-turn session for adapter ingest."""
    return Session(
        session_id=sid,
        date_time=date,
        speaker_a="A",
        speaker_b="B",
        turns=[{"speaker": "A", "text": text}],
    )


async def _adapter_temporal_cluster_sort():
    """3 deadline sessions across dates → all variants kept, newest first."""
    adapter = DemoAdapter()
    await adapter.ingest([
        _session("s1", "2024-01-10T00:00:00", "The Q1 release deadline is March 15."),
        _session("s2", "2024-02-01T00:00:00",
                 "The Q1 release deadline has been moved to March 30."),
        _session("s3", "2024-02-20T00:00:00", "The Q1 release deadline is now April 5."),
    ])
    res = await adapter.retrieve("When is the Q1 release deadline?")
    joined = " | ".join(res)
    tr.add("[T1] all 3 deadline variants present (Apr 5 / Mar 15 / Mar 30)",
           all(k in joined for k in ("April 5", "March 15", "March 30")),
           f"got {len(res)} results")
    idx_apr = next((i for i, c in enumerate(res) if "April 5" in c), -1)
    idx_mar = next((i for i, c in enumerate(res) if "March 15" in c), -1)
    tr.add("[T1] April 5 ranked before March 15 (temporal cluster sort)",
           idx_apr != -1 and idx_mar != -1 and idx_apr < idx_mar,
           f"April5@{idx_apr} March15@{idx_mar}")


def test_adapter_temporal_cluster_sort():
    asyncio.run(_adapter_temporal_cluster_sort())


test_adapter_temporal_cluster_sort()


async def _adapter_temporal_mmr_dedup():
    """Identical same-date duplicates dedup; different-date variant kept."""
    adapter = DemoAdapter()
    await adapter.ingest([
        _session("s1", "2024-01-10T00:00:00", "The Q1 release deadline is March 15."),
        _session("s2", "2024-01-10T00:00:00", "The Q1 release deadline is March 15."),
        _session("s3", "2024-02-20T00:00:00", "The Q1 release deadline is now April 5."),
    ])
    res = await adapter.retrieve("When is the Q1 release deadline?")
    mar_count = sum(1 for c in res if "March 15" in c)
    tr.add("[T2] identical same-date duplicate deduped (at most 1 copy)",
           mar_count <= 1, f"March-15 copies: {mar_count}")
    tr.add("[T2] different-date April 5 variant still present",
           any("April 5" in c for c in res), f"got {len(res)} results")


def test_adapter_temporal_mmr_dedup():
    asyncio.run(_adapter_temporal_mmr_dedup())


test_adapter_temporal_mmr_dedup()


async def _adapter_semantic_vector():
    """'before' question shares no tokens with the Python 3.8 memory —
    only the cached BGE vector path can surface it. (Content kept
    lexically distinct from the 3.12 doc so temporal MMR keeps both.)"""
    adapter = DemoAdapter()
    await adapter.ingest([
        _session("s1", "2023-06-01T00:00:00",
                 "The team decided on Python 3.8 for the legacy batch jobs."),
        _session("s2", "2024-07-01T00:00:00",
                 "The team migrated to Python 3.12 for the new stack."),
    ])
    res = await adapter.retrieve("What version was used before?")
    tr.add("[T3] 'Python 3.8' retrieved via semantic vector path",
           any("Python 3.8" in c for c in res), f"got {len(res)} results")


def test_adapter_semantic_vector():
    asyncio.run(_adapter_semantic_vector())


test_adapter_semantic_vector()

# ============================================================
# 10 — EntityGraph: content & created_at storage
# ============================================================

print("\n" + "="*60)
print("10. EntityGraph — Content & Created-At Storage")
print("="*60)


def test_graph_content_and_time():
    """EntityGraph 增强: 存储并取回记忆文本与创建时间."""
    g = EntityGraph()
    g.add_memory("m1", "Alice is the PM.", ["Alice", "PM"], created_at="2024-01-10T00:00:00")
    g.add_memory("m2", "Office on 3rd floor.", ["Office"], created_at=None)
    tr.add("get_content returns text", g.get_content("m1") == "Alice is the PM.")
    tr.add("get_content unknown id -> None", g.get_content("nope") is None)
    tr.add("get_created_at returns value", g.get_created_at("m1") == "2024-01-10T00:00:00")
    tr.add("get_created_at None when absent", g.get_created_at("m2") is None)
    tr.add("spreading_activation unchanged", "m1" in g.spreading_activation(["Alice"]))


test_graph_content_and_time()

# ============================================================
# Summary
# ============================================================

if __name__ == "__main__":
    all_pass = tr.summary()
    sys.exit(0 if all_pass else 1)
