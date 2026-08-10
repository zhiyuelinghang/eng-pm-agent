"""
MemoryManager — unified entry point for long/short-term memory (§9.1).

Aggregates compression / lifecycle / fusion / graphiti_client modules
into a single Facade. Not a forced migration — existing Demo files and
LangGraph nodes continue to work directly with underlying functions.

Usage:
    mm = MemoryManager(project_id="demo", role_id="dobby_core")
    state = await mm.start_session()
    ctx = await mm.assemble_context(state, "用户的问题")
    await mm.end_session(state)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import config as _cfg
from .skill_registry import SkillRegistry
from .audit_logger import get_audit_logger
from .compression import (
    estimate_tokens,
    needs_compression,
    trim_messages,
    build_compress_messages,
    parse_compress_response,
)
from .langgraph_utils import (
    DobbyState,
    _call_model,
    _msg_content,
    _last_user_text,
    _make_system,
    _make_user,
    get_mem0,
    _build_weknora_client,
    _get_kb_id_by_name,
    build_role_node,
    build_graph,
    compile_with_checkpointer,
    setup_checkpointer,
)
from .lifecycle import (
    apply_decay,
    reflect_if_needed,
    extract_experiences,
    consolidate_if_needed,
)
from .fusion import MemoryFusion, ContextAssembler
from .fusion import (
    _search_experiences_structured,
    _graphiti_to_items,
)
from .entity_graph import EntityExtractor, EntityGraph
from .context_trigger import classify
from .auto_hints import AutoHinter
from .token_budget import TokenBudget, BudgetAllocation, format_budget_report


# ============================================================
# Data structures
# ============================================================

@dataclass
class ContextAssembly:
    """Result of context assembly (7-layer)."""
    messages: list = field(default_factory=list)
    token_estimate: int = 0
    within_budget: bool = True
    budget_warnings: list[str] = field(default_factory=list)
    layer_tokens: dict[str, int] = field(default_factory=dict)
    fused_results: list = field(default_factory=list)
    mode_used: str = "standard"


# ============================================================
# MemoryManager
# ============================================================

class MemoryManager:
    """Long/Short-term memory manager — recommended entry point for Agent runtime.

    Aggregates:
      - compression: token estimation, compression trigger, message trimming
      - lifecycle: decay, reflection, experience extraction, consolidation
      - fusion: RRF merge (Mem0 + WeKnora)
      - graphiti_client: bi-temporal timeline search
      - entity_graph: 实体图懒加载 + 扩散候选扩展 (对标 _kb_cache TTL 模式)

    All methods are async-safe. Internal Mem0 calls run in thread pools.
    """

    _ENTITY_GRAPH_TTL: float = 300.0  # 实体图 TTL 缓存 300s (对标 langgraph_utils._KBCACHE_TTL)

    def __init__(self, project_id: str = "", role_id: str = "dobby_core"):
        self.project_id = project_id
        self.role_id = role_id
        self._token_budget = TokenBudget()
        self._fusion = MemoryFusion(
            default_weights={
                "mem0": _cfg.FUSION_WEIGHT_MEM0,
                "kb": _cfg.FUSION_WEIGHT_KB,
                "timeline": _cfg.FUSION_WEIGHT_TIMELINE,
                "experience": _cfg.FUSION_WEIGHT_EXPERIENCE,
            },
            rrf_k=_cfg.RRF_K,
            mmr_lambda=_cfg.FUSION_MMR_LAMBDA,
        )
        self._auto_hinter = AutoHinter(hint_threshold=_cfg.AUTO_HINT_THRESHOLD)
        # 实体图 (懒加载, 首次 _search_memory 时从 mem0 全量构建)
        self._entity_graph: EntityGraph | None = None
        self._entity_graph_ts: float = 0.0

    # ================================================================
    # Session management
    # ================================================================

    async def start_session(
        self,
        session_id: str | None = None,
        project_id: str | None = None,
        role_id: str | None = None,
    ) -> DobbyState:
        """Initialize a new session with fresh DobbyState.

        Args:
            session_id: unique session identifier (auto-generated if None)
            project_id: override project_id from constructor
            role_id: override role_id from constructor

        Returns:
            DobbyState ready for LangGraph invocation
        """
        import uuid
        pid = project_id or self.project_id
        rid = role_id or self.role_id
        sid = session_id or str(uuid.uuid4())

        # ── Audit log: session start ──
        try:
            await get_audit_logger().log_session_start(sid, pid, role=rid)
        except Exception:
            pass

        return DobbyState(
            thread_id=sid,
            project_id=pid,
            current_role=rid,
            created_at=datetime.now(timezone.utc).isoformat(),
            max_token_budget=_cfg.MAX_TOKEN_BUDGET,
            compression_trigger_ratio=_cfg.CONTEXT_TRIGGER_RATIO,
            bound_knowledge_bases=[],
        )

    async def resume_session(self, thread_id: str) -> DobbyState | None:
        """Resume an existing session from PostgresSaver checkpoint.

        Args:
            thread_id: LangGraph thread_id to resume

        Returns:
            DobbyState with history loaded, or None if thread not found
        """
        try:
            cp, conn = await setup_checkpointer()
            try:
                config = {"configurable": {"thread_id": thread_id}}
                state = await cp.aget_tuple(config)
                if state is None:
                    return None
                # Reconstruct DobbyState from checkpoint
                channel_values = getattr(state, "values", {}) or {}
                if isinstance(channel_values, dict):
                    ds = DobbyState(**{k: v for k, v in channel_values.items()
                                        if k in DobbyState.__init__.__code__.co_varnames})
                    return ds
                return None
            finally:
                conn.close()
        except Exception:
            return None

    async def end_session(self, state: DobbyState) -> dict:
        """End a session: apply decay, reflect, and extract experiences.

        Args:
            state: the current DobbyState

        Returns:
            {
                "decay": {"deleted": int, "scanned": int},
                "reflection": {...} or {"skipped": True},
                "experiences": {"extracted": {...}, "total_inserts": int},
            }
        """
        project_id = state.get("project_id", self.project_id)
        user_id = project_id or _cfg.MEM0_USER_ID
        tasks = state.get("tasks", {})
        messages = state.get("messages", [])
        session_id = state.get("thread_id", "")

        # 1. Decay — @deprecated old path: lifecycle.apply_decay() still exists
        # for backward compatibility. New code should use:
        #   self.run_dreamer(task_name="decay") → DecayV2Task via DreamerScheduler
        decay_result = await apply_decay(project_id, user_id=user_id)

        # 2. Reflection
        reflection_result = await reflect_if_needed(project_id, user_id=user_id)

        # 3. Experience extraction (if tasks exist)
        experience_result = {"extracted": {}, "total_inserts": 0}
        if tasks:
            experience_result = await extract_experiences(
                project_id, tasks, messages,
            )

        # ── 4. Session-end consolidation ──
        consolidation_result = {"skipped": True, "reason": "disabled"}
        if _cfg.EXPERIENCE_EVENT_DRIVEN_ENABLED:
            try:
                from .consolidation_engine import ConsolidationEngine
                engine = ConsolidationEngine()
                cr = await engine.run(
                    project_id, source="extracts", mode="session",
                )
                consolidation_result = {
                    "skipped": cr.skipped,
                    "reason": cr.reason or "",
                    "items_loaded": cr.items_loaded,
                    "direct_merged": cr.direct_merged,
                    "llm_judged": cr.llm_judged,
                    "created": cr.created,
                    "updated": cr.updated,
                    "solo_clusters": cr.solo_clusters,
                    "duration_seconds": cr.duration_seconds,
                }
            except Exception:
                consolidation_result = {"skipped": True, "reason": "error"}

        result = {
            "decay": decay_result,
            "reflection": reflection_result,
            "experiences": experience_result,
            "consolidation": consolidation_result,
        }

        # ── Audit log: session end ──
        try:
            await get_audit_logger().log_session_end(
                session_id, project_id, stats={
                    "decay_deleted": decay_result.get("deleted", 0),
                    "reflection_insights": len(reflection_result.get("insights", [])),
                    "experiences_extracted": experience_result.get("total_inserts", 0),
                    "message_count": len(messages) if messages else 0,
                }
            )
        except Exception:
            pass

        return result

    # ================================================================
    # Context assembly
    # ================================================================

    async def assemble_context(
        self,
        state: DobbyState,
        user_input: str,
        system_prompt: str | None = None,
        mode: str = "auto",
    ) -> ContextAssembly:
        """Assemble 7-layer context for an LLM call.

        Layers:
          ① System Prompt  → role persona
          ② Summary        → compressed history
          ③④⑤ LTM+KB+Timeline → <system-reminder> injection
          ⑥ Runtime Context → time/project/role
          ⑦ Recent History → last N messages
          + User Message

        Args:
            state: current DobbyState
            user_input: the current user message text
            system_prompt: override system prompt (uses role default if None)

        Returns:
            ContextAssembly with assembled messages and budget diagnostics
        """
        project_id = state.get("project_id", self.project_id)
        role_id = state.get("current_role", self.role_id)
        summary = state.get("summary", "")
        tasks = state.get("tasks", {})
        messages = state.get("messages", [])

        # ── 0. Mode resolution (§2) ──
        if mode == "auto":
            mode = classify(user_input, state)

        # ── 0b. Save mode for result ──
        actual_mode = mode

        # ── Layer ①: System Prompt ──
        if system_prompt is None:
            system_prompt = self._default_system_prompt(role_id)

        # ── Layers ③④⑤ + Experience: conditional retrieval ──
        fused = []
        reminder = ""

        if mode == "minimal":
            # Fast path: no retrieval, only summary + runtime + history
            pass

        else:
            # Standard or Full: parallel retrieval
            from .graphiti_client import graphiti_search as _graphiti_search

            if mode in ("standard", "full"):
                # 5-source: Mem0 + KB + Graphiti + Experience + GraphRAG
                mem0_results, kb_results, graphiti_data, exp_results, graphrag_result = await asyncio.gather(
                    self._search_memory(user_input, project_id, role_id),
                    self._search_knowledge(user_input),
                    _graphiti_search(project_id, user_input),
                    _search_experiences_structured(user_input, project_id),
                    self._search_graph_rag(user_input),
                    return_exceptions=True,
                )

            # Normalize exceptions → empty
            if isinstance(mem0_results, Exception):
                mem0_results = []
            if isinstance(kb_results, Exception):
                kb_results = []
            if isinstance(graphiti_data, Exception) or not isinstance(graphiti_data, dict):
                graphiti_data = {}
            if isinstance(exp_results, Exception) or not isinstance(exp_results, list):
                exp_results = []
            if isinstance(graphrag_result, Exception) or not isinstance(graphrag_result, dict):
                graphrag_result = {}

            # Extract graphiti items for fusion
            timeline_items = _graphiti_to_items(graphiti_data) if graphiti_data else []

            # ── RRF fusion ──
            mem0_strs = [
                r.get("memory", str(r)) if isinstance(r, dict) else str(r)
                for r in mem0_results
            ]
            # 平行时间元数据 (created_at 用于时间聚类排序)
            mem0_meta = [
                {"created_at": r.get("created_at")} if isinstance(r, dict) else {}
                for r in mem0_results
            ]
            # 将 graphrag_result dict 转为 list[dict] 供 fuse() 使用
            graphrag_items = self._graphrag_to_items(graphrag_result)

            fused = self._fusion.fuse(
                mem0_strs, kb_results,
                timeline_items=timeline_items,
                experience_results=exp_results,
                graphrag_results=graphrag_items,
                query=user_input,
                mem0_meta=mem0_meta,
            )

            # ── Format <system-reminder> ──
            if fused:
                reminder = ContextAssembler.format_system_reminder(
                    fused,
                    mem0_raw=mem0_strs,
                    kb_raw=kb_results,
                )

        # ── Build message list ──
        msgs = [_make_system(system_prompt)]

        # ── Layer ①b: Skill Injection (§10) ──
        skill_text = ""
        try:
            skill_text = await SkillRegistry.render_injection(
                project_id=project_id,
                role_id=role_id,
                token_budget=_cfg.TOKEN_BUDGET_SKILL_INJECTION,
            )
            if skill_text:
                msgs.append(_make_system(skill_text))
        except Exception:
            pass  # best-effort, never block

        if summary:
            msgs.append(_make_system(f"<summary>\n{summary}\n</summary>"))

        # ── Auto-hints (minimal mode only) ──
        if mode == "minimal":
            try:
                hints = await self._auto_hinter.get_hints(
                    user_input,
                    get_mem0(),
                    _build_weknora_client(),
                    _get_kb_id_by_name(_cfg.WEKNORA_KB_NAME),
                    project_id,
                )
                if hints:
                    msgs.insert(1, _make_system(hints))
            except Exception:
                pass  # hints are best-effort, never block

        # ── P0-2: Compartment history injection (m[0] cache-stable prefix) ──
        compartments = state.get("_compartments", [])
        if compartments:
            from .decay_render import render_all_compartments
            current_tokens = estimate_tokens(messages) if messages else 0
            budget_pressure = current_tokens / max(_cfg.MAX_TOKEN_BUDGET, 1)
            comp_text = render_all_compartments(compartments, budget_pressure)
            if comp_text:
                msgs.append(_make_system(
                    f"<session-history>\n{comp_text}\n</session-history>"
                ))

        if reminder:
            msgs.append(_make_system(reminder))

        # Runtime context
        runtime = (
            f"<runtime_context>\n"
            f"  当前时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  项目: {project_id}\n"
            f"  角色: {role_id}\n"
            f"</runtime_context>"
        )
        msgs.append(_make_system(runtime))

        # Recent history (last 20)
        for m in messages[-20:]:
            msgs.append(m)

        # Current user message
        msgs.append(_make_user(user_input))

        # ── Token budget check ──
        layers = {
            "system_prompt": system_prompt,
            "skill_injection": skill_text,
            "summary": summary,
            "ltm_kb_timeline": reminder,
            "runtime": runtime,
            "recent_history": messages[-20:],
            "user_message": user_input,
        }
        allocation = self._token_budget.allocate(layers)

        return ContextAssembly(
            messages=msgs,
            token_estimate=allocation.total_estimate,
            within_budget=allocation.within_budget,
            budget_warnings=allocation.warnings,
            layer_tokens={
                name: estimate_tokens_str(c) if isinstance(c, str) else estimate_tokens(c) if isinstance(c, list) else 0
                for name, c in layers.items()
            },
            fused_results=fused,
            mode_used=actual_mode,
        )

    # ================================================================
    # Compression
    # ================================================================

    async def compress_if_needed(self, state: DobbyState) -> bool:
        """Check token budget and trigger compression if needed.

        Returns True if compression was triggered.
        """
        messages = state.get("messages", [])
        if not needs_compression(messages):
            return False

        old_summary = state.get("summary", "")
        old_tasks = state.get("tasks", {})

        compress_msgs = build_compress_messages(
            existing_summary=old_summary,
            existing_tasks=old_tasks,
            recent_messages=messages,
        )

        try:
            resp = await _call_model(compress_msgs)
            content = _msg_content(resp)
            parsed = parse_compress_response(content)
        except Exception:
            parsed = {"summary": old_summary, "tasks": old_tasks,
                      "decisions": [], "context_to_preserve": ""}

        new_summary = parsed.get("summary", old_summary)
        new_tasks = parsed.get("tasks", old_tasks) or old_tasks
        new_decisions = parsed.get("decisions", state.get("decisions", []))
        new_context = parsed.get("context_to_preserve", state.get("context_to_preserve", ""))

        trimmed = trim_messages(messages)

        # Update state in-place
        state["summary"] = new_summary
        state["tasks"] = new_tasks
        state["decisions"] = new_decisions
        state["context_to_preserve"] = new_context
        state["messages"] = trimmed
        state["token_estimate"] = estimate_tokens(trimmed)
        state["compression_count"] = state.get("compression_count", 0) + 1

        return True

    # ================================================================
    # Memory CRUD
    # ================================================================

    async def remember(
        self,
        content: str,
        importance: float = 0.5,
        memory_type: str = "fact",
        agent_id: str | None = None,
    ) -> list:
        """Write to Mem0 long-term memory.

        Args:
            content: text to remember
            importance: 0-1 importance score
            memory_type: "fact" | "decision" | "preference" | "reflection"
            agent_id: Mem0 agent isolation key (defaults to role_id)

        Returns:
            list of memory items created by Mem0
        """
        if agent_id is None:
            agent_id = self.project_id or _cfg.MEM0_USER_ID  # ← shared project pool

        user_id = self.project_id or _cfg.MEM0_USER_ID

        try:
            def _sync_add():
                m = get_mem0()
                return m.add(
                    content,
                    user_id=user_id,
                    agent_id=agent_id,
                    metadata={
                        "memory_type": memory_type,
                        "importance": importance,
                        "role": self.role_id,
                        "recall_count": 0,   # P0-1: initialize recall counter
                        "strength": 1.0,     # P0-1: initialize at full strength
                    },
                    infer=False,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_sync_add).result(timeout=30)
                # mem0 v2 返回 {"results": [...]} — 与 recall() 相同的解包
                items = result.get("results", result) if isinstance(result, dict) else result
                # 实体图增量: 图已加载时同步新记忆
                if self._entity_graph is not None:
                    for item in items if isinstance(items, list) else [items]:
                        if isinstance(item, dict):
                            mid = str(item.get("id", ""))
                            content = str(item.get("memory", item.get("data", "")) or "")
                            if mid and content:
                                self._entity_graph.add_memory(
                                    mid, content, EntityExtractor.extract(content),
                                    created_at=item.get("created_at"),
                                )
                # 返回解包后的列表 (mem0 v2 dict 形状下旧代码返回 [{"results": [...]}],
                # 文档契约是 "list of memory items created by Mem0", 代码库无调用方消费返回值)
                return items if isinstance(items, list) else [items]
        except Exception:
            return []

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        agent_id: str | None = None,
    ) -> list:
        """Search Mem0 long-term memory.

        Args:
            query: search query
            top_k: max results
            agent_id: Mem0 agent isolation key (defaults to role_id)

        Returns:
            list of memory dicts from Mem0
        """
        if agent_id is None:
            agent_id = self.project_id or _cfg.MEM0_USER_ID  # ← shared project pool

        user_id = self.project_id or _cfg.MEM0_USER_ID

        try:
            def _sync_search():
                m = get_mem0()
                return m.search(
                    query,
                    filters={"user_id": user_id, "agent_id": agent_id},
                    top_k=top_k,
                    threshold=0.3,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_sync_search).result(timeout=30)

                # P0-1: Bump recall_count for high-similarity results
                _bumped = 0
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict):
                            sim = item.get("score", item.get("similarity", 0))
                            if sim >= _cfg.MEMORY_REINFORCE_THRESHOLD:
                                try:
                                    meta = item.get("metadata", {})
                                    if isinstance(meta, dict):
                                        rc = int(meta.get("recall_count", 0)) + 1
                                        meta["recall_count"] = rc
                                        meta["strength"] = item.get("strength", 1.0)
                                        get_mem0().update(item["id"], metadata=meta)
                                        _bumped += 1
                                except Exception:
                                    pass
                    return result
                if isinstance(result, dict):
                    return result.get("results", [])
                return []
        except Exception:
            return []

    async def forget(self, memory_id: str) -> bool:
        """Delete a single memory by ID.

        Returns True if deletion succeeded.
        """
        try:
            def _sync_delete():
                m = get_mem0()
                m.delete(memory_id)
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_sync_delete).result(timeout=15)
                return True
        except Exception:
            return False

    # ================================================================
    # Reflection & consolidation
    # ================================================================

    async def reflect(self, project_id: str | None = None) -> dict:
        """Trigger reflection (Generative Agents paradigm).

        Returns:
            {"skipped": True, "reason": "..."} if skipped
            {"insights": [...], "patterns": "...", "written": int, "l3_upgraded": int} if run
        """
        pid = project_id or self.project_id
        user_id = pid or _cfg.MEM0_USER_ID
        return await reflect_if_needed(pid, user_id=user_id)

    async def consolidate_experiences(
        self,
        project_id: str | None = None,
    ) -> dict:
        """Trigger Phase 2 experience consolidation (per-night batch).

        Returns:
            {"skipped": True, "reason": "..."} if skipped
            {"extracts_processed": N, "experiences_created": N, ...} if run
        """
        pid = project_id or self.project_id
        return await consolidate_if_needed(pid)

    # ================================================================
    # Dreamer 夜间维护
    # ================================================================

    async def run_dreamer(
        self,
        project_id: str | None = None,
        task_name: str | None = None,
    ) -> dict:
        """运行 Dreamer 维护任务。

        Args:
            project_id: 项目ID，None=使用当前
            task_name: 指定运行单个任务，None=运行所有到期任务

        Returns:
            {"decay": DreamerResult, "verify": DreamerResult, ...}
        """
        from .dreamer import DreamerScheduler

        pid = project_id or self.project_id
        scheduler = DreamerScheduler(pid)

        if task_name is not None:
            result = await scheduler.run_task(task_name)
            return {task_name: result}
        return await scheduler.run_due_tasks()

    # ================================================================
    # Knowledge base search
    # ================================================================

    async def search_knowledge(
        self,
        query: str,
        top_k: int = 3,
        kb_names: list[str] | None = None,
    ) -> list[dict]:
        """Search WeKnora knowledge base via hybrid search.

        Args:
            query: search query
            top_k: max results per KB
            kb_names: KB names to search (defaults to configured KB)

        Returns:
            list of result dicts with content/score
        """
        if kb_names is None:
            kb_names = [_cfg.WEKNORA_KB_NAME]

        all_results = []
        try:
            wc = _build_weknora_client()

            for kb_name in kb_names:
                kb_id = _get_kb_id_by_name(kb_name)
                if kb_id:
                    results = wc.hybrid_search(
                        kb_id=kb_id,
                        query=query,
                        vector_threshold=0.15,
                        keyword_threshold=0.15,
                    )
                    for r in results[:top_k]:
                        r["kb_name"] = kb_name
                        all_results.append(r)
        except Exception:
            pass

        return all_results

    # ================================================================
    # Internal helpers
    # ================================================================

    async def _get_entity_graph(
        self, project_id: str, role_id: str,
    ) -> EntityGraph | None:
        """懒加载实体图: 首次调用时从 mem0 全量拉取建图, TTL 300s 缓存.

        对标 langgraph_utils._kb_cache 懒加载模式 + agentmemory V4 ingest 全量建图.
        mem0 不可用时返回 None (优雅降级, 走原检索路径).
        user_id 与 recall/remember 一致回退到 _cfg.MEM0_USER_ID,
        保证默认构造 (project_id=\"\") 也能按共享项目池建图, 扩散不静默失效.
        """
        import time
        now = time.monotonic()
        if (self._entity_graph is not None
                and now - self._entity_graph_ts < self._ENTITY_GRAPH_TTL):
            return self._entity_graph

        user_id = project_id or _cfg.MEM0_USER_ID  # 与 recall/remember 一致的回退
        try:
            def _sync_get_all():
                m = get_mem0()
                return m.get_all(
                    filters={"user_id": user_id, "agent_id": f"role:{role_id}"},
                    top_k=500,  # 全量拉取 (demo 规模)
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                all_mems = pool.submit(_sync_get_all).result(timeout=30)
            # mem0 v2 返回 {"results": [...]} — 与 recall() 相同的解包 (memory_manager.py:633-634)
            if isinstance(all_mems, dict):
                all_mems = all_mems.get("results", [])
        except Exception:
            return None  # 优雅降级: mem0 不可用时无图, 走原检索路径

        graph = EntityGraph()
        extractor = EntityExtractor()
        for item in all_mems or []:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id", ""))
            content = str(item.get("memory", ""))
            created = item.get("created_at") or item.get("updated_at")
            if mid and content:
                graph.add_memory(
                    mid, content, extractor.extract(content),
                    created_at=str(created) if created else None,
                )

        self._entity_graph = graph
        self._entity_graph_ts = now
        return graph

    async def _search_memory(
        self,
        query: str,
        project_id: str,
        role_id: str,
    ) -> list:
        """Internal: Mem0 search with proper scoping + 实体图扩散扩展候选集.

        对标 agentmemory V4 _candidates() entity-centric retrieval:
        recall() 基础结果之上, 用实体图 2 跳扩散补充跨会话关联记忆.
        """
        results = await self.recall(
            query,
            top_k=_cfg.MEMORY_TOP_K,
            agent_id=f"role:{role_id}",
        )

        # 实体图扩散: 扩展候选集 (对标 agentmemory V4 _candidates() entity-centric retrieval)
        graph = await self._get_entity_graph(project_id, role_id)
        if graph:
            try:
                query_entities = EntityExtractor.extract(query)
                activation = graph.spreading_activation(query_entities, max_depth=2)
                existing_ids = {
                    str(r.get("id", "")) for r in results if isinstance(r, dict)
                }
                for mem_id, act in activation.items():
                    if mem_id not in existing_ids:
                        content = graph.get_content(mem_id)
                        created = graph.get_created_at(mem_id)
                        if content:
                            results.append({
                                "id": mem_id,
                                "memory": content,
                                "created_at": created,
                                "score": float(act),
                                "metadata": {"source": "entity_graph"},
                            })
            except Exception:
                pass  # 扩散失败不影响基础检索

        return results

    async def _search_knowledge(self, query: str) -> list[dict]:
        """Internal: WeKnora search."""
        return await self.search_knowledge(query)

    async def _search_graph_rag(self, query: str) -> dict:
        """Internal: GraphRAG search with graceful degradation."""
        if not _cfg.LIGHTRAG_ENABLED:
            return {}
        try:
            from .graph_rag_engine import get_graph_rag
            engine = await get_graph_rag(self.project_id)
            return await engine.search(query, mode=_cfg.LIGHTRAG_QUERY_MODE)
        except Exception:
            return {}

    @staticmethod
    def _graphrag_to_items(data: dict) -> list[dict]:
        """将 graphrag search() 返回的 dict 转换为可融合的条目列表。

        search() 返回 {"entities": [...], "relations": [...], "chunks": [...], "formatted": "..."}
        对于 RRF 融合，使用 formatted 字段作为内容。
        """
        if not data or not data.get("formatted"):
            return []
        return [{
            "content": data["formatted"],
            "formatted": data["formatted"],
            "entities": data.get("entities", []),
            "relations": data.get("relations", []),
            "chunks": data.get("chunks", []),
        }]

    @staticmethod
    def _default_system_prompt(role_id: str) -> str:
        """Return default system prompt for a role."""
        prompts = {
            "dobby_core": (
                "你是 Dobby，工程管理 AI 助手。回答工程管理相关问题，"
                "查询和管理项目任务、进度、整改状态，记录重要决策和事实。"
            ),
            "safety_director": (
                "你是 Dobby 安全总监。查询和解读工程安全规范、标准、法规，"
                "引用具体规范编号，给出权威、可操作的指导。"
            ),
            "supervisor": (
                "你是 Dobby 监理。负责整改复核、合规检查和质量把关。"
            ),
        }
        return prompts.get(role_id, prompts["dobby_core"])


# ============================================================
# Module-level convenience
# ============================================================

# Re-export estimate_tokens_str for token_budget usage
from .token_budget import estimate_tokens_str  # noqa: E402, F811
