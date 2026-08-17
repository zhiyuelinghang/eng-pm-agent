"""
LangGraph StateGraph builder for Dobby (Step 3).

Defines DobbyState, the 4-node graph (supervisor → compress | safety_director | dobby_core),
and helper functions for building the compiled graph with PostgresSaver.

All config values read via _cfg.XXX for dynamic override support.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
import json
import threading
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.types import Command, Send
# Module-level role registry (set by build_graph, read by supervisor_node)
_current_role_registry: dict = {}
# Module-level role node function registry (for parallel dispatch)
_role_nodes: dict = {}


def get_role_registry() -> dict | None:
    """Return the current role registry (for external consumers)."""
    return _current_role_registry

from . import config as _cfg
from .audit_logger import get_audit_logger
from .message_adapter import MessageAdapter, UnifiedMessage
from .compression import (
    estimate_tokens,
    needs_compression,
    trim_messages,
    build_compress_messages,
    parse_compress_response,
)
from .compression_guard import CompressionGuard
from .graphiti_client import graphiti_search, _format_timeline_context
from .model_router import ModelRouter
_router = ModelRouter()

_MEMORY_MODEL_INTENTS = frozenset({
    "compress",
    "consolidate",
    "dreamer",
    "extract",
    "historian",
    "reflect",
    "scope",
})
_runtime_model_factory: Callable[[], Awaitable[Any]] | None = None
_runtime_mem0_llm_config: dict[str, Any] | None = None
_runtime_graph_llm_config: dict[str, Any] | None = None
_runtime_model_context_size: int | None = None
_runtime_model_signature = "environment"
_runtime_model_lock = threading.RLock()
_mem0_instance = None


def configure_runtime_memory_model(
    *,
    model_factory: Callable[[], Awaitable[Any]] | None = None,
    mem0_llm_config: dict[str, Any] | None = None,
    graph_llm_config: dict[str, Any] | None = None,
    context_size: int | None = None,
    signature: str = "environment",
) -> bool:
    """Install one process-wide model for memory-only LLM operations.

    Returns ``True`` when the effective selection changed. A change invalidates
    Mem0 because its provider client captures credentials during construction.
    """

    global _runtime_model_factory
    global _runtime_mem0_llm_config
    global _runtime_graph_llm_config
    global _runtime_model_context_size
    global _runtime_model_signature
    global _mem0_instance

    with _runtime_model_lock:
        changed = signature != _runtime_model_signature
        _runtime_model_factory = model_factory
        _runtime_mem0_llm_config = deepcopy(mem0_llm_config)
        _runtime_graph_llm_config = deepcopy(graph_llm_config)
        _runtime_model_context_size = context_size
        _runtime_model_signature = signature
        if changed:
            _mem0_instance = None
        return changed


def has_runtime_memory_model() -> bool:
    """Whether an explicit platform memory model is active."""

    with _runtime_model_lock:
        return _runtime_model_factory is not None


def get_runtime_graph_llm_config() -> dict[str, Any] | None:
    """Return a secret-bearing copy for optional graph integrations."""

    with _runtime_model_lock:
        return deepcopy(_runtime_graph_llm_config)


def get_runtime_memory_model_context_size() -> int | None:
    """Return the selected model's declared context window, when known."""

    with _runtime_model_lock:
        return _runtime_model_context_size

# Module-level compression guard instance
_compression_guard = CompressionGuard()


# ============================================================
# DobbyState — the single source of truth
# ============================================================

class DobbyState(dict):
    """LangGraph State for Dobby — the single source of truth (§3.1).

    Fields:
        messages: list — conversation history
        summary: str — compression summary
        tasks: dict — active task state
        thread_id: str — session identifier
        project_id: str — project isolation key
        current_role: str — last active agent role
        token_estimate: int — rough token count
        compression_count: int — number of compressions applied
        created_at: str — ISO timestamp

        # ── §3.1 Anti-compression fields ──
        decisions: list — key decisions this session (preserved after compression)
        context_to_preserve: str — user preferences/commitments (never discarded)

        # ── §3.3 Budget fields ──
        max_token_budget: int — window upper bound (default 200000)
        compression_trigger_ratio: float — trigger threshold (default 0.8)

        # ── §5 Knowledge base binding ──
        bound_knowledge_bases: list — WeKnora KB IDs bound to this session
        pinned_documents: list — user-pinned documents

        # ── Supervisor loop fields (§7) ──
        called_roles: list[str] — roles already invoked this turn
        iteration_count: int — current supervisor loop iteration
        max_cycles: int — hard iteration cap (default 10)

        # ── Parallel subset dispatch fields (§9) ──
        parallel_mode: bool — True when executing parallel multi-role dispatch
        parallel_routes: list[str] — roles dispatched in current parallel batch
        parallel_pending: list[str] — roles still awaiting completion
        parallel_responses: dict — {role_name: response_text} collected results

        # ── LLM Autonomous Context Scheduling fields ──
        last_compress_round: int — message round when last compression occurred
        message_count: int — current message counter
    """

    messages: Any
    summary: str
    tasks: dict
    thread_id: str
    project_id: str
    current_role: str
    token_estimate: int
    compression_count: int
    created_at: str
    decisions: list
    context_to_preserve: str
    max_token_budget: int
    compression_trigger_ratio: float
    bound_knowledge_bases: list
    pinned_documents: list
    called_roles: list
    iteration_count: int
    max_cycles: int
    parallel_mode: bool
    parallel_routes: list
    parallel_pending: list
    parallel_responses: dict
    last_compress_round: int
    message_count: int

    def __init__(
        self,
        messages=None,
        summary="",
        tasks=None,
        thread_id="",
        project_id="",
        current_role="",
        token_estimate=0,
        compression_count=0,
        created_at="",
        decisions=None,
        context_to_preserve="",
        max_token_budget=200000,
        compression_trigger_ratio=0.8,
        bound_knowledge_bases=None,
        pinned_documents=None,
        called_roles=None,
        iteration_count=0,
        max_cycles=10,
        parallel_mode=False,
        parallel_routes=None,
        parallel_pending=None,
        parallel_responses=None,
        last_compress_round=0,
        message_count=0,
        **kwargs,  # Accept ephemeral keys for forward compat
    ):
        super().__init__(
            messages=messages or [],
            summary=summary,
            tasks=tasks or {},
            thread_id=thread_id,
            project_id=project_id,
            current_role=current_role,
            token_estimate=token_estimate,
            compression_count=compression_count,
            created_at=created_at,
            decisions=decisions or [],
            context_to_preserve=context_to_preserve,
            max_token_budget=max_token_budget,
            compression_trigger_ratio=compression_trigger_ratio,
            bound_knowledge_bases=bound_knowledge_bases or [],
            pinned_documents=pinned_documents or [],
            called_roles=called_roles or [],
            iteration_count=iteration_count,
            max_cycles=max_cycles,
            parallel_mode=parallel_mode,
            parallel_routes=parallel_routes or [],
            parallel_pending=parallel_pending or [],
            parallel_responses=parallel_responses or {},
            last_compress_round=last_compress_round,
            message_count=message_count,
        )
        self.update(kwargs)


# ============================================================
# Shared helpers
# ============================================================

def _build_model(intent: str | None = None):
    """Build a fresh DeepSeekChatModel instance.

    Args:
        intent: 调用意图标识，由 _router.resolve() 选择 flash/pro。
                None → flash（向后兼容）。
    """
    from agentscope.model import DeepSeekChatModel
    from agentscope.credential import DeepSeekCredential

    model_name = _router.resolve(intent)

    return DeepSeekChatModel(
        credential=DeepSeekCredential(
            api_key=_cfg.DEEPSEEK_API_KEY,
            base_url=_cfg.DEEPSEEK_BASE_URL,
        ),
        model=model_name,
        context_size=_cfg.DEEPSEEK_CONTEXT_SIZE,
    )


async def _resolve_model(intent: str | None = None):
    """Resolve the dedicated memory model only for memory-owned work."""

    with _runtime_model_lock:
        factory = (
            _runtime_model_factory
            if intent in _MEMORY_MODEL_INTENTS
            else None
        )
    if factory is not None:
        return await factory()
    return _build_model(intent=intent)


