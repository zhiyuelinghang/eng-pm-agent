#!/usr/bin/env python3
"""
TDD Test Suite for P0-2: Background Async Compression + Cache Stability.

Tests for the historian module (compartment production, trigger detection)
and the decay_render module (deterministic tier selection, no-LLM rendering).

Run:
    python test_p0_2_historian.py
"""

import asyncio
import math
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
# 1 — Compartment dataclass
# ============================================================

print("\n" + "="*60)
print("1. Compartment Dataclass — Structure")
print("="*60)


def test_compartment_creation():
    """Compartment should be creatable with required fields."""
    from utils.historian import Compartment

    comp = Compartment(
        id="comp_test001",
        start_ordinal=0,
        end_ordinal=50,
        importance=0.7,
        episode_type="task",
        p1_verbose="详细描述",
        p2_standard="标准摘要",
        p3_brief="简要概述",
        p4_anchor="关键词",
    )
    tr.add("compartment created", comp.id == "comp_test001")
    tr.add("importance stored", comp.importance == 0.7)
    tr.add("all 4 tiers present",
           comp.p1_verbose and comp.p2_standard and comp.p3_brief and comp.p4_anchor)


test_compartment_creation()


def test_compartment_defaults():
    """Compartment should have sensible defaults."""
    from utils.historian import Compartment

    comp = Compartment(
        id="c2",
        start_ordinal=10,
        end_ordinal=20,
    )
    tr.add("default importance 0.5", comp.importance == 0.5)
    tr.add("default episode_type conversation", comp.episode_type == "conversation")
    tr.add("default facts empty", comp.facts == [])
    tr.add("default events empty", comp.events == [])


test_compartment_defaults()

# ============================================================
# 2 — Historian trigger detection
# ============================================================

print("\n" + "="*60)
print("2. Historian Trigger Detection")
print("="*60)


def test_should_trigger_below_threshold():
    """Short conversation should NOT trigger historian."""
    from utils.historian import should_trigger_historian

    # 20 short messages (~200 tokens total) → below HISTORIAN_TRIGGER_TOKENS
    msgs = [{"role": "user", "content": "short msg " + str(i)} for i in range(20)]
    tr.add("short conv not triggered",
           should_trigger_historian(msgs, []) is False)


test_should_trigger_below_threshold()


def test_should_trigger_empty():
    """Empty messages should not trigger."""
    from utils.historian import should_trigger_historian

    tr.add("empty not triggered", should_trigger_historian([], []) is False)


test_should_trigger_empty()


def test_should_trigger_already_covered():
    """All messages already covered by compartments → no trigger."""
    from utils.historian import should_trigger_historian
    from utils.historian import Compartment

    # Create a compartment that covers all messages
    comp = Compartment(
        id="full_cover",
        start_ordinal=0,
        end_ordinal=100,
        p1_verbose="all covered",
    )
    msgs = [{"role": "user", "content": "x" * 500} for _ in range(200)]
    tr.add("fully covered not triggered",
           should_trigger_historian(msgs, [comp]) is False)


test_should_trigger_already_covered()

# ============================================================
# 3 — Decay Render: Age Score
# ============================================================

print("\n" + "="*60)
print("3. Decay Render — Age Score Calculation")
print("="*60)


def test_age_score_brand_new():
    """A brand-new compartment should have age_score ≈ 0."""
    from utils.decay_render import compartment_age_score

    now = datetime.now(timezone.utc)
    score = compartment_age_score(
        created_at_str=now.isoformat(),
        importance=0.5,
        budget_pressure=0.5,
    )
    tr.add("new compartment age_score ≈ 0", score < 0.1)


test_age_score_brand_new()


def test_age_score_old_compartment():
    """A 7-day-old compartment with low importance should score higher."""
    from utils.decay_render import compartment_age_score

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=7)
    score = compartment_age_score(
        created_at_str=old.isoformat(),
        importance=0.3,
        budget_pressure=0.5,
    )
    # Should be measurably > 0 after 7 days
    tr.add("7-day-old has positive score", score > 0.1)


test_age_score_old_compartment()


def test_age_score_importance_protection():
    """High importance should slow aging (lower score = slower to decay)."""
    from utils.decay_render import compartment_age_score

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    low_imp = compartment_age_score(old.isoformat(), importance=0.2)
    high_imp = compartment_age_score(old.isoformat(), importance=0.9)
    tr.add("high importance ages slower", high_imp < low_imp)


test_age_score_importance_protection()


def test_age_score_budget_pressure():
    """Higher budget pressure should accelerate aging."""
    from utils.decay_render import compartment_age_score

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=5)
    low_pressure = compartment_age_score(old.isoformat(), budget_pressure=0.2)
    high_pressure = compartment_age_score(old.isoformat(), budget_pressure=0.8)
    tr.add("high pressure accelerates aging", high_pressure > low_pressure)


test_age_score_budget_pressure()

# ============================================================
# 4 — Decay Render: Tier Selection
# ============================================================

print("\n" + "="*60)
print("4. Decay Render — Tier Selection")
print("="*60)


def test_select_tier_mapping():
    """select_tier should map scores to correct tiers."""
    from utils.decay_render import select_tier

    tr.add("score 0.1 → tier 1 (p1)", select_tier(0.1) == 1)
    tr.add("score 0.5 → tier 2 (p2)", select_tier(0.5) == 2)
    tr.add("score 1.0 → tier 3 (p3)", select_tier(1.0) == 3)
    tr.add("score 2.0 → tier 4 (p4)", select_tier(2.0) == 4)


test_select_tier_mapping()


