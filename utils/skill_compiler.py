"""
Experience-to-skill compiler (Step 10).

Transforms raw events (skill_events table) and consolidated experiences
(experiences table) into CompiledCard structures, then (via LLM) into
SkillRecord SKILL.md documents.

Design decisions (ref: Agentica compiler.py + compiled_store.py):
  - Pure functions for event -> card conversion
  - Deterministic dedup: _rule_to_title() stem extraction + stopword filter
  - Single LLM call: judge + generate in one step (ref: maybe_spawn_skill)
  - Two compilation sources: skill_events (A) + experiences (B)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import config as _cfg


# -- Dedup: deterministic title extraction (ref: compiler.py:_rule_to_title) --

_RULE_STOPWORDS = frozenset({
    # English
    "a", "an", "the", "is", "are", "be", "being", "been", "to", "of", "in",
    "on", "at", "for", "by", "with", "from", "as", "or", "and", "but", "not",
    "no", "always", "never", "should", "must", "when", "if", "then", "else",
    "this", "that", "you", "your", "please", "do", "does", "did", "make",
    "sure", "try", "use", "using", "used", "via",
    "step", "steps", "first", "second", "third", "fourth", "fifth",
    "follow", "follows", "following", "followed",
    "every", "any", "each", "all", "next", "once", "now", "again",
    "ensure", "ensures", "ensuring",
    "perform", "call", "remember",
    # Chinese
    "\u7684", "\u4e86", "\u5728", "\u662f", "\u6709", "\u548c", "\u5c31", "\u90fd", "\u8981", "\u4f1a", "\u4e0d",
    "\u5e94\u8be5", "\u5fc5\u987b", "\u9700\u8981", "\u53ef\u4ee5", "\u4e0d\u80fd", "\u4e00\u4e2a", "\u8fd9\u4e2a", "\u90a3\u4e2a",
    "\u7b2c", "\u6b65", "\u68c0\u67e5", "\u786e\u8ba4", "\u7136\u540e", "\u4e4b\u540e", "\u4e4b\u524d", "\u5148", "\u518d",
    "\u8bf7", "\u4f60", "\u6211", "\u4ed6", "\u5979", "\u4ed6\u4eec", "\u6211\u4eec",
})

_TITLE_TOKEN_CAP = 4


def _stem(token: str) -> str:
    """Cheap suffix stripping (ref: compiler.py:_stem)."""
    for suf in ("ings", "ing", "ies", "ied", "ed", "es", "s"):
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            base = token[: -len(suf)]
            if suf == "ies":
                base += "y"
            return base
    return token


def _rule_to_title(rule: str) -> str:
    """Deterministic snake_case title (ref: compiler.py:_rule_to_title).

    Different LLM rewordings of the same rule collapse to the same title.
    Returns empty string if nothing meaningful survives filtering.
    """
    # Match CJK + ASCII tokens
    tokens = re.findall(r"[a-z\u4e00-\u9fff]+", rule.lower())
    keep: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        if raw in _RULE_STOPWORDS or len(raw) <= 1:
            continue
        stem = _stem(raw)
        if stem in _RULE_STOPWORDS or len(stem) <= 1:
            continue
        if stem in seen:
            continue
        seen.add(stem)
        keep.append(stem)
    if not keep:
        return ""
    return "_".join(keep[:_TITLE_TOKEN_CAP])


# -- Data classes --

@dataclass
class CompiledCard:
    """Compiled experience card (ref: compiler.py:CompiledCard)."""
    title: str
    content: str
    experience_type: str              # tool_error | correction | success_pattern | consolidated
    role_scope: str = "global"        # "global" | "safety_director" | ...
    bucket: str = "procedure"         # preference | procedure | decision | environment
    source_event_ids: list[str] = field(default_factory=list)


@dataclass
class SkillRecord:
    """Compiled skill document (ref: compiled_store.py write pattern)."""
    slug: str
    role_id: str
    bucket: str
    title: str
    body_md: str
    project_id: str = ""
    status: str = "shadow"
    tier: str = "hot"
    importance: float = 0.5
    repeat_count: int = 1
    source_event_ids: list[str] = field(default_factory=list)


# -- Compilation prompt (adapted from Agentica skill_spawn.md) --

_COMPILE_SYSTEM = """你是 Dobby 技能编译器。分析以下经验卡片，判断是否应该编译为可复用的技能文档。

