#!/usr/bin/env python3
"""
Dobby Web — Gradio Chat Interface

Provides a browser-based chat UI for the Dobby multi-agent system.
Supports supervisor loop routing across multiple specialist roles, project switching, session
management, memory search, and knowledge base search.

Usage:
    python app.py                          # default port 7860
    python app.py --port 8080              # custom port
    python app.py --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

# ── 绕过本地代理 + 强制离线模式（模型已缓存）──
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,huggingface.co,cdn-lfs.huggingface.co")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import gradio as gr

# ── Load .env (container or local) ──
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent / ".env"
    load_dotenv(_env_file, override=True)
except ImportError:
    pass


# ============================================================
# Text extraction helper
# ============================================================

def _msg_text(msg) -> str:
    """Extract plain text from a LangGraph message object."""
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


# ============================================================
# Global state — initialized once at startup
# ============================================================

_graph = None          # Compiled LangGraph
_roles: list = []      # All role configs
_conn = None           # PostgreSQL connection (for graceful shutdown)
_startup_ok = False    # Whether services are healthy
_startup_error = ""    # Error message if startup failed


# ============================================================
# Service health check
# ============================================================

async def _check_health(url: str, timeout: float = 5.0) -> bool:
    """Check if a URL responds OK."""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


# ============================================================
# Initialize graph and services
# ============================================================

async def _init_graph():
    """Build and compile the LangGraph with all roles."""
    global _graph, _roles, _conn, _startup_ok, _startup_error

    print("=" * 60)
    print("Dobby Web — Initializing...")
    print("=" * 60)

    # 1. Check PostgreSQL
    from utils.config import LANGGRAPH_CHECKPOINT_DB
    print(f"[1/4] Checking PostgreSQL: {LANGGRAPH_CHECKPOINT_DB[:50]}...")
    try:
        import psycopg
        _conn = psycopg.Connection.connect(
            LANGGRAPH_CHECKPOINT_DB, autocommit=True, prepare_threshold=0,
        )
        cursor = _conn.execute("SELECT 1")
        cursor.fetchone()
        print("  ✅ PostgreSQL connected")
    except Exception as e:
        _startup_error = f"PostgreSQL 连接失败: {e}"
        print(f"  ❌ {_startup_error}")
        return

    # 2. Check Embed Server
    from utils.config import EMBED_SERVER_URL
    embed_health = f"{EMBED_SERVER_URL.rstrip('/v1')}/health" if "/v1" in EMBED_SERVER_URL else f"{EMBED_SERVER_URL}/health"
    print(f"[2/4] Checking Embed Server: {embed_health}")
    if await _check_health(embed_health):
        print("  ✅ Embed Server healthy")
    else:
        print("  ⚠️  Embed Server not reachable — embeddings may fail")

    # 2b. Pre-warm WeKnora KB cache
    from utils.langgraph_utils import _warm_kb_cache
    _warm_kb_cache()

    # 3. Load roles
    print("[3/4] Loading roles...")
    from utils.roles import get_all_roles
    _roles = get_all_roles()
    print(f"  ✅ {len(_roles)} roles loaded: {[r.name for r in _roles]}")

    # 4. Build graph
    print("[4/4] Building LangGraph...")
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from utils.langgraph_utils import build_graph, compile_with_checkpointer

        cp = PostgresSaver(conn=_conn)
        cp.setup()
        builder = build_graph(roles=_roles)
        _graph = compile_with_checkpointer(builder, checkpointer=cp)
        print(f"  ✅ Graph compiled with checkpointer")
    except Exception as e:
        _startup_error = f"Graph 构建失败: {e}"
        print(f"  ❌ {_startup_error}")
        return

    _startup_ok = True
    print("=" * 60)
    print("✅ Dobby Web ready!")
    print("=" * 60)


# ============================================================
# Chat handler — supervisor loop routing
# ============================================================

async def _chat(
    message: str,
    project_id: str,
    thread_id: str,
) -> str:
    """Send message through supervisor loop routing (non-streaming fallback)."""
    global _graph

    if not _graph:
        return "⚠️ **系统未初始化**，请检查服务健康状态。"

    from agentscope.message import UserMsg

    config = {"configurable": {"thread_id": thread_id}}

    try:
        prev = await _graph.aget_state(config)
        existing = list(prev.values.get("messages", [])) if prev and prev.values else []
        result = await _graph.ainvoke(
            {
                "messages": existing + [UserMsg("user", message)],
                "project_id": project_id,
                "thread_id": thread_id,
            },
            config=config,
        )

        msgs = result.get("messages", [])
        current_role = result.get("current_role", "")

        if msgs:
            response = _msg_text(msgs[-1])
            role_display = _get_role_display(current_role) if current_role else ""
            if role_display and role_display != "supervisor":
                return f"**[{role_display}]**\n\n{response}"
            return response
        else:
            return "⚠️ **无响应** — Agent 未返回消息。"

    except Exception as e:
        return f"❌ **调用失败**: {str(e)[:300]}"


async def _chat_stream(
    message: str,
    project_id: str,
    thread_id: str,
):
    """Streaming chat: Phase 1 execute graph → Phase 2 stream synthesis tokens.

    Yields cumulative full response text each time a new token arrives.
    First yield includes role prefix (e.g., "**[安全总监]**\n\n").
    """
    global _graph

    if not _graph:
        yield "⚠️ **系统未初始化**，请检查服务健康状态。"
        return

    from agentscope.message import UserMsg

    config = {"configurable": {"thread_id": thread_id}}

    try:
        prev = await _graph.aget_state(config)
        existing = list(prev.values.get("messages", [])) if prev and prev.values else []

        # ── Phase 1: Execute graph with deferred synthesis ──
        result = await _graph.ainvoke(
            {
                "messages": existing + [UserMsg("user", message)],
                "project_id": project_id,
                "thread_id": thread_id,
                "__defer_synthesis__": True,  # ← skip synthesis LLM, store context
            },
            config=config,
        )

        msgs = result.get("messages", [])
        current_role = result.get("current_role", "")

        # ── Phase 2: Stream synthesis if pending (multi-role parallel) ──
        if result.get("__synthesis_pending__"):
            from utils.langgraph_utils import _generate_final_answer_stream

            # Build role prefix for display
            role_prefix = ""
            if current_role and current_role != "supervisor":
                role_display = _get_role_display(current_role)
                if role_display:
                    role_prefix = f"**[{role_display}]**\n\n"

            # Stream tokens from synthesis LLM
            full_response = ""
            async for token in _generate_final_answer_stream(result):
                full_response += token
                yield role_prefix + full_response

            # Persist the final answer to LangGraph state for conversation continuity
            try:
                from agentscope.message import AssistantMsg
                await _graph.aupdate_state(
                    config,
                    {"messages": [AssistantMsg("assistant", role_prefix + full_response)]},
                )
            except Exception:
                pass  # Non-critical — conversation will still work via checkpoint

        elif msgs:
            # Single role or sequential — return immediately (no synthesis needed)
            response = _msg_text(msgs[-1])
            role_display = _get_role_display(current_role) if current_role else ""
            if role_display and role_display != "supervisor":
                yield f"**[{role_display}]**\n\n{response}"
            else:
                yield response
        else:
            yield "⚠️ **无响应** — Agent 未返回消息。"

    except Exception as e:
        yield f"❌ **调用失败**: {str(e)[:300]}"


# ============================================================
# Memory search
# ============================================================

async def _search_memory(query: str, project_id: str, user_id: str) -> str:
    """Search Mem0 for relevant memories."""
    try:
        from utils.memory_tools import execute_tool

        results = await execute_tool(
            tool_name="search_memory",
            arguments={"query": query, "top_k": 5},
            user_id=user_id,
            agent_id=user_id,
            state={"project_id": project_id},
        )

        # results is a pre-formatted string from execute_tool
        return "### 📊 记忆检索结果\n\n" + results

    except Exception as e:
        return f"❌ **记忆检索失败**: {str(e)[:200]}"


# ============================================================
# Knowledge base search
# ============================================================

async def _search_knowledge(query: str, project_id: str) -> str:
    """Search WeKnora knowledge base."""
    try:
        from utils.config import WEKNORA_API_KEY, WEKNORA_BASE_URL
        if not WEKNORA_API_KEY:
            return "⚠️ **WeKnora 未配置** — 请设置 WEKNORA_API_KEY"

        from utils.memory_tools import execute_tool

        results = await execute_tool(
            tool_name="search_knowledge_base",
            arguments={"query": query, "top_k": 5},
            user_id="",
            agent_id="",
            state={"project_id": project_id},
            kb_names=None,
        )

        # results is a pre-formatted string from execute_tool
        return "### 📚 知识库搜索结果\n\n" + results

    except Exception as e:
        return f"❌ **知识库搜索失败**: {str(e)[:200]}"


# ============================================================
# Helpers
# ============================================================

def _get_role_display(role_name: str) -> str:
    """Get the display name for a role."""
    for r in _roles:
        if r.name == role_name:
            return f"{r.display} ({r.name})"
    return role_name


# ============================================================
# Gradio UI — main chat function
# ============================================================

async def chat_handler(
    message: str,
    history: list,
    project_id: str,
    thread_id: str,
):
    """Main chat handler — unified supervisor loop routing."""
    global _startup_ok, _startup_error

    if not _startup_ok:
        return f"❌ **系统未就绪**: {_startup_error or '请等待初始化完成'}"

    if not message or not message.strip():
        return "请输入消息。"

    try:
        return await _chat(message, project_id, thread_id)
    except asyncio.TimeoutError:
        return "⏰ **请求超时** — LLM 响应时间过长，请稍后重试或缩短问题。"
    except Exception as e:
        return f"❌ **处理失败**: {str(e)[:300]}"


# ============================================================
# Gradio UI — layout
# ============================================================

# ── ChatGPT light theme (module-level for Gradio 6.0 launch()) ──
_CHATGPT_CSS = r"""
/* ═══════════════════════════════════════════
   ChatGPT Light Theme — Dobby Edition
   ═══════════════════════════════════════════ */