async def _call_model(msgs: list, intent: str | None = None):
    """Call DeepSeekChatModel and return a single AssistantMsg.

    AgentScope v2 DeepSeekChatModel.__call__ returns an async generator
    of ChatResponse objects. Each chunk's content is a list of TextBlocks
    with CUMULATIVE text. We extract text from the last chunk only.

    IMPORTANT: The last chunk may contain multiple TextBlocks each with
    the full cumulative text. We take the FIRST block's text to avoid
    accidental concatenation duplicates.
    """
    from agentscope.message import AssistantMsg

    model = await _resolve_model(intent=intent)
    last_content = ""

    def _first_text(blocks) -> str:
        """Get first text block content (blocks are cumulative — first is enough)."""
        for block in blocks:
            if hasattr(block, "text"):
                return block.text
            elif isinstance(block, dict) and "text" in block:
                return block["text"]
        return ""

    try:
        result = model(msgs)

        if hasattr(result, '__aiter__'):
            # Async generator — streaming mode
            async for chunk in result:
                if hasattr(chunk, 'get') and chunk.get("is_last"):
                    last_content = _first_text(chunk.get("content", []))
                    break
                elif hasattr(chunk, 'content') and not last_content:
                    last_content = _first_text(getattr(chunk, 'content', []))

        elif hasattr(result, '__await__'):
            awaited = await result
            if hasattr(awaited, '__aiter__'):
                async for chunk in awaited:
                    if hasattr(chunk, 'get') and chunk.get("is_last"):
                        last_content = _first_text(chunk.get("content", []))
                        break
                    elif hasattr(chunk, 'content') and not last_content:
                        last_content = _first_text(getattr(chunk, 'content', []))
            elif hasattr(awaited, 'content'):
                last_content = _first_text(getattr(awaited, 'content', []))
            else:
                last_content = str(awaited)

        elif hasattr(result, 'content'):
            last_content = _first_text(getattr(result, 'content', []))

        else:
            last_content = str(result)

    except Exception:
        try:
            async for chunk in await model(msgs):
                if hasattr(chunk, 'get') and chunk.get("is_last"):
                    last_content = _first_text(chunk.get("content", []))
                    break
        except Exception:
            last_content = ""

    if not last_content:
        last_content = "(empty response)"

    return AssistantMsg("assistant", last_content)


async def _call_model_stream(msgs: list, intent: str | None = None):
    """Stream tokens from DeepSeekChatModel, yielding text as it arrives.

    Unlike _call_model which buffers and returns a single AssistantMsg,
    this async generator yields incremental text tokens for real-time
    streaming to the frontend.

    Handles the same response shapes as _call_model:
    - Async generator (streaming mode) → yield delta text
    - Awaitable → await then iterate or yield single result
    """
    model = await _resolve_model(intent=intent)

    def _extract_text(chunk) -> str:
        """Extract text from a ChatResponse chunk's content blocks."""
        content = None
        if hasattr(chunk, 'get'):
            content = chunk.get("content", [])
            if chunk.get("is_last"):
                return ""  # Skip final accumulated chunk
        elif hasattr(chunk, 'content'):
            content = getattr(chunk, 'content', [])
        if not content:
            return ""
        for block in content:
            if hasattr(block, "text") and block.text:
                return block.text
            elif isinstance(block, dict) and block.get("text"):
                return block["text"]
        return ""

    try:
        result = model(msgs)

        if hasattr(result, '__aiter__'):
            # Async generator — streaming mode
            async for chunk in result:
                text = _extract_text(chunk)
                if text:
                    yield text

        elif hasattr(result, '__await__'):
            awaited = await result
            if hasattr(awaited, '__aiter__'):
                async for chunk in awaited:
                    text = _extract_text(chunk)
                    if text:
                        yield text
            else:
                # Non-streaming fallback — yield entire text at once
                text = _extract_text(awaited)
                if text:
                    yield text
                elif hasattr(awaited, 'content'):
                    for block in getattr(awaited, 'content', []):
                        if hasattr(block, "text") and block.text:
                            yield block.text
                            break
                else:
                    s = str(awaited)
                    if s:
                        yield s
        elif hasattr(result, 'content'):
            for block in getattr(result, 'content', []):
                if hasattr(block, "text") and block.text:
                    yield block.text
                    break
        else:
            s = str(result)
            if s:
                yield s

    except Exception:
        pass  # Silent degradation — caller handles empty stream


async def _call_model_with_tools(
    msgs: list,
    tools: list[dict] | None = None,
    tool_executor=None,
    max_rounds: int = 5,
    intent: str | None = None,
):
    """Call model with function calling support (§2.4 enhanced).

    Runs up to `max_rounds` tool-calling iterations. On each round:
      1. Send messages + tools to LLM
      2. If LLM returns text → done, return response
      3. If LLM returns tool_calls → execute tools, append results, loop

    Falls back gracefully to plain text mode if the model doesn't support
    function calling or if the API returns an error.

    Args:
        msgs: context messages
        tools: OpenAI-format tool definitions
        tool_executor: async callable(tool_name, arguments) → str
        max_rounds: max tool-calling iterations
        intent: 调用意图标识，由 _router.resolve() 选择 flash/pro。
                None → flash（向后兼容）。

    Returns:
        AssistantMsg with the final text response
    """
    from agentscope.message import AssistantMsg, SystemMsg, UserMsg

    model = await _resolve_model(intent=intent)
    # DeepSeek API supports OpenAI-compatible tool calling
    # AgentScope v2 passes extra kwargs through to the underlying API
    model_kwargs = {"tools": tools, "tool_choice": "auto"}

    for round_num in range(max_rounds):
        try:
            last_content = ""
            tool_calls_raw = []

            async for chunk in await model(msgs, **model_kwargs):
                # ── Scan ALL chunks for tool_calls (may stream before is_last) ──
                if hasattr(chunk, 'get'):
                    tc = chunk.get("tool_calls") or chunk.get("tool_calls_raw")
                    if tc:
                        if isinstance(tc, list):
                            tool_calls_raw = tc
                        elif hasattr(tc, "model_dump"):
                            tool_calls_raw = tc.model_dump()
                        elif hasattr(tc, "__iter__"):
                            tool_calls_raw = list(tc)

                # ── Content extraction: same defensive pattern as _call_model ──
                if hasattr(chunk, 'get') and chunk.get("is_last"):
                    # Final chunk has cumulative complete text — overwrite, don't append
                    for block in chunk.get("content", []):
                        if hasattr(block, "text"):
                            last_content = block.text
                            break
                        elif isinstance(block, dict) and "text" in block:
                            last_content = block["text"]
                            break
                    break
                elif hasattr(chunk, 'content') and not last_content:
                    # Fallback: capture from first content-bearing chunk
                    for block in getattr(chunk, 'content', []):
                        if hasattr(block, "text"):
                            last_content = block.text
                            break
                        elif isinstance(block, dict) and "text" in block:
                            last_content = block["text"]
                            break

            # ── No tool calls → normal text response ──
            if not tool_calls_raw and last_content:
                return AssistantMsg("assistant", last_content)

            # ── Collect all content (may be partial) ──
            if not last_content:
                async for chunk in await model(msgs, **model_kwargs):
                    for block in chunk.get("content", []):
                        if hasattr(block, "text"):
                            last_content += block.text

            # ── Execute tool calls ──
            if tool_calls_raw:
                # Append the assistant's tool_call message
                assistant_msg = {
                    "role": "assistant",
                    "content": last_content or None,
                    "tool_calls": tool_calls_raw,
                }
                msgs.append(assistant_msg)

                for tc in tool_calls_raw:
                    fn = tc.get("function", tc)
                    tool_name = fn.get("name", "")
                    try:
                        arguments = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        arguments = {}

                    result = await tool_executor(
                        tool_name, arguments,
                        user_id="", agent_id="",
                        state=None, kb_names=None,
                    )

                    # Append tool result
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{round_num}"),
                        "content": result,
                    })

                continue  # Next round — model sees tool results
            else:
                # No tool calls in this round → done
                return AssistantMsg("assistant", last_content or "")

        except Exception:
            # Fallback: try plain call without tools
            try:
                return await _call_model(msgs, intent=intent)
            except Exception:
                return AssistantMsg("assistant", "")

    # Max rounds exceeded → force final response
    try:
        msgs.append(_make_system("已达到工具调用轮次上限，请基于已有信息给出最终回答。"))
        return await _call_model(msgs, intent=intent)
    except Exception:
        return AssistantMsg("assistant", last_content if last_content else "")


