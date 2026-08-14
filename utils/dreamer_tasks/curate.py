# utils/dreamer_tasks/curate.py
"""CurateTask — 参考 Magic Context curate + YourMemory _consolidate + Dobby 现有逻辑"""

import numpy as np
from datetime import datetime, timezone

from agentscope.message import SystemMsg, UserMsg

from ..dreamer import DreamerTask, DreamerTaskConfig, DreamerResult
from .. import config as _cfg
from .base import (
    _call_llm, _now_iso, _parse_json_response,
    _get_advisory_lock, _release_advisory_lock, _write_run_log,
)
from ..consolidation_engine import _parse_emb, _cosine

HIGH_SIM = _cfg.DREAMER_CURATE_HIGH_SIM            # 0.92 — 直接合并
COARSE_FILTER = _cfg.DREAMER_CURATE_COARSE_FILTER   # 0.75 — LLM判断
ARCHIVE_IMPORTANCE = _cfg.DREAMER_CURATE_ARCHIVE_IMPORTANCE  # 0.3

CURATE_SYSTEM = """你是 Dobby 记忆整理器。分析候选经验对，决定如何处理。

**操作选项**:
- merge: 两条经验描述同一件事 → 合并
- tighten: 措辞可改进 → 优化表述
- keep_separate: 各自独立有价值 → 分别保留
- archive: 内容过时/不再有用 → 归档

**输出格式** — 严格 JSON:
{
  "actions": [
    {"id": "UUID", "action": "merge|tighten|keep_separate|archive",
     "reason": "原因", "new_content": "仅merge/tighten时需要"}
  ]
}
只输出 JSON。"""

CURATE_USER = """项目: {project_id}

候选经验对（相似度 {sim_min}-{sim_max}）:
{pairs_text}

决定每个经验如何处理，输出 JSON。"""


