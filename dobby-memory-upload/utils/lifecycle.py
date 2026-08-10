"""
Memory lifecycle management for Dobby (Step 4).

Decay simulation, reflection trigger, and experience extraction (Phase 1).
All three functions operate outside the LangGraph StateGraph — they are
called at session boundaries (start_session / end_session).

Imports from sibling utils modules to reuse existing patterns:
  - _call_model, get_mem0 from langgraph_utils
  - _extract_text from compression
  - config for all thresholds
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from datetime import datetime, timedelta, timezone
from typing import Any

# Package-relative imports
from . import config as _cfg
from .langgraph_utils import _call_model, get_mem0
from .compression import _extract_text


def _parse_json_response(text: str) -> dict:
    """Parse LLM JSON response, handling markdown fences.

    Unlike parse_compress_response (which only extracts summary/tasks),
    this returns the full parsed dict.
    """
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return {}


# ============================================================
# Internal helpers
# ============================================================

def _run_sync_mem0(func, timeout: float = 30):
    """Run a sync mem0 call in a thread pool, return result or None on error."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(func).result(timeout=timeout)
    except Exception:
        return None


def _compute_recency_score(
    created_at_str: str | None,
    half_life_days: float | None = None,
    importance: float = 0.5,
    memory_type: str = "fact",
    recall_count: int = 0,
) -> float:
    """Ebbinghaus decay (P0-1 upgrade).

    Now delegates to decay_curves.compute_recency_score_replacement
    which uses category-tuned decay rates, recall_count boost,
    and importance-modulated effective lambda.

    The half_life_days parameter is kept for backward compatibility
    but is IGNORED — decay rates are now category-based.
    """
    from .decay_curves import compute_recency_score_replacement

    return compute_recency_score_replacement(
        created_at_str=created_at_str,
        importance=importance,
        memory_type=memory_type,
        recall_count=recall_count,
    )


def _search_all_memories(user_id: str, limit: int = 200) -> list[dict]:
    """Retrieve all memories for a user_id using a broad search.

    Mem0 search() returns a list of dicts (verified against mem0ai 2.0.12).
    user_id must be passed via filters=, not as a top-level kwarg.
    Uses a minimal query '.' because Mem0 rejects empty queries.
    """
    m = get_mem0()
    try:
        result = m.search(".", filters={"user_id": user_id}, top_k=limit, threshold=0.0)
    except Exception:
        return []

    # Handle both possible return formats
    if isinstance(result, dict):
        items = result.get("results", [])
    elif isinstance(result, list):
        items = result
    else:
        return []

    return [r for r in items if isinstance(r, dict)]


def _get_memory_importance(mem: dict) -> float:
    """Extract importance from a memory dict. Defaults to 0.5."""
    meta = mem.get("metadata", {})
    if isinstance(meta, dict):
        imp = meta.get("importance")
        if imp is not None:
            return float(imp)
    return 0.5


def _get_memory_type(mem: dict) -> str:
    """Extract memory_type from Mem0 metadata. Defaults to 'fact'.

    Maps to Dobby's 4 experience buckets + risk + reflection.
    """
    meta = mem.get("metadata", {})
    if isinstance(meta, dict):
        mt = meta.get("memory_type", "")
        if mt in ("fact", "decision", "preference", "procedure",
                  "risk", "reflection", "environment"):
            return mt
    return "fact"


def _get_recall_count(mem: dict) -> int:
    """Extract recall_count from Mem0 metadata. Defaults to 0."""
    meta = mem.get("metadata", {})
    if isinstance(meta, dict):
        return int(meta.get("recall_count", 0))
    return 0


def _parse_dt_safe(created_at_str: str) -> datetime:
    """Parse created_at string safely, falling back to epoch - 1 year."""
    try:
        ts = str(created_at_str).replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.now(timezone.utc) - timedelta(days=365)


def _get_db_conn():
    """Create a fresh psycopg connection for experience_extracts writes."""
    import psycopg
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )


# ============================================================
# Module 1: Decay simulation
# ============================================================

