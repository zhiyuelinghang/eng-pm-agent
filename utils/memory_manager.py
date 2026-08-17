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
import hashlib
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
from .compression_guard import CompressionGuard, QualityScorer
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
    memory_results: list = field(default_factory=list)
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

    def __init__(
        self,
        project_id: str = "",
        role_id: str = "dobby_core",
        runtime_settings: Any | None = None,
    ):
        self.project_id = project_id
        self.role_id = role_id
        self._runtime_settings: dict[str, Any] = {}
        self._token_budget = TokenBudget()
        self._compression_guard = CompressionGuard()
        # Entity graph cache survives settings refreshes between chat runs.
        self._entity_graph: EntityGraph | None = None
        self._entity_graph_ts: float = 0.0
        self._entity_graph_signature: tuple[tuple[str, str], ...] = ()
        self.configure(runtime_settings)

    def invalidate_entity_graph(self) -> None:
        """Drop cached entity expansion after a memory mutation."""

        self._entity_graph = None
        self._entity_graph_ts = 0.0
        self._entity_graph_signature = ()

    @staticmethod
    def _as_settings_dict(settings: Any | None) -> dict[str, Any]:
        if settings is None:
            return {}
        if hasattr(settings, "model_dump"):
            return dict(settings.model_dump())
        if isinstance(settings, dict):
            return dict(settings)
        return {}

    def _setting(self, name: str, fallback: Any) -> Any:
        return self._runtime_settings.get(name, fallback)

    def configure(self, settings: Any | None) -> None:
        """Apply one platform-global policy without owning model context size."""

        values = self._as_settings_dict(settings)
        if values:
            self._runtime_settings = values
        self._fusion = MemoryFusion(
            default_weights={
                "mem0": self._setting("fusion_weight_mem0", _cfg.FUSION_WEIGHT_MEM0),
                "kb": self._setting("fusion_weight_kb", _cfg.FUSION_WEIGHT_KB),
                "timeline": self._setting("fusion_weight_timeline", _cfg.FUSION_WEIGHT_TIMELINE),
                "experience": self._setting("fusion_weight_experience", _cfg.FUSION_WEIGHT_EXPERIENCE),
                "graphrag": self._setting("fusion_weight_graphrag", _cfg.FUSION_WEIGHT_GRAPHRAG),
            },
            rrf_k=int(self._setting("rrf_k", _cfg.RRF_K)),
            mmr_lambda=float(
                self._setting("fusion_mmr_lambda", _cfg.FUSION_MMR_LAMBDA),
            ),
        )
        self._auto_hinter = AutoHinter(hint_threshold=_cfg.AUTO_HINT_THRESHOLD)
        self._compression_guard.configure(
            max_consecutive=int(self._setting(
                "compression_max_consecutive",
                _cfg.COMPRESSION_MAX_CONSECUTIVE,
            )),
            quality_threshold=float(self._setting(
                "compression_quality_threshold",
                _cfg.COMPRESSION_QUALITY_THRESHOLD,
            )),
            min_rounds_between=int(self._setting(
                "compression_min_rounds_between",
                _cfg.COMPRESSION_MIN_ROUNDS_BETWEEN,
            )),
        )

    def _token_budget_for(self, state: DobbyState) -> TokenBudget:
        max_budget = int(state.get("max_token_budget") or _cfg.MAX_TOKEN_BUDGET)
        return TokenBudget(
            max_budget=max_budget,
            layer_limits={
                "system_prompt": int(self._setting(
                    "token_budget_system_prompt",
                    _cfg.TOKEN_BUDGET_SYSTEM_PROMPT,
                )),
                "skill_injection": int(self._setting(
                    "token_budget_skill_injection",
                    _cfg.TOKEN_BUDGET_SKILL_INJECTION,
                )),
                "summary": int(self._setting(
                    "token_budget_summary",
                    _cfg.TOKEN_BUDGET_SUMMARY,
                )),
                "ltm_kb_timeline": int(self._setting(
                    "token_budget_ltm_kb_timeline",
                    _cfg.TOKEN_BUDGET_LTM_KB_TIMELINE,
                )),
                "runtime": int(self._setting(
                    "token_budget_runtime",
                    _cfg.TOKEN_BUDGET_RUNTIME,
                )),
                "recent_history": int(self._setting(
                    "token_budget_recent_history",
                    _cfg.TOKEN_BUDGET_RECENT_HISTORY,
                )),
            },
            output_reserve=int(self._setting(
                "token_budget_output_reserve",
                _cfg.TOKEN_BUDGET_OUTPUT_RESERVE,
            )),
        )

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
            compression_trigger_ratio=float(self._setting(
                "compression_trigger_ratio",
                _cfg.CONTEXT_TRIGGER_RATIO,
            )),
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
        memory_targets = self._normalise_memory_targets(
            state.get("memory_targets", []),
        )
        tasks = state.get("tasks", {})
        messages = state.get("messages", [])
        session_id = state.get("thread_id", "")

        # 1. Decay — @deprecated old path: lifecycle.apply_decay() still exists
        # for backward compatibility. New code should use:
        #   self.run_dreamer(task_name="decay") → DecayV2Task via DreamerScheduler
        if memory_targets:
            decay_scopes = []
            reflection_scopes = []
            for target in memory_targets:
                namespace = (
                    f"{target['user_id']}\0{target['agent_id']}"
                ).encode("utf-8")
                lifecycle_scope = (
                    "memory_scope_"
                    + hashlib.sha256(namespace).hexdigest()[:32]
                )
                decay_scopes.append({
                    "scope_type": target.get("scope_type", ""),
                    **await apply_decay(
                        lifecycle_scope,
                        user_id=str(target["user_id"]),
                        agent_id=str(target["agent_id"]),
                    ),
                })
                reflection_scopes.append({
                    "scope_type": target.get("scope_type", ""),
                    **await reflect_if_needed(
                        lifecycle_scope,
                        user_id=str(target["user_id"]),
                        agent_id=str(target["agent_id"]),
                        metadata={
                            key: value
                            for key, value in target.items()
                            if key not in {"user_id", "agent_id"}
                            and value is not None
                        },
                    ),
                })
            decay_result = {
                "pruned": sum(int(item.get("pruned", 0)) for item in decay_scopes),
                "updated": sum(int(item.get("updated", 0)) for item in decay_scopes),
                "scanned": sum(int(item.get("scanned", 0)) for item in decay_scopes),
                "scopes": decay_scopes,
            }
            reflection_result = {
                "insights": [
                    insight
                    for item in reflection_scopes
                    for insight in item.get("insights", [])
                ],
                "written": sum(int(item.get("written", 0)) for item in reflection_scopes),
                "scopes": reflection_scopes,
            }
            self.invalidate_entity_graph()
        else:
            user_id = project_id or _cfg.MEM0_USER_ID
            decay_result = await apply_decay(project_id, user_id=user_id)
            reflection_result = await reflect_if_needed(
                project_id,
                user_id=user_id,
            )

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
                    "decay_deleted": decay_result.get(
                        "pruned",
                        decay_result.get("deleted", 0),
                    ),
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
        memory_targets = state.get("memory_targets", [])
        if not isinstance(memory_targets, list):
            memory_targets = []
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
        mem0_results = []
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
                    self._search_memory(
                        user_input,
                        project_id,
                        role_id,
                        memory_targets=memory_targets,
                    ),
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
                token_budget=int(self._setting(
                    "token_budget_skill_injection",
                    _cfg.TOKEN_BUDGET_SKILL_INJECTION,
                )),
            )
            if skill_text:
                msgs.append(_make_system(skill_text))
        except Exception:
            pass  # best-effort, never block

        if summary:
            msgs.append(_make_system(f"<summary>\n{summary}\n</summary>"))

        # ── Auto-hints (minimal mode only) ──
        if mode == "minimal" and _cfg.WEKNORA_ENABLED:
            try:
                hints = await self._auto_hinter.get_hints(
                    user_input,
                    get_mem0(),
                    _build_weknora_client(),
                    _get_kb_id_by_name(_cfg.WEKNORA_KB_NAME),
                    project_id,
                    memory_targets=memory_targets,
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
            budget_pressure = current_tokens / max(
                int(state.get("max_token_budget") or _cfg.MAX_TOKEN_BUDGET),
                1,
            )
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
        allocation = self._token_budget_for(state).allocate(layers)

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
            memory_results=mem0_results,
            mode_used=actual_mode,
        )

    # ================================================================
    # Compression
    # ================================================================

    async def compress_if_needed(
        self,
        state: DobbyState,
        *,
        call_model: Any | None = None,
    ) -> bool:
        """Check token budget and trigger compression if needed.

        Returns True if compression was triggered.
        """
        messages = state.get("messages", [])
        max_budget = int(state.get("max_token_budget") or _cfg.MAX_TOKEN_BUDGET)
        trigger_ratio = float(state.get("compression_trigger_ratio") or self._setting(
            "compression_trigger_ratio",
            _cfg.CONTEXT_TRIGGER_RATIO,
        ))
        threshold = max(1, int(max_budget * trigger_ratio))
        if not needs_compression(messages, threshold=threshold):
            return False

        old_summary = state.get("summary", "")
        old_tasks = state.get("tasks", {})
        keep_messages = int(self._setting(
            "compression_keep_messages",
            _cfg.COMPRESSION_KEEP_MESSAGES,
        ))

        pressure = estimate_tokens(messages) / max(max_budget, 1)
        emergency_ratio = float(self._setting(
            "emergency_compression_ratio",
            _cfg.EMERGENCY_COMPRESSION_THRESHOLD,
        ))
        if pressure >= emergency_ratio:
            state["messages"] = trim_messages(messages, keep=keep_messages)
            state["token_estimate"] = estimate_tokens(state["messages"])
            state["compression_count"] = state.get("compression_count", 0) + 1
            state["last_compress_round"] = state.get("message_count", 0)
            return True

        decision = self._compression_guard.decide(messages, state)
        if decision.action == "reset":
            system_messages = [
                message
                for message in messages
                if getattr(message, "role", "") == "system"
            ][:1]
            non_system_messages = [
                message
                for message in messages
                if getattr(message, "role", "") != "system"
            ]
            state["summary"] = ""
            state["messages"] = system_messages + non_system_messages[-10:]
            state["token_estimate"] = estimate_tokens(state["messages"])
            state["compression_count"] = state.get("compression_count", 0) + 1
            state["last_compress_round"] = state.get("message_count", 0)
            state.update(self._compression_guard.on_reset(state))
            return True
        if decision.action == "trim_only":
            state["messages"] = trim_messages(messages, keep=keep_messages)
            state["token_estimate"] = estimate_tokens(state["messages"])
            state["compression_count"] = state.get("compression_count", 0) + 1
            state["last_compress_round"] = state.get("message_count", 0)
            return True

        compress_msgs = build_compress_messages(
            existing_summary=old_summary,
            existing_tasks=old_tasks,
            recent_messages=messages,
            system_prompt=self._setting("compression_system_prompt", None),
            user_prompt=self._setting("compression_user_prompt", None),
            incremental_prompt=self._setting(
                "compression_incremental_prompt",
                None,
            ),
            incremental=(
                self._setting("compression_mode", _cfg.COMPRESSION_MODE)
                == "incremental"
            ),
        )

        try:
            if call_model is None:
                async def model_call(msgs):
                    return await _call_model(msgs, intent="compress")
            else:
                model_call = call_model
            resp = await model_call(compress_msgs)
            content = _msg_content(resp)
            parsed = parse_compress_response(content)
        except Exception:
            parsed = {"summary": old_summary, "tasks": old_tasks,
                      "decisions": [], "context_to_preserve": ""}

        new_summary = parsed.get("summary", old_summary)
        new_tasks = parsed.get("tasks", old_tasks) or old_tasks
        new_decisions = parsed.get("decisions", state.get("decisions", []))
        new_context = parsed.get("context_to_preserve", state.get("context_to_preserve", ""))

        if bool(self._setting(
            "compression_background",
            _cfg.COMPRESSION_BACKGROUND,
        )):
            try:
                from .historian import historian_cycle

                historian_update = await asyncio.wait_for(
                    historian_cycle(
                        {
                            "messages": messages,
                            "_compartments": state.get("_compartments", []),
                            "summary": new_summary,
                            "max_token_budget": max_budget,
                            "historian_trigger_ratio": float(self._setting(
                                "historian_trigger_ratio",
                                0.3,
                            )),
                        },
                        _call_model_fn=model_call,
                    ),
                    timeout=3.0,
                )
                if historian_update:
                    state.update(historian_update)
            except Exception:
                pass

        trimmed = trim_messages(
            messages,
            keep=keep_messages,
        )

        # Update state in-place
        state["summary"] = new_summary
        state["tasks"] = new_tasks
        state["decisions"] = new_decisions
        state["context_to_preserve"] = new_context
        state["messages"] = trimmed
        state["token_estimate"] = estimate_tokens(trimmed)
        state["compression_count"] = state.get("compression_count", 0) + 1
        state["last_compress_round"] = state.get("message_count", 0)
        state.update(self._compression_guard.on_compress(state))
        try:
            quality = QualityScorer.score_summary(
                new_summary,
                old_tasks,
                new_tasks,
                new_decisions,
                new_context,
            )
            state.update(
                self._compression_guard.record_quality(state, quality.score),
            )
        except Exception:
            pass

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
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        infer: bool = False,
    ) -> list:
        """Write to Mem0 long-term memory.

        Args:
            content: text to remember
            importance: 0-1 importance score
            memory_type: "fact" | "decision" | "preference" | "reflection"
            agent_id: Mem0 agent isolation key (defaults to role_id)
            user_id: Mem0 owner key (defaults to the legacy project pool)
            metadata: additional platform scope and source metadata
            infer: whether Mem0 should run LLM fact extraction

        Returns:
            list of memory items created by Mem0
        """
        if agent_id is None:
            agent_id = self.project_id or _cfg.MEM0_USER_ID  # ← shared project pool

        if user_id is None:
            user_id = self.project_id or _cfg.MEM0_USER_ID

        memory_metadata = {
            "memory_type": memory_type,
            "importance": importance,
            "role": self.role_id,
            "recall_count": 0,
            "strength": 1.0,
        }
        if metadata:
            memory_metadata.update(metadata)

        try:
            def _sync_add():
                m = get_mem0()
                return m.add(
                    content,
                    user_id=user_id,
                    agent_id=agent_id,
                    metadata=memory_metadata,
                    infer=infer,
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
        user_id: str | None = None,
    ) -> list:
        """Search Mem0 long-term memory.

        Args:
            query: search query
            top_k: max results
            agent_id: Mem0 agent isolation key (defaults to role_id)
            user_id: Mem0 owner key (defaults to the legacy project pool)

        Returns:
            list of memory dicts from Mem0
        """
        if agent_id is None:
            agent_id = self.project_id or _cfg.MEM0_USER_ID  # ← shared project pool

        if user_id is None:
            user_id = self.project_id or _cfg.MEM0_USER_ID

        try:
            def _sync_search():
                m = get_mem0()
                return m.search(
                    query,
                    filters={"user_id": user_id, "agent_id": agent_id},
                    top_k=top_k,
                    threshold=float(self._setting(
                        "recall_threshold",
                        _cfg.MEMORY_THRESHOLD,
                    )),
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_sync_search).result(timeout=30)

                # P0-1: Bump recall_count for high-similarity results
                items = (
                    result.get("results", [])
                    if isinstance(result, dict)
                    else result
                    if isinstance(result, list)
                    else []
                )

                # P0-1: Bump recall_count for high-similarity results.
                # mem0ai 2.x wraps search results in {"results": [...]}, so
                # reinforcement must run after normalising the response shape.
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    sim = item.get("score", item.get("similarity", 0))
                    if sim < float(self._setting(
                        "recall_reinforce_threshold",
                        _cfg.MEMORY_REINFORCE_THRESHOLD,
                    )):
                        continue
                    try:
                        meta = item.get("metadata", {})
                        if isinstance(meta, dict):
                            meta = dict(meta)
                            meta["recall_count"] = int(meta.get("recall_count", 0)) + 1
                            meta["strength"] = item.get("strength", 1.0)
                            get_mem0().update(item["id"], metadata=meta)
                    except Exception:
                        pass
                return items
        except Exception:
            return []

    @staticmethod
    def _normalise_memory_targets(value: Any) -> list[dict[str, Any]]:
        """Keep only complete, unique Mem0 namespace descriptors."""

        if not isinstance(value, (list, tuple)):
            return []
        targets: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            user_id = str(item.get("user_id") or "").strip()
            agent_id = str(item.get("agent_id") or "").strip()
            if not user_id or not agent_id:
                continue
            key = (user_id, agent_id)
            if key in seen:
                continue
            seen.add(key)
            targets.append({**item, "user_id": user_id, "agent_id": agent_id})
        return targets

    async def recall_scopes(
        self,
        query: str,
        memory_targets: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search all personal scopes visible to the current user and project."""

        targets = self._normalise_memory_targets(memory_targets)
        if not targets:
            return []
        limit = max(1, int(top_k))
        batches = await asyncio.gather(
            *(
                self.recall(
                    query,
                    top_k=limit,
                    user_id=str(target["user_id"]),
                    agent_id=str(target["agent_id"]),
                )
                for target in targets
            ),
            return_exceptions=True,
        )

        by_key: dict[str, dict[str, Any]] = {}
        for target, batch in zip(targets, batches):
            if isinstance(batch, Exception) or not isinstance(batch, list):
                continue
            for item in batch:
                if not isinstance(item, dict):
                    continue
                tagged = dict(item)
                metadata = dict(tagged.get("metadata") or {})
                for name in (
                    "scope_version",
                    "scope_type",
                    "tenant_id",
                    "identity_type",
                    "platform_user_id",
                    "project_id",
                ):
                    if target.get(name) is not None:
                        metadata.setdefault(name, target.get(name))
                tagged["metadata"] = metadata
                tagged["scope_type"] = metadata.get("scope_type")
                content = str(tagged.get("memory") or "").strip()
                key = (
                    f"text:{' '.join(content.casefold().split())}"
                    if content
                    else str(tagged.get("id") or "")
                )
                if not key:
                    continue
                previous = by_key.get(key)
                if previous is None or float(tagged.get("score") or 0) > float(
                    previous.get("score") or 0,
                ):
                    by_key[key] = tagged

        return sorted(
            by_key.values(),
            key=lambda item: (
                float(item.get("score") or 0),
                str(item.get("updated_at") or item.get("created_at") or ""),
            ),
            reverse=True,
        )[:limit]

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
                self.invalidate_entity_graph()
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
        if not _cfg.WEKNORA_ENABLED:
            return []

        all_results = []
        try:
            wc = _build_weknora_client()

            if kb_names is None:
                configured_name = str(_cfg.WEKNORA_KB_NAME or "").strip()
                if configured_name:
                    kb_names = [configured_name]
                else:
                    kb_names = [
                        str(item.get("name") or "")
                        for item in wc.list_knowledge_bases()
                        if item.get("name")
                    ]

            for kb_name in kb_names:
                kb_id = _get_kb_id_by_name(kb_name)
                if kb_id:
                    results = wc.hybrid_search(
                        kb_id=kb_id,
                        query=query,
                        vector_threshold=0.5,
                        keyword_threshold=0.3,
                        match_count=top_k,
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
                    for raw_result in results[:top_k]:
                        if not isinstance(raw_result, dict):
                            continue
                        result = dict(raw_result)
                        knowledge_id = str(
                            result.get("knowledge_id") or "",
                        )
                        detail = details.get(knowledge_id, {})
                        result["kb_name"] = kb_name
                        result["title"] = (
                            result.get("knowledge_title")
                            or detail.get("title")
                            or ""
                        )
                        result["file_name"] = (
                            result.get("knowledge_filename")
                            or detail.get("file_name")
                            or ""
                        )
                        result["file_type"] = detail.get("file_type") or ""
                        result["file_size"] = detail.get("file_size")
                        result["source"] = (
                            result.get("knowledge_source")
                            or detail.get("source")
                            or ""
                        )
                        all_results.append(result)
        except Exception:
            pass

        return all_results

    # ================================================================
    # Internal helpers
    # ================================================================

    async def _get_entity_graph(
        self,
        project_id: str,
        role_id: str,
        memory_targets: list[dict[str, Any]] | None = None,
    ) -> EntityGraph | None:
        """懒加载实体图: 首次调用时从 mem0 全量拉取建图, TTL 300s 缓存.

        对标 langgraph_utils._kb_cache 懒加载模式 + agentmemory V4 ingest 全量建图.
        mem0 不可用时返回 None (优雅降级, 走原检索路径).
        user_id 与 recall/remember 一致回退到 _cfg.MEM0_USER_ID,
        保证默认构造 (project_id=\"\") 也能按共享项目池建图, 扩散不静默失效.
        """
        import time
        targets = self._normalise_memory_targets(memory_targets or [])
        if not targets:
            user_id = project_id or _cfg.MEM0_USER_ID
            targets = [{"user_id": user_id, "agent_id": user_id}]
        signature = tuple(sorted(
            (str(item["user_id"]), str(item["agent_id"]))
            for item in targets
        ))
        now = time.monotonic()
        if (self._entity_graph is not None
                and self._entity_graph_signature == signature
                and now - self._entity_graph_ts < self._ENTITY_GRAPH_TTL):
            return self._entity_graph

        try:
            def _sync_get_all():
                m = get_mem0()
                merged: list[dict[str, Any]] = []
                for target in targets:
                    result = m.get_all(
                        filters={
                            "user_id": str(target["user_id"]),
                            "agent_id": str(target["agent_id"]),
                        },
                        top_k=500,
                    )
                    items = (
                        result.get("results", [])
                        if isinstance(result, dict)
                        else result
                    )
                    if isinstance(items, list):
                        merged.extend(item for item in items if isinstance(item, dict))
                return merged
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                all_mems = pool.submit(_sync_get_all).result(timeout=30)
        except Exception:
            return None  # 优雅降级: mem0 不可用时无图, 走原检索路径

        graph = EntityGraph()
        extractor = EntityExtractor()
        seen_ids: set[str] = set()
        for item in all_mems or []:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id", ""))
            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)
            content = str(item.get("memory", ""))
            created = item.get("created_at") or item.get("updated_at")
            if mid and content:
                graph.add_memory(
                    mid, content, extractor.extract(content),
                    created_at=str(created) if created else None,
                )

        self._entity_graph = graph
        self._entity_graph_ts = now
        self._entity_graph_signature = signature
        return graph

    async def _search_memory(
        self,
        query: str,
        project_id: str,
        role_id: str,
        memory_targets: list[dict[str, Any]] | None = None,
    ) -> list:
        """Internal: Mem0 search with proper scoping + 实体图扩散扩展候选集.

        对标 agentmemory V4 _candidates() entity-centric retrieval:
        recall() 基础结果之上, 用实体图 2 跳扩散补充跨会话关联记忆.
        """
        top_k = int(self._setting("recall_top_k", _cfg.MEMORY_TOP_K))
        targets = self._normalise_memory_targets(memory_targets or [])
        if targets:
            results = await self.recall_scopes(query, targets, top_k=top_k)
        else:
            results = await self.recall(
                query,
                top_k=top_k,
                agent_id=project_id or _cfg.MEM0_USER_ID,
            )

        # 实体图扩散: 扩展候选集 (对标 agentmemory V4 _candidates() entity-centric retrieval)
        graph = await self._get_entity_graph(
            project_id,
            role_id,
            memory_targets=targets,
        )
        if graph:
            try:
                query_entities = EntityExtractor.extract(query)
                activation = graph.spreading_activation(query_entities, max_depth=2)
                existing_ids = {
                    str(r.get("id", "")) for r in results if isinstance(r, dict)
                }
                candidates = [
                    (mem_id, act)
                    for mem_id, act in sorted(
                        activation.items(),
                        key=lambda item: float(item[1]),
                        reverse=True,
                    )
                    if mem_id not in existing_ids
                ][: max(top_k * 4, 20)]
                allowed_pairs = {
                    (str(target["user_id"]), str(target["agent_id"]))
                    for target in targets
                }

                def _validate_candidates() -> set[str]:
                    if not allowed_pairs:
                        return {str(mem_id) for mem_id, _ in candidates}
                    memory = get_mem0()
                    valid: set[str] = set()
                    for mem_id, _ in candidates:
                        try:
                            current = memory.get(str(mem_id))
                        except Exception:
                            continue
                        if not isinstance(current, dict):
                            continue
                        pair = (
                            str(current.get("user_id") or ""),
                            str(current.get("agent_id") or ""),
                        )
                        if pair in allowed_pairs:
                            valid.add(str(mem_id))
                    return valid

                valid_ids = await asyncio.to_thread(_validate_candidates)
                for mem_id, act in candidates:
                    if str(mem_id) not in valid_ids:
                        continue
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

        deduped: dict[str, Any] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            content = str(item.get("memory") or "").strip()
            key = (
                f"text:{' '.join(content.casefold().split())}"
                if content
                else str(item.get("id") or "")
            )
            if not key:
                continue
            previous = deduped.get(key)
            if previous is None or float(item.get("score") or 0) > float(
                previous.get("score") or 0,
            ):
                deduped[key] = item

        return sorted(
            deduped.values(),
            key=lambda item: float(item.get("score") or 0)
            if isinstance(item, dict)
            else 0.0,
            reverse=True,
        )[:top_k]

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
