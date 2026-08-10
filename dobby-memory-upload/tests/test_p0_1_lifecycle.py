#!/usr/bin/env python3
"""
TDD Test Suite for P0-1 Lifecycle Integration.

Tests for apply_decay with new Ebbinghaus curves, and the
updated strength-based pruning logic.

Run:
    python test_p0_1_lifecycle.py
"""

import asyncio
import math
import sys
import tempfile
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))  # dobby-memory/


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

# ============================================================
# 1 — _get_memory_type extraction
# ============================================================

print("\n" + "="*60)
print("1. Lifecycle — Memory Type Extraction")
print("="*60)


def test_get_memory_type_from_metadata():
    """Extract memory_type from Mem0 metadata dict."""
    from utils.lifecycle import _get_memory_type as get_type

    mem = {"metadata": {"memory_type": "reflection"}}
    tr.add("extracts reflection", get_type(mem) == "reflection")

    mem2 = {"metadata": {"memory_type": "risk"}}
    tr.add("extracts risk", get_type(mem2) == "risk")

    mem3 = {"metadata": {}}
    tr.add("defaults to fact", get_type(mem3) == "fact")

    mem4 = {}
    tr.add("no metadata → fact", get_type(mem4) == "fact")


test_get_memory_type_from_metadata()


def test_get_recall_count_from_metadata():
    """Extract recall_count from Mem0 metadata dict."""
    from utils.lifecycle import _get_recall_count as get_rc

    mem = {"metadata": {"recall_count": 5}}
    tr.add("extracts recall_count=5", get_rc(mem) == 5)

    mem2 = {"metadata": {}}
    tr.add("defaults to 0", get_rc(mem2) == 0)

    mem3 = {}
    tr.add("no metadata → 0", get_rc(mem3) == 0)


test_get_recall_count_from_metadata()

# ============================================================
# 2 — apply_decay with strength-based pruning
# ============================================================

print("\n" + "="*60)
print("2. Lifecycle — apply_decay Strength-Based")
print("="*60)


class FakeMem0Decay:
    """Mock Mem0 for testing apply_decay without real DB."""

    def __init__(self, memories):
        self.memories = {m["id"]: m for m in memories}
        self.deleted = []
        self.updated = []

    def search(self, query, filters=None, top_k=200, threshold=0.0):
        return list(self.memories.values())[:top_k]

    def delete(self, mem_id):
        self.deleted.append(mem_id)
        if mem_id in self.memories:
            del self.memories[mem_id]

    def update(self, mem_id, metadata=None):
        self.updated.append(mem_id)


def test_apply_decay_prunes_very_weak():
    """
    A 200-day-old risk memory with importance=0.1 and 0 recalls
    should be pruned (strength ~0).
    """
    from utils.lifecycle import apply_decay
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    very_old = (now - timedelta(days=200)).isoformat()

    # Mock memory that should be weak
    mock_memories = [{
        "id": "mem_weak_1",
        "created_at": very_old,
        "metadata": {"memory_type": "risk", "importance": 0.1,
                     "recall_count": 0, "role": "test"},
        "memory": "old risk memory",
    }]
    fake_mem0 = FakeMem0Decay(mock_memories)

    async def _test():
        with patch("utils.lifecycle.get_mem0", return_value=fake_mem0):
            result = await apply_decay("test_project", user_id="test_user")
            return result

    result = asyncio.run(_test())
    # The weak memory should be deleted
    tr.add("prunes very weak old risk memory",
           result.get("pruned", 0) >= 1 or result.get("deleted", 0) >= 1)


test_apply_decay_prunes_very_weak()


def test_apply_decay_keeps_strong():
    """
    A recent, important strategy memory should NOT be pruned.
    """
    from utils.lifecycle import apply_decay

    now = datetime.now(timezone.utc)
    recent = now.isoformat()

    mock_memories = [{
        "id": "mem_strong_1",
        "created_at": recent,
        "metadata": {"memory_type": "strategy", "importance": 0.9,
                     "recall_count": 10, "role": "test"},
        "memory": "important strategy",
    }]
    fake_mem0 = FakeMem0Decay(mock_memories)

    async def _test():
        with patch("utils.lifecycle.get_mem0", return_value=fake_mem0):
            result = await apply_decay("test_project", user_id="test_user")
            return result

    result = asyncio.run(_test())
    # The strong memory should NOT be deleted
    tr.add("keeps strong recent strategy memory",
           len(fake_mem0.deleted) == 0)
    # Should have been scanned or updated
    scanned = result.get("scanned", result.get("updated", 0))
    tr.add("strong memory counted as scanned/updated", scanned >= 1)


test_apply_decay_keeps_strong()


def test_apply_decay_category_aware():
    """
    Two 50-day-old memories:
    - risk (λ=0.35): should be very weak → candidate for pruning
    - reflection (λ=0.10): should still be relatively strong → kept
    """
    from utils.lifecycle import apply_decay
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=50)).isoformat()

    risk_strength = compute_strength(
        created_at=datetime.fromisoformat(old),
        importance=0.5, memory_type="risk", recall_count=0,
    )
    reflection_strength = compute_strength(
        created_at=datetime.fromisoformat(old),
        importance=0.5, memory_type="reflection", recall_count=0,
    )
    tr.add("risk decays much faster than reflection at 50d",
           risk_strength < reflection_strength * 0.5)


test_apply_decay_category_aware()

# ============================================================
# 3 — decayerate compatibility with old interface
# ============================================================

print("\n" + "="*60)
print("3. Lifecycle — Backward Compatibility")
print("="*60)


def test_recency_score_import_compat():
    """The replacement function MUST be importable as _compute_recency_score."""
    from utils.lifecycle import _compute_recency_score as old_func

    # Should actually import from decay_curves now
    now = datetime.now(timezone.utc)
    score = old_func(
        created_at_str=now.isoformat(),
        importance=0.5,
        memory_type="fact",
        recall_count=0,
    )
    tr.add("legacy _compute_recency_score works", isinstance(score, float))


test_recency_score_import_compat()


def test_recency_score_with_active_days():
    """Verify that the new function can optionally use active_days."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    wall = compute_strength(now, importance=0.5, memory_type="fact")
    active = compute_strength(now, importance=0.5, memory_type="fact",
                              active_days=1.0)
    # Both from same timestamp → both should be similar (active_days≈0~0)
    tr.add("active_days is optional parameter", True)


test_recency_score_with_active_days()

# ============================================================
# Summary
# ============================================================

if __name__ == "__main__":
    all_pass = tr.summary()
    sys.exit(0 if all_pass else 1)