async def apply_decay(
    project_id: str,
    user_id: str | None = None,
) -> dict:
    """@deprecated: Use MemoryManager.run_dreamer(task_name="decay") instead.
    
    This function is kept for backward compatibility.
    New code should use the DecayV2Task via DreamerScheduler.

    Apply Ebbinghaus decay: compute strength, prune weak, update stats.
    
    P0-1 Upgrade — now uses category-tuned decay rates, recall_count boost,
    and importance-modulated effective lambda from decay_curves.
    
    Algorithm (YourMemory src/jobs/decay_job.py:44-85):
      1. Scan all memories for the project
      2. Compute strength via decay_curves.compute_strength()
      3. If strength < MEMORY_PRUNE_THRESHOLD (0.05) → delete
      4. Otherwise → update metadata with new strength
    
    Returns:
        {"pruned": int, "updated": int, "scanned": int}
    """
    if user_id is None:
        user_id = _cfg.MEM0_USER_ID

    from .decay_curves import compute_strength

    m = get_mem0()
    memories = _search_all_memories(user_id)

    pruned = 0
    updated = 0

    for mem in memories:
        mem_id = mem.get("id", "")
        if not mem_id:
            continue

        created_at_str = mem.get("created_at", "")
        importance = _get_memory_importance(mem)
        memory_type = _get_memory_type(mem)
        recall_count = _get_recall_count(mem)

        # Parse timestamp
        try:
            ts = str(created_at_str).replace("Z", "+00:00")
            created_dt = datetime.fromisoformat(ts)
        except Exception:
            created_dt = datetime.now(timezone.utc) - timedelta(days=365)

        # Compute new strength
        strength = compute_strength(
            created_at=created_dt,
            importance=importance,
            memory_type=memory_type,
            recall_count=recall_count,
        )

        if strength < _cfg.MEMORY_PRUNE_THRESHOLD:
            try:
                m.delete(mem_id)
                pruned += 1
            except Exception:
                pass  # idempotent: might already be deleted
        else:
            # Update strength in metadata for future use
            try:
                existing_meta = mem.get("metadata", {})
                if isinstance(existing_meta, dict):
                    existing_meta["strength"] = strength
                    m.update(mem_id, metadata=existing_meta)
            except Exception:
                pass
            updated += 1

    return {"pruned": pruned, "updated": updated, "scanned": len(memories)}


# ============================================================
# Module 2: Reflection trigger
# ============================================================

REFLECTION_SYSTEM = """你是 Dobby 反思引擎。分析以下近期记忆，合成高层洞察。

**反思目标**:
- 识别反复出现的风险模式
- 提炼跨任务的通用经验
- 总结用户的持久偏好和工作风格
- 发现项目特定的规律和约束

**输出格式** — 严格 JSON:
{
  "insights": [
    {
      "insight": "洞察内容（一句话）",
      "evidence": ["支撑这条洞察的记忆摘要"],
      "importance": 0.8
    }
  ],
  "patterns": "跨任务的通用模式总结（可选，可为空字符串）",
  "should_skip": false
}

如果记忆不足以产生有价值的洞察，设置 should_skip=true，insights=[]。
重要性评分: 0.9=关键发现, 0.7=有用洞察, 0.5=一般观察。"""

REFLECTION_USER = """**近期记忆** (按时间倒序):

{memories_text}

请分析以上记忆，合成高层洞察。只输出 JSON，不要其他文字。"""


