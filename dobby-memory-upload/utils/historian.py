"""
分层历史学家 (Historian) — P0-2 后台异步压缩引擎。

参考实现: Magic Context ARCHITECTURE.md
  - Compartment model:   compartment-runner-incremental.ts
  - Trigger detection:   compartment-trigger.ts
  - Decay rendering:     decay-curve.ts

核心概念:
  Compartment — 一段已压缩的对话区间（分舱）
  每个分舱包含4个复述层级(p1详细→p4锚点)，
  由衰减渲染器(decay_render)按age/importance选择渲染层级。

与现有 compress_node 的关系:
  - compress_node 继续负责全局摘要(Layer ② Summary)
  - historian 负责分层历史(Layer ②b 新增)
  - 两者并存，historian 是可选增强
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from . import config as _cfg
from .compression import estimate_tokens, _extract_text


# ============================================================
# 1 — Compartment dataclass
# ============================================================

@dataclass
class Compartment:
    """一个历史分舱——代表一段已压缩的对话区间。

    参考 Magic Context compartment-runner-incremental.ts 的输出格式。

    Fields:
        id: unique compartment identifier
        start_ordinal: 原始消息起始位置(messages list index)
        end_ordinal:   原始消息结束位置
        importance:    0-1, affects decay speed (higher = slower to age)
        episode_type:  conversation | task | decision | summary
        p1-p4:        四层复述(verbose → anchor)
        facts:        提取的耐久事实
        events:       提取的事件
        created_at:   ISO8601 timestamp
    """
    id: str
    start_ordinal: int
    end_ordinal: int
    importance: float = 0.5
    episode_type: str = "conversation"
    p1_verbose: str = ""
    p2_standard: str = ""
    p3_brief: str = ""
    p4_anchor: str = ""
    facts: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    created_at: str = ""


# ============================================================
# 2 — Trigger detection
# ============================================================

def should_trigger_historian(
    messages: list,
    compartments: list[Compartment] | None = None,
) -> bool:
    """
    判断是否应触发后台历史学家。

    参考 Magic Context compartment-trigger.ts：
    - 未被分舱覆盖的原始消息部分超过阈值
    - 保留最近的 live tail 不被压缩

    Args:
        messages: full message list
        compartments: existing compartments (may be empty/None)
    """
    if not messages:
        return False
    if compartments is None:
        compartments = []

    # 找到最后一个分舱覆盖到的位置
    last_covered = 0
    if compartments:
        last_covered = max(c.end_ordinal for c in compartments)

    # 未被覆盖的 messages
    uncovered = messages[last_covered:]
    if not uncovered:
        return False

    uncovered_tokens = estimate_tokens(uncovered)
    return uncovered_tokens >= _cfg.HISTORIAN_TRIGGER_TOKENS


# ============================================================
# 3 — Compartment production (LLM sub-agent)
# ============================================================

HISTORIAN_SYSTEM = """你是 Dobby 对话历史学家（Historian）。你的任务是将一段对话压缩为结构化分舱。

**输出格式** — 严格 JSON:
{
  "importance": 0.7,
  "episode_type": "task",
  "p1_verbose": "详细的事件描述...",
  "p2_standard": "标准摘要(50%长度)...",
  "p3_brief": "1-2句话简要概述",
  "p4_anchor": "关键词1,关键词2,关键词3",
  "facts": ["事实1", "事实2"],
  "events": ["事件1", "事件2"]
}

**episode_type**: conversation | task | decision | summary
**importance**: 0.9=关键决策/重大变更, 0.7=任务完成, 0.5=一般交互, 0.3=闲聊
**分层规则**: p1保留who/when/what/why, p2精简50%, p3一句话, p4仅关键词

只输出 JSON，不要其他文字。"""


async def produce_compartment(
    messages_slice: list,
    existing_summary: str = "",
    _call_model_fn=None,
) -> Compartment | None:
    """
    LLM子Agent生成一个分舱。

    参考 Magic Context compartment-runner-incremental.ts：
    - 传入有限上下文(最多30条消息)
    - 不传完整历史(避免token浪费)
    - 如果失败返回 None(调用者优雅降级)

    Args:
        messages_slice: 待压缩的消息切片
        existing_summary: 现有全局摘要(提供上下文)
        _call_model_fn: 可选的mock LLM函数(用于测试)
    """
    if _call_model_fn is None:
        from .langgraph_utils import _call_model
        _call_model_fn = _call_model

    if not messages_slice:
        return None

    # 精简上下文: 最多30条, 每条截断到500字
    recent_text = "\n\n".join(
        f"[{getattr(m, 'role', '?')}] {_extract_text(m)[:500]}"
        for m in messages_slice[-30:]
    )

    user_text = (
        f"现有摘要（如有）:\n{existing_summary or '(无)'}\n\n"
        f"待压缩对话内容:\n{recent_text}\n\n"
        f"请生成结构化分舱。"
    )

    from agentscope.message import SystemMsg, UserMsg
    try:
        resp = await _call_model_fn([
            SystemMsg("historian", HISTORIAN_SYSTEM),
            UserMsg("historian", user_text),
        ])
        content = _extract_text(resp)
        parsed = _parse_json(content)
        if not parsed:
            return None

        import uuid
        from datetime import datetime, timezone

        return Compartment(
            id=f"comp_{uuid.uuid4().hex[:12]}",
            start_ordinal=0,   # caller sets
            end_ordinal=len(messages_slice),
            importance=float(parsed.get("importance", 0.5)),
            episode_type=str(parsed.get("episode_type", "conversation")),
            p1_verbose=str(parsed.get("p1_verbose", "")),
            p2_standard=str(parsed.get("p2_standard", "")),
            p3_brief=str(parsed.get("p3_brief", "")),
            p4_anchor=str(parsed.get("p4_anchor", "")),
            facts=parsed.get("facts", []) or [],
            events=parsed.get("events", []) or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        return None


# ============================================================
# 4 — Orchestration: one historian cycle
# ============================================================

async def historian_cycle(
    state: dict,
    _call_model_fn=None,
) -> dict | None:
    """
    一次完整的历史学家周期: 检测 → 生产 → 返回。

    在 LangGraph 中作为异步后台任务调用。
    返回 None 表示无需操作, 返回 dict 包含 _compartments 更新。
    """
    messages = state.get("messages", [])
    compartments: list[Compartment] = state.get("_compartments", [])
    summary = state.get("summary", "")

    if not should_trigger_historian(messages, compartments):
        return None

    # 找到未覆盖的消息切片
    last_covered = 0
    if compartments:
        last_covered = max(c.end_ordinal for c in compartments)

    # 保留 live tail (最近15%不压缩)
    live_tail = max(10, int(len(messages) * 0.15))
    slice_end = max(last_covered + 1, len(messages) - live_tail)
    if slice_end <= last_covered:
        return None

    slice_to_compress = messages[last_covered:slice_end]
    if len(slice_to_compress) < 3:
        return None  # too small to compress

    new_comp = await produce_compartment(
        slice_to_compress, summary, _call_model_fn,
    )
    if new_comp is None:
        return None

    new_comp.start_ordinal = last_covered
    new_comp.end_ordinal = slice_end

    new_compartments = list(compartments) + [new_comp]
    limit = getattr(_cfg, "COMPARTMENT_COUNT_LIMIT", 50)
    if len(new_compartments) > limit:
        new_compartments = new_compartments[-limit:]

    return {"_compartments": new_compartments}


# ============================================================
# Internal helpers
# ============================================================

def _parse_json(text: str) -> dict:
    """Parse LLM JSON output, handling markdown fences."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        t = "\n".join(lines).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return {}