def _msg_content(msg) -> str:
    """Extract text content from any message object.

    AgentScope Msg.content can be: str, TextBlock, or list[TextBlock].
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


def _last_user_text(state: dict) -> str:
    """Extract the last user message text from state."""
    msgs = state.get("messages", [])
    for m in reversed(msgs):
        if hasattr(m, "role") and m.role == "user":
            return _msg_content(m)
        elif isinstance(m, dict) and m.get("role") == "user":
            return _msg_content(m)
    return ""


def _make_system(content: str) -> Any:
    """Create an AgentScope SystemMsg."""
    from agentscope.message import SystemMsg
    return SystemMsg("system", content)


def _make_user(content: str) -> Any:
    """Create an AgentScope UserMsg."""
    from agentscope.message import UserMsg
    return UserMsg("user", content)


def _normalize_user_message(raw: Any, source: str = "direct") -> dict:
    """Normalize a user message through the message adapter (§2.6).

    Returns a dict with:
        - msg: AgentScope UserMsg ready for the graph
        - source: message source identifier
        - sender_name: display name of sender
        - mentions: @mentioned users (if any)

    When source="direct", this is a transparent pass-through for
    existing Demo flows.
    """
    unified = MessageAdapter.normalize(raw, source=source)

    # Build context-enriched content
    parts = [unified.content]
    if unified.sender_name and source != "direct":
        parts.insert(0, f"[来自 {unified.sender_name} / {source}]")
    if unified.reply_to:
        parts.append(f"\n（回复消息 #{unified.reply_to}）")

    enriched = "".join(parts)
    msg = _make_user(enriched)

    return {
        "msg": msg,
        "source": unified.source,
        "sender_name": unified.sender_name,
        "sender_id": unified.sender_id,
        "mentions": unified.mentions,
        "timestamp": unified.timestamp,
        "attachments": unified.attachments,
    }


# ── Mem0 singleton — loaded once, reused across all nodes ──


def _build_mem0_config():
    """Build Mem0 config for pgvector — unified across all code paths.

    Supports three embedder providers based on EMBEDDING_PROVIDER env var:
      - "local"  → HuggingFace SentenceTransformer (offline, model cached)
      - "dashscope" → Alibaba DashScope (OpenAI-compatible API)
      - default  → DeepSeek API (OpenAI-compatible)
    """
    from mem0.configs.base import MemoryConfig as MC
    from mem0.vector_stores.configs import VectorStoreConfig

    provider = _cfg.EMBEDDING_PROVIDER

    # ── Embedder config ──
    if provider == "dashscope":
        embedder_config = {
            "provider": "openai",
            "config": {
                "model": _cfg.EMBEDDING_MODEL or "text-embedding-v4",
                "embedding_dims": _cfg.EMBEDDING_DIMS,
                "api_key": _cfg.EMBEDDING_API_KEY,
                "openai_base_url": _cfg.EMBEDDING_BASE_URL,
            },
        }
    elif provider == "local":
        embedder_config = {
            "provider": "huggingface",
            "config": {"model": _cfg.EMBEDDING_MODEL},
        }
    else:
        embedder_config = {
            "provider": "openai",
            "config": {
                "model": _cfg.EMBEDDING_MODEL,
                "embedding_dims": _cfg.EMBEDDING_DIMS,
                "api_key": _cfg.EMBEDDING_API_KEY,
                "openai_base_url": _cfg.EMBEDDING_BASE_URL,
            },
        }

    with _runtime_model_lock:
        runtime_llm = deepcopy(_runtime_mem0_llm_config)
    llm_config = runtime_llm or {
        "provider": "deepseek",
        "config": {
            "model": _cfg.DEEPSEEK_MODEL,
            "api_key": _cfg.DEEPSEEK_API_KEY,
            "deepseek_base_url": _cfg.DEEPSEEK_BASE_URL,
            "temperature": 0.1,
            "max_tokens": 2000,
        },
    }

    return MC(
        vector_store=VectorStoreConfig(
            provider="pgvector",
            config={
                "connection_string": _cfg.DATABASE_URL,
                "embedding_model_dims": _cfg.EMBEDDING_DIMS,
                "collection_name": _cfg.MEM0_COLLECTION,
            },
        ),
        llm=llm_config,
        embedder=embedder_config,
        version="v1.1",
        history_db_path=":memory:",
    )


def get_mem0():
    """Return the singleton Mem0 Memory instance (thread-safe, lazy-loaded).

    The embedding model is loaded once on first call and reused across
    all nodes, tools, and lifecycle tasks for the lifetime of the process.
    """
    global _mem0_instance
    if _mem0_instance is None:
        with _runtime_model_lock:
            if _mem0_instance is None:  # double-checked locking
                from mem0 import Memory as MM
                _mem0_instance = MM(_build_mem0_config())
    return _mem0_instance


async def _background_enrich_memory(
    content: str,
    user_id: str,
    agent_id: str,
    metadata: dict,
) -> None:
    """Fire-and-forget: enrich memory with LLM fact extraction in background.

    Uses the shared mem0 singleton to re-add the content with infer=True,
    which triggers mem0's internal LLM call for structured fact extraction.
    Failure is silent — the raw text is already stored and searchable.
    """
    import logging as _logging
    _log = _logging.getLogger("dobby.mem0.enrich")
    try:
        import asyncio as _asyncio
        m = get_mem0()
        await _asyncio.to_thread(
            m.add,
            content,
            user_id=user_id,
            agent_id=agent_id,
            metadata=metadata,
            infer=True,
        )
    except Exception:
        _log.debug("Background memory enrichment failed", exc_info=True)


def _build_weknora_client():
    """Build WeKnoraClient (lazy, Step 2 dependency)."""
    if not _cfg.WEKNORA_ENABLED:
        raise RuntimeError("WeKnora is not enabled")
    from .weknora_client import WeKnoraClient

    return WeKnoraClient(
        base_url=_cfg.WEKNORA_BASE_URL,
        api_key=_cfg.WEKNORA_API_KEY,
        timeout=(_cfg.WEKNORA_TIMEOUT_CONNECT, _cfg.WEKNORA_TIMEOUT_READ),
    )


# ── WeKnora KB ID cache — avoids list_knowledge_bases() on every search ──

_kb_cache: dict[str, str] = {}       # KB name → KB id
_kb_cache_ts: float = 0.0
_KBCACHE_TTL: float = 300.0           # 5 minute TTL


def _get_kb_id_by_name(name: str) -> str | None:
    """Get WeKnora KB ID by name, with 5-minute TTL cache.

    On cache miss or expiry, calls list_knowledge_bases() once
    and caches all KB name→id mappings. Returns None if not found.
    """
    import time
    now = time.monotonic()
    global _kb_cache, _kb_cache_ts
    if not _kb_cache or (now - _kb_cache_ts) > _KBCACHE_TTL:
        try:
            wc = _build_weknora_client()
            kb_list = wc.list_knowledge_bases()
            _kb_cache = {
                kb["name"]: kb["id"]
                for kb in kb_list
                if kb.get("name") and kb.get("id")
            }
            _kb_cache_ts = now
        except Exception:
            pass  # keep stale cache on transient error
    return _kb_cache.get(name)


def _warm_kb_cache() -> None:
    """Pre-warm the KB cache at startup. Non-fatal on failure."""
    try:
        _get_kb_id_by_name("")  # trigger cache population
    except Exception:
        pass


# ============================================================
# Node 1: supervisor — router
# ============================================================

# ── Dynamic supervisor prompt builder ──

_SUPERVISOR_BASE = """你是 Dobby 路由器。分析用户的意图，完成两项决策：
① 路由：选择需要参与回答的角色
② 记忆：判断是否需要检索长期记忆/知识库

## 可用角色:
{role_descriptions}

## 路由规则:
1. 简单问题选择 1 个角色，如 ["dobby_core"]
2. 跨领域问题选多个，如 ["safety_director", "pm", "inspector"]
3. 只选真正相关的角色，最多选 4 个
4. 无法确定时选 ["dobby_core"]

## 记忆检索指引:
系统已自动注入了基本上下文（<system-reminder> 中的内容）。
如果判断需要更多信息，角色可以使用以下工具：
- search_memory：搜索长期记忆（历史讨论、决策、偏好）
- search_knowledge_base：搜索工程规范标准
- search_experiences：搜索历史经验教训

**不需要检索的情况**：简单问候、闲聊、用户已提供全部信息的指令
**建议检索的情况**：需要规范引用、涉及历史决策、询问"之前怎么做的"

## 输出格式 — 严格JSON:
{{"routes": ["role1", "role2"], "need_retrieval": false, "reason": "简短理由"}}

