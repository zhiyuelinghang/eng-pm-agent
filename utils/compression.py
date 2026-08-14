"""
LangGraph compression utilities (Step 3).

Token estimation, summary generation, and message trimming for
the compress_node in the Dobby StateGraph.

All config values read dynamically via `config.XXX` so tests can
temporarily override thresholds.
"""

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

from . import config  # module-level for dynamic access


def _extract_text(msg) -> str:
    """Extract plain text from any message object.

    Handles AgentScope Msg (content=list[TextBlock]), LangChain messages,
    and plain dicts.
    """
    content = ""
    if hasattr(msg, "content"):
        content = msg.content
    elif isinstance(msg, dict):
        content = msg.get("content", "")

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(str(block))
        return "".join(parts)
    if hasattr(content, "text"):
        return content.text
    return str(content)


def estimate_tokens(messages: list, chars_per_token: float | None = None) -> int:
    """Rough token count from message list.

    Uses char / ratio heuristic — good enough for threshold detection.
    For CJK text the ratio is ~1.5-2.5 chars/token; default 2.5 is conservative.
    """
    if chars_per_token is None:
        chars_per_token = config.TOKEN_ESTIMATION_CHARS_PER_TOKEN

    total = 0
    for m in messages:
        text = _extract_text(m)
        total += len(text)
    return int(total / chars_per_token)


def needs_compression(messages: list, threshold: int | None = None) -> bool:
    """Check if message list exceeds compression threshold."""
    if threshold is None:
        threshold = config.COMPRESSION_TRIGGER_TOKENS
    return estimate_tokens(messages) >= threshold


def trim_messages(messages: list, keep: int | None = None) -> list:
    """Keep the last N messages after compression."""
    if keep is None:
        keep = config.COMPRESSION_KEEP_MESSAGES
    if len(messages) <= keep:
        return list(messages)
    return list(messages[-keep:])


# ── Compress prompt templates ──

COMPRESS_SYSTEM = """你是 Dobby 对话压缩器。你的任务是将长对话历史压缩为结构化摘要。

**压缩规则**:
1. 保留所有活跃任务的状态（task_id, status, owner, description）
2. 保留关键决策和承诺（谁在什么时候决定了什么）
3. 保留用户偏好和约束（格式要求、风格偏好、禁止事项）
4. 普通闲聊和中间推理过程可以丢弃
5. 摘要应简洁但信息完整，中文书写

**输出格式** — 严格 JSON:
{
  "summary": "完整的对话摘要...",
  "tasks": {"task_id": {"status": "in_progress|done|blocked", "desc": "任务描述"}},
  "decisions": ["决定1", "决定2"],
  "context_to_preserve": "用户偏好和约束..."
}"""

COMPRESS_USER = """现有摘要:
{existing_summary}

活跃任务:
{existing_tasks}

新对话内容 (最近50轮):
{recent_messages}

请生成更新后的摘要。只输出 JSON，不要其他文字。"""

COMPRESS_USER_INCREMENTAL = """你正在**更新**已有的对话摘要。无需重写整个摘要，只需整合新增内容。

## 旧摘要（请保留其中仍然有效的所有信息）
{existing_summary}

## 当前任务快照
{existing_tasks}

## 新增对话（最近50轮，整合进上述摘要）
{recent_messages}

## 更新规则
1. **保留**旧摘要中仍然有效的所有事项（任务、决策、偏好）
2. **新增**上面"新增对话"中出现的新任务、新决策、新约束
3. **更新**旧摘要中已经变化的任务状态（进行中→已完成、阻塞→解除等）
4. **删除**已经完成的、不再需要追踪的一次性闲聊内容
5. 如果新增对话无实质变化，摘要应与旧摘要基本一致

**输出格式** — 严格 JSON:
{{
  "summary": "完整的对话摘要...",
  "tasks": {{"task_id": {{"status": "in_progress|done|blocked", "desc": "任务描述"}}}},
  "decisions": ["决定1", "决定2"],
  "context_to_preserve": "用户偏好和约束..."
}}

只输出 JSON，不要其他文字。"""


def _msg_to_str(msg) -> str:
    """Convert a message object to a readable string for compression."""
    role = ""
    if hasattr(msg, "role"):
        role = msg.role
    elif hasattr(msg, "type"):
        role = msg.type
    elif isinstance(msg, dict):
        role = msg.get("role", msg.get("type", "unknown"))
    else:
        role = "unknown"

    content = _extract_text(msg)

    # Truncate long tool results
    if len(content) > 2000:
        content = content[:2000] + "...[truncated]"

    return f"[{role}] {content}"


def build_compress_messages(
    existing_summary: str,
    existing_tasks: dict,
    recent_messages: list,
    *,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    incremental_prompt: str | None = None,
    incremental: bool | None = None,
) -> list:
    """Build the message list for the compression LLM call."""
    from agentscope.message import SystemMsg, UserMsg

    system_prompt = system_prompt or COMPRESS_SYSTEM
    user_prompt = user_prompt or COMPRESS_USER
    incremental_prompt = incremental_prompt or COMPRESS_USER_INCREMENTAL

    recent_text = "\n\n".join(
        _msg_to_str(m) for m in recent_messages[-50:]
    )

    user_text = user_prompt.format(
        existing_summary=existing_summary or "(无)",
        existing_tasks=json.dumps(existing_tasks or {}, ensure_ascii=False, indent=2),
        recent_messages=recent_text or "(无)",
    )

    # ── Iterative summary: if prior summary exists, use incremental template ──
    # Reference: Agentica compression/manager.py _summarise_conversation()
    use_incremental = (
        bool(existing_summary and existing_summary != "(无)")
        if incremental is None
        else incremental
    )
    if use_incremental and existing_summary and existing_summary != "(无)":
        user_text = incremental_prompt.format(
            existing_summary=existing_summary,
            existing_tasks=json.dumps(existing_tasks or {}, ensure_ascii=False, indent=2),
            recent_messages=recent_text or "(无)",
        )

    return [
        SystemMsg("compressor", system_prompt),
        UserMsg("compressor", user_text),
    ]


def parse_compress_response(response_text: str) -> dict:
    """Parse the LLM compression response.

    Returns {"summary": str, "tasks": dict}.  Falls back gracefully
    on parse errors.
    """
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
        return {
            "summary": str(data.get("summary", "")),
            "tasks": data.get("tasks", {}),
            "decisions": data.get("decisions", []),
            "context_to_preserve": str(data.get("context_to_preserve", "")),
        }
    except json.JSONDecodeError:
        return {
            "summary": response_text[:4000],
            "tasks": {},
            "decisions": [],
            "context_to_preserve": "",
        }
