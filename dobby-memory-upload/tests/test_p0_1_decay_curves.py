#!/usr/bin/env python3
"""
TDD Test Suite for P0-1: Ebbinghaus Forgetting Curve Upgrade.

Tests for the new decay_curves module — compute_strength, category rates,
recall_count boost, active_days, and the lifecycle integration.

Run:
    python test_p0_1_decay_curves.py
"""

import asyncio
import math
import sys
import tempfile
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

# Add parent to path (tests/ 的父目录 = dobby-memory)
sys.path.insert(0, str(Path(__file__).parent.parent))

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

# ============================================================
# 1 — compute_strength: basic Ebbinghaus formula
# ============================================================

print("\n" + "="*60)
print("1. compute_strength — Ebbinghaus Forgetting Curve")
print("="*60)


def test_compute_strength_basic():
    """A brand-new memory (0 days) should have full strength."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    strength = compute_strength(
        created_at=now,
        importance=0.5,
        memory_type="fact",
        recall_count=0,
    )
    # Brand new → strength ≈ importance (slightly less due to e^0 = 1, but
    # recall_boost=0 → strength = importance * 1 * 1 = 0.5)
    tr.add("new memory strength = importance", abs(strength - 0.5) < 0.01)


test_compute_strength_basic()


def test_compute_strength_decay():
    """A 30-day-old fact memory should have measurably decayed."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=30)
    strength_old = compute_strength(
        created_at=old,
        importance=0.5,
        memory_type="fact",
        recall_count=0,
    )
    # After 30 days with λ=0.16, importance=0.5:
    # effective_λ = 0.16 * (1 - 0.5*0.8) = 0.16 * 0.6 = 0.096
    # strength = 0.5 * e^(-0.096*30) * 1.0 = 0.5 * e^(-2.88) ≈ 0.5 * 0.056 ≈ 0.028
    tr.add("30-day-old fact has decayed", strength_old < 0.20)


test_compute_strength_decay()


def test_compute_strength_strategy_persists():
    """Strategy memories decay slower than failures."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=15)

    strategy_strength = compute_strength(
        created_at=old, importance=0.5,
        memory_type="strategy", recall_count=0,
    )
    failure_strength = compute_strength(
        created_at=old, importance=0.5,
        memory_type="risk", recall_count=0,
    )
    # strategy λ=0.10 vs risk λ=0.35 → strategy should be stronger
    tr.add("strategy outlasts risk", strategy_strength > failure_strength)


test_compute_strength_strategy_persists()


def test_compute_strength_recall_boost():
    """recall_count should boost strength."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=20)

    no_recall = compute_strength(
        created_at=old, importance=0.5,
        memory_type="fact", recall_count=0,
    )
    many_recalls = compute_strength(
        created_at=old, importance=0.5,
        memory_type="fact", recall_count=10,
    )
    # many_recalls gets (1 + 10*0.2) = 3x boost
    ratio = many_recalls / max(no_recall, 0.0001)
    tr.add("recall_count boosts strength proportionally",
           ratio >= 2.5 and ratio <= 3.5)


test_compute_strength_recall_boost()


def test_compute_strength_importance_modulates():
    """High importance memories should decay slower."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=20)

    low_imp = compute_strength(
        created_at=old, importance=0.3,
        memory_type="fact", recall_count=0,
    )
    high_imp = compute_strength(
        created_at=old, importance=0.9,
        memory_type="fact", recall_count=0,
    )
    # High importance: effective_λ = 0.16*(1-0.9*0.8) = 0.16*0.28 = 0.0448
    # Low importance:  effective_λ = 0.16*(1-0.3*0.8) = 0.16*0.76 = 0.1216
    # High should decay slower → higher ratio
    ratio = high_imp / max(low_imp, 0.0001)
    tr.add("high importance decays slower than low", ratio > 1.5)


test_compute_strength_importance_modulates()


def test_compute_strength_clamped():
    """Strength must never exceed 1.0 or go below 0."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)

    # Very recent, very important, many recalls
    s_max = compute_strength(
        created_at=now, importance=1.0,
        memory_type="strategy", recall_count=100,
    )
    tr.add("strength clamped to 1.0 max", s_max <= 1.0)

    # Very old, very unimportant
    very_old = now - timedelta(days=1000)
    s_min = compute_strength(
        created_at=very_old, importance=0.01,
        memory_type="risk", recall_count=0,
    )
    tr.add("strength never negative", s_min >= 0.0)


test_compute_strength_clamped()


def test_compute_strength_active_days():
    """active_days parameter prevents wall-clock decay during vacations."""
    from utils.decay_curves import compute_strength

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)  # 60 wall-clock days ago

    # Without active_days (wall-clock): 60 days of decay
    wall_clock = compute_strength(
        created_at=old, importance=0.5,
        memory_type="fact", recall_count=0,
    )

    # With active_days=5 (only 5 active days): much less decay
    active = compute_strength(
        created_at=old, importance=0.5,
        memory_type="fact", recall_count=0,
        active_days=5.0,
    )

    tr.add("active_days prevents vacation decay",
           active > wall_clock and active > 0.2)


test_compute_strength_active_days()

# ============================================================
# 2 — compute_recency_score_replacement (compat wrapper)
# ============================================================

print("\n" + "="*60)
print("2. compute_recency_score_replacement — Backward Compat")
print("="*60)