只输出 JSON，不要其他文字。"""


def _build_supervisor_prompt(role_registry: dict) -> str:
    """Build a dynamic supervisor prompt from role registry.

    Args:
        role_registry: dict of {node_name: RoleConfig}
    """
    lines = []
    for node_name, cfg in role_registry.items():
        desc = getattr(cfg, "handoff_description", "") or getattr(cfg, "display", node_name)
        lines.append(f"- **{node_name}**: {desc}")

    return _SUPERVISOR_BASE.format(role_descriptions="\n".join(lines))


async def _generate_final_answer(state: dict) -> str:
    """Generate a synthesized final answer from accumulated context.

    Supports both sequential (legacy) and parallel (multi-role) modes.
    In parallel mode, uses __parallel_context__ for synthesis.
    """
    msgs = state.get("messages", [])
    query = state.get("__parallel_query__", "") or _last_user_text(state)
    parallel_context = state.get("__parallel_context__", "")

    if parallel_context:
        prompt = (
            "你是一个专业的工程管理助手。以下是多位专家角色针对用户问题的并行分析。"
            "请基于这些分析，给出一个综合性最终回答。"
            "结构清晰：先给出结论，再分点说明依据。"
            "如果各角色意见一致，直接汇总；如果存在分歧，明确指出。"
        )
        context = [
            _make_system(prompt),
            _make_system(f"用户问题: {query}"),
            _make_system(f"各角色分析:\n{parallel_context}"),
        ]
    else:
        prompt = (
            "你是一个专业的工程管理助手。以下是多位专家角色针对用户问题的分析。"
            "请基于这些分析，给出一个综合性最终回答。"
            "结构清晰：先给出结论，再分点说明依据。"
            "不要引入新的分析，只综合已有内容。"
        )
        context = [_make_system(prompt)]
        for m in msgs[-30:]:
            context.append(m)

    try:
        resp = await _call_model(context, intent="synthesize")
        return _msg_content(resp)
    except Exception:
        # Fallback: return the last assistant message
        for m in reversed(msgs):
            role = getattr(m, "role", "")
            if role == "assistant":
                content = _msg_content(m)
                if content:
                    return content
        return "处理完成，但无法生成汇总。请查看各角色详细分析。"


async def _generate_final_answer_stream(state: dict):
    """Streaming version of _generate_final_answer — yields tokens as they arrive.

    Builds the same synthesis context as _generate_final_answer but uses
    _call_model_stream to yield incremental text tokens for real-time display.
    """
    msgs = state.get("messages", [])
    query = state.get("__parallel_query__", "") or _last_user_text(state)
    parallel_context = state.get("__parallel_context__", "")

    if parallel_context:
        prompt = (
            "你是一个专业的工程管理助手。以下是多位专家角色针对用户问题的并行分析。"
            "请基于这些分析，给出一个综合性最终回答。"
            "结构清晰：先给出结论，再分点说明依据。"
            "如果各角色意见一致，直接汇总；如果存在分歧，明确指出。"
        )
        context = [
            _make_system(prompt),
            _make_system(f"用户问题: {query}"),
            _make_system(f"各角色分析:\n{parallel_context}"),
        ]
    else:
        prompt = (
            "你是一个专业的工程管理助手。以下是多位专家角色针对用户问题的分析。"
            "请基于这些分析，给出一个综合性最终回答。"
            "结构清晰：先给出结论，再分点说明依据。"
            "不要引入新的分析，只综合已有内容。"
        )
        context = [_make_system(prompt)]
        for m in msgs[-30:]:
            context.append(m)

    try:
        async for token in _call_model_stream(context):
            yield token
    except Exception:
        # Fallback: yield the last assistant message content
        for m in reversed(msgs):
            role = getattr(m, "role", "")
            if role == "assistant":
                content = _msg_content(m)
                if content:
                    yield content
                    return
        yield "处理完成，但无法生成汇总。请查看各角色详细分析。"


async def _force_finish(state: dict) -> Command:
    """Force termination: generate final answer and route to END."""
    from agentscope.message import AssistantMsg

    final_answer = await _generate_final_answer(state)
    return Command(
        goto=END,
        update={
            "messages": state.get("messages", []) + [AssistantMsg("assistant", final_answer)],
            "current_role": "supervisor",
        },
    )


async def supervisor_node(state: dict) -> Command:
    """Supervisor router — parallel subset dispatch (§9).

    Single call to LLM to determine which roles are needed, then:
    - Single role → Command(goto=role) fast path (sequential, no overhead)
    - Multi-role → parallel dispatch, collect results, synthesize final answer
    - Detects parallel completion via parallel_pending tracking
    - Detects sequential completion when called_roles is non-empty (role returned via loop)
    """
    import asyncio

    msgs = state.get("messages", [])
    query = _last_user_text(state)
    iteration = state.get("iteration_count", 0)
    max_cycles = state.get("max_cycles", 10)
    role_registry = _current_role_registry
    token_est = estimate_tokens(msgs)

    # ── 0. New turn detection: reset routing state on fresh user message ──
    if msgs and getattr(msgs[-1], "role", "") == "user":
        state["called_roles"] = []
        state["iteration_count"] = 0
        state["parallel_mode"] = False
        state["parallel_pending"] = []
        state["parallel_responses"] = {}
        iteration = 0

    # ── 0a. Parallel completion check: all roles finished? ──
    if state.get("parallel_mode"):
        pending = state.get("parallel_pending", [])
        if not pending:
            # All parallel roles complete → synthesize final answer
            parallel_responses = state.get("parallel_responses", {})
            routes = state.get("parallel_routes", [])
            context_parts = []
            for role_name in routes:
                text = parallel_responses.get(role_name, "")
                if text:
                    context_parts.append(f"【{role_name}】\n{text}")
            if context_parts:
                state["__parallel_context__"] = "\n\n---\n\n".join(context_parts)
                state["__parallel_query__"] = query
            return await _force_finish(state)
        else:
            # Still waiting for other roles — pass through (this branch is done)
            return Command(goto=END, update={"current_role": "supervisor"})

    # ── 0b. Sequential completion: role returned via loop edge → auto-finish ──
    called_roles = state.get("called_roles", [])
    if called_roles and iteration > 0:
        # A single role was dispatched and has now completed.
        # For single-role routing, skip synthesis — return role's response directly.
        last_msg = None
        for m in reversed(msgs):
            role = getattr(m, "role", "")
            if role == "assistant":
                last_msg = m
                break

        # ── Quality recording for compression guard ──
        if last_msg:
            content = _msg_content(last_msg)
            from .compression_guard import QualityScorer
            qs = QualityScorer.score_reply(content)
            guard_update = _compression_guard.record_quality(state, qs.score)
            state.update(guard_update)

        if last_msg:
            return Command(
                goto=END,
                update={
                    "current_role": "supervisor",
                    "called_roles": called_roles,
                },
            )
        # Fallback: synthesize if no assistant message found
        return await _force_finish(state)

    # ── 0b. Guard: no role registry ──
    if not role_registry:
        return await _force_finish(state)

    # ── 1. Hard cap: force FINISH ──
    if iteration >= max_cycles:
        try:
            await get_audit_logger().log_message(
                "system", f"Max cycles ({max_cycles}) reached, forcing FINISH",
                session_id=state.get("thread_id", ""),
                project_id=state.get("project_id", ""),
                role="supervisor",
            )
        except Exception:
            pass
        return await _force_finish(state)

    # ── 2. Compression check ──
    if needs_compression(msgs):
        return Command(
            goto="compress_node",
            update={
                "token_estimate": token_est,
                "current_role": "supervisor",
            },
        )

    # ── 3. No user input → default to dobby_core ──
    if not query:
        return Command(
            goto="dobby_core",
            update={
                "token_estimate": token_est,
                "current_role": "supervisor",
            },
        )

    # ── 4. LLM routing decision (multi-role output) ──
    prompt = _build_supervisor_prompt(role_registry)

    routes = ["dobby_core"]
    try:
        resp = await _call_model([
            _make_system(prompt),
            _make_user(query),
        ], intent="routing")
        content = _msg_content(resp).strip()

        # Parse JSON (with markdown fence tolerance)
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            content = "\n".join(lines).strip()
        data = json.loads(content)
        routes = data.get("routes", ["dobby_core"])
    except Exception:
        routes = ["dobby_core"]

    # ── 5. Validate routes ──
    valid_routes = [r for r in routes if r in role_registry]
    # Deduplicate while preserving order
    seen = set()
    valid_routes = [r for r in valid_routes if not (r in seen or seen.add(r))]
    if not valid_routes:
        valid_routes = ["dobby_core"]

    # ── 6. Single role: fast path (sequential, no parallel overhead) ──
    if len(valid_routes) == 1:
        return Command(
            goto=valid_routes[0],
            update={
                "token_estimate": token_est,
                "iteration_count": iteration + 1,
                "called_roles": list(set(state.get("called_roles", [])) | {valid_routes[0]}),
                "current_role": "supervisor",
            },
        )

    # ── 7. Multi-role: parallel dispatch ──
    # Run all selected roles in parallel, collect results
    parallel_responses = {}
    all_new_messages = list(msgs)

    async def _run_role(role_name: str):
        """Run a single role node and return (role_name, result_dict)."""
        node_fn = _role_nodes.get(role_name)
        if not node_fn:
            return role_name, None
        try:
            # Each role gets a copy of the state at dispatch time
            role_state = dict(state)
            role_state["parallel_mode"] = True
            role_state["parallel_routes"] = valid_routes
            role_state["parallel_pending"] = list(valid_routes)
            result = await node_fn(role_state)
            return role_name, result
        except Exception as e:
            try:
                await get_audit_logger().log_message(
                    "system", f"Parallel role '{role_name}' failed: {e}",
                    session_id=state.get("thread_id", ""),
                    project_id=state.get("project_id", ""),
                    role="supervisor",
                )
            except Exception:
                pass
            return role_name, None

    # Dispatch all roles in parallel
    tasks = [_run_role(name) for name in valid_routes]
    results = await asyncio.gather(*tasks)

    # Collect results
    for role_name, result in results:
        if isinstance(result, dict):
            role_msgs = result.get("messages", [])
            # Extend with new messages (parallel mode returns only [response])
            all_new_messages.extend(role_msgs)
            # Merge parallel_responses from role node
            role_responses = result.get("parallel_responses", {})
            if role_responses:
                parallel_responses.update(role_responses)
        else:
            parallel_responses[role_name] = f"[{role_name} 未能生成回复]"

    # Build parallel context for synthesis
    context_parts = []
    for role_name in valid_routes:
        text = parallel_responses.get(role_name, "")
        if text:
            context_parts.append(f"【{role_name}】\n{text}")
    parallel_context = "\n\n---\n\n".join(context_parts)

    # Generate final answer from parallel results
    from agentscope.message import AssistantMsg

    state["messages"] = all_new_messages
    state["__parallel_context__"] = parallel_context
    state["__parallel_query__"] = query

    # ── Deferred synthesis: skip LLM call, let caller stream it ──
    if state.get("__defer_synthesis__"):
        return Command(
            goto=END,
            update={
                "messages": all_new_messages,
                "current_role": "supervisor",
                "parallel_responses": parallel_responses,
                "__parallel_context__": parallel_context,
                "__parallel_query__": query,
                "__synthesis_pending__": True,
            },
        )

    final_answer = await _generate_final_answer(state)

    return Command(
        goto=END,
        update={
            "messages": all_new_messages + [AssistantMsg("assistant", final_answer)],
            "current_role": "supervisor",
            "parallel_responses": parallel_responses,
        },
    )

# ============================================================
# Node 2: compress_node — summary generation
# ============================================================

async def compress_node(state: dict) -> dict:
    """Generate summary and trim messages when token budget exceeded."""
    msgs = state.get("messages", [])
    old_summary = state.get("summary", "")
    old_tasks = state.get("tasks", {})

    # ── Guard check: should we actually compress? ──
    decision = _compression_guard.decide(msgs, state)

    if decision.action == "skip":
        return {
            "messages": msgs,
            "summary": old_summary,
            "tasks": old_tasks,
            "token_estimate": state.get("token_estimate", 0),
            "compression_count": state.get("compression_count", 0),
            "last_compress_round": state.get("last_compress_round", 0),
            "current_role": "compress_node",
        }

    if decision.action == "reset":
        # Clear summary, keep only system + last 10 messages + tasks
        from .message_adapter import UnifiedMessage

        system_msgs = [m for m in msgs if isinstance(m, UnifiedMessage) and getattr(m, "role", "") == "system"][:1]
        non_system_msgs = [m for m in msgs if not (isinstance(m, UnifiedMessage) and getattr(m, "role", "") == "system")]
        state["summary"] = ""
        state["messages"] = system_msgs + non_system_msgs[-10:]
        state["compression_count"] = state.get("compression_count", 0) + 1
        state["last_compress_round"] = state.get("message_count", 0)
        guard_update = _compression_guard.on_reset(state)
        state.update(guard_update)
        return {
            "messages": state["messages"],
            "summary": "",
            "tasks": old_tasks,
            "compression_count": state["compression_count"],
            "last_compress_round": state["last_compress_round"],
            "token_estimate": estimate_tokens(state["messages"]),
            "current_role": "compress_node",
        }

    if decision.action == "trim_only":
        # Keep last 20 messages, reuse existing summary
        trimmed = trim_messages(msgs)
        state["messages"] = trimmed
        state["token_estimate"] = estimate_tokens(trimmed)
        state["compression_count"] = state.get("compression_count", 0) + 1
        state["last_compress_round"] = state.get("message_count", 0)
        return {
            "messages": trimmed,
            "summary": old_summary,
            "tasks": old_tasks,
            "token_estimate": state["token_estimate"],
            "compression_count": state["compression_count"],
            "last_compress_round": state["last_compress_round"],
            "current_role": "compress_node",
        }

    # Build compression prompt
    compress_msgs = build_compress_messages(
        existing_summary=old_summary,
        existing_tasks=old_tasks,
        recent_messages=msgs,
    )

    # ── LLMLingua-2 fast compression (pre-processing, §2.1) ──
    if getattr(_cfg, "COMPRESSION_ENGINE", "llm") == "llmlingua2":
        try:
            from .llmlingua_compressor import compress_via_llmlingua

            # Rapid token-level compression before LLM summarization
            msgs = await compress_via_llmlingua(
                msgs,
                ratio=getattr(_cfg, "LLMLINGUA2_RATIO", 0.5),
                protected_roles={"system", "user"},
            )
        except Exception:
            pass  # Silent fallback to LLM-only compression

    # LLM compression (primary engine, or post-LLMLingua summarization)
    try:
        resp = await _call_model(compress_msgs, intent="compress")
        content = _msg_content(resp)
        parsed = parse_compress_response(content)
    except Exception:
        parsed = {"summary": old_summary, "tasks": old_tasks}

    new_summary = parsed.get("summary", old_summary)
    new_tasks = parsed.get("tasks", old_tasks)
    new_decisions = parsed.get("decisions", state.get("decisions", []))
    new_context_to_preserve = parsed.get("context_to_preserve", state.get("context_to_preserve", ""))

    if not new_tasks:
        new_tasks = old_tasks

    # Trim messages
    trimmed = trim_messages(msgs)
    new_token_est = estimate_tokens(trimmed)

    # ── Audit log: compression ──
    try:
        before_tokens = estimate_tokens(msgs)
        await get_audit_logger().log_compress(
            before_tokens=before_tokens,
            after_tokens=new_token_est,
            summary_preview=new_summary[:200] if new_summary else "",
            session_id=state.get("thread_id", ""),
            project_id=state.get("project_id", ""),
            compression_count=state.get("compression_count", 0) + 1,
        )
    except Exception:
        pass

    # ── P0-2: Launch async historian (fire-and-forget, non-blocking) ──
    _historian_result = {}
    if getattr(_cfg, "COMPRESSION_BACKGROUND", False):
        try:
            from .historian import historian_cycle

            # Clone minimal state for historian (avoids mutating live state)
            historian_state = {
                "messages": msgs,
                "_compartments": state.get("_compartments", []),
                "summary": new_summary,
                "max_token_budget": state.get(
                    "max_token_budget",
                    _cfg.MAX_TOKEN_BUDGET,
                ),
                "historian_trigger_ratio": state.get(
                    "historian_trigger_ratio",
                    0.3,
                ),
            }
            # Fire-and-forget: don't await, let it run in background
            _historian_task = asyncio.create_task(
                historian_cycle(historian_state)
            )
            try:
                _historian_result = await asyncio.wait_for(
                    _historian_task, timeout=3.0,
                ) or {}
            except asyncio.TimeoutError:
                _historian_result = {}  # historian still running, don't block
        except Exception:
            pass

    # ── Guard: record successful compression (session-level state update) ──
    guard_update = _compression_guard.on_compress(state)
    state.update(guard_update)

    # ── Quality: score the compression summary ──
    try:
        from .compression_guard import QualityScorer, verify_anchors
        summary_quality = QualityScorer.score_summary(
            new_summary, old_tasks, new_tasks,
            state.get("decisions", []),
            state.get("context_to_preserve", ""),
        )
        qual_update = _compression_guard.record_quality(state, summary_quality.score)
        state.update(qual_update)

        # Anchor verification log
        anchor_report = verify_anchors(
            new_summary, new_tasks,
            state.get("decisions", []),
            state.get("context_to_preserve", ""),
        )
        try:
            await get_audit_logger().log_message(
                "system",
                f"Compression anchor check: {anchor_report.preserved}/{anchor_report.total_anchors} "
                f"preserved, verdict={anchor_report.verdict}, quality={summary_quality.score:.3f}",
                session_id=state.get("thread_id", ""),
                project_id=state.get("project_id", ""),
                role="compress_node",
            )
        except Exception:
            pass
    except Exception:
        pass  # quality scoring is advisory — never block compression

    result = {
        "summary": new_summary,
        "tasks": new_tasks,
        "decisions": new_decisions,
        "context_to_preserve": new_context_to_preserve,
        "messages": trimmed,
        "token_estimate": new_token_est,
        "compression_count": state.get("compression_count", 0) + 1,
        "last_compress_round": state.get("message_count", 0),
        "current_role": "compress_node",
        # ── Session-level guard state (persisted via PostgresSaver) ──
        "_guard_compress_count": state.get("_guard_compress_count", 0),
        "_guard_quality_scores": state.get("_guard_quality_scores", []),
    }

    # Merge historian result if available
    if _historian_result.get("_compartments"):
        result["_compartments"] = _historian_result["_compartments"]

    return result


# ============================================================
# Node 3: safety_director — safety standards queries
# ============================================================

SAFETY_DIRECTOR_PROMPT = """你是 Dobby 安全总监（Safety Director）。

