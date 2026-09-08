"""Fill legacy display gaps on read, without rewriting original messages."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import re
import time
from typing import Any

from ...tool import ToolBase
from ...tool._presentation import tool_presentation
from ..memory._tool_metadata import memory_presentations


def builtin_presentations() -> dict[str, dict[str, str]]:
    """Reuse loaded tool declarations; never execute tools to get their titles."""
    result = {}
    pending = list(ToolBase.__subclasses__())
    seen = set()
    while pending:
        cls = pending.pop()
        if cls in seen:
            continue
        seen.add(cls)
        pending.extend(cls.__subclasses__())
        if not cls.__module__.startswith("agentscope."):
            continue
        name = getattr(cls, "name", None)
        if isinstance(name, str):
            value = tool_presentation(cls)
            if value["source"] != "fallback":
                result[name] = value
    result.update(memory_presentations())
    return result


_CHILDREN = {
    "content", "metadata", "platform_runtime_trace", "runtime_trace",
    "collaborations", "activities", "current_activity", "subagent_hitl",
    "event", "tool_calls", "pending", "call",
}


def _records(value):
    if isinstance(value, list):
        for item in value:
            yield from _records(item)
    elif isinstance(value, dict):
        if value.get("type") == "tool_call" or value.get("kind") == "tool":
            yield value
        for key in _CHILDREN:
            if key in value:
                yield from _records(value[key])


def fill_presentations(payload, catalogue):
    """Mark compatibility titles honestly as current-catalogue annotations."""
    result = deepcopy(payload)
    for record in _records(result):
        existing = record.get("presentation") or {}
        if existing.get("label") and existing.get("source") not in {"fallback", "catalog_backfill"}:
            continue
        name = record.get("name") if record.get("type") == "tool_call" else record.get("tool_name")
        value = catalogue.get(name)
        if value and value.get("source") != "fallback":
            record["presentation"] = {**value, "source": "catalog_backfill"}
    return result


async def enrich_history(messages, pending_inputs, *, state: Any, storage, user_id: str, agent_id: str):
    payload = [
        [message.model_dump(mode="json") if hasattr(message, "model_dump") else message for message in messages],
        pending_inputs,
    ]
    builtins = builtin_presentations()
    payload = fill_presentations(payload, builtins)
    missing = {record.get("name") or record.get("tool_name") for record in _records(payload)
               if not (record.get("presentation") or {}).get("label")
               or (record.get("presentation") or {}).get("source") == "fallback"}
    if not missing or state is None:
        return payload
    cache = getattr(state, "history_tool_titles", None)
    if cache is None:
        cache = state.history_tool_titles = {}
    key = (user_id, agent_id)
    # Cache is isolated by authenticated owner/agent; unrelated sessions cannot
    # contribute titles. Bounded cache and timeout keep history polling cheap.
    if key not in cache:
        if len(cache) >= 128:
            cache.pop(next(iter(cache)))
        cache[key] = {"lock": asyncio.Lock(), "expires": 0, "titles": {}}
    entry = cache[key]
    async with entry["lock"]:
        if entry["expires"] <= time.monotonic():
            titles = dict(builtins)
            async def resolve():
                registry = getattr(state, "mcp_registry_manager", None)
                if registry is not None:
                    aliases = {}
                    for package in await registry.list_records():
                        for tool in package.tools:
                            value = tool.presentation
                            normalized = re.sub(r"[^a-zA-Z0-9_-]", "x", tool.name)
                            titles[f"mcp__{package.id}__{normalized}"] = value
                            aliases.setdefault(tool.name, []).append(value)
                    # Old system tools sometimes used an unqualified name.
                    # Ambiguous MCP names must never borrow another server's title.
                    titles.update({name: values[0] for name, values in aliases.items() if len(values) == 1})
                factory = getattr(state, "extra_agent_tool_catalog", None)
                if factory is not None:
                    for tool in await factory(user_id, agent_id):
                        titles[tool.name] = tool_presentation(tool)
                manager = getattr(state, "database_interaction_manager", None)
                if manager is not None:
                    agent = await storage.get_agent(user_id, agent_id)
                    if agent is not None:
                        for tool in await manager.list_catalog(agent_id, agent.data.tool_config.allowed_tool_names):
                            titles[tool["key"]] = tool_presentation(
                                name=tool["key"], display_name=tool.get("display_name"),
                                category="database", read_only=tool.get("read_only", True), source="database_catalog",
                            )
            try:
                await asyncio.wait_for(resolve(), timeout=2)
            except Exception:
                # A presentation catalogue failure must not hide conversation history.
                entry["expires"] = time.monotonic() + 15
            else:
                entry["expires"] = time.monotonic() + 60
            entry["titles"] = titles
    return fill_presentations(payload, entry["titles"])