:root {
        --chatgpt-bg: #ffffff;
        --chatgpt-sidebar: #f9fafb;
        --chatgpt-user-bubble: #f4f4f4;
        --chatgpt-text: #1a1a1a;
        --chatgpt-muted: #6b7280;
        --chatgpt-accent: #10a37f;
        --chatgpt-accent-hover: #0d8c6d;
        --chatgpt-border: #e5e7eb;
        --chatgpt-hover: #f3f4f6;
    }

    /* ── Global reset ── */
    body {
        background-color: var(--chatgpt-bg) !important;
        font-family: "Soehne", ui-sans-serif, -apple-system, "Segoe UI", system-ui, "Helvetica Neue", sans-serif !important;
    }
    .gradio-container {
        max-width: none !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    footer { visibility: hidden !important; }

    /* ═══════════════════════════════════════════
       Main Layout — Two Columns
       ═══════════════════════════════════════════ */
    .main-row {
        height: 100vh !important;
        margin: 0 !important;
        gap: 0 !important;
        flex-wrap: nowrap !important;
    }

    /* ── Left Sidebar Column ── */
    .sidebar-column {
        width: 300px !important;
        min-width: 300px !important;
        max-width: 300px !important;
        flex-shrink: 0 !important;
        background: var(--chatgpt-sidebar) !important;
        border-right: 1px solid var(--chatgpt-border) !important;
        padding: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        overflow-y: auto !important;
    }
    .sidebar-column > .wrap {
        padding: 0 !important;
        gap: 0 !important;
        flex: 1 !important;
        display: flex !important;
        flex-direction: column !important;
    }
    .sidebar-column .prose { font-size: inherit; }

    /* Sidebar header */
    .sidebar-header {
        padding: 20px 16px 6px 16px;
    }
    .sidebar-header h2 {
        margin: 0;
        font-size: 1.15em;
        font-weight: 700;
        color: var(--chatgpt-text);
        letter-spacing: -0.3px;
    }
    .sidebar-header .subtitle {
        margin: 2px 0 0 0;
        font-size: 0.76em;
        color: var(--chatgpt-muted);
        font-weight: 400;
    }

    /* New chat button row */
    .new-chat-row {
        padding: 4px 12px 8px 12px;
    }
    .new-chat-row button {
        width: 100% !important;
        border: 1px solid var(--chatgpt-border) !important;
        border-radius: 10px !important;
        background: var(--chatgpt-bg) !important;
        color: var(--chatgpt-text) !important;
        font-size: 0.88em !important;
        font-weight: 500 !important;
        padding: 10px 14px !important;
        justify-content: flex-start !important;
        gap: 8px !important;
        box-shadow: none !important;
        transition: background 0.15s ease !important;
    }
    .new-chat-row button:hover {
        background: var(--chatgpt-hover) !important;
    }

    /* Section label */
    .sidebar-section-label {
        padding: 16px 16px 6px 16px;
        font-size: 0.72em;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--chatgpt-muted);
    }

    /* Sidebar divider */
    .sidebar-divider {
        margin: 8px 16px !important;
        border: none !important;
        border-top: 1px solid var(--chatgpt-border) !important;
        opacity: 0.7;
    }

    /* Compact control wrapper */
    .sidebar-control {
        padding: 3px 14px;
    }
    .sidebar-control .label-wrap {
        margin-bottom: 1px !important;
    }
    .sidebar-control label,
    .sidebar-control .label-text {
        font-size: 0.82em !important;
        font-weight: 500 !important;
        color: var(--chatgpt-muted) !important;
    }
    .sidebar-control input,
    .sidebar-control select,
    .sidebar-control .wrap-inner {
        font-size: 0.88em !important;
    }
    .sidebar-control .info-text {
        font-size: 0.72em !important;
        color: var(--chatgpt-muted) !important;
    }

    /* Thread ID input */
    .thread-id-input input {
        font-family: 'JetBrains Mono', 'SF Mono', 'Consolas', monospace !important;
        font-size: 0.8em !important;
    }

    /* Search section */
    .search-section {
        padding: 3px 14px;
    }
    .search-section .label-wrap {
        margin-bottom: 1px !important;
    }
    .search-section label {
        font-size: 0.82em !important;
        font-weight: 500 !important;
        color: var(--chatgpt-muted) !important;
    }
    .search-section button {
        font-size: 0.84em !important;
        margin-top: 4px !important;
    }

    /* Search result */
    .sidebar-search-result {
        padding: 2px 14px;
    }
    .sidebar-search-result .prose {
        font-size: 0.8em !important;
        line-height: 1.5 !important;
        color: var(--chatgpt-text) !important;
    }

    /* ═══════════════════════════════════════════
       Right Chat Column
       ═══════════════════════════════════════════ */
    .chat-column {
        flex: 1 !important;
        min-width: 0 !important;
        padding: 0 !important;
        background: var(--chatgpt-bg) !important;
        display: flex !important;
        flex-direction: column !important;
    }
    .chat-column > .wrap {
        height: 100% !important;
        padding: 0 !important;
        gap: 0 !important;
    }

    /* ChatInterface — full height */
    .chat-column .chatbot {
        flex: 1 !important;
        min-height: 0 !important;
        border: none !important;
    }

    /* ── Chat bubbles: ChatGPT style ── */
    /* User row — right aligned, grey bubble */
    .bubble-wrap.user {
        background: var(--chatgpt-user-bubble) !important;
        border-radius: 18px !important;
        padding: 10px 18px !important;
        color: var(--chatgpt-text) !important;
        max-width: 75% !important;
        margin-left: auto !important;
    }

    /* Bot row — left aligned, no bubble background (white on white) */
    .bubble-wrap.bot {
        background: transparent !important;
        border-radius: 0 !important;
        padding: 8px 16px !important;
        color: var(--chatgpt-text) !important;
        max-width: 85% !important;
    }

    /* Message row spacing */
    .message-row {
        padding: 4px 0 !important;
    }

    /* ── Input area ── */
    .chat-input-row {
        padding: 12px 24px 16px 24px !important;
        border-top: 1px solid var(--chatgpt-border) !important;
        background: var(--chatgpt-bg) !important;
        align-items: flex-end !important;
        gap: 8px !important;
    }
    .chat-input-row textarea,
    .chat-input-row input[type="text"] {
        border-radius: 14px !important;
        border: 1px solid var(--chatgpt-border) !important;
        padding: 12px 18px !important;
        font-size: 0.95em !important;
        line-height: 1.5 !important;
        background: var(--chatgpt-bg) !important;
        color: var(--chatgpt-text) !important;
        box-shadow: 0 0 0 0 transparent !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }
    .chat-input-row textarea:focus,
    .chat-input-row input[type="text"]:focus {
        border-color: var(--chatgpt-accent) !important;
        box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.12) !important;
        outline: none !important;
    }
    .chat-input-row textarea::placeholder,
    .chat-input-row input[type="text"]::placeholder {
        color: #9ca3af !important;
    }

    /* Send button */
    .send-btn button {
        border-radius: 12px !important;
        padding: 10px 18px !important;
        font-weight: 500 !important;
        font-size: 0.9em !important;
        transition: background 0.15s ease !important;
    }

    /* ═══════════════════════════════════════════
       Status Bar (sidebar bottom)
       ═══════════════════════════════════════════ */
    .status-bar {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 12px 16px;
        font-size: 0.78em;
        color: var(--chatgpt-muted);
        margin-top: auto !important;
        border-top: 1px solid var(--chatgpt-border);
    }
    .status-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .status-dot.online { background: var(--chatgpt-accent); }
    .status-dot.offline { background: #ef4444; }

    /* ── Scrollbar styling ── */
    .sidebar-column::-webkit-scrollbar { width: 4px; }
    .sidebar-column::-webkit-scrollbar-track { background: transparent; }
    .sidebar-column::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }

    /* ── Hide Gradio badges / built-with ── */
    .built-with { display: none !important; }