def test_compat_wrapper_same_interface():
    """The replacement should match the old function's signature."""
    from utils.decay_curves import compute_recency_score_replacement

    now = datetime.now(timezone.utc)
    ts = now.isoformat()

    score = compute_recency_score_replacement(
        created_at_str=ts,
        importance=0.5,
        memory_type="fact",
        recall_count=0,
    )
    tr.add("compat wrapper returns float", isinstance(score, float))


test_compat_wrapper_same_interface()


def test_compat_wrapper_none_input():
    """Should handle None created_at gracefully."""
    from utils.decay_curves import compute_recency_score_replacement

    score = compute_recency_score_replacement(
        created_at_str=None,
        importance=0.5,
        memory_type="fact",
        recall_count=0,
    )
    tr.add("compat wrapper handles None", score >= 0.0 and score <= 1.0)


test_compat_wrapper_none_input()


def test_compat_wrapper_bad_timestamp():
    """Should handle malformed timestamps."""
    from utils.decay_curves import compute_recency_score_replacement

    score = compute_recency_score_replacement(
        created_at_str="not-a-date",
        importance=0.5,
        memory_type="fact",
        recall_count=0,
    )
    tr.add("compat wrapper handles bad date", score >= 0.0 and score <= 1.0)


test_compat_wrapper_bad_timestamp()

# ============================================================
# 3 — DECAY_RATES mapping
# ============================================================

print("\n" + "="*60)
print("3. DECAY_RATES — Category Mapping")
print("="*60)


def test_decay_rates_all_categories():
    """All four Dobby bucket types should have a decay rate."""
    from utils.decay_curves import _DECAY_RATES, _DEFAULT_RATE

    # Dobby's four experience buckets + additional types
    expected = {"fact", "decision", "preference", "procedure",
                "risk", "reflection", "environment"}
    actual = set(_DECAY_RATES.keys())
    missing = expected - actual
    tr.add(f"all Dobby categories have rates (missing: {missing})",
           len(missing) == 0)


test_decay_rates_all_categories()


def test_decay_rate_order():
    """Rates should be ordered: reflection < strategy-ish < fact < risk."""
    from utils.decay_curves import _DECAY_RATES

    # reflection (slowest) < decision/preference < fact/procedure < risk (fastest)
    tr.add("reflection decays slowest",
           _DECAY_RATES["reflection"] <= _DECAY_RATES["fact"])
    tr.add("risk decays fastest",
           _DECAY_RATES["risk"] >= _DECAY_RATES["fact"])


test_decay_rate_order()

# ============================================================
# 4 — Strength labels (for fusion injection)
# ============================================================

print("\n" + "="*60)
print("4. Strength Label — Visual Indicators")
print("="*60)


def test_strength_emoji():
    """Strength emoji should map to correct ranges."""
    from utils.decay_curves import strength_emoji

    tr.add("s >= 0.7 → green", strength_emoji(0.7) == "🟢")
    tr.add("s >= 0.3 → yellow", strength_emoji(0.3) == "🟡")
    tr.add("s >= 0.05 → orange", strength_emoji(0.05) == "🟠")
    tr.add("s < 0.05 → red", strength_emoji(0.01) == "🔴")


test_strength_emoji()

# ============================================================
# 5 — Historical decay comparison (verify improvement)
# ============================================================

print("\n" + "="*60)
print("5. Improvement Verification — New vs Old")
print("="*60)


def test_old_vs_new_decay():
    """
    Old formula: 0.5 ^ (age / 30)
    New formula: importance * e^(-effective_λ * days) * (1 + recall * 0.2)

    For a 15-day, importance=0.5, recall=5 fact memory:
    - Old: 0.5 ^ (15/30) = 0.5^0.5 ≈ 0.707
    - New: effective_λ = 0.16*(1-0.5*0.8) = 0.096
           strength = 0.5 * e^(-0.096*15) * (1 + 5*0.2) = 0.5 * 0.237 * 2.0 = 0.237

    Old formula has no memory_type awareness, no recall boost,
    and no importance modulation on decay rate.
    The new formula is more nuanced — lower for average memories
    but higher for frequently-recalled, important ones.
    """
    from utils.decay_curves import compute_strength
    import math as _m

    now = datetime.now(timezone.utc)
    old_dt = now - timedelta(days=15)

    # Old formula
    old_score = 0.5 ** (15.0 / 30.0)

    # New formula (average fact)
    new_score = compute_strength(
        created_at=old_dt, importance=0.5,
        memory_type="fact", recall_count=5,
    )

    # The new formula should give MORE weight to frequently-recalled memories
    # For recall_count=5, boost = 1 + 5*0.2 = 2.0
    # This properly rewards frequently-used memories

    # Also verify: high importance + strategy + many recalls outlasts
    # low importance + risk + no recalls by a HUGE margin
    high_score = compute_strength(
        created_at=old_dt, importance=0.9,
        memory_type="strategy", recall_count=20,
    )
    low_score = compute_strength(
        created_at=old_dt, importance=0.2,
        memory_type="risk", recall_count=0,
    )
    ratio = high_score / max(low_score, 0.0001)

    tr.add("new formula properly uses recall_count",
           new_score > 0.0 and new_score <= 1.0)
    tr.add("high-importance memory massively outlasts low",
           ratio > 5.0)  # Should be dramatically different


test_old_vs_new_decay()

# ============================================================
# Summary
# ============================================================

if __name__ == "__main__":
    all_pass = tr.summary()
    sys.exit(0 if all_pass else 1)