**职责**:
- 查询和解读工程安全规范、标准、法规
- 引用具体规范编号（如 JGJ 80-2016 §4.2、GB 50656-2011 §5.3）
- 结合检索到的规范内容给出权威、可操作的指导
- 如规范未覆盖用户问题，诚实说明并建议查阅途径

**风格**:
- 专业、权威、有据可查
- 先给出结论，再引用规范条款作为依据
- 必要时提供对比分析（不同规范对同一问题的要求）"""


async def safety_director_node(state: dict) -> dict:
    """Handle safety standards queries via WeKnora hybrid search."""
    query = _last_user_text(state)
    msgs = state.get("messages", [])
    summary = state.get("summary", "")

    # 1. WeKnora search
    kb_results = []
    try:
        kb_id = _get_kb_id_by_name(_cfg.WEKNORA_KB_NAME)
        if kb_id:
            wc = _build_weknora_client()
            kb_results = wc.hybrid_search(
                kb_id=kb_id,
                query=query,
                vector_threshold=0.15,
                keyword_threshold=0.15,
            )
    except Exception as e:
        kb_results = [{"content": f"(WeKnora 检索失败: {e})", "score": 0}]

    # 2. Format KB results
    kb_text = ""
    for i, r in enumerate(kb_results[:5], 1):
        content = r.get("content", str(r))
        score = r.get("score", 0)
        kb_text += f"\n[规范{i}] (score={score:.3f})\n{content[:800]}\n"

    # 3. Build context messages
    context_msgs = [_make_system(SAFETY_DIRECTOR_PROMPT)]

    if summary:
        context_msgs.append(_make_system(f"[会话摘要]\n{summary}"))

    # Graphiti timeline search
    project_id = state.get("project_id", "")
    graphiti_text = ""
    if query and project_id:
        try:
            timeline_data = await graphiti_search(project_id, query)
            if timeline_data.get("timeline") or timeline_data.get("active_risks"):
                graphiti_text = _format_timeline_context(timeline_data)
        except Exception:
            pass

    # ── Assemble <system-reminder> trusted channel (§7.2) ──
    reminder_parts = []
    if kb_text:
        reminder_parts.append(f"【知识库 — 规范标准】\n{kb_text}")
    if graphiti_text:
        reminder_parts.append(graphiti_text)

    if reminder_parts:
        reminder = "<system-reminder>\n" + "\n".join(reminder_parts) + "\n</system-reminder>"
        context_msgs.append(_make_system(reminder))

    for m in msgs[-20:]:
        context_msgs.append(m)

    # 4. LLM call
    response = await _call_model(context_msgs, intent="synthesize")

    return {
        "messages": msgs + [response],  # accumulate, not replace
        "current_role": "safety_director",
    }


# ============================================================
# Node 4: dobby_core — general dialogue + memory
# ============================================================

DOBBY_CORE_PROMPT = """你是 Dobby，工程管理 AI 助手。