"""

# ── Gradio 6.0 theme (module-level for launch()) ──
_CHATGPT_THEME = gr.themes.Base(
    primary_hue="emerald",
    neutral_hue="gray",
    font=gr.themes.GoogleFont("Inter"),
    font_mono=gr.themes.GoogleFont("JetBrains Mono"),
).set(
    # ── 背景 ──
    body_background_fill="#ffffff",
    body_background_fill_dark="#ffffff",
    block_background_fill="#ffffff",
    block_background_fill_dark="#ffffff",
    block_border_color="#e5e7eb",
    block_border_width="0px",
    block_radius="8px",
    block_title_text_color="#1a1a1a",
    block_label_text_color="#6b7280",
    # ── 输入框 ──
    input_background_fill="#ffffff",
    input_background_fill_dark="#ffffff",
    input_border_color="#d1d5db",
    input_border_color_focus="#10a37f",
    input_radius="8px",
    # ── 按钮 ──
    button_primary_background_fill="#10a37f",
    button_primary_background_fill_hover="#0d8c6d",
    button_primary_text_color="#ffffff",
    button_secondary_background_fill="#ffffff",
    button_secondary_background_fill_hover="#f3f4f6",
    button_secondary_text_color="#1a1a1a",
    button_secondary_border_color="#d1d5db",
)


def _build_ui():
    """Build the Gradio interface — ChatGPT light theme with sidebar."""
    with gr.Blocks(
        title="Dobby — 工程管理智能助手",
    ) as demo:
        # ═══════════════════════════════════════════
        # Two-Column Layout
        # ═══════════════════════════════════════════
        with gr.Row(elem_classes="main-row", equal_height=True):
            # ═══════════════════════════════
            # ── LEFT: Sidebar ──
            # ═══════════════════════════════
            with gr.Column(elem_classes="sidebar-column", scale=0):
                # Header
                gr.HTML("""
                <div class="sidebar-header">
                    <h2>🏗️ Dobby</h2>
                    <p class="subtitle">工程管理智能助手</p>
                </div>
                """)

                # New chat button
                with gr.Row(elem_classes="new-chat-row"):
                    new_chat_btn = gr.Button(
                        "＋ 新建对话",
                        variant="secondary",
                        size="sm",
                    )

                gr.HTML('<hr class="sidebar-divider">')

                # ── Config section ──
                gr.HTML('<div class="sidebar-section-label">⚙ 配置</div>')

                with gr.Column(elem_classes="sidebar-control"):
                    project_id = gr.Textbox(
                        label="项目",
                        value="demo",
                        placeholder="输入项目标识符",
                    )

                with gr.Column(elem_classes="sidebar-control"):
                    thread_id = gr.Textbox(
                        value="",
                        placeholder="留空自动生成",
                        label="会话 ID",
                        info="留空自动生成 · 输入已有ID恢复历史",
                        elem_classes="thread-id-input",
                    )

                gr.HTML('<hr class="sidebar-divider">')

                # ── Search section ──
                gr.HTML('<div class="sidebar-section-label">🔍 快速搜索</div>')

                with gr.Column(elem_classes="search-section"):
                    mem_query = gr.Textbox(
                        label="记忆检索",
                        placeholder="搜索历史记忆...",
                    )
                    mem_search_btn = gr.Button(
                        "搜索记忆",
                        variant="secondary",
                        size="sm",
                    )
                    mem_result = gr.Markdown("", elem_classes="sidebar-search-result", visible=False)

                with gr.Column(elem_classes="search-section"):
                    kb_query = gr.Textbox(
                        label="知识库检索",
                        placeholder="搜索知识库...",
                    )
                    kb_search_btn = gr.Button(
                        "搜索知识库",
                        variant="secondary",
                        size="sm",
                    )
                    kb_result = gr.Markdown("", elem_classes="sidebar-search-result", visible=False)

                # ── Spacer pushes status to bottom ──
                gr.HTML('<div style="flex:1; min-height:8px;"></div>')

                # ── Status bar at bottom ──
                gr.HTML(
                    '<div class="status-bar"><div class="status-dot online"></div>系统就绪</div>'
                    if _startup_ok else
                    '<div class="status-bar"><div class="status-dot offline"></div>未连接</div>'
                )

            # ═══════════════════════════════
            # ── RIGHT: Chat Area ──
            # ═══════════════════════════════
            with gr.Column(elem_classes="chat-column", scale=1):
                chatbot = gr.Chatbot(
                    height="100%",
                    avatar_images=(None, None),
                    label="",
                    elem_classes="chatbot",
                    show_label=False,
                )

                with gr.Row(elem_classes="chat-input-row"):
                    msg_input = gr.Textbox(
                        placeholder="输入消息... (Enter 发送, Shift+Enter 换行)",
                        container=False,
                        scale=1,
                        autofocus=True,
                    )
                    send_btn = gr.Button(
                        "发送",
                        variant="primary",
                        size="sm",
                        scale=0,
                        elem_classes="send-btn",
                    )

        # ═══════════════════════════════════════════
        # Event Bindings
        # ═══════════════════════════════════════════

        # New chat — clear thread_id AND chat history
        def _new_chat():
            return "", []

        new_chat_btn.click(_new_chat, None, [thread_id, chatbot])

        # ── Main chat submit handler ──
        async def _load_history_from_checkpointer(tid: str) -> list:
            """Load previous conversation from LangGraph checkpointer for a given thread_id."""
            global _graph
            if not _graph or not tid:
                return []
            try:
                config = {"configurable": {"thread_id": tid}}
                state = await _graph.aget_state(config)
                if state and state.values:
                    msgs = state.values.get("messages", [])
                    history = []
                    for m in msgs:
                        role = "user" if getattr(m, "role", "") == "user" else "assistant"
                        text = _msg_text(m)
                        if text.strip():
                            history.append({"role": role, "content": text})
                    return history
            except Exception:
                pass
            return []

        async def _on_chat_submit(
            message: str,
            history: list,
            pid: str,
            tid: str,
        ):
            """Streaming handler: update chatbot incrementally as tokens arrive.

            Yields (history, tid, "") tuples — Gradio updates chatbot on each yield,
            creating a typewriter effect for streaming responses.
            """
            if not message or not message.strip():
                yield history, tid, ""
                return

            # Auto-generate thread_id if empty
            is_new_tid = not tid or not tid.strip()
            if is_new_tid:
                tid = f"web_{uuid.uuid4().hex[:12]}"

            # Load previous conversation from checkpointer if restoring a session
            history = history or []
            if history == [] and not is_new_tid:
                loaded = await _load_history_from_checkpointer(tid)
                if loaded:
                    history = loaded

            # Append user message + placeholder for assistant
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": ""})

            # Stream response token-by-token
            async for partial_response in _chat_stream(message, pid, tid):
                history[-1]["content"] = partial_response
                yield history, tid, ""

        # Submit on Enter (no Shift)
        msg_input.submit(
            _on_chat_submit,
            [msg_input, chatbot, project_id, thread_id],
            [chatbot, thread_id, msg_input],
        )

        send_btn.click(
            _on_chat_submit,
            [msg_input, chatbot, project_id, thread_id],
            [chatbot, thread_id, msg_input],
        )

        # Memory search
        async def _on_mem_search(query, pid):
            if not query or not query.strip():
                return gr.update(value="", visible=False)
            result = await _search_memory(query, pid, pid)
            return gr.update(value=result, visible=True)

        mem_search_btn.click(
            _on_mem_search, [mem_query, project_id], [mem_result]
        )

        # Knowledge base search
        async def _on_kb_search(query, pid):
            if not query or not query.strip():
                return gr.update(value="", visible=False)
            result = await _search_knowledge(query, pid)
            return gr.update(value=result, visible=True)

        kb_search_btn.click(
            _on_kb_search, [kb_query, project_id], [kb_result]
        )

    return demo


# ============================================================
# Main entry point
# ============================================================

def main():
    """Start the Gradio web server."""
    import argparse

    parser = argparse.ArgumentParser(description="Dobby Web Chat Interface")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7860, help="Listen port (default: 7860)")
    parser.add_argument("--share", action="store_true", help="Create a public Gradio share link")
    parser.add_argument("--no-kill", action="store_true", help="Skip auto-kill of stale process on port")
    args = parser.parse_args()

    # ── Auto-recover from stale processes ──
    if not args.no_kill:
        from utils.port_utils import kill_process_on_port
        kill_process_on_port(args.port, host=args.host if args.host != "0.0.0.0" else "127.0.0.1")

    # Initialize graph (async)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_init_graph())
    except Exception as e:
        global _startup_error
        _startup_error = str(e)
        print(f"FATAL: Initialization failed: {e}")
        # Continue anyway — UI will show error

    # Build and launch UI
    demo = _build_ui()
    print(f"\nStarting Gradio on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.\n")

    # Use queue for async support — higher limits for long LLM calls
    demo.queue(default_concurrency_limit=5, max_size=20)

    try:
        demo.launch(
            server_name=args.host,
            server_port=args.port,
            share=args.share,
            show_error=True,
            max_threads=80,
            theme=_CHATGPT_THEME,
            css=_CHATGPT_CSS,
        )
    finally:
        # Cleanup
        global _conn
        if _conn:
            try:
                _conn.close()
                print("PostgreSQL connection closed.")
            except Exception:
                pass
        loop.close()


if __name__ == "__main__":
    main()