async def reflect_if_needed(
    project_id: str,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> dict:
    """Check cumulative importance and trigger reflection if threshold met.

    Returns:
        {"skipped": True} if below threshold
        {"insights": [...], "patterns": "...", "written": int, "l3_upgraded": int}
    """
    if user_id is None:
        user_id = _cfg.MEM0_USER_ID
    if agent_id is None:
        agent_id = user_id  # ← shared project pool, not _cfg.MEM0_AGENT_ID

    # 1. Check cooldown
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            "SELECT MAX(created_at) FROM experience_extracts "
            "WHERE project_id = %s AND bucket = 'reflection'",
            (project_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            last_reflection = row[0]
            if isinstance(last_reflection, str):
                last_reflection = datetime.fromisoformat(
                    last_reflection.replace("Z", "+00:00")
                )
            hours_since = (
                datetime.now(timezone.utc) - last_reflection
            ).total_seconds() / 3600.0
            if hours_since < _cfg.REFLECTION_COOLDOWN_HOURS:
                return {"skipped": True, "reason": "cooldown"}
    except Exception:
        pass  # first run or table not yet created → proceed

    # 2. Retrieve memories and check cumulative importance
    memories = _search_all_memories(user_id, limit=_cfg.REFLECTION_MAX_MEMORIES)
    if not memories:
        return {"skipped": True, "reason": "no_memories"}

    # P0-1: Use strength-weighted total instead of raw importance sum
    from .decay_curves import compute_strength

    total_strength = 0.0
    for m in memories:
        created_at_str = m.get("created_at", "")
        strength = compute_strength(
            created_at=_parse_dt_safe(created_at_str),
            importance=_get_memory_importance(m),
            memory_type=_get_memory_type(m),
            recall_count=_get_recall_count(m),
        )
        total_strength += strength

    if total_strength < _cfg.REFLECTION_IMPORTANCE_THRESHOLD:
        return {
            "skipped": True,
            "reason": "below_threshold",
            "total_importance": round(total_strength, 2),
            "threshold": _cfg.REFLECTION_IMPORTANCE_THRESHOLD,
        }

    # 3. Build prompt with top memories
    mem_lines = []
    for i, m in enumerate(memories[:50], 1):
        text = m.get("memory", str(m))
        imp = _get_memory_importance(m)
        created = m.get("created_at", "unknown")
        mem_lines.append(f"[{i}] (importance={imp:.1f}, {created}) {text[:300]}")

    user_text = REFLECTION_USER.format(memories_text="\n\n".join(mem_lines))

    from agentscope.message import SystemMsg, UserMsg
    msgs = [
        SystemMsg("reflection", REFLECTION_SYSTEM),
        UserMsg("reflection", user_text),
    ]

    # 4. LLM call for reflection
    try:
        resp = await _call_model(msgs, intent="reflect")
        content = _extract_text(resp)
        parsed = _parse_json_response(content)
    except Exception:
        return {"skipped": True, "reason": "llm_error"}

    if parsed.get("should_skip"):
        return {"skipped": True, "reason": "llm_skip"}

    insights = parsed.get("insights", [])
    patterns = parsed.get("patterns", "")

    # 5. Write insights to Mem0
    m = get_mem0()
    written = 0
    l3_upgraded = 0

    for insight in insights:
        if not isinstance(insight, dict):
            continue
        text = insight.get("insight", "")
        importance = float(insight.get("importance", 0.5))
        evidence = insight.get("evidence", [])

        if not text:
            continue

        # Write to Mem0 as reflection memory
        try:
            _run_sync_mem0(
                lambda t=text, imp=importance, ev=evidence: m.add(
                    t,
                    user_id=user_id,
                    agent_id=agent_id,
                    metadata={
                        "memory_type": "reflection",
                        "importance": imp,
                        "evidence": ev,
                    },
                    infer=False,  # store directly without LLM extraction
                ),
                timeout=30,
            )
            written += 1
        except Exception:
            pass

        # L3 upgrade: importance >= 0.8 → experience_extracts
        if importance >= 0.8:
            try:
                conn2 = _get_db_conn()
                conn2.execute(
                    """INSERT INTO experience_extracts
                       (project_id, task_id, task_outcome, bucket,
                        description, reusable_knowledge, importance)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        project_id,
                        f"reflection_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{written}",
                        "success",
                        "reflection",
                        text[:1000],
                        evidence[0][:500] if evidence else "",
                        importance,
                    ),
                )
                conn2.close()
                l3_upgraded += 1
            except Exception:
                pass

    return {
        "skipped": False,
        "insights": insights,
        "patterns": patterns,
        "written": written,
        "l3_upgraded": l3_upgraded,
    }


# ============================================================
# Module 3: Experience extraction (Phase 1)
# ============================================================

EXPERIENCE_SYSTEM = """你是 Dobby 经验抽取器。分析以下已完成任务，抽取可复用知识。

**抽取规则** — 只抽取满足"未来 agent 会因此做得更好"的内容:
1. preference（用户操作偏好）— 用户反复要求的格式/风格/流程
2. procedure（程序性知识）— 解决了一个可能重复出现的问题
3. decision（决策触发）— 条件→行动的规律
4. environment（环境证据）— 项目特有的配置、约定、约束
不满足以上任一条件 → 输出空数组

**输出格式** — 严格 JSON:
{
  "extracts": [
    {
      "bucket": "preference|procedure|decision|environment",
      "description": "简洁描述（一句话）",
      "reusable_knowledge": "未来 agent 如何使用这条知识",
      "pitfalls": "需要注意的坑或反模式（无则空字符串）",
      "keywords": ["关键词1", "关键词2"],
      "importance": 0.7
    }
  ]
}
如果无可抽取内容，返回 {"extracts": []}。只输出 JSON，不要其他文字。"""

EXPERIENCE_USER = """**任务描述**: {task_description}

**任务结果**: {task_outcome}

**相关上下文**: 
{context_snippet}

请分析以上已完成任务，抽取可复用知识。"""


async def extract_experiences(
    project_id: str,
    tasks: dict,
    messages: list | None = None,
) -> dict:
    """Scan completed tasks and spawn isolated sub-agent for experience extraction.

    Args:
        project_id: project identifier
        tasks: dict of {task_id: {status, description, outcome, extracted?}}
        messages: conversation history (used for context snippet, NOT fully passed)

    Returns:
        {"extracted": {task_id: True}, "total_inserts": int}
    """
    if not tasks:
        return {"extracted": {}, "total_inserts": 0}

    extracted_map = {}
    total_inserts = 0
    written_buckets: set[str] = set()  # track unique buckets for event trigger

    for task_id, task_info in tasks.items():
        if not isinstance(task_info, dict):
            continue

        status = task_info.get("status", "")
        if status != "done":
            continue

        # Already extracted?
        if task_info.get("extracted"):
            continue

        # Check DB for existing extracts
        already_in_db = False
        try:
            conn = _get_db_conn()
            cur = conn.execute(
                "SELECT COUNT(*) FROM experience_extracts WHERE task_id = %s",
                (task_id,),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0] > 0:
                already_in_db = True
        except Exception:
            pass

        if already_in_db:
            extracted_map[task_id] = True
            continue

        description = str(task_info.get("description", ""))
        outcome = str(task_info.get("outcome", "success"))

        # Signal threshold check
        if len(description) < _cfg.EXPERIENCE_MIN_CONTENT_LENGTH:
            continue  # NO-OP

        # Build isolated context snippet (NOT the full history)
        context_snippet = ""
        if messages:
            # Extract at most 2000 chars from relevant messages
            parts = []
            total_chars = 0
            for m in reversed(messages[-30:]):
                text = _extract_text(m)
                if total_chars + len(text) > 2000:
                    parts.append(text[:2000 - total_chars] + "...")
                    break
                parts.append(text)
                total_chars += len(text)
            context_snippet = "\n".join(reversed(parts))[:2000]

        # Build prompt (isolated — no parent history)
        user_text = EXPERIENCE_USER.format(
            task_description=description[:1000],
            task_outcome=outcome,
            context_snippet=context_snippet or "(无)",
        )

        from agentscope.message import SystemMsg, UserMsg
        exp_msgs = [
            SystemMsg("experience_extractor", EXPERIENCE_SYSTEM),
            UserMsg("experience_extractor", user_text),
        ]

        # LLM call
        try:
            resp = await _call_model(exp_msgs, intent="extract")
            content = _extract_text(resp)
            parsed = _parse_json_response(content)
        except Exception:
            continue

        extracts = parsed.get("extracts", [])
        if not isinstance(extracts, list) or not extracts:
            continue

        # Write to DB
        inserts = 0
        for ext in extracts:
            if not isinstance(ext, dict):
                continue
            bucket = ext.get("bucket", "procedure")
            if bucket not in ("preference", "procedure", "decision", "environment"):
                bucket = "procedure"
            desc = str(ext.get("description", ""))[:1000]
            reusable = str(ext.get("reusable_knowledge", ""))[:2000]
            pitfalls = str(ext.get("pitfalls", ""))[:1000]
            keywords = ext.get("keywords", [])
            if isinstance(keywords, list):
                keywords = [str(k)[:100] for k in keywords[:10]]
            else:
                keywords = []
            importance = float(ext.get("importance", 0.5))

            if not desc:
                continue

            try:
                conn2 = _get_db_conn()
                conn2.execute(
                    """INSERT INTO experience_extracts
                       (project_id, task_id, task_outcome, bucket,
                        description, reusable_knowledge, pitfalls,
                        keywords, importance)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        project_id, task_id, outcome, bucket,
                        desc, reusable, pitfalls, keywords, importance,
                    ),
                )
                conn2.close()
                inserts += 1
                written_buckets.add(bucket)  # ★ track bucket for event trigger
            except Exception:
                pass

        # ★ event-driven: fire once per unique bucket written this batch
        if written_buckets:
            from .consolidation_engine import _maybe_fire_consolidation
            for b in written_buckets:
                asyncio.create_task(_maybe_fire_consolidation(project_id, b))

        total_inserts += inserts
        extracted_map[task_id] = True

    # ── Trigger skill compilation if threshold met (§10) ──
    if total_inserts >= _cfg.SKILL_COMPILE_THRESHOLD:
        try:
            asyncio.create_task(trigger_skill_compile(project_id))
        except Exception:
            pass

    return {"extracted": extracted_map, "total_inserts": total_inserts}


# ============================================================
# Module 4: Experience consolidation (Phase 2)
# ============================================================

CONSOLIDATION_SYSTEM = """你是 Dobby 经验整合引擎。分析候选经验对，判断是否应合并为一条结构化经验文档。

**四桶分类**（同 Phase 1）:
- preference（用户操作偏好）— 用户反复要求的格式/风格/流程
- procedure（程序性知识）— 解决了一个可能重复出现的问题
- decision（决策触发）— 条件→行动的规律
- environment（环境证据）— 项目特有的配置、约定、约束

**合并规则**:
- 描述同一类问题/模式 → action: "merge"，合并为一条
- 有因果关系（A 是原因 B 是结果）→ action: "merge"，合并为一条
- 互相矛盾 → action: "conflict"，各自保留并标记冲突
- 完全无关 → action: "keep_separate"，各自保留

**输出格式** — 严格 JSON:
{
  "clusters": [
    {
      "source_ids": ["uuid1", "uuid2"],
      "action": "merge",
      "slug": "简短唯一标识-用连字符",
      "body_md": "## 经验摘要\\n...\\n## 可复用知识\\n...\\n## 注意事项\\n...",
      "bucket": "procedure",
      "importance": 0.85,
      "keywords": ["关键词1", "关键词2"]
    }
  ],
  "unmerged_ids": []
}

注意:
- slug 必须 ≤ 80 字符，只含小写字母、数字、连字符
- 每条 extract 只能出现在一个 cluster 中
- 未被任何 cluster 引用的 extract id 放入 unmerged_ids
- 只输出 JSON，不要其他文字。"""

CONSOLIDATION_USER = """**候选经验对**（共 {pair_count} 对）:

{pairs_text}

请分析以上候选对，输出合并计划 JSON。"""


async def consolidate_if_needed(
    project_id: str,
    user_id: str | None = None,
) -> dict:
    """Phase 2 per-night consolidation — delegates to ConsolidationEngine.

    Retained for backward compatibility. New code should use
    ConsolidationEngine.run() directly.

    Args:
        project_id: project identifier
        user_id: Mem0 user_id (unused, kept for API consistency)

    Returns:
        {"skipped": True, "reason": "..."} if not run
        {"extracts_processed": N, "experiences_created": N,
         "experiences_updated": N, "wiki_synced": N} if run
    """
    from .consolidation_engine import ConsolidationEngine

    engine = ConsolidationEngine()
    result = await engine.run(project_id, source="extracts", mode="nightly")

    if result.skipped:
        return {"skipped": True, "reason": result.reason}

    # ── Trigger skill compilation as batch fallback (§10) ──
    try:
        await trigger_skill_compile(project_id)
    except Exception:
        pass

    return {
        "skipped": False,
        "extracts_processed": result.items_loaded,
        "experiences_created": result.created,
        "experiences_updated": result.updated,
        "wiki_synced": result.wiki_synced,
    }


async def _ensure_embeddings(extracts: list[dict]) -> None:
    """Generate embeddings for extracts missing them, write back to DB.

    Uses embed_server HTTP API (bge-large-zh-v1.5, :9999) for consistency
    with graphiti_client. No local SentenceTransformer loading — avoids
    duplicating ~1.3GB of model memory.
    """
    import numpy as np

    need_embed = [
        e for e in extracts
        if e.get("embedding") is None and e.get("description")
    ]
    if not need_embed:
        return

    texts = [
        f"{e.get('description', '')} {e.get('reusable_knowledge', '')}"
        for e in need_embed
    ]

    # ── Call embed_server HTTP API ──
    vectors = None
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_cfg.EMBED_SERVER_URL}/embeddings",
                json={"input": texts, "model": _cfg.EMBEDDING_MODEL},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            vectors = [np.array(item["embedding"]) for item in data["data"]]
    except Exception:
        # Fallback: try local SentenceTransformer if embed_server is down
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(_cfg.EMBEDDING_MODEL)
            vectors = model.encode(texts, normalize_embeddings=True)
            vectors = [np.array(v) for v in vectors]
        except Exception:
            return  # both methods failed, skip

    if vectors is None:
        return

    for ext, vec in zip(need_embed, vectors):
        try:
            conn = _get_db_conn()
            conn.execute(
                "UPDATE experience_extracts SET embedding = %s WHERE id = %s",
                (vec.tolist(), ext["id"]),
            )
            conn.close()
            ext["embedding"] = vec.tolist()  # update in-memory too
        except Exception:
            pass