一个技能是"别再踩这个坑了"的警示，而不是"怎么做X"的教程。

**决策规则**:
1. 优先选择 repeat_count 最高的 correction 类型卡片
2. repeat_count >= 3 -> 生成技能
3. 跳过: (a) 只有 tool_error 没有 correction, (b) 已有技能已覆盖, (c) 一次性偏好无程序性内容

**返回 JSON**:
{
  "action": "ignore|generate",
  "skill_name": "kebab-case-name",
  "title": "人类可读标题",
  "reason": "为什么值得编译为技能",
  "body_md": "完整的技能文档（见下方格式）"
}

**body_md 格式（必须遵守）**:
开头 YAML frontmatter:
---
name: <kebab-case-slug>
description: <一句话，<=25字>
when-to-use: <逗号分隔的关键词>
---

正文结构（严格顺序）:
1. 一句话摘要（<=30字）
2. ## 常见坑 (REQUIRED, >=2条)
   - 每条 = 观察到的失败现象 + 根因 + 最小修复
   - 每条必须能追溯到输入的经验卡片，禁止编造
3. ## 推荐做法
   - 给出正确操作步骤（<=5条）
4. ## 适用角色
   - 列出适用的角色名称

**禁止**:
- '概述'/'使用场景'/'工作流程' 等教科书式标题
- '# TODO' / '<你的值>' / 'pass # implement' 占位符
- 从工具文档就能推导出的通用步骤
- 未经经验卡片验证的主张
"""

_COMPILE_USER = """**角色范围**: {role_scope}

**候选经验卡片**:
{cards_text}