class CurateTask(DreamerTask):
    """记忆质量整理 — 综合 YourMemory + Magic Context + Dobby 现有逻辑"""

    async def run(self, project_id: str) -> DreamerResult:
        started = datetime.now(timezone.utc)
        result = DreamerResult(task_name="curate")

        lock_id, lock_conn = _get_advisory_lock(project_id, "curate")
        if lock_conn is None:
            result.skipped = True
            result.reason = "locked"
            return result

        try:
            # ── 加载所有活跃经验 ──
            experiences = self._load_active(project_id)
            if len(experiences) < 2:
                result.skipped = True
                result.reason = "too_few_experiences"
                return result

            for bucket in ["preference", "procedure", "decision", "environment"]:
                bucket_items = [e for e in experiences if e["bucket"] == bucket]
                if len(bucket_items) < 2:
                    continue

                # ── Step 1: 高相似度直接合并（委托给统一引擎）──
                from ..consolidation_engine import ConsolidationEngine
                engine = ConsolidationEngine()
                cr = await engine.run(
                    project_id, source="experiences", mode="nightly", bucket=bucket,
                )
                result.merged += cr.direct_merged

                # ── Step 2: 中等相似度 LLM 判断 ──
                tightened = await self._llm_curate(bucket_items, project_id)
                result.tightened += tightened

            # ── Step 3: 低价值归档（参考 Magic Context curate 的 archive）──
            archived = self._archive_low_value(experiences, project_id)
            result.archived += archived

        except Exception as exc:
            result.error = str(exc)
        finally:
            _release_advisory_lock(lock_id, lock_conn)

        result.duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        _write_run_log("curate", project_id,
                       {"merged": result.merged, "tightened": result.tightened,
                        "archived": result.archived},
                       status="completed" if not result.error else "failed",
                       error=result.error)
        return result

    def _load_active(self, project_id: str) -> list[dict]:
        conn = self._get_db_conn()
        try:
            cur = conn.execute(
                """SELECT id, project_id, bucket, body_md, importance,
                          recall_count, embedding, status
                   FROM experiences
                   WHERE project_id = %s AND status = 'active'
                   ORDER BY bucket, importance DESC""",
                (project_id,),
            )
            cols = ["id", "project_id", "bucket", "body_md", "importance",
                    "recall_count", "embedding", "status"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    async def _llm_curate(self, items: list[dict], project_id: str) -> int:
        """中等相似度 → LLM 判断 merge/tighten/keep_separate/archive"""
        # 使用 Dobby 现有的 coarse filter 逻辑（移植自 lifecycle.py:_coarse_filter）
        indexed = [(e, np.array(_parse_emb(e.get("embedding"))))
                    for e in items if _parse_emb(e.get("embedding")) is not None]
        pairs = []
        for i in range(len(indexed)):
            for j in range(i + 1, len(indexed)):
                sim = float(np.dot(indexed[i][1], indexed[j][1]))
                if COARSE_FILTER <= sim < HIGH_SIM:
                    pairs.append((indexed[i][0], indexed[j][0], sim))

        if not pairs:
            return 0

        # 构建 prompt（参考 lifecycle.py:_llm_consolidate）
        lines = []
        for idx, (a, b, sim) in enumerate(pairs[:20], 1):  # 最多20对
            lines.append(
                f"[对{idx}] sim={sim:.3f}\n"
                f"  A({a['id'][:8]}): {a['body_md'][:200]}\n"
                f"  B({b['id'][:8]}): {b['body_md'][:200]}"
            )
        user_text = CURATE_USER.format(
            project_id=project_id,
            sim_min=f"{COARSE_FILTER}",
            sim_max=f"{HIGH_SIM}",
            pairs_text="\n\n".join(lines)[:8000],
        )

        msgs = [SystemMsg("curate", CURATE_SYSTEM), UserMsg("curate", user_text)]

        text = await _call_llm(msgs, task_name="curate")
        manifest = _parse_json_response(text)

        return self._apply_curate_manifest(manifest, {e["id"]: e for e in items})

    def _apply_curate_manifest(self, manifest: dict, item_map: dict) -> int:
        actions = manifest.get("actions", [])
        if not isinstance(actions, list):
            return 0
        count = 0
        conn = self._get_db_conn()
        try:
            for action in actions:
                aid = str(action.get("id", ""))
                act = action.get("action", "")
                if aid not in item_map:
                    continue
                if act == "merge":
                    new_content = str(action.get("new_content", ""))[:20000]
                    if new_content:
                        conn.execute(
                            """UPDATE experiences
                               SET body_md = %s, version = version + 1, updated_at = NOW()
                               WHERE id = %s""",
                            (new_content, aid),
                        )
                        count += 1
                elif act == "tighten":
                    new_content = str(action.get("new_content", ""))[:20000]
                    if new_content:
                        conn.execute(
                            """UPDATE experiences
                               SET body_md = %s, updated_at = NOW()
                               WHERE id = %s""",
                            (new_content, aid),
                        )
                        count += 1
                elif act == "archive":
                    conn.execute(
                        """UPDATE experiences
                           SET status = 'archived',
                               archived_reason = %s, updated_at = NOW()
                           WHERE id = %s""",
                        (f"curate:{action.get('reason', 'low_value')[:500]}", aid),
                    )
                    count += 1
        finally:
            conn.close()
        return count

    def _chain_safe_to_archive(self, memory: dict, project_id: str) -> bool:
        """参考 YourMemory graph_store.py:293-325 chain_safe_to_prune

        只有同 bucket 所有邻居 importance 也 < CURATE_ARCHIVE_IMPORTANCE 时才安全归档。
        """
        conn = self._get_db_conn()
        try:
            row = conn.execute(
                """SELECT MAX(e2.importance)
                   FROM experiences e1
                   JOIN experiences e2 ON e1.project_id = e2.project_id
                     AND e1.id != e2.id
                     AND e1.bucket = e2.bucket
                   WHERE e1.id = %s
                     AND e2.status = 'active'""",
                (memory["id"],),
            ).fetchone()
            if not row or row[0] is None:
                return True  # 孤立节点 → 安全
            return float(row[0]) < _cfg.DREAMER_CURATE_ARCHIVE_IMPORTANCE
        finally:
            conn.close()

    def _archive_low_value(self, experiences: list[dict], project_id: str) -> int:
        """低价值归档 — 参考 Magic Context curate archive"""
        archived = 0
        conn = self._get_db_conn()
        try:
            for exp in experiences:
                if float(exp.get("importance", 0.5)) >= ARCHIVE_IMPORTANCE:
                    continue
                if int(exp.get("recall_count", 0)) > 0:
                    continue
                if not self._chain_safe_to_archive(exp, project_id):
                    continue  # has strong neighbors, keep alive
                conn.execute(
                    """UPDATE experiences
                       SET status = 'archived',
                           archived_reason = 'low_value_auto', updated_at = NOW()
                       WHERE id = %s""",
                    (exp["id"],),
                )
                archived += 1
        finally:
            conn.close()
        return archived
