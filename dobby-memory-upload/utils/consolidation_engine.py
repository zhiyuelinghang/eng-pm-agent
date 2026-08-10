"""
Unified ConsolidationEngine — event-driven N→1 merge for Dobby Phase 2.

Replaces three duplicated merge paths:
  - lifecycle.py:consolidate_if_needed() (24h batch, extracts → experiences)
  - decay_v2.py:_quick_consolidate()     (daily decay, direct merge only)
  - curate.py:_direct_merge()            (weekly curate, direct merge only)

All three now delegate to ConsolidationEngine.run().

Reference: YourMemory src/jobs/decay_job.py:_consolidate() (O(n²) cosine merge)
Reference: Magic Context dreamer curate + verify task scheduler pattern
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

from . import config as _cfg
from .langgraph_utils import _call_model
from .compression import _extract_text


# ============================================================
# Data structures
# ============================================================

@dataclass
class ConsolidationResult:
    """Unified merge result — replaces three separate return formats."""
    skipped: bool = False
    reason: str = ""
    items_loaded: int = 0
    direct_merged: int = 0         # cos ≥ 0.92, no LLM
    llm_judged: int = 0            # cos 0.75~0.92, LLM
    created: int = 0               # new experiences INSERT
    updated: int = 0               # existing experiences UPDATE
    solo_clusters: int = 0         # items with no candidate pairs
    wiki_synced: int = 0
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class MemoryItem:
    """Normalized internal representation — unifies extract and experience rows."""
    id: str
    bucket: str
    content: str          # extracts.description ↔ experiences.body_md
    importance: float
    recall_count: int     # extracts default 0; experiences from table column
    embedding: list | None = None
    raw: dict = field(default_factory=dict)  # original row for metadata access


# ============================================================
# Internal helpers
# ============================================================

def _get_db_conn():
    """Reuse lifecycle.py pattern for psycopg connections."""
    import psycopg
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_emb(raw) -> list | None:
    """Parse embedding from DB row — handle str/list/ndarray/None."""
    if raw is None:
        return None
    if isinstance(raw, (list, np.ndarray)):
        return list(raw)
    try:
        return json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        return None


def _cosine(a, b) -> float:
    """Cosine similarity between two numpy vectors."""
    a, b = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / n) if n > 0 else 0.0


def _parse_json_response(text: str) -> dict:
    """Parse LLM JSON response, handling markdown fences."""
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
# ConsolidationEngine
# ============================================================

CONSOLIDATION_SYSTEM = """你是 Dobby 经验整合引擎。分析候选经验对，判断是否应合并为一条结构化经验文档。

**四桶分类**:
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


def _make_slug(description: str, bucket: str = "procedure") -> str:
    """Generate a URL-safe slug from description text (from lifecycle.py:1031)."""
    import re, uuid
    base = description[:60].lower()
    base = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '-', base)
    base = base.strip('-')
    if not base:
        base = f"{bucket}-{uuid.uuid4().hex[:8]}"
    return base[:80]