def _coarse_filter(
    extracts: list[dict],
    threshold: float = 0.75,
) -> list[tuple]:
    """Find candidate similar pairs via cosine similarity.

    Uses brute-force pairwise comparison for small datasets (≤50 extracts),
    HNSW index for larger ones. Vectors are already L2-normalized by
    bge-large-zh-v1.5, so cosine similarity = dot product.

    Symmetric dedup: (A,B) and (B,A) are merged.
    Filters pairs below threshold.

    Returns:
        [(extract_dict_a, extract_dict_b, similarity), ...]
    """
    if len(extracts) < 2:
        return []

    import numpy as np

    pairs = []
    seen = set()

    # ── Brute-force pairwise cosine (fast for ≤50 extracts) ──
    indexed = [(e, np.array(e["embedding"])) for e in extracts
               if e.get("embedding") is not None]

    for i in range(len(indexed)):
        e_i, v_i = indexed[i]
        for j in range(i + 1, len(indexed)):
            e_j, v_j = indexed[j]
            # Cosine similarity (vectors are already normalized)
            sim = float(np.dot(v_i, v_j))
            if sim < threshold:
                continue
            pair_key = tuple(sorted([str(e_i["id"]), str(e_j["id"])]))
            if pair_key not in seen:
                seen.add(pair_key)
                pairs.append((e_i, e_j, sim))

    return pairs


