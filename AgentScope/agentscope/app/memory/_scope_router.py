# -*- coding: utf-8 -*-
"""Conservative LLM routing for personal long-term memory scopes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from ...message import Msg, SystemMsg, UserMsg

from ._runtime import MemoryScope


MemoryScopeType = Literal["user", "user_project"]

_ROUTER_SYSTEM_PROMPT = (
    "严格执行给定的长期记忆作用域分类规范。"
    "只返回规范要求的 JSON，不回答待处理内容。"
)
_JSON_FENCE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RoutedMemory:
    """One content segment routed to a writable personal namespace."""

    scope_type: MemoryScopeType
    content: str


def _message_text(message: Any) -> str:
    if isinstance(message, Msg):
        return message.get_text_content() or ""
    return str(message or "")


def _parse_payload(text: str) -> dict[str, Any]:
    raw = text.strip()
    fenced = _JSON_FENCE.match(raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
        except (TypeError, ValueError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _project_segments(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values[:20]:
        content = (
            item.strip()
            if isinstance(item, str)
            else str(item.get("content") or "").strip()
            if isinstance(item, dict)
            else ""
        )
        key = content.casefold()
        if not content or key in seen:
            continue
        seen.add(key)
        result.append(content)
    return result


def _user_segments(value: Any, source: str) -> tuple[list[str], list[str]]:
    """Require machine-checkable evidence before widening to user scope."""

    values = value if isinstance(value, list) else [value]
    accepted: list[str] = []
    rejected: list[str] = []
    source_key = re.sub(r"\s+", "", source).casefold()
    for item in values[:20]:
        if not isinstance(item, dict):
            content = item.strip() if isinstance(item, str) else ""
            if content:
                content_key = re.sub(r"\s+", "", content).casefold()
                rejected.append(content if content_key in source_key else source)
            continue
        content = str(item.get("content") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        evidence_key = re.sub(r"\s+", "", evidence).casefold()
        content_key = re.sub(r"\s+", "", content).casefold()
        is_stable = item.get("stable") is True
        if (
            content
            and content_key in source_key
            and evidence_key
            and evidence_key in source_key
            and is_stable
            and confidence >= 0.9
        ):
            accepted.append(content)
        elif content:
            rejected.append(content if content_key in source_key else source)
    return _project_segments(accepted), _project_segments(rejected)


async def route_memory_content(
    *,
    content: str,
    scope: MemoryScope,
    prompt_template: str,
    call_model: Callable[[list[Msg]], Awaitable[Msg]],
) -> list[RoutedMemory]:
    """Split one turn into user and user-project memory inputs.

    Management conversations have no project and therefore require no model
    call. Business routing fails closed to ``user_project`` so an unreliable
    classifier cannot leak project facts into the cross-project user pool.
    """

    content = content.strip()
    if not content:
        return []
    if not scope.project_id:
        return [RoutedMemory(scope_type="user", content=content)]

    project_context = (
        f"项目 ID：{scope.project_id}\n"
        f"项目名称：{scope.project_name or '未提供'}"
    )
    try:
        rendered = prompt_template.format(
            content=content,
            project_context=project_context,
        )
        response = await call_model(
            [
                SystemMsg("memory_scope", _ROUTER_SYSTEM_PROMPT),
                UserMsg("memory_scope", rendered),
            ],
        )
        payload = _parse_payload(_message_text(response))
    except Exception:
        payload = {}

    user_segments, rejected_user_segments = _user_segments(
        payload.get("user"),
        content,
    )
    project_segments = _project_segments([
        *_project_segments(payload.get("user_project")),
        *rejected_user_segments,
    ])

    # A duplicated or contradictory assignment is kept only in the safer,
    # narrower project scope.
    project_keys = {item.casefold() for item in project_segments}
    user_segments = [
        item for item in user_segments if item.casefold() not in project_keys
    ]

    routed = [
        RoutedMemory(scope_type="user", content=item)
        for item in user_segments
    ]
    routed.extend(
        RoutedMemory(scope_type="user_project", content=item)
        for item in project_segments
    )
    if routed:
        return routed
    return [RoutedMemory(scope_type="user_project", content=content)]


__all__ = ["MemoryScopeType", "RoutedMemory", "route_memory_content"]