class ConsolidationEngine:
    """Unified merge engine — three trigger paths, one implementation.

    Reference: YourMemory src/jobs/decay_job.py:_consolidate() (O(n²) cosine merge)
    Reference: Magic Context dreamer curate + verify task scheduler pattern
    """

    def __init__(
        self,
        direct_merge_threshold: float = 0.92,
        llm_judge_threshold: float = 0.75,
    ):
        self.direct_merge_threshold = direct_merge_threshold
        self.llm_judge_threshold = llm_judge_threshold

    # ── Public API ──────────────────────────────────────────────

    async def run(
        self,
        project_id: str,
        *,
        source: Literal["extracts", "experiences"] = "extracts",
        mode: Literal["event", "session", "nightly"] = "event",
        bucket: str | None = None,
        max_items: int | None = None,
        max_llm_pairs: int | None = None,
        timeout: float | None = None,
    ) -> ConsolidationResult:
        """Unified merge entry.

        Steps:
          0. PG advisory lock (fine-grained)
          1. load items → normalize to MemoryItem
          2. _ensure_embeddings (source="extracts" only)
          3. _coarse_filter → candidate_pairs
          4. classify pairs by sim:
               ≥ 0.92 → direct_merge (no LLM)
               0.75~0.92 → llm_judge
          5. no-pair items → auto solo clusters
          6. _apply_merge_plan → INSERT/UPDATE experiences
          7. source="extracts" → mark extracts consolidated_at
          8. write log
          9. release lock
        """
        started = datetime.now(timezone.utc)
        result = ConsolidationResult()

        # Mode defaults
        if max_items is None:
            max_items = {"event": 20, "session": 50, "nightly": 50}.get(mode, 20)
        if max_llm_pairs is None:
            max_llm_pairs = {"event": 10, "session": 20, "nightly": 30}.get(mode, 20)
        if timeout is None:
            timeout = {"event": 60.0, "session": 120.0, "nightly": None}.get(mode, 60.0)

        lock_key = f"{project_id}:{mode}:{bucket or 'all'}"
        lock_id = hash(lock_key) & 0x7FFFFFFF
        lock_conn = None

        try:
            # 0. Lock
            import psycopg
            lock_conn = psycopg.Connection.connect(
                _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
            )
            cur = lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
            acquired = cur.fetchone()[0]
            if not acquired:
                lock_conn.close()
                result.skipped = True
                result.reason = "locked"
                return result

            # 1. Load items
            if source == "extracts":
                items = self._load_extracts(project_id, bucket, max_items)
            else:
                items = self._load_experiences(project_id, bucket, max_items)

            if not items:
                result.skipped = True
                result.reason = "no_items"
                return result

            result.items_loaded = len(items)

            # 2. Ensure embeddings (only for extracts that may be missing them)
            if source == "extracts":
                await self._ensure_embeddings(items)

            # 3. Coarse filter: cosine similarity
            candidate_pairs = self._coarse_filter(items)

            # 4. Classify and process
            merged_count = 0
            for pair_a, pair_b, sim in candidate_pairs:
                if sim >= self.direct_merge_threshold:
                    self._direct_merge_pair(pair_a, pair_b, project_id, source)
                    merged_count += 1
                elif sim >= self.llm_judge_threshold and len(
                    [p for p in candidate_pairs if p[2] >= self.llm_judge_threshold]
                ) <= max_llm_pairs:
                    result.llm_judged += 1

            result.direct_merged = merged_count

            # LLM judgment batch
            llm_pairs = [
                (a, b, s) for a, b, s in candidate_pairs
                if self.llm_judge_threshold <= s < self.direct_merge_threshold
            ][:max_llm_pairs]
            if llm_pairs:
                llm_result = await self._llm_judge_pairs(
                    llm_pairs, items, project_id, timeout,
                )
                result.created += llm_result.get("created", 0)
                result.updated += llm_result.get("updated", 0)

            # 5. Solo clusters for items with no candidate pairs
            paired_ids = set()
            for a, b, _ in candidate_pairs:
                paired_ids.add(a.id)
                paired_ids.add(b.id)
            solo_items = [it for it in items if it.id not in paired_ids]
            if solo_items and source == "extracts":
                solo = self._auto_solo_clusters(solo_items, project_id)
                result.created += solo
                result.solo_clusters += solo

            # 6. Mark extracts as done
            if source == "extracts":
                all_extract_ids = [it.id for it in items]
                self._mark_extracts_done(all_extract_ids)

        except Exception as exc:
            result.error = str(exc)
        finally:
            if lock_conn:
                try:
                    lock_conn.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                    lock_conn.close()
                except Exception:
                    pass

        result.duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        return result

    # ── Internal: load ─────────────────────────────────────────

    def _load_extracts(
        self, project_id: str, bucket: str | None, max_items: int,
    ) -> list[MemoryItem]:
        conn = _get_db_conn()
        try:
            if bucket:
                rows = conn.execute(
                    """SELECT id, project_id, bucket, description, importance,
                              reusable_knowledge, embedding
                       FROM experience_extracts
                       WHERE project_id = %s AND bucket = %s
                         AND consolidated_at IS NULL
                       ORDER BY importance DESC
                       LIMIT %s""",
                    (project_id, bucket, max_items),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, project_id, bucket, description, importance,
                              reusable_knowledge, embedding
                       FROM experience_extracts
                       WHERE project_id = %s
                         AND consolidated_at IS NULL
                       ORDER BY importance DESC
                       LIMIT %s""",
                    (project_id, max_items),
                ).fetchall()

            return [
                MemoryItem(
                    id=str(r[0]), bucket=str(r[2] or "procedure"),
                    content=str(r[3] or ""), importance=float(r[4] or 0.5),
                    recall_count=0, embedding=r[6],
                    raw={"id": r[0], "project_id": r[1], "bucket": r[2],
                         "description": r[3], "importance": r[4],
                         "reusable_knowledge": r[5]},
                )
                for r in rows
            ]
        finally:
            conn.close()

    def _load_experiences(
        self, project_id: str, bucket: str | None, max_items: int,
    ) -> list[MemoryItem]:
        conn = _get_db_conn()
        try:
            if bucket:
                rows = conn.execute(
                    """SELECT id, bucket, body_md, importance, recall_count, embedding
                       FROM experiences
                       WHERE project_id = %s AND status = 'active' AND bucket = %s
                       ORDER BY importance DESC
                       LIMIT %s""",
                    (project_id, bucket, max_items),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, bucket, body_md, importance, recall_count, embedding
                       FROM experiences
                       WHERE project_id = %s AND status = 'active'
                       ORDER BY importance DESC
                       LIMIT %s""",
                    (project_id, max_items),
                ).fetchall()

            return [
                MemoryItem(
                    id=str(r[0]), bucket=str(r[1] or "procedure"),
                    content=str(r[2] or ""), importance=float(r[3] or 0.5),
                    recall_count=int(r[4] or 0), embedding=r[5],
                )
                for r in rows
            ]
        finally:
            conn.close()

    # ── Internal: embeddings ───────────────────────────────────

    async def _ensure_embeddings(self, items: list[MemoryItem]) -> None:
        """Reuse lifecycle.py:_ensure_embeddings pattern via embed_server HTTP API."""
        need_embed = [
            it for it in items if it.embedding is None and it.content
        ]
        if not need_embed:
            return

        texts = [
            f"{it.content} {it.raw.get('reusable_knowledge', '')}"
            for it in need_embed
        ]

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
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(_cfg.EMBEDDING_MODEL)
                vectors = model.encode(texts, normalize_embeddings=True)
                vectors = [np.array(v) for v in vectors]
            except Exception:
                return

        if vectors is None:
            return

        conn = _get_db_conn()
        try:
            for it, vec in zip(need_embed, vectors):
                it.embedding = vec.tolist()
                conn.execute(
                    "UPDATE experience_extracts SET embedding = %s WHERE id = %s",
                    (vec.tolist(), it.id),
                )
        finally:
            conn.close()

    # ── Internal: coarse filter ────────────────────────────────

    def _coarse_filter(self, items: list[MemoryItem]) -> list[tuple]:
        """Find candidate similar pairs via cosine similarity.
        Duplicates lifecycle.py:_coarse_filter O(n²) brute-force logic.
        """
        if len(items) < 2:
            return []

        indexed = [
            (it, np.array(it.embedding)) for it in items
            if it.embedding is not None
        ]
        pairs = []
        seen = set()

        for i in range(len(indexed)):
            e_i, v_i = indexed[i]
            for j in range(i + 1, len(indexed)):
                e_j, v_j = indexed[j]
                sim = float(np.dot(v_i, v_j))  # vectors already L2-normalized
                if sim < self.llm_judge_threshold:
                    continue
                pair_key = tuple(sorted([e_i.id, e_j.id]))
                if pair_key not in seen:
                    seen.add(pair_key)
                    pairs.append((e_i, e_j, sim))
        return pairs

    # ── Internal: direct merge ─────────────────────────────────

    def _direct_merge_pair(
        self,
        keep_item: MemoryItem,
        drop_item: MemoryItem,
        project_id: str,
        source: str,
    ) -> None:
        """Direct merge two items with cos ≥ 0.92 — no LLM call.

        Reference: YourMemory src/jobs/decay_job.py:_consolidate() lines 168-211
        Pattern: keep higher importance, merge recall_count, archive the other.
        """
        # Ensure keep has higher importance
        if drop_item.importance > keep_item.importance:
            keep_item, drop_item = drop_item, keep_item

        sim = _cosine(
            np.array(keep_item.embedding, dtype=np.float32),
            np.array(drop_item.embedding, dtype=np.float32),
        )

        conn = _get_db_conn()
        try:
            if source == "extracts":
                # Generate a slug and insert as new experience
                slug = _make_slug(keep_item.content, keep_item.bucket)
                body_md = (
                    f"## 经验摘要\n\n{keep_item.content}\n\n"
                    f"## 可复用知识\n\n{keep_item.raw.get('reusable_knowledge', '') or '(待补充)'}"
                )

                cur = conn.execute(
                    "SELECT id, version FROM experiences "
                    "WHERE project_id = %s AND slug = %s ORDER BY version DESC LIMIT 1",
                    (project_id, slug),
                )
                existing = cur.fetchone()
                if existing:
                    conn.execute(
                        """UPDATE experiences
                           SET body_md = %s, version = %s,
                               source_extract_ids = %s, updated_at = NOW()
                           WHERE id = %s""",
                        (body_md, existing[1] + 1,
                         [keep_item.id, drop_item.id], existing[0]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO experiences
                           (project_id, slug, body_md, source_extract_ids,
                            bucket, version, importance)
                           VALUES (%s, %s, %s, %s, %s, 1, %s)""",
                        (project_id, slug, body_md,
                         [keep_item.id, drop_item.id],
                         keep_item.bucket, keep_item.importance),
                    )
            else:
                # Merging existing experiences
                merged_recall = keep_item.recall_count + drop_item.recall_count
                merged_importance = max(keep_item.importance, drop_item.importance)

                conn.execute(
                    """UPDATE experiences
                       SET recall_count = %s,
                           importance = GREATEST(importance, %s),
                           strength = GREATEST(strength, %s),
                           updated_at = NOW()
                       WHERE id = %s""",
                    (merged_recall, merged_importance,
                     drop_item.importance, keep_item.id),
                )
                conn.execute(
                    """UPDATE experiences
                       SET status = 'archived',
                           archived_reason = %s,
                           updated_at = NOW()
                       WHERE id = %s""",
                    (f"merged_into:{keep_item.id}_sim:{sim:.3f}", drop_item.id),
                )
        finally:
            conn.close()

    # ── Internal: LLM judgment ─────────────────────────────────

    async def _llm_judge_pairs(
        self,
        pairs: list[tuple],
        items: list[MemoryItem],
        project_id: str,
        timeout: float | None,
    ) -> dict[str, int]:
        """Medium-sim pairs → LLM decides merge/tighten/archive.

        Reference: lifecycle.py:_llm_consolidate() (lines 937-1028)
        """
        lines = []
        for idx, (a, b, sim) in enumerate(pairs[:20], 1):
            lines.append(
                f"[对 {idx}] similarity={sim:.3f}\n"
                f"  A ({a.id[:8]}): {a.content[:200]}\n"
                f"  B ({b.id[:8]}): {b.content[:200]}"
            )

        from agentscope.message import SystemMsg, UserMsg
        user_text = CONSOLIDATION_USER.format(
            pair_count=len(pairs),
            pairs_text="\n\n".join(lines)[:8000],
        )
        msgs = [
            SystemMsg("consolidation", CONSOLIDATION_SYSTEM),
            UserMsg("consolidation", user_text),
        ]

        try:
            if timeout:
                resp = await asyncio.wait_for(_call_model(msgs), timeout=timeout)
            else:
                resp = await _call_model(msgs)
            content = _extract_text(resp)
            parsed = _parse_json_response(content)
        except asyncio.TimeoutError:
            return {"created": 0, "updated": 0}
        except Exception:
            return {"created": 0, "updated": 0}

        if not parsed or not isinstance(parsed.get("clusters"), list):
            return {"created": 0, "updated": 0}

        return self._apply_merge_plan(project_id, parsed)

    # ── Internal: apply merge plan ─────────────────────────────

    def _apply_merge_plan(self, project_id: str, merge_plan: dict) -> dict[str, int]:
        """Execute merge plan: INSERT or UPDATE experiences table.

        Reference: lifecycle.py:_apply_merge_plan() (lines 1047-1064)
        Idempotent: same slug → UPDATE version+1 rather than duplicate.
        """
        created = 0
        updated = 0

        for cluster in merge_plan.get("clusters", []):
            action = cluster.get("action", "")
            if action not in ("merge", "conflict"):
                continue

            slug = str(cluster.get("slug", ""))[:160]
            source_ids = cluster.get("source_ids", [])
            body_md = str(cluster.get("body_md", ""))[:_cfg.EXPERIENCE_MAX_BODY_LENGTH]
            bucket = cluster.get("bucket", "procedure")
            importance = float(cluster.get("importance", 0.5))

            if not slug or not source_ids:
                continue

            conn = _get_db_conn()
            try:
                cur = conn.execute(
                    "SELECT id, version FROM experiences "
                    "WHERE project_id = %s AND slug = %s "
                    "ORDER BY version DESC LIMIT 1",
                    (project_id, slug),
                )
                existing = cur.fetchone()

                if existing:
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
                    conn.execute(
                        """INSERT INTO experiences
                           (project_id, slug, body_md, source_extract_ids,
                            bucket, version, importance)
                           VALUES (%s, %s, %s, %s, %s, 1, %s)""",
                        (project_id, slug, body_md, source_ids, bucket, importance),
                    )
                    created += 1
            except Exception:
                pass
            finally:
                conn.close()

        return {"created": created, "updated": updated}

    # ── Internal: solo clusters ────────────────────────────────

    def _auto_solo_clusters(
        self, items: list[MemoryItem], project_id: str,
    ) -> int:
        """Items with no candidate pairs → auto-generate one experience each.

        Reference: lifecycle.py:_llm_consolidate() solo_clusters branch (lines 958-973)
        """
        created = 0
        for it in items:
            slug = _make_slug(it.content, it.bucket)
            body_md = (
                f"## 经验摘要\n\n{it.content[:500]}\n\n"
                f"## 可复用知识\n\n{it.raw.get('reusable_knowledge', '') or '(待补充)'}"
            )
            conn = _get_db_conn()
            try:
                cur = conn.execute(
                    "SELECT id FROM experiences WHERE project_id = %s AND slug = %s LIMIT 1",
                    (project_id, slug),
                )
                if cur.fetchone():
                    continue  # skip duplicates

                conn.execute(
                    """INSERT INTO experiences
                       (project_id, slug, body_md, source_extract_ids,
                        bucket, version, importance)
                       VALUES (%s, %s, %s, %s, %s, 1, %s)""",
                    (project_id, slug, body_md, [it.id], it.bucket, it.importance),
                )
                created += 1
            except Exception:
                pass
            finally:
                conn.close()
        return created

    # ── Internal: mark done ────────────────────────────────────

    def _mark_extracts_done(self, extract_ids: list[str]) -> None:
        """Mark extracts as consolidated. Replaces the NOT IN subquery pattern."""
        if not extract_ids:
            return
        conn = _get_db_conn()
        try:
            conn.execute(
                "UPDATE experience_extracts SET consolidated_at = %s WHERE id = ANY(%s)",
                (_now_iso(), extract_ids),
            )
        finally:
            conn.close()


# ============================================================
# Event-driven trigger
# ============================================================

# Module-level cooldown tracker — key="project_id:bucket", value=timestamp
_last_fire: dict[str, float] = {}


async def _count_pending_extracts(project_id: str, bucket: str) -> int:
    """Count unconsolidated extracts in a given bucket. <1ms query."""
    conn = _get_db_conn()
    try:
        row = conn.execute(
            """SELECT COUNT(*) FROM experience_extracts
               WHERE project_id = %s AND bucket = %s AND consolidated_at IS NULL""",
            (project_id, bucket),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _cooldown_active(project_id: str, bucket: str, minutes: int = 30) -> bool:
    """Check if this bucket was recently fired. Returns True if still in cooldown."""
    key = f"{project_id}:{bucket}"
    now = datetime.now(timezone.utc).timestamp()
    last = _last_fire.get(key, 0.0)
    return (now - last) < (minutes * 60)


def _touch_cooldown(project_id: str, bucket: str) -> None:
    """Record that a fire just happened."""
    key = f"{project_id}:{bucket}"
    _last_fire[key] = datetime.now(timezone.utc).timestamp()


async def _maybe_fire_consolidation(project_id: str, bucket: str) -> None:
    """Check threshold and fire engine.run(mode='event') if conditions met.

    Called after each extract INSERT in extract_experiences().
    Uses asyncio.create_task so it never blocks the caller.
    """
    if not _cfg.EXPERIENCE_EVENT_DRIVEN_ENABLED:
        return

    pending = await _count_pending_extracts(project_id, bucket)
    if pending < _cfg.EXPERIENCE_EVENT_MIN_CLUSTER_SIZE:
        return

    if _cooldown_active(project_id, bucket, _cfg.EXPERIENCE_EVENT_COOLDOWN_MINUTES):
        return

    _touch_cooldown(project_id, bucket)

    engine = ConsolidationEngine()
    asyncio.create_task(
        engine.run(project_id, source="extracts", mode="event", bucket=bucket)
    )
