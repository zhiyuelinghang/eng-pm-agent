"""
Memory Tools — function calling tool definitions for Agent exposure (§9.2).

Provides OpenAI-compatible function schemas and executors for 5 tools:
  - search_memory: semantic search over Mem0 long-term memory
  - add_memory: actively write a new memory
  - search_knowledge_base: search WeKnora knowledge bases
  - search_experiences: search the experience store (Phase 2)
  - get_session_summary: retrieve current session summary

Each executor is a standalone async function callable from both the
tool calling loop and external code. Designed to work with the
`_call_model_with_tools()` enhanced model call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any, Optional

from . import config as _cfg
from .audit_logger import get_audit_logger

# ============================================================
# Tool schemas (OpenAI function calling format)
# ============================================================

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "搜索项目的长期记忆库，查找历史讨论、决策、经验教训。当需要回忆之前讨论过的内容时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "语义搜索查询，用自然语言描述你想查什么",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认5，最大10",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_memory",
            "description": "主动将一条重要信息写入长期记忆。当用户明确说'记住这个'或对话产生重要结论时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记忆的内容",
                    },
                    "importance": {
                        "type": "number",
                        "description": "重要性 0-1，默认0.5。重要决策用0.8+，普通信息用0.5",
                        "default": 0.5,
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "搜索 WeKnora 工程知识库，查找规范、标准、技术文档。当需要查阅具体规范条款时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "知识库搜索查询",
                    },
                    "kb_name": {
                        "type": "string",
                        "description": "指定知识库名称（可选，不指定则搜索所有绑定的KB）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_experiences",
            "description": "搜索项目经验库，查找类似任务的历史处理方式、踩过的坑、最佳实践。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "经验搜索查询",
                    },
                    "task_type": {
                        "type": "string",
                        "description": "任务类型（可选）：preference | procedure | decision | environment",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_summary",
            "description": "获取当前会话的结构化摘要，包括任务概览、当前状态、重要发现和下一步计划。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_graph_rag",
            "description": "搜索知识图谱，查找跨文档的实体关联和规范引用关系。当需要了解多个规范之间的关联、某条款被哪些其他条款引用、或某个安全措施涉及的所有相关规范时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "知识图谱搜索查询",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ============================================================
# Tool executors
# ============================================================


async def _execute_search_memory(
    query: str,
    user_id: str = "",
    agent_id: str = "",
    top_k: int = 5,
) -> str:
    """Execute Mem0 semantic memory search."""
    try:
        uid = user_id or _cfg.MEM0_USER_ID
        aid = agent_id or _cfg.MEM0_AGENT_ID
        limit = min(top_k, 10)

        def _sync_search():
            from utils.langgraph_utils import get_mem0
            m = get_mem0()
            return m.search(
                query,
                filters={"user_id": uid, "agent_id": aid},
                top_k=limit,
                threshold=_cfg.MEMORY_THRESHOLD,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            results = pool.submit(_sync_search).result(timeout=30)

        # mem0 v2.0.12 returns {"results": [...]}, extract the list
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        if not isinstance(results, list):
            results = []

        if not results:
            return "未找到相关记忆。"

        lines = []
        for i, r in enumerate(results[:limit], 1):
            if isinstance(r, dict):
                memory = r.get("memory", str(r))
                score = r.get("score", 0)
                lines.append(f"{i}. {memory} (相关度: {score:.2f})")
            else:
                lines.append(f"{i}. {r}")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索记忆失败: {e}"


async def _execute_add_memory(
    content: str,
    user_id: str = "",
    agent_id: str = "",
    importance: float = 0.5,
) -> str:
    """Execute Mem0 memory addition."""
    try:
        uid = user_id or _cfg.MEM0_USER_ID
        aid = agent_id or _cfg.MEM0_AGENT_ID

        def _sync_add():
            from utils.langgraph_utils import get_mem0
            m = get_mem0()
            m.add(
                content,
                user_id=uid,
                agent_id=aid,
                metadata={"importance": max(0.0, min(1.0, importance)),
                          "memory_type": "explicit"},
                infer=False,
            )
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_sync_add).result(timeout=15)

        return f"已记住: {content[:200]}"
    except Exception as e:
        return f"写入记忆失败: {e}"


async def _execute_search_knowledge_base(
    query: str,
    kb_names: list[str] | None = None,
) -> str:
    """Execute WeKnora knowledge base search."""
    if not _cfg.WEKNORA_ENABLED:
        return "WeKnora 知识库未启用。设置 WEKNORA_ENABLED=true 并配置连接后可使用。"
    try:
        from .langgraph_utils import _build_weknora_client, _get_kb_id_by_name

        wc = _build_weknora_client()

        if not kb_names:
            # Search all available KBs — only list on cache miss
            kb_list = wc.list_knowledge_bases()
            kb_names = [kb.get("name", "") for kb in kb_list if kb.get("name")]

        lines = []
        for kb_name in kb_names:
            kb_id = _get_kb_id_by_name(kb_name)
            if not kb_id:
                continue

            try:
                results = wc.hybrid_search(
                    kb_id=kb_id, query=query,
                    vector_threshold=0.5, keyword_threshold=0.3,
                    match_count=5,
                )
                knowledge_ids = [
                    str(item.get("knowledge_id") or "")
                    for item in results
                    if isinstance(item, dict) and item.get("knowledge_id")
                ]
                try:
                    details = {
                        str(item.get("id")): item
                        for item in wc.get_knowledge_batch(knowledge_ids)
                        if item.get("id")
                    }
                except Exception:
                    details = {}
                for j, r in enumerate(results[:3], 1):
                    content = r.get("content", str(r))
                    knowledge_id = str(r.get("knowledge_id") or "")
                    detail = details.get(knowledge_id, {})
                    source = (
                        r.get("knowledge_filename")
                        or detail.get("file_name")
                        or r.get("knowledge_title")
                        or detail.get("title")
                        or knowledge_id
                        or "未知来源"
                    )
                    score = float(r.get("score") or 0)
                    folder_path = str(detail.get("folder_path") or "")
                    source_path = (
                        f"{folder_path}/{source}" if folder_path else source
                    )
                    lines.append(
                        f"[{kb_name} #{j}] 来源: {source_path}; "
                        f"相关度: {score:.3f}; knowledge_id: {knowledge_id}\n"
                        f"{content[:1200]}",
                    )
            except Exception:
                continue

        if not lines:
            return "未在知识库中找到相关内容。"
        return "\n".join(lines)
    except Exception as e:
        return f"搜索知识库失败: {e}"


async def _execute_search_experiences(
    query: str,
    task_type: str = "",
    project_id: str = "default",
) -> str:
    """Execute experience store search."""
    def _sync_search() -> list[tuple]:
        from .langgraph_utils import get_mem0
        import psycopg

        query_vector: str | None = None
        if query.strip():
            encoded = get_mem0().embedding_model.embed(query, "search")
            query_vector = "[" + ",".join(str(float(v)) for v in encoded) + "]"

        filters = ["project_id = %s", "status = 'active'"]
        params: list[Any] = [project_id]
        if task_type:
            filters.append("bucket = %s")
            params.append(task_type)

        if query_vector is not None:
            score_sql = (
                "CASE WHEN embedding IS NULL THEN 0.0 "
                "ELSE 1 - (embedding <=> %s::vector) END"
            )
            select_params: list[Any] = [query_vector]
        else:
            score_sql = "importance"
            select_params = []

        conn = psycopg.Connection.connect(
            _cfg.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT id, body_md, bucket, version,
                               {score_sql} AS score
                        FROM experiences
                        WHERE {' AND '.join(filters)}
                        ORDER BY score DESC, importance DESC, updated_at DESC
                        LIMIT 5""",
                    [*select_params, *params],
                )
                return cur.fetchall()
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_sync_search)
        if not rows:
            return "未在经验库中找到相关内容。"

        lines = []
        for eid, body, bucket, version, score in rows:
            lines.append(
                f"[经验 #{eid}] 类型: {bucket or '通用'} v{version} "
                f"得分: {float(score or 0):.2f}\n{(body or '')[:300]}"
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"搜索经验库失败: {e}"


async def _execute_get_session_summary(state: dict) -> str:
    """Return current session summary."""
    summary = state.get("summary", "")
    tasks = state.get("tasks", {})
    decisions = state.get("decisions", [])

    parts = []
    if summary:
        parts.append(f"## 会话摘要\n{summary}")
    if tasks:
        parts.append(f"## 活跃任务\n{json.dumps(tasks, ensure_ascii=False, indent=2)}")
    if decisions:
        parts.append(f"## 关键决策\n" + "\n".join(f"- {d}" for d in decisions))

    if not parts:
        return "当前会话暂无摘要、任务或决策记录。"
    return "\n\n".join(parts)


async def _execute_search_graph_rag(query: str, project_id: str = "default") -> str:
    """Execute GraphRAG knowledge graph search."""
    if not _cfg.LIGHTRAG_ENABLED:
        return "知识图谱未启用。设置 LIGHTRAG_ENABLED=true 后可使用。"
    try:
        from .graph_rag_engine import get_graph_rag
        engine = await get_graph_rag(project_id=project_id)
        result = await engine.search(query, mode=_cfg.LIGHTRAG_QUERY_MODE)
        return result.get("formatted", "未在知识图谱中找到相关内容。")
    except Exception as e:
        return f"知识图谱搜索失败: {e}"


# ============================================================
# Tool dispatch
# ============================================================


async def execute_tool(
    tool_name: str,
    arguments: dict,
    user_id: str = "",
    agent_id: str = "",
    state: dict = None,
    kb_names: list[str] = None,
    project_id: str = "default",
) -> str:
    """Dispatch a tool call to the appropriate executor.

    Args:
        tool_name: name of the tool (matches TOOL_SCHEMAS)
        arguments: tool arguments from the model
        user_id: Mem0 user_id
        agent_id: Mem0 agent_id
        state: current DobbyState (for get_session_summary)
        kb_names: WeKnora KB names to search

    Returns:
        Tool result as a string (to be fed back to the model)
    """
    tool_map = {
        "search_memory": lambda: _execute_search_memory(
            query=arguments.get("query", ""),
            user_id=user_id,
            agent_id=agent_id,
            top_k=arguments.get("top_k", 5),
        ),
        "add_memory": lambda: _execute_add_memory(
            content=arguments.get("content", ""),
            user_id=user_id,
            agent_id=agent_id,
            importance=arguments.get("importance", 0.5),
        ),
        "search_knowledge_base": lambda: _execute_search_knowledge_base(
            query=arguments.get("query", ""),
            kb_names=(
                kb_names
                or (
                    [arguments["kb_name"]]
                    if arguments.get("kb_name")
                    else None
                )
            ),
        ),
        "search_experiences": lambda: _execute_search_experiences(
            query=arguments.get("query", ""),
            task_type=arguments.get("task_type", ""),
            project_id=project_id,
        ),
        "get_session_summary": lambda: _execute_get_session_summary(state or {}),
        "search_graph_rag": lambda: _execute_search_graph_rag(
            query=arguments.get("query", ""),
            project_id=project_id,
        ),
    }

    executor = tool_map.get(tool_name)
    if not executor:
        return f"未知工具: {tool_name}"

    # ── Audit log: tool call ──
    try:
        await get_audit_logger().log_tool_call(
            tool_name, arguments,
            session_id=state.get("thread_id", "") if state else "",
            project_id=state.get("project_id", "") if state else "",
        )
    except Exception:
        pass

    return await executor()