async def _llm_consolidate(
    extracts: list[dict],
    candidate_pairs: list[tuple],
    _call_model_fn=None,
) -> dict:
    """Spawn isolated consolidation sub-agent (Codex MemoryConsolidation pattern).

    No parent history, no network, write-only. Returns merge plan JSON.

    When there are no candidate pairs, auto-generates solo clusters
    (one experience per extract) without calling the LLM.

    Args:
        extracts: all unconsolidated extracts
        candidate_pairs: from _coarse_filter
        _call_model_fn: optional mock for testing

    Returns:
        {"clusters": [...], "unmerged_ids": [...]}
    """
    # ── No candidate pairs → auto-generate solo clusters ──
    if not candidate_pairs:
        solo_clusters = []
        for e in extracts:
            desc = e.get("description", "")[:500]
            bucket = e.get("bucket", "procedure")
            solo_clusters.append({
                "source_ids": [e["id"]],
                "action": "merge",
                "slug": _make_slug(desc, bucket),
                "body_md": f"## 经验摘要\n\n{desc}\n\n"
                           f"## 可复用知识\n\n{e.get('reusable_knowledge', '') or '(待补充)'}",
                "bucket": bucket,
                "importance": float(e.get("importance", 0.5)),
                "keywords": [],
            })
        return {"clusters": solo_clusters, "unmerged_ids": []}

    if _call_model_fn is None:
        _call_model_fn = _call_model

    # ── Build pairs text ──
    lines = []
    for i, (e_a, e_b, sim) in enumerate(candidate_pairs, 1):
        lines.append(
            f"[对 {i}] similarity={sim:.3f}\n"
            f"  A ({e_a['id']}): {e_a.get('description', '')[:200]}\n"
            f"  B ({e_b['id']}): {e_b.get('description', '')[:200]}"
        )
    pairs_text = "\n\n".join(lines)

    user_text = CONSOLIDATION_USER.format(
        pair_count=len(candidate_pairs),
        pairs_text=pairs_text[:8000],  # safety cap
    )

    from agentscope.message import SystemMsg, UserMsg
    msgs = [
        SystemMsg("consolidation", CONSOLIDATION_SYSTEM),
        UserMsg("consolidation", user_text),
    ]

    try:
        resp = await asyncio.wait_for(
            _call_model_fn(msgs),
            timeout=180.0,
        )
        content = _extract_text(resp)
        parsed = _parse_json_response(content)
    except asyncio.TimeoutError:
        return {"clusters": [], "unmerged_ids": [e["id"] for e in extracts]}
    except Exception:
        return {"clusters": [], "unmerged_ids": [e["id"] for e in extracts]}

    if not parsed or not isinstance(parsed.get("clusters"), list):
        # Fallback: auto-generate solo clusters
        fallback = []
        for e in extracts:
            desc = e.get("description", "")[:500]
            bucket = e.get("bucket", "procedure")
            fallback.append({
                "source_ids": [e["id"]],
                "action": "merge",
                "slug": _make_slug(desc, bucket),
                "body_md": f"## 经验摘要\n\n{desc}",
                "bucket": bucket,
                "importance": float(e.get("importance", 0.5)),
                "keywords": [],
            })
        return {"clusters": fallback, "unmerged_ids": []}

    return parsed


