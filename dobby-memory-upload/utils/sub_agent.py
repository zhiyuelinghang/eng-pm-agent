"""
Task sub-agent lifecycle management (Step 5).

Implements Claude Code-style isolated sub-agent execution:
- Spawn: create independent thread_id and context window
- Execute: isolated LLM call with read-only tools
- Return: structured JSON result only (not full history)
- Destroy: cleanup and return result to parent

The sub-agent has a separate 200K context window, no access to Mem0 or
WeKnora, and returns only a structured conclusion — not the full conversation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any


# Sub-agent system prompt — task executor, not a role persona
SUB_AGENT_SYSTEM = """你是 Dobby 任务执行器。你的工作是根据任务描述完成指定任务并返回结构化结果。

**规则**:
1. 只做任务描述中要求的事情，不要扩展范围
2. 需要额外的文件或数据时，使用 Read 工具
3. 完成任务后输出严格 JSON，不要其他文字
4. 不闲聊，不追问，不提问
5. 不要生成不在任务范围内的内容

**输出格式** — 严格 JSON:
{
  "status": "success" | "failed",
  "summary": "一句话结论（中文）",
  "findings": ["发现1", "发现2"],
  "severity": "high" | "medium" | "low",
  "recommendation": "建议或下一步行动",
  "confidence": 0.85
}

只输出 JSON，不要其他文字。"""


async def delegate_task(
    description: str,
    file_refs: list[str] | None = None,
    role_hint: str | None = None,
    timeout: float = 120.0,
    max_rounds: int = 10,
    _call_model_fn=None,
) -> dict:
    """Spawn an isolated sub-agent to complete a task.

    The sub-agent gets:
      - Independent context window (no parent history)
      - Task description + optional file references
      - Read-only tools (Read file)
      - NO Mem0, NO WeKnora, NO delegate_task (prevents recursion)

    Args:
        description: Natural language task description
        file_refs: Optional list of file paths the sub-agent can read
        role_hint: Optional hint about which role context is relevant
        timeout: Maximum execution time in seconds (default 120)
        max_rounds: Maximum reasoning rounds (enforced via prompt, default 10)
        _call_model_fn: Optional override for _call_model (for testing)

    Returns:
        dict with keys: status, summary, findings, severity, recommendation, confidence
        On timeout: {"status": "timeout", "summary": "...", ...}
        On error: {"status": "failed", "summary": "error message", ...}
    """
    # Build the isolated prompt
    prompt_parts = [SUB_AGENT_SYSTEM]

    # Task description
    task_text = f"\n\n## 任务描述\n{description}"
    if role_hint:
        task_text += f"\n\n角色背景: {role_hint}"
    if max_rounds:
        task_text += f"\n\n注意: 最多 {max_rounds} 轮推理，超过则返回当前结论。"
    prompt_parts.append(task_text)

    # File references
    if file_refs:
        files_text = "\n\n## 可用文件\n" + "\n".join(f"- {f}" for f in file_refs)
        prompt_parts.append(files_text)

    # Build the message list
    from agentscope.message import SystemMsg, UserMsg
    msgs = [
        SystemMsg("sub_agent", prompt_parts[0]),
        UserMsg("task", "\n".join(prompt_parts[1:])),
    ]

    # Get the LLM call function
    if _call_model_fn is None:
        from .langgraph_utils import _call_model
        _call_model_fn = _call_model

    # Execute with timeout
    try:
        resp = await asyncio.wait_for(
            _call_model_fn(msgs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "summary": f"任务执行超时（{timeout}秒）",
            "findings": [],
            "severity": "low",
            "recommendation": "建议拆分任务或增加超时时间",
            "confidence": 0.0,
        }
    except Exception as e:
        return {
            "status": "failed",
            "summary": f"任务执行失败: {str(e)[:200]}",
            "findings": [],
            "severity": "low",
            "recommendation": "检查任务描述和依赖",
            "confidence": 0.0,
        }

    # Parse the structured response
    content = ""
    if hasattr(resp, "content"):
        c = resp.content
        if isinstance(c, str):
            content = c
        elif isinstance(c, list):
            parts = []
            for block in c:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif isinstance(block, dict) and "text" in block:
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            content = "".join(parts)
    elif isinstance(resp, str):
        content = resp
    else:
        content = str(resp)

    # Clean markdown code fences
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()

    # Parse JSON
    try:
        data = json.loads(text)
        return {
            "status": data.get("status", "success"),
            "summary": str(data.get("summary", "")),
            "findings": data.get("findings", []),
            "severity": data.get("severity", "low"),
            "recommendation": str(data.get("recommendation", "")),
            "confidence": float(data.get("confidence", 0.5)),
        }
    except json.JSONDecodeError:
        # Fallback: wrap the raw response
        return {
            "status": "success",
            "summary": content[:500],
            "findings": [],
            "severity": "low",
            "recommendation": "",
            "confidence": 0.3,
        }
