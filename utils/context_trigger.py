# dobby-memory/utils/context_trigger.py
"""
Zero-latency context mode classifier.

Magic Context 参考: decay-render.ts 的确定性 tier 选择（纯规则，无LLM调用）。
延迟 < 1ms，不含任何 I/O 或 LLM 调用。

触发逻辑:
  - 高优先级关键词（规范/标准/安全）→ "full" (4源MMR)
  - 中优先级关键词（任务/进度/项目）→ "standard" (3源,当前行为)
  - 其余 → "minimal" (summary + runtime + history 仅基本上下文)

兜底策略:
  - LLM 可通过工具覆盖任何模式
  - 用户显式指令（"查一下"/"搜索"/"回忆"）→ 强制 full
  - 不再按对话轮数强制检索，避免无关消息触发长期记忆
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# Trigger keyword sets
# ═══════════════════════════════════════════════════════════════

_FULL_KEYWORDS = [
    # 规范/标准类 → knowledge base heavy
    "规范", "标准", "GB", "条款", "合规", "安全规程", "验收",
    "整改", "风险评估", "专项方案", "施工组织设计",
]

_STANDARD_KEYWORDS = [
    # 任务/进度类 → moderate retrieval
    "进度", "任务", "项目", "周报", "月报", "计划",
    "检查", "巡检", "质量", "记录", "之前", "上次", "讨论",
]

_EXPLICIT_SEARCH_KEYWORDS = [
    # 用户显式指令 → 强制 full
    "查一下", "搜索", "回忆", "找一下", "检索",
    "看看有没有", "有没有记录", "帮我查",
]


def classify(query: str, state: dict | None = None) -> str:
    """Zero-latency classification. Returns 'minimal' | 'standard' | 'full'.

    Args:
        query: user input text
        state: retained for API compatibility; classification does not mutate it
    """
    if not query:
        return "minimal"

    # ── Explicit search → force full ──
    if any(kw in query for kw in _EXPLICIT_SEARCH_KEYWORDS):
        return "full"

    # ── Full keywords → full ──
    if any(kw in query for kw in _FULL_KEYWORDS):
        return "full"

    # ── Standard keywords → standard ──
    if any(kw in query for kw in _STANDARD_KEYWORDS):
        return "standard"

    # ── Default: minimal ──
    return "minimal"