def test_select_tier_boundaries():
    """select_tier should always return 1-4."""
    from utils.decay_render import select_tier

    for s in [0.0, 0.100, 0.201, 0.500, 0.729, 1.000, 1.322, 3.141, 99.999]:
        tier = select_tier(s)
        tr.add(f"score {s:.3f} → tier {tier}", 1 <= tier <= 4)


test_select_tier_boundaries()

# ============================================================
# 5 — Decay Render: Compartment Rendering
# ============================================================

print("\n" + "="*60)
print("5. Decay Render — Compartment Rendering")
print("="*60)


def test_render_compartment():
    """render_compartment should select correct tier text."""
    from utils.decay_render import render_compartment
    from utils.historian import Compartment

    comp = Compartment(
        id="test", start_ordinal=0, end_ordinal=10,
        p1_verbose="详细版本",
        p2_standard="标准版本",
        p3_brief="简要版本",
        p4_anchor="锚点版本",
    )
    tr.add("tier 1 → p1", render_compartment(comp, 1) == "详细版本")
    tr.add("tier 2 → p2", render_compartment(comp, 2) == "标准版本")
    tr.add("tier 3 → p3", render_compartment(comp, 3) == "简要版本")
    tr.add("tier 4 → p4", render_compartment(comp, 4) == "锚点版本")
    tr.add("invalid tier → p4", render_compartment(comp, 99) == "锚点版本")


test_render_compartment()


def test_render_all_compartments():
    """render_all_compartments should merge multiple compartments."""
    from utils.decay_render import render_all_compartments
    from utils.historian import Compartment

    now = datetime.now(timezone.utc)

    comps = [
        Compartment(
            id="c1", start_ordinal=0, end_ordinal=10,
            importance=0.9, episode_type="task",
            p1_verbose="任务完成：安全检查",
            p2_standard="安全检查完成",
            p3_brief="安全检查",
            p4_anchor="安全",
            created_at=now.isoformat(),
        ),
        Compartment(
            id="c2", start_ordinal=11, end_ordinal=20,
            importance=0.5, episode_type="conversation",
            p1_verbose="讨论了施工方案",
            p2_standard="讨论施工",
            p3_brief="施工讨论",
            p4_anchor="施工",
            created_at=(now - timedelta(days=10)).isoformat(),
        ),
    ]

    result = render_all_compartments(comps)
    tr.add("rendered string not empty", len(result) > 0)
    tr.add("contains high-importance marker", "📌" in result or "task" in result)
    tr.add("rendered string has multiple lines", "\n" in result)


test_render_all_compartments()


def test_render_empty_compartments():
    """Empty list should render as empty string."""
    from utils.decay_render import render_all_compartments
    tr.add("empty → empty string", render_all_compartments([]) == "")


test_render_empty_compartments()

# ============================================================
# 6 — Decay Render is NO-LLM (deterministic, no API calls)
# ============================================================

print("\n" + "="*60)
print("6. Decay Render — Deterministic (No LLM)")
print("="*60)


def test_age_score_deterministic():
    """Same inputs → same output (no randomness)."""
    from utils.decay_render import compartment_age_score

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=5)
    ts = old.isoformat()

    score1 = compartment_age_score(ts, importance=0.5)
    score2 = compartment_age_score(ts, importance=0.5)
    tr.add("deterministic output", score1 == score2)


test_age_score_deterministic()


def test_no_llm_in_render():
    """The render functions must NOT import/call any LLM module."""
    import inspect
    from utils.decay_render import (
        compartment_age_score, select_tier,
        render_compartment, render_all_compartments,
    )

    for func in [compartment_age_score, select_tier,
                 render_compartment, render_all_compartments]:
        source = inspect.getsource(func)
        # Must NOT contain LLM-related patterns (only real API calls, not stdlib)
        illegal = ["_call_model", "openai.", "OpenAI", "deepseek",
                   "anthropic", "llm_client", "ChatCompletion"]
        found = [w for w in illegal if w.lower() in source.lower()]
        tr.add(f"{func.__name__}: no LLM calls",
               len(found) == 0)


test_no_llm_in_render()

# ============================================================
# 7 — Half-life math correctness
# ============================================================

print("\n" + "="*60)
print("7. Half-Life Math — Verification")
print("="*60)


def test_half_life_formula():
    """
    Verify the half-life formula from Magic Context ARCHITECTURE.md:281:
        H = H50 * 2^((I-50)/D) / max(p, 0.10)

    For importance=0.5 (transformed to 50), H should be ≈ H50 / p
    """
    from utils.decay_render import H50, D

    imp_score = 0.5 * 100.0  # → 50
    budget_p = 0.5

    half_life = H50 * (2 ** ((imp_score - 50.0) / D)) / max(budget_p, 0.10)

    # When I=50 → 2^0 = 1 → H = H50 / p = 24 / 0.5 = 48 hours
    tr.add("I=0.5,p=0.5 → half-life ≈ 48h", abs(half_life - 48.0) < 1.0)

    # When I=1.0 (→100): 2^((100-50)/25) = 2^2 = 4 → H = 24*4/0.5 = 192 hours
    imp_score_high = 1.0 * 100.0
    half_life_high = H50 * (2 ** ((imp_score_high - 50.0) / D)) / max(budget_p, 0.10)
    tr.add("I=1.0,p=0.5 → half-life ≈ 192h", abs(half_life_high - 192.0) < 1.0)


test_half_life_formula()

# ============================================================
# Summary
# ============================================================

if __name__ == "__main__":
    all_pass = tr.summary()
    sys.exit(0 if all_pass else 1)
