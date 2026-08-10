"""
Layered Token Budget Manager (§3.3).

Implements the 7-layer token budget allocation and overflow trimming
from the core design. Used by build_role_node() and compress_node()
to ensure each layer stays within its budget.

Overflow trim priority:
  1. Drop oldest history messages (Recent History exceeds budget)
  2. Trigger compression (Summary exceeds budget → compress_node)
  3. Trim retrieval results (LTM/KB/Timeline exceeds budget → reduce top_k)
  4. ★ NEVER trim System Prompt or User Message
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config as _cfg
from .compression import estimate_tokens


# ============================================================
# Data structures
# ============================================================

@dataclass
class BudgetAllocation:
    """Result of a token budget allocation check.

    Fields:
        layers: dict — trimmed content per layer (same keys as input)
        total_estimate: int — total token estimate after trimming
        within_budget: bool — True if total fits within max_budget
        warnings: list[str] — human-readable overflow warnings
        overflow_layers: list[str] — layers that were trimmed
    """
    layers: dict = field(default_factory=dict)
    total_estimate: int = 0
    within_budget: bool = True
    warnings: list[str] = field(default_factory=list)
    overflow_layers: list[str] = field(default_factory=list)


# ============================================================
# Layer definition
# ============================================================

# Layer names and their budget limits + protection level
# protected=True → never trimmed; protected=False → can be trimmed
LAYER_CONFIG = {
    "system_prompt": {
        "max_tokens": lambda: _cfg.TOKEN_BUDGET_SYSTEM_PROMPT,
        "protected": True,
        "description": "System Prompt",
    },
    "skill_injection": {
        "max_tokens": lambda: _cfg.TOKEN_BUDGET_SKILL_INJECTION,
        "protected": True,
        "description": "Skill Injection",
    },
    "summary": {
        "max_tokens": lambda: _cfg.TOKEN_BUDGET_SUMMARY,
        "protected": False,
        "description": "Summary",
    },
    "ltm_kb_timeline": {
        "max_tokens": lambda: _cfg.TOKEN_BUDGET_LTM_KB_TIMELINE,
        "protected": False,
        "description": "LTM + KB + Timeline",
    },
    "runtime": {
        "max_tokens": lambda: _cfg.TOKEN_BUDGET_RUNTIME,
        "protected": True,
        "description": "Runtime Context",
    },
    "recent_history": {
        "max_tokens": lambda: _cfg.TOKEN_BUDGET_RECENT_HISTORY,
        "protected": False,
        "description": "Recent History",
    },
    "user_message": {
        "max_tokens": lambda: None,  # no limit
        "protected": True,
        "description": "User Message",
    },
}

# Trim priority: layers are trimmed in this order (first = trimmed first)
# Lower-numbered layers get trimmed before higher-numbered ones.
# Layers not in this list are never trimmed (protected).
TRIM_PRIORITY = ["recent_history", "summary", "ltm_kb_timeline"]


# ============================================================
# TokenBudget
# ============================================================

class TokenBudget:
    """Layered token budget manager.

    Usage:
        budget = TokenBudget()
        allocation = budget.allocate({
            "system_prompt": role_system_prompt,
            "summary": state.get("summary", ""),
            "ltm_kb_timeline": mem_text + kb_text,
            "runtime": f"project={pid}, role={rid}",
            "recent_history": recent_msgs,
            "user_message": query,
        })
        # Check allocation.warnings, use allocation.layers for context assembly
    """

    def __init__(self, max_budget: int | None = None):
        self.max_budget = max_budget or _cfg.MAX_TOKEN_BUDGET
        self._output_reserve = _cfg.TOKEN_BUDGET_OUTPUT_RESERVE

    # ── Public API ──

    def allocate(self, layers: dict[str, Any]) -> BudgetAllocation:
        """Check all layers against budget and trim overflow.

        Args:
            layers: dict mapping layer_name → content.
                    Content can be str (text) or list (messages).
                    Valid keys match LAYER_CONFIG.

        Returns:
            BudgetAllocation with trimmed layers and diagnostics.
        """
        warnings: list[str] = []
        overflow_layers: list[str] = []
        trimmed = dict(layers)  # start with input copy
        protected = set()

        # ── Phase 1: check each layer ──
        for name, content in layers.items():
            cfg = LAYER_CONFIG.get(name)
            if cfg is None:
                warnings.append(f"Unknown layer '{name}' — skipping budget check")
                continue

            if cfg["protected"]:
                protected.add(name)

            max_tokens_fn = cfg["max_tokens"]
            if max_tokens_fn is None:
                continue  # no limit for this layer

            max_tokens = max_tokens_fn()
            if max_tokens is None:
                continue  # no limit for this layer
            tokens = self._count_tokens(content)

            if tokens > max_tokens:
                overflow_layers.append(name)
                desc = cfg["description"]
                warnings.append(
                    f"[TokenBudget] {desc}: {tokens} tokens exceeds limit "
                    f"({max_tokens}), marking for trim"
                )

        # ── Phase 2: trim overflow in priority order ──
        if overflow_layers:
            trimmed = self.trim_overflow(trimmed, overflow_layers)

        # ── Phase 3: compute total ──
        total = sum(
            self._count_tokens(c) for name, c in trimmed.items()
        )

        # Reserve for output
        effective_total = total + self._output_reserve
        within = effective_total <= self.max_budget

        if not within:
            warnings.append(
                f"[TokenBudget] Total {effective_total} (incl. {self._output_reserve} "
                f"output reserve) exceeds max budget {self.max_budget}"
            )

        return BudgetAllocation(
            layers=trimmed,
            total_estimate=effective_total,
            within_budget=within,
            warnings=warnings,
            overflow_layers=overflow_layers,
        )

    def check_layer(self, name: str, content: Any) -> tuple[bool, str]:
        """Check a single layer. Returns (within_budget, warning_or_empty)."""
        cfg = LAYER_CONFIG.get(name)
        if cfg is None:
            return True, ""
        if cfg["protected"]:
            return True, ""
        max_tokens_fn = cfg["max_tokens"]
        if max_tokens_fn is None:
            return True, ""
        max_tokens = max_tokens_fn()
        if max_tokens is None:
            return True, ""
        tokens = self._count_tokens(content)
        if tokens > max_tokens:
            return False, (
                f"{cfg['description']}: {tokens} tokens exceeds limit {max_tokens}"
            )
        return True, ""

    def trim_overflow(
        self,
        layers: dict[str, Any],
        overflow_layers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Trim layers in priority order.

        Args:
            layers: dict of layer_name → content
            overflow_layers: which layers were flagged as overflow (if None, derive from check)

        Returns:
            layers with trimmed content

        Trim algorithm per layer type:
            - recent_history: drop oldest messages until under budget
            - summary: truncate to max chars (chars_per_token * max_tokens)
            - ltm_kb_timeline: truncate each chunk proportionally
        """
        result = dict(layers)

        # Sort overflow layers by trim priority (lower index = trim first)
        if overflow_layers is None:
            overflow_layers = [
                name for name in TRIM_PRIORITY
                if name in layers
            ]
        else:
            overflow_layers = sorted(
                overflow_layers,
                key=lambda n: TRIM_PRIORITY.index(n) if n in TRIM_PRIORITY else 999,
            )

        for name in overflow_layers:
            cfg = LAYER_CONFIG.get(name, {})
            max_tokens_fn = cfg.get("max_tokens")
            if max_tokens_fn is None:
                continue
            max_tokens = max_tokens_fn()
            if max_tokens is None:
                continue

            content = result.get(name)
            if content is None:
                continue

            current_tokens = self._count_tokens(content)
            if current_tokens <= max_tokens:
                continue

            if name == "recent_history":
                result[name] = self._trim_recent_history(content, max_tokens)
            elif name == "summary":
                result[name] = self._trim_text(content, max_tokens)
            elif name == "ltm_kb_timeline":
                result[name] = self._trim_text(content, max_tokens)

        return result

    # ── Internal helpers ──

    def _count_tokens(self, content: Any) -> int:
        """Count tokens for a layer's content (str or list of messages)."""
        if isinstance(content, str):
            return estimate_tokens_str(content)
        if isinstance(content, list):
            return estimate_tokens(content)
        return 0

    def _trim_recent_history(self, messages: list, max_tokens: int) -> list:
        """Keep the most recent messages that fit within max_tokens."""
        if not messages:
            return []
        kept = []
        tokens = 0
        for m in reversed(messages):
            t = self._count_tokens(m)
            if tokens + t > max_tokens:
                break
            kept.insert(0, m)
            tokens += t
        return kept

    def _trim_text(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within max_tokens (approximate)."""
        if not text:
            return ""
        chars_per_token = _cfg.TOKEN_ESTIMATION_CHARS_PER_TOKEN
        max_chars = int(max_tokens * chars_per_token)
        if len(text) <= max_chars:
            return text
        # Try to break at a newline or sentence boundary
        truncated = text[:max_chars]
        last_nl = truncated.rfind("\n")
        if last_nl > max_chars * 0.5:
            return truncated[:last_nl] + "\n...[truncated by token budget]"
        return truncated[:max_chars - 50] + "...[truncated by token budget]"


# ============================================================
# Standalone helpers (used by TokenBudget and external callers)
# ============================================================

def estimate_tokens_str(text: str) -> int:
    """Estimate token count for a plain string."""
    if not text:
        return 0
    return int(len(text) / _cfg.TOKEN_ESTIMATION_CHARS_PER_TOKEN)


def format_budget_report(allocation: BudgetAllocation) -> str:
    """Human-readable budget report for logging/debugging."""
    lines = [
        f"Token Budget Report:",
        f"  Total estimate: {allocation.total_estimate} / {_cfg.MAX_TOKEN_BUDGET}",
        f"  Within budget:  {allocation.within_budget}",
    ]
    if allocation.overflow_layers:
        lines.append(f"  Overflow layers: {', '.join(allocation.overflow_layers)}")
    if allocation.warnings:
        lines.append("  Warnings:")
        for w in allocation.warnings:
            lines.append(f"    - {w}")
    for name, content in allocation.layers.items():
        tokens = estimate_tokens_str(content) if isinstance(content, str) else estimate_tokens(content) if isinstance(content, list) else 0
        max_t = LAYER_CONFIG.get(name, {}).get("max_tokens", lambda: None)()
        max_str = f" / {max_t}" if max_t else ""
        lines.append(f"  {name}: {tokens}{max_str} tokens")
    return "\n".join(lines)