def _make_slug(description: str, bucket: str = "procedure") -> str:
    """Generate a URL-safe slug from description text.

    Truncates to 80 chars, keeps only lowercase alphanumeric and hyphens.
    """
    import re
    import uuid
    # Take first meaningful words, lowercase, replace non-alnum with hyphens
    base = description[:60].lower()
    base = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '-', base)
    base = base.strip('-')
    if not base:
        base = f"{bucket}-{uuid.uuid4().hex[:8]}"
    return base[:80]


def _apply_merge_plan(project_id: str, merge_plan: dict) -> dict:
    """Execute merge plan: INSERT new experiences or UPDATE existing ones.

    Idempotent: same slug → UPDATE version+1 rather than duplicate.

    Returns:
        {"created": int, "updated": int}
    """
    created = 0
    updated = 0

    for cluster in merge_plan.get("clusters", []):
        action = cluster.get("action", "")
        if action not in ("merge", "conflict"):
            continue

        slug = str(cluster.get("slug", ""))[:160]
        source_ids = cluster.get("source_ids", [])
        body_md = str(cluster.get("body_md", ""))[
            :_cfg.EXPERIENCE_MAX_BODY_LENGTH
        ]
        bucket = cluster.get("bucket", "procedure")
        importance = float(cluster.get("importance", 0.5))

        if not slug or not source_ids:
            continue

        try:
            conn = _get_db_conn()
            cur = conn.execute(
                "SELECT id, version FROM experiences "
                "WHERE project_id = %s AND slug = %s "
                "ORDER BY version DESC LIMIT 1",
                (project_id, slug),
            )
            existing = cur.fetchone()

            if existing:
                # UPDATE: version increment
                new_version = existing[1] + 1
                conn.execute(
                    """UPDATE experiences
                       SET body_md = %s, version = %s,
                           source_extract_ids = %s,
                           bucket = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (body_md, new_version, source_ids, bucket, existing[0]),
                )
                updated += 1
            else:
                # INSERT: new experience
                conn.execute(
                    """INSERT INTO experiences
                       (project_id, slug, body_md, source_extract_ids,
                        bucket, version, importance)
                       VALUES (%s, %s, %s, %s, %s, 1, %s)""",
                    (project_id, slug, body_md, source_ids,
                     bucket, importance),
                )
                created += 1
            conn.close()
        except Exception:
            pass

    return {"created": created, "updated": updated}


async def _sync_to_wiki(project_id: str, slugs: list[str]) -> int:
    """Publish consolidated experiences to WeKnora wiki (fire-and-forget).

    Each experience becomes a wiki page with frontmatter metadata.
    Failures are silently ignored — wiki is best-effort.

    Returns:
        Number of pages successfully synced.
    """
    synced = 0

    for slug in slugs:
        try:
            conn = _get_db_conn()
            cur = conn.execute(
                """SELECT body_md, bucket, version, source_extract_ids, importance
                   FROM experiences
                   WHERE project_id = %s AND slug = %s
                   ORDER BY version DESC LIMIT 1""",
                (project_id, slug),
            )
            row = cur.fetchone()
            conn.close()

            if not row:
                continue

            body_md, bucket, version, source_ids, importance = row
            source_count = len(source_ids) if source_ids else 0

            # Build wiki page with frontmatter
            page = (
                f"---\n"
                f"project: {project_id}\n"
                f"bucket: {bucket or 'procedure'}\n"
                f"version: {version}\n"
                f"keywords: [{', '.join(['...'] if not bucket else [bucket])}]\n"
                f"importance: {importance or 0.5}\n"
                f"source_count: {source_count}\n"
                f"updated_at: {datetime.now(timezone.utc).isoformat()}\n"
                f"---\n\n"
                f"{body_md}\n\n"
                f"---\n"
                f"> 此页面由 Dobby 经验合并器自动生成 · 版本 {version}\n"
                f"> 溯源：来自 {source_count} 条任务执行记录"
            )

            # WeKnora wiki sync via MCP (best-effort)
            # In production this would call WeKnora's wiki API.
            # For now, we log success — actual MCP integration is Phase 2.1.
            _ = page  # consumed by MCP call in production
            synced += 1

        except Exception:
            pass

    return synced


# ============================================================
# Dreamer curate 薄包装 — 向后兼容
# ============================================================

async def run_dreamer_curate(project_id: str) -> dict:
    """使用新的 CurateTask 替代旧的 consolidate_if_needed。
    
    旧的 consolidate_if_needed() 保持不变作为兼容接口。
    """
    from .dreamer_tasks.curate import CurateTask
    from .dreamer import DreamerTaskConfig
    from . import config as _cfg2

    task = CurateTask(DreamerTaskConfig(
        name="curate",
        cron="",  # 手动触发，不需要 cron
        timeout_seconds=_cfg2.DREAMER_DEFAULT_TIMEOUT * 2,
        model=_cfg2.DREAMER_DEFAULT_MODEL,
        enabled=True,
    ))
    result = await task.run(project_id)
    return {
        "skipped": result.skipped,
        "merged": result.merged,
        "tightened": result.tightened,
        "archived": result.archived,
        "error": result.error,
        "duration_seconds": result.duration_seconds,
    }


# ============================================================
# Module 5: Skill compilation trigger (Step 10)
# ============================================================

async def trigger_skill_compile(project_id: str) -> dict:
    """Check compilation threshold and trigger if met.

    Event-driven (called after extract_experiences) or batch (called after
    consolidate_if_needed). Respects cooldown to avoid excessive LLM calls.

    Returns:
        {"skipped": True, "reason": "..."} if not triggered
        {"compiled": N, "skills_created": N} if triggered
    """
    import logging
    import asyncio as _asyncio

    _logger = logging.getLogger(__name__)

    try:
        # ── Cooldown check (PG-based, reuse _get_db_conn pattern) ──
        try:
            conn = _get_db_conn()
            cur = conn.execute(
                """SELECT MAX(created_at) FROM skill_registry
                   WHERE project_id = %s AND created_at > NOW() - INTERVAL '%s hours'""",
                (project_id, str(_cfg.SKILL_COMPILE_COOLDOWN_HOURS)),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return {"skipped": True, "reason": "cooldown"}
        except Exception:
            pass

        # ── Check uncompiled events ──
        from .skill_events import get_uncompiled_events, mark_compiled
        events = await get_uncompiled_events(project_id)
        if len(events) < _cfg.SKILL_COMPILE_THRESHOLD:
            return {"skipped": True, "reason": f"below_threshold ({len(events)} < {_cfg.SKILL_COMPILE_THRESHOLD})"}

        # ── Compile from events (Source A) ──
        from .skill_compiler import SkillCompiler
        from .skill_registry import SkillRegistry, SkillRecord
        from .langgraph_utils import _call_model

        compiled = 0
        skills_created = 0

        # Compile by role scope
        roles_seen = set(e.get("role_id", "global") for e in events)

        for role_scope in roles_seen:
            role_events = [e for e in events if e.get("role_id", "global") == role_scope]

            # Step 1: Compile events → cards (pure, no LLM)
            error_cards = SkillCompiler.compile_tool_errors(role_events)
            correction_cards = SkillCompiler.compile_corrections(role_events)
            all_cards = error_cards + correction_cards

            if not all_cards:
                continue

            # Step 2: LLM judge + generate (one call)
            result = await SkillCompiler.compile_to_skill(
                model_fn=_call_model,
                cards=all_cards,
                role_scope=role_scope,
            )

            if result and result.get("action") == "generate":
                body_md = result.get("body_md", "")
                skill_name = result.get("skill_name", "")
                title = result.get("title", skill_name)

                record = SkillRecord(
                    project_id=project_id,
                    slug=skill_name,
                    role_id=role_scope,
                    bucket="procedure",
                    title=title,
                    body_md=body_md,
                    status="shadow",
                    repeat_count=1,
                    source_event_ids=[
                        str(e.get("id", "")) for e in role_events
                    ],
                )

                # Check if safety-critical → review_pending
                if role_scope != "global":
                    record.status = "review_pending"

                written = await SkillRegistry.write_skill(record)
                if written:
                    skills_created += 1

                # Mark events as compiled
                event_ids = [str(e.get("id", "")) for e in role_events]
                await mark_compiled(event_ids, skill_name)
                compiled += len(event_ids)

        return {
            "skipped": False,
            "compiled": compiled,
            "skills_created": skills_created,
        }
    except Exception as e:
        _logger.warning(f"Skill compile failed for project {project_id}: {e}")
        return {"skipped": True, "reason": f"error: {e}"}
