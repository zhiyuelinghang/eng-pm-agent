"""
确定性衰减渲染器 — P0-2 无LLM渲染引擎。

参考实现: Magic Context decay-curve.ts (ARCHITECTURE.md:281)

核心公式 (Magic Context ARCHITECTURE.md:281):
    half_life H = H50 · 2^((importance−50)/D) / max(budget_pressure, 0.10)
    tier_boundaries = [0.201, 0.729, 1.322, 2.587]

完全确定性 — 纯数学公式, 无LLM调用, 无随机性。
Self-tuning: 根据 context window 压力自动调整渲染精度。

工作原理:
  1. 计算每个 Compartment 的 age_score (log-cost)
  2. 根据 score 落入哪个 tier 选择渲染层级
  3. 年龄越大 / 重要性越低 / 预算压力越高 → 渲染更精简的层级
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .historian import Compartment


# ============================================================
# 常量 (Magic Context ARCHITECTURE.md:281)
# ============================================================

H50 = 24.0                  # 半衰基础值(小时)
D   = 25.0                  # 重要性缩放系数
TIERS = [0.201, 0.729, 1.322, 2.587]  # 四层log-cost边界


# ============================================================
# 1 — Age score
# ============================================================

def compartment_age_score(
    created_at_str: str,
    importance: float = 0.5,
    budget_pressure: float = 0.5,
) -> float:
    """
    计算分舱的"年龄分数" — 分数越高 → 越应降级渲染。

    Formula (Magic Context ARCHITECTURE.md:281):
        half_life H = H50 · 2^((importance×100 − 50) / D) / max(budget_p, 0.10)
        age_score = age_hours / H

    Args:
        created_at_str: ISO8601 timestamp
        importance: 0-1 importance
        budget_pressure: 0-1 token预算压力

    Returns:
        age_score: float, higher = older in log-cost terms
    """
    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age_hours = (now - created_at).total_seconds() / 3600.0

    # importance 0-1 → 0-100 for the formula
    imp_score = importance * 100.0
    budget_p = max(budget_pressure, 0.10)

    half_life = H50 * (2 ** ((imp_score - 50.0) / D)) / budget_p
    return age_hours / max(half_life, 1e-9)


# ============================================================
# 2 — Tier selection
# ============================================================

def select_tier(age_score: float) -> int:
    """
    根据 age_score 选择渲染层级(1-4)。

    TIERS = [0.201, 0.729, 1.322, 2.587]
    age_score ≤ 0.201 → tier 1 (p1: detailed)
    age_score ≤ 0.729 → tier 2 (p2: standard)
    age_score ≤ 1.322 → tier 3 (p3: brief)
    age_score ≤ 2.587 → tier 4 (p4: anchor)
    age_score > 2.587 → tier 4 (fallback to anchor)

    Returns: int 1-4
    """
    for i, boundary in enumerate(TIERS):
        if age_score <= boundary:
            return i + 1
    return 4  # beyond all boundaries → p4 anchor


# ============================================================
# 3 — Rendering
# ============================================================

def render_compartment(comp: Compartment, tier: int) -> str:
    """Render a single compartment at the selected tier."""
    tier_map = {
        1: comp.p1_verbose,
        2: comp.p2_standard,
        3: comp.p3_brief,
        4: comp.p4_anchor,
    }
    return tier_map.get(tier, comp.p4_anchor) or ""


def render_all_compartments(
    compartments: list[Compartment],
    budget_pressure: float = 0.5,
) -> str:
    """
    渲染所有分舱为上下文文本(确定性, 无LLM)。

    Algorithm:
      1. 计算每个分舱的 age_score
      2. 选择 rendering tier
      3. 高重要性分舱加 📌 前缀
      4. 合并为换行分隔的文本

    Returns: rendered context string (or "" if no compartments)
    """
    if not compartments:
        return ""

    rendered = []
    for comp in compartments:
        score = compartment_age_score(
            comp.created_at or datetime.now(timezone.utc).isoformat(),
            comp.importance,
            budget_pressure,
        )
        tier = select_tier(score)
        text = render_compartment(comp, tier)

        if text:
            prefix = "📌 " if comp.importance >= 0.8 else ""
            rendered.append(f"{prefix}[{comp.episode_type}] {text}")

    return "\n\n".join(rendered)