请分析以上卡片，决定是否编译技能。只输出 JSON。"""


class SkillCompiler:
    """Pure compiler: raw events -> CompiledCard -> SkillRecord.

    No I/O, no mutable state. LLM calls via injected model function.
    """

    # -- Source A: skill_events table --

    @staticmethod
    def compile_tool_errors(events: list[dict]) -> list[CompiledCard]:
        """Compile tool_error events into cards.

        Each unique tool_name produces one card. Dedup by tool name.
        (ref: compiler.py:compile_tool_errors)
        """
        cards: list[CompiledCard] = []
        seen_tools: set[str] = set()
        for e in events:
            if e.get("event_type") != "tool_error":
                continue
            tool = e.get("tool_name", "unknown")
            if tool in seen_tools:
                continue
            seen_tools.add(tool)

            error_msg = e.get("error_message", "")[:300]
            title = f"{tool}_error"
            content = (
                f"工具 `{tool}` 调用失败。\n"
                f"错误: {error_msg}\n"
                f"角色: {e.get('role_id', 'unknown')}"
            )
            cards.append(CompiledCard(
                title=title,
                content=content,
                experience_type="tool_error",
                role_scope=e.get("role_id", "global"),
                bucket="procedure",
                source_event_ids=[str(e.get("id", ""))],
            ))
        return cards

    @staticmethod
    def compile_corrections(events: list[dict]) -> list[CompiledCard]:
        """Compile user_correction events into cards.

        Groups by deterministic title to avoid duplicates.
        (ref: compiler.py:compile_correction)
        """
        cards: list[CompiledCard] = []
        seen_titles: set[str] = set()

        for e in events:
            if e.get("event_type") != "user_correction":
                continue
            user_msg = e.get("user_message", "")
            prev_resp = e.get("previous_response", "")

            # Extract the rule from user correction text
            # Use simple heuristic: capture the sentence containing key patterns
            rule_text = _extract_correction_rule(user_msg)
            if not rule_text:
                rule_text = user_msg[:200]

            title = _rule_to_title(rule_text)
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            content = (
                f"用户纠正: {user_msg[:300]}\n"
                f"原回答: {prev_resp[:200]}\n"
                f"角色: {e.get('role_id', 'unknown')}"
            )
            cards.append(CompiledCard(
                title=title,
                content=content,
                experience_type="correction",
                role_scope=e.get("role_id", "global"),
                bucket="decision",
                source_event_ids=[str(e.get("id", ""))],
            ))
        return cards

    @staticmethod
    def compile_success_patterns(events: list[dict]) -> list[CompiledCard]:
        """Compile success_pattern events (>=3 distinct tools)."""
        cards: list[CompiledCard] = []
        for e in events:
            if e.get("event_type") != "success_pattern":
                continue
            tools = e.get("tool_sequence", [])
            if len(tools) < 3:
                continue
            distinct = list(dict.fromkeys(tools))
            title = f"success_combo_{'_'.join(distinct[:3])}"[:60]
            content = (
                f"成功工具组合: {' -> '.join(distinct)}\n"
                f"总调用: {e.get('tool_count', len(tools))}次\n"
                f"角色: {e.get('role_id', 'unknown')}"
            )
            cards.append(CompiledCard(
                title=title,
                content=content,
                experience_type="success_pattern",
                role_scope=e.get("role_id", "global"),
                bucket="procedure",
                source_event_ids=[str(e.get("id", ""))],
            ))
        return cards

    # -- Source B: experiences table --

    @staticmethod
    def compile_experiences(exp_rows: list[dict]) -> list[CompiledCard]:
        """Compile consolidated experiences (Phase 2 output) into cards.

        Each row from the experiences table becomes one CompiledCard.
        Uses the existing slug + bucket for dedup.
        """
        cards: list[CompiledCard] = []
        for row in exp_rows:
            slug = row.get("slug", "")
            bucket = row.get("bucket", "procedure")
            body = row.get("body_md", "")
            if not slug or not body:
                continue

            # Determine role scope from bucket
            role_scope = "global" if bucket in ("preference", "environment") else "any"
            title = f"exp_{slug}"[:60]
            cards.append(CompiledCard(
                title=title,
                content=body[:500],
                experience_type="consolidated",
                role_scope=role_scope,
                bucket=bucket,
                source_event_ids=[str(row.get("id", ""))],
            ))
        return cards

    # -- LLM compilation --

    @staticmethod
    async def compile_to_skill(
        model_fn,           # async callable: model_fn(msgs) -> response
        cards: list[CompiledCard],
        role_scope: str = "global",
    ) -> dict | None:
        """Judge + generate SKILL.md in one LLM call.

        Returns:
            {"action": "generate"|"ignore", "skill_name": str, "title": str, "reason": str, "body_md": str}
            or None if LLM fails
        """
        if not cards:
            return None

        cards_lines = []
        for i, c in enumerate(cards, 1):
            cards_lines.append(
                f"[{i}] type={c.experience_type} bucket={c.bucket}\n"
                f"    role={c.role_scope}\n"
                f"    {c.content[:300]}"
            )
        cards_text = "\n\n".join(cards_lines)

        user_text = _COMPILE_USER.format(
            role_scope=role_scope,
            cards_text=cards_text,
        )

        from agentscope.message import SystemMsg, UserMsg
        msgs = [
            SystemMsg("skill_compiler", _COMPILE_SYSTEM),
            UserMsg("skill_compiler", user_text),
        ]

        try:
            resp = await model_fn(msgs)
            # Extract text from response
            content = ""
            if hasattr(resp, "content"):
                content = resp.content
            elif isinstance(resp, dict):
                content = resp.get("content", "")
            if isinstance(content, list):
                parts = []
                for block in content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                    elif isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                content = "".join(parts)

            text = content.strip()
            # Strip markdown fences
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(lines).strip()

            result = json.loads(text)
            if isinstance(result, dict) and result.get("action") == "generate":
                return result
            return None
        except Exception:
            return None


# -- Helper --

def _extract_correction_rule(user_msg: str) -> str:
    """Extract correction rule from user message using pattern matching.

    Ref: Agentica hooks.py:_RULE_PREFIX_PATTERNS (adapted for Chinese).
    """
    patterns = [
        r"记住，?规则是(.+)",
        r"(?:规则是|下次请|以后请|必须先|不要再|不要)(.+)",
        r"(?:应该是|应该是这样|正确的做法是)(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, user_msg)
        if m:
            return m.group(1).strip()[:100]
    return ""
