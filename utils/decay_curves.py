"""
分类别艾宾浩斯遗忘曲线引擎 (P0-1).

基于 YourMemory (sachitrafa/YourMemory) 的源码实现：
  - compute_strength(): src/services/decay.py:33-42
  - DECAY_RATES:       src/services/decay.py:14-22
  - active_days:       src/services/decay.py:63-131
  - 剪枝逻辑:          src/jobs/decay_job.py:44-85

核心公式:
    effective_λ = base_λ × (1 − importance × 0.8)
    strength    = importance × e^(−effective_λ × days) × (1 + recall_count × 0.2)

与旧的 _compute_recency_score (lifecycle.py:61-80) 的区别:
  1. 分类别衰减率 — 不同类型的记忆衰减速度不同
  2. recall_count 加成 — 被回忆越多次越持久
  3. active_days — 休假不计入衰减（仅计用户活跃天数）
  4. importance 调节衰减速度 — 重要记忆衰减更慢
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, date, timezone
from typing import Any

from . import config as _cfg


# ============================================================
# 分类别衰减率
# ============================================================
# 来源: YourMemory src/services/decay.py:14-22
#   λ值越高 → 衰减越快 → 存活时间越短
#
# Category survival (importance=0.5, never recalled, wall-clock):
#   reflection λ=0.10 → ~38 days (反思洞察最持久)
#   decision   λ=0.12 → ~32 days
#   preference λ=0.12 → ~32 days
#   fact       λ=0.16 → ~24 days
#   procedure  λ=0.20 → ~19 days
#   environment λ=0.20 → ~19 days
#   risk       λ=0.35 → ~11 days (风险/故障快速淘汰)

_DECAY_RATES = {
    "fact":         0.16,
    "decision":     0.12,
    "preference":   0.12,
    "procedure":    0.20,
    "risk":         0.35,
    "reflection":   0.10,
    "environment":  0.20,
}
_DEFAULT_RATE = 0.16


# ============================================================
# 核心公式
# ============================================================

def compute_strength(
    created_at: datetime,
    importance: float = 0.5,
    memory_type: str = "fact",
    recall_count: int = 0,
    active_days: float | None = None,
) -> float:
    """
    Ebbinghaus forgetting curve with category-tuned decay rates.

    公式 (YourMemory src/services/decay.py:33-42):
        base_λ      = _DECAY_RATES[memory_type]
        effective_λ = base_λ × (1 − importance × 0.8)
        strength    = importance × e^(−effective_λ × days) × (1 + recall_count × 0.2)

    Args:
        created_at: memory creation datetime
        importance: 0-1 importance score
        memory_type: category key in _DECAY_RATES
        recall_count: number of times this memory was retrieved
        active_days: if set, use this instead of wall-clock days
                     (prevents vacation decay)
    Returns:
        strength 0-1, rounded to 6 decimals.
    """
    if active_days is not None:
        days = max(0.0, active_days)
    else:
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        days = (now - created_at).total_seconds() / 86400.0

    base_lambda = _DECAY_RATES.get(memory_type, _DEFAULT_RATE)
    effective_lambda = base_lambda * (1.0 - importance * 0.8)
    strength = (
        importance
        * math.exp(-effective_lambda * days)
        * (1.0 + recall_count * 0.2)
    )
    return round(min(1.0, max(0.0, strength)), 6)


# ============================================================
# 兼容包装器 (替代 lifecycle._compute_recency_score)
# ============================================================

def compute_recency_score_replacement(
    created_at_str: str | None,
    importance: float = 0.5,
    memory_type: str = "fact",
    recall_count: int = 0,
) -> float:
    """
    兼容旧的 _compute_recency_score(lifecycle.py:61-80) 签名。

    返回 0-1 强度分数。与旧实现的区别：
      - 使用分类别衰减率而非固定30天半衰
      - 使用 e^(-λ*days) 而非 0.5^(days/30)
      - 集成 recall_count 和 importance 调节
    """
    if not created_at_str:
        return 0.3  # neutral for unknown age
    try:
        ts = str(created_at_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
    except Exception:
        return 0.3  # parse error → neutral
    return compute_strength(
        created_at=dt,
        importance=importance,
        memory_type=memory_type,
        recall_count=recall_count,
    )


# ============================================================
# 可视化辅助
# ============================================================

def strength_emoji(s: float) -> str:
    """Return emoji label for a strength score (for context injection)."""
    if s >= 0.7:
        return "\U0001f7e2"   # 🟢 强记忆
    if s >= 0.3:
        return "\U0001f7e1"   # 🟡 衰退中
    if s >= 0.05:
        return "\U0001f7e0"   # 🟠 即将过期
    return "\U0001f534"        # 🔴 几乎遗忘


# ============================================================
# 活跃日管理 (参考 YourMemory src/services/decay.py:63-82)
# ============================================================

def _get_db_conn():
    """复用 lifecycle.py 的 PG 连接模式。"""
    import psycopg
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )


async def record_user_activity(project_id: str) -> None:
    """
    记录今天为活跃日 (幂等)。

    user_activity 表追踪用户每天的活跃情况。
    休假/周末不计入衰减计算。
    """
    today = date.today().isoformat()
    try:
        conn = _get_db_conn()
        conn.execute(
            """INSERT INTO user_activity (project_id, active_on)
               VALUES (%s, %s) ON CONFLICT DO NOTHING""",
            (project_id, today),
        )
        conn.close()
    except Exception:
        pass  # table might not exist yet


async def get_active_days_since(project_id: str, since: datetime) -> float:
    """
    返回自 since 以来的活跃天数。

    如果 user_activity 表无数据/不存在，回退到 wall-clock 天数。
    """
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since_date = since.date().isoformat()
    today = date.today().isoformat()

    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """SELECT COUNT(*) FROM user_activity
               WHERE project_id = %s
                 AND active_on >= %s AND active_on <= %s""",
            (project_id, since_date, today),
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0] and row[0] > 0:
            return float(row[0])
    except Exception:
        pass

    # fallback: wall-clock days
    now = datetime.now(timezone.utc)
    return max(0.0, (now - since).total_seconds() / 86400.0)