**职责**:
- 回答工程管理相关问题
- 查询和管理项目任务、进度、整改状态
- 记录重要决策、事实到长期记忆
- 协调各方资源和信息

**重要原则**:
- 回答必须基于 <system-reminder> 中提供的实际数据
- 如果 <system-reminder> 显示「暂无相关记录」或没有匹配的记忆，请友好地告知用户这是首次对话，尚无存储数据，引导用户分享项目背景信息，不得编造任何不存在的数据
- 绝不能虚构风险编号、人名、时间、金额等具体信息
- 引用历史记忆时注明来源

**风格**:
- 友好、务实、有条理
- 任务管理使用明确的优先级和状态
- 当用户询问安全规范时，建议切换到安全总监

**可用能力**:
- 长期记忆：跨会话记住项目发生过的事实和决策
- 任务管理：跟踪整改项、里程碑、责任人"""


async def dobby_core_node(state: dict) -> dict:
    """Handle general queries with Mem0 memory retrieval."""
    import concurrent.futures

    query = _last_user_text(state)
    msgs = state.get("messages", [])
    summary = state.get("summary", "")

    # 1. Mem0 memory search (scoped by project_id)
    mem0_results = []
    try:
        _proj_id = state.get("project_id") or _cfg.MEM0_USER_ID
        def _sync_search():
            m = get_mem0()
            return m.search(
                query,
                filters={"user_id": _proj_id, "agent_id": _proj_id},
                top_k=5,
                threshold=0.3,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            mem0_results = pool.submit(_sync_search).result(timeout=30)
    except Exception:
        mem0_results = []

    # 2a. Apply recency decay to search results (Step 4)
    # Mem0 2.x returns {"results": [...]} — unwrap before sorting
    if isinstance(mem0_results, dict) and "results" in mem0_results:
        mem0_results = mem0_results["results"]
    if not isinstance(mem0_results, list):
        mem0_results = []

    if mem0_results:
        from datetime import datetime, timezone as _dt_tz
        _now = datetime.now(_dt_tz.utc)
        def _decayed_score(r):
            if not isinstance(r, dict):
                return 0
            base = float(r.get("score", 0))
            ts_str = r.get("created_at") or r.get("updated_at", "")
            try:
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                age_days = (_now - dt).total_seconds() / 86400.0
                recency = 0.5 ** (age_days / _cfg.RECENCY_HALF_LIFE_DAYS)
            except Exception:
                recency = 0.5
            return base * _cfg.RELEVANCE_WEIGHT + recency * _cfg.RECENCY_WEIGHT

        try:
            mem0_results = sorted(mem0_results, key=_decayed_score, reverse=True)
        except Exception:
            pass  # keep original order if sorting fails

    # 3. Format memory results (already unwrapped from {"results": [...]} above)
    mem_text = ""
    for i, r in enumerate(mem0_results[:5], 1):
        if isinstance(r, dict):
            text = r.get('memory', '') or r.get('data', '') or ''
            if text:
                mem_text += f"\n[记忆{i}] {text}\n"
        else:
            mem_text += f"\n[记忆{i}] {r}\n"

    # 2b. Graphiti timeline search
    project_id = state.get("project_id", "")
    if query and project_id:
        try:
            timeline_data = await graphiti_search(project_id, query)
            if timeline_data.get("timeline") or timeline_data.get("active_risks"):
                graphiti_text = _format_timeline_context(timeline_data)
        except Exception:
            graphiti_text = ""
    else:
        graphiti_text = ""

    # 4. Build context messages
    context_msgs = [_make_system(DOBBY_CORE_PROMPT)]

    if summary:
        context_msgs.append(_make_system(f"[会话摘要]\n{summary}"))

    # ── Assemble <system-reminder> trusted channel (§7.2) ──
    reminder_parts = []
    if mem_text:
        reminder_parts.append(f"【长期记忆 — 项目历史】\n{mem_text}")
    else:
        reminder_parts.append("【长期记忆 — 项目历史】\n暂无相关记录（首次对话或该项目尚未存储记忆）。请引导用户提供项目背景信息。")
    if graphiti_text:
        reminder_parts.append(graphiti_text)

    reminder = "<system-reminder>\n" + "\n".join(reminder_parts) + "\n</system-reminder>"
    context_msgs.append(_make_system(reminder))

    for m in msgs[-20:]:
        context_msgs.append(m)

    # 5. LLM call
    response = await _call_model(context_msgs, intent="respond")

    # 6. Async memory write (scoped by project_id)
    try:
        _proj_id = state.get("project_id") or _cfg.MEM0_USER_ID
        def _sync_add():
            m = get_mem0()
            m.add(query, user_id=_proj_id, agent_id=_proj_id,
                   infer=_cfg.MEM0_INFER_ENABLED)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_sync_add).result(timeout=15)
    except Exception:
        pass

    return {
        "messages": msgs + [response],  # accumulate, not replace
        "current_role": "dobby_core",
    }


# ============================================================
# Dynamic role node factory (Step 5)
# ============================================================

def build_role_node(role_config):
    """Build a LangGraph node function from a role configuration.

    role_config should have attributes:
      - name: str (node name, e.g. "safety_director")
      - display: str (human-readable name)
      - system_prompt: str
      - tools: list[str] (e.g. ["search_memory", "search_knowledge", "add_memory", "delegate_task"])
      - tool_mode: str — "inject" (pre-injected context, no tool calling) or
          "native" (LLM can actively call tools via function calling). Default "native".
      - mem0_agent_id: str (Mem0 agent isolation key)
      - weknora_kb_ids: list[str] | None (WeKnora KB names to bind)
    """
    import concurrent.futures

    role_name = getattr(role_config, "name", "unknown")
    system_prompt = getattr(role_config, "system_prompt", "")
    tools = getattr(role_config, "tools", [])
    mem0_agent_id = getattr(role_config, "mem0_agent_id", f"role:{role_name}")
    weknora_kb_ids = getattr(role_config, "weknora_kb_ids", None)
    tool_mode = getattr(role_config, "tool_mode", "inject")  # "inject" | "native"

    has_mem0 = "search_memory" in tools or "add_memory" in tools
    has_weknora = "search_knowledge" in tools
    has_delegate = "delegate_task" in tools

    async def _role_node(state: dict) -> dict:
        """Auto-generated role node for {display}."""
        query = _last_user_text(state)
        msgs = state.get("messages", [])
        summary = state.get("summary", "")
        tasks = state.get("tasks", {})
        project_id = state.get("project_id", "")
        thread_id = state.get("thread_id", "")

        # ── Skill event capture state (§10) ──
        _captured_tool_names: list[str] = []

        # ── Audit log: user message ──
        if query:
            try:
                await get_audit_logger().log_message(
                    "user", query,
                    session_id=thread_id, project_id=project_id,
                    role=role_name,
                )
            except Exception:
                pass

        context_msgs = [
            _make_system(
                "⚠️ **核心约束（优先级最高）**\n"
                "你的回答必须严格基于 <system-reminder> 中提供的实际数据。\n"
                "- 如果 <system-reminder> 显示「暂无相关记录」，请友好地告知用户这是首次对话或新项目，\n"
                "  尚无存储数据，并主动介绍你能提供的帮助（记录项目信息、查询规范、跟踪任务等），\n"
                "  引导用户先分享项目背景、当前进度或遇到的问题。\n"
                "- **绝对禁止**编造任何不存在的风险、问题、人名、规范编号、时间等具体信息。\n"
                "- **绝对禁止**列出「常见隐患」「典型问题」「基于经验推测」等未经验证的清单。\n"
                "以下为你的角色定义："
            ),
            _make_system(system_prompt),
        ]

        # ── Native mode: inject tool usage guidance (§2.4) ──
        if tool_mode == "native":
            from .roles import _NATIVE_TOOL_GUIDANCE
            context_msgs.append(_make_system(_NATIVE_TOOL_GUIDANCE))

        # Inject summary
        if summary:
            context_msgs.append(_make_system(f"[会话摘要]\n{summary}"))

        # Inject tasks if present
        if tasks and has_mem0:
            tasks_text = json.dumps(tasks, ensure_ascii=False, indent=2)
            if len(tasks_text) > 2000:
                tasks_text = tasks_text[:2000] + "..."
            context_msgs.append(_make_system(f"[活跃任务]\n{tasks_text}"))

        # ── Mem0 memory search ──
        if has_mem0 and query:
            mem0_results = []
            try:
                user_id = project_id or _cfg.MEM0_USER_ID
                def _sync_search():
                    m = get_mem0()
                    return m.search(
                        query,
                        filters={"user_id": user_id, "agent_id": user_id},
                        top_k=_cfg.MEMORY_TOP_K,
                        threshold=0.3,
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    mem0_results = pool.submit(_sync_search).result(timeout=30)
            except Exception:
                mem0_results = []

            # Apply recency decay (Step 4)
            # Mem0 2.x returns {"results": [...]} — unwrap before sorting
            if isinstance(mem0_results, dict) and "results" in mem0_results:
                mem0_results = mem0_results["results"]
            if not isinstance(mem0_results, list):
                mem0_results = []

            if mem0_results:
                from datetime import datetime, timezone as _dt_tz
                _now = datetime.now(_dt_tz.utc)
                def _decayed_score(r):
                    if not isinstance(r, dict):
                        return 0
                    base = float(r.get("score", 0))
                    ts_str = r.get("created_at") or r.get("updated_at", "")
                    try:
                        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                        age_days = (_now - dt).total_seconds() / 86400.0
                        recency = 0.5 ** (age_days / _cfg.RECENCY_HALF_LIFE_DAYS)
                    except Exception:
                        recency = 0.5
                    return base * _cfg.RELEVANCE_WEIGHT + recency * _cfg.RECENCY_WEIGHT

                try:
                    mem0_results = sorted(mem0_results, key=_decayed_score, reverse=True)
                except Exception:
                    pass

            # Format memory results (already unwrapped from {"results": [...]} above)
            mem_text = ""
            for i, r in enumerate(mem0_results[:_cfg.MEMORY_TOP_K], 1):
                if isinstance(r, dict):
                    text = r.get('memory', '') or r.get('data', '') or ''
                    if text:
                        mem_text += f"\n[记忆{i}] {text}\n"
                else:
                    mem_text += f"\n[记忆{i}] {r}\n"

        # ── WeKnora KB search ──
        kb_text = ""
        if has_weknora and query and weknora_kb_ids:
            try:
                wc = _build_weknora_client()
                for kb_name in weknora_kb_ids:
                    kb_id = _get_kb_id_by_name(kb_name)
                    if kb_id:
                        results = wc.hybrid_search(
                            kb_id=kb_id,
                            query=query,
                            vector_threshold=0.15,
                            keyword_threshold=0.15,
                        )
                        for j, r in enumerate(results[:3], 1):
                            content = r.get("content", str(r))
                            kb_text += f"\n[{kb_name} #{j}] {content[:600]}\n"
            except Exception:
                pass

        # ── 🆕 Graphiti timeline search ──
        has_graphiti = "search_timeline" in tools
        graphiti_text = ""
        if has_graphiti and query:
            try:
                timeline_data = await graphiti_search(project_id, query)
                if timeline_data.get("timeline") or timeline_data.get("active_risks"):
                    graphiti_text = _format_timeline_context(timeline_data)
            except Exception:
                pass  # Silent degradation

        # ── Assemble <system-reminder> trusted channel (§7.2) ──
        reminder_parts = []
        if mem_text:
            reminder_parts.append(f"【长期记忆 — 项目历史】\n{mem_text}")
        else:
            reminder_parts.append("【长期记忆 — 项目历史】\n暂无相关记录（首次对话或该项目尚未存储记忆）。请引导用户提供项目背景信息，以便后续对话提供更精准的回答。")
        if kb_text:
            reminder_parts.append(f"【知识库 — 规范标准】\n{kb_text}")
        if graphiti_text:
            reminder_parts.append(graphiti_text)

        reminder = "<system-reminder>\n" + "\n".join(reminder_parts) + "\n</system-reminder>"
        context_msgs.append(_make_system(reminder))

        # ── Recent messages ──
        for m in msgs[-20:]:
            context_msgs.append(m)

        # ── LLM call (inject mode) ──
        if tool_mode == "inject" or not tools:
            response = await _call_model(context_msgs, intent="respond")
        else:
            # ── LLM call (native tool calling mode) ──
            from .memory_tools import TOOL_SCHEMAS, execute_tool

            # Build tool schemas matching this role's configured tools
            active_schemas = [t for t in TOOL_SCHEMAS
                             if t["function"]["name"] in tools]

            async def _executor(name, args, **ctx):
                nonlocal _captured_tool_names
                try:
                    result = await execute_tool(
                        name, args,
                        user_id=project_id or _cfg.MEM0_USER_ID,
                        agent_id=project_id or _cfg.MEM0_USER_ID,  # ← shared project pool
                        state=state,
                        kb_names=weknora_kb_ids,
                    )
                    _captured_tool_names.append(name)
                    return result
                except Exception as tool_err:
                    # ── Record tool error (§10) ──
                    try:
                        from .skill_events import record_tool_error as _rte
                        import asyncio as _asyncio
                        _asyncio.create_task(_rte(
                            project_id=project_id,
                            role_id=role_name,
                            tool_name=name,
                            error_message=str(tool_err)[:2000],
                        ))
                    except Exception:
                        pass
                    raise

            response = await _call_model_with_tools(
                context_msgs,
                tools=active_schemas,
                tool_executor=_executor,
                max_rounds=5,
                intent="respond",
            )

            # ── Record success pattern (§10) ──
            distinct_tools = list(dict.fromkeys(_captured_tool_names))
            if len(distinct_tools) >= 3:
                try:
                    from .skill_events import record_success_pattern as _rsp
                    import asyncio as _asyncio
                    _asyncio.create_task(_rsp(
                        project_id=project_id,
                        role_id=role_name,
                        tool_sequence=distinct_tools,
                        tool_count=len(_captured_tool_names),
                    ))
                except Exception:
                    pass

        # ── Async memory write (scoped to project, shared across roles) ──
        if has_mem0 and "add_memory" in tools and query:
            try:
                user_id = project_id or _cfg.MEM0_USER_ID
                if _cfg.MEM0_INFER_ENABLED and _cfg.MEM0_INFER_ASYNC:
                    # Fire-and-forget: enrich memory in background, don't block response
                    import asyncio as _asyncio
                    _asyncio.create_task(
                        _background_enrich_memory(
                            query, user_id, user_id,
                            {"memory_type": "interaction", "importance": 0.5, "role": role_name},
                        )
                    )
                else:
                    def _sync_add():
                        m = get_mem0()
                        m.add(
                            query,
                            user_id=user_id,
                            agent_id=user_id,
                            metadata={"memory_type": "interaction",
                                       "importance": 0.5,
                                       "role": role_name},
                            infer=_cfg.MEM0_INFER_ENABLED,
                        )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(_sync_add).result(timeout=15)
            except Exception:
                pass

        # ── Detect user correction for skill compilation (§10) ──
        if query and hasattr(response, "content"):
            try:
                from .skill_compiler import _extract_correction_rule as _ecr
                correction_rule = _ecr(query)
                if correction_rule:
                    from .skill_events import record_user_correction as _ruc
                    import asyncio as _asyncio
                    resp_text = _msg_content(response) if response else ""
                    _asyncio.create_task(_ruc(
                        project_id=project_id,
                        role_id=role_name,
                        user_message=query[:500],
                        previous_response=resp_text[:500],
                    ))
            except Exception:
                pass

        # ── Audit log: assistant response ──
        try:
            resp_text = _msg_content(response) if response else ""
            if resp_text:
                await get_audit_logger().log_message(
                    "assistant", resp_text[:2000],
                    session_id=thread_id, project_id=project_id,
                    role=role_name,
                )
        except Exception:
            pass

        result = {
            "messages": [response] if state.get("parallel_mode") else msgs + [response],
            "current_role": role_name,
        }
        # ── Parallel mode: collect response for supervisor synthesis ──
        if state.get("parallel_mode"):
            # Add this role's response to parallel_responses
            resp_text = _msg_content(response) if response else ""
            responses = dict(state.get("parallel_responses", {}))
            responses[role_name] = resp_text
            result["parallel_responses"] = responses
            # Remove self from pending list
            pending = list(state.get("parallel_pending", []))
            if role_name in pending:
                pending.remove(role_name)
            result["parallel_pending"] = pending
        return result

    # Set metadata for introspection
    _role_node.__name__ = f"{role_name}_node"
    _role_node._role_name = role_name
    _role_node._role_display = getattr(role_config, "display", role_name)
    return _role_node


# ============================================================
# Graph builder
# ============================================================

def build_graph(roles: list | None = None):
    """Build the Dobby StateGraph with supervisor loop routing.

    All role nodes and compress_node route back to supervisor,
    forming a loop. Only supervisor routes to END (on FINISH).

    Role node functions are stored in the module-level _role_nodes
    registry for parallel dispatch access.

    Args:
        roles: list of RoleConfig objects. All roles added as nodes.

    Returns a StateGraph builder (not yet compiled — attach checkpointer separately).
    """
    if not roles:
        roles = []

    global _current_role_registry, _role_nodes
    _role_nodes.clear()
    _current_role_registry.clear()

    builder = StateGraph(DobbyState)

    # Build role registry for supervisor access
    for rc in roles:
        node_name = getattr(rc, "name", "unknown")
        _current_role_registry[node_name] = rc

    # Add nodes
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("compress_node", compress_node)

    for rc in roles:
        node_name = getattr(rc, "name", "unknown")
        node_fn = build_role_node(rc)
        builder.add_node(node_name, node_fn)
        _role_nodes[node_name] = node_fn  # ← register for parallel dispatch

    builder.set_entry_point("supervisor")

    # ── Loop topology: all nodes → supervisor ──
    for rc in roles:
        node_name = getattr(rc, "name", "unknown")
        builder.add_edge(node_name, "supervisor")
    builder.add_edge("compress_node", "supervisor")

    return builder


def compile_with_checkpointer(builder: StateGraph, checkpointer=None):
    """Compile a StateGraph with PostgresSaver checkpointer.

    Pass an existing checkpointer, or one will be created.
    Patches async methods for LangGraph 1.x compatibility.
    """
    from langgraph.checkpoint.postgres import PostgresSaver

    if checkpointer is None:
        import psycopg
        conn = psycopg.Connection.connect(
            _cfg.LANGGRAPH_CHECKPOINT_DB,
            autocommit=True,
            prepare_threshold=0,
        )
        checkpointer = PostgresSaver(conn=conn)

    # Patch async methods → delegate to sync (langgraph-checkpoint-postgres 3.1.0
    # doesn't implement async methods yet, but LangGraph 1.x requires them).
    _patch_async_checkpointer(checkpointer)

    return builder.compile(checkpointer=checkpointer)


def _patch_async_checkpointer(cp):
    """Monkey-patch async checkpoint methods to delegate to sync ones.

    langgraph-checkpoint-postgres==3.1.0 only implements sync get/put/list.
    LangGraph 1.x calls async variants (aget_tuple, aput, aput_writes, etc.).
    """
    import asyncio

    async def _aget_tuple(config):
        return cp.get_tuple(config)

    async def _aput(config, checkpoint, metadata, new_versions):
        return cp.put(config, checkpoint, metadata, new_versions)

    async def _aput_writes(config, writes, task_id):
        return cp.put_writes(config, writes, task_id)

    async def _adelete_thread(thread_id):
        return cp.delete_thread(thread_id)

    async def _aget(config):
        return cp.get(config)

    async def _alist(config, *, filter=None, before=None, limit=None):
        return cp.list(config, filter=filter, before=before, limit=limit)

    async def _aget_delta(config):
        return cp.get_delta_channel_history(config)

    cp.aget_tuple = _aget_tuple
    cp.aput = _aput
    cp.aput_writes = _aput_writes
    cp.adelete_thread = _adelete_thread
    cp.aget = _aget
    cp.alist = _alist
    cp.aget_delta_channel_history = _aget_delta


async def setup_checkpointer():
    """Create a PostgresSaver with persistent connection and initialize tables.

    Returns (checkpointer, connection) — caller must close connection when done.
    """
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.Connection.connect(
        _cfg.LANGGRAPH_CHECKPOINT_DB,
        autocommit=True,
        prepare_threshold=0,
    )
    checkpointer = PostgresSaver(conn=conn)
    checkpointer.setup()  # synchronous
    return checkpointer, conn
