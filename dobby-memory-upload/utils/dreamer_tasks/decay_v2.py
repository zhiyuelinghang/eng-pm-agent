# utils/dreamer_tasks/decay_v2.py
"""DecayV2Task — 参考 YourMemory decay_job.py + decay_curves.py"""

import math
import numpy as np
from datetime import datetime, timezone

from ..dreamer import DreamerTask, DreamerTaskConfig, DreamerResult
from .. import config as _cfg
from ..decay_curves import compute_strength, get_active_days_since
from .base import (
    _parse_dt, _now_iso, _parse_json_response,
    _get_advisory_lock, _release_advisory_lock, _write_run_log,
)

PRUNE_THRESHOLD = _cfg.MEMORY_PRUNE_THRESHOLD    # 0.05


class DecayV2Task(DreamerTask):
    """每日衰减维护 — 参考 YourMemory decay_job.py run()"""

    async def run(self, project_id: str) -> DreamerResult:
        started = datetime.now(timezone.utc)
        result = DreamerResult(task_name="decay")

        # ── 获取锁 ──
        lock_id, lock_conn = _get_advisory_lock(project_id, "decay")
        if lock_conn is None:
            result.skipped = True
            result.reason = "locked"
            return result

        try:
            conn = self._get_db_conn()
            try:
                cur = conn.execute(
                    """SELECT id, project_id, bucket, body_md, importance,
                              recall_count, created_at, strength, status
                       FROM experiences
                       WHERE project_id = %s AND status = 'active'""",
                    (project_id,),
                )
                rows = cur.fetchall()
            finally:
                conn.close()

            col_names = ["id", "project_id", "bucket", "body_md", "importance",
                         "recall_count", "created_at", "strength", "status"]
            memories = []
            for row in rows:
                mem = {}
                for i, name in enumerate(col_names):
                    mem[name] = row[i] if i < len(row) else None
                memories.append(mem)

            for mem in memories:
                created_at = _parse_dt(mem["created_at"])
                active_days = await get_active_days_since(project_id, created_at)
                strength = compute_strength(
                    created_at=created_at,
                    importance=float(mem.get("importance", 0.5)),
                    memory_type=mem.get("bucket", "procedure"),
                    recall_count=int(mem.get("recall_count", 0)),
                    active_days=active_days,
                )

                conn2 = self._get_db_conn()
                try:
                    if strength < PRUNE_THRESHOLD:
                        if not self._chain_safe_to_archive(mem, project_id):
                            conn2.execute(
                                "UPDATE experiences SET strength = %s WHERE id = %s",
                                (strength, mem["id"]),
                            )
                            result.updated += 1
                            continue
                        conn2.execute(
                            """UPDATE experiences
                               SET status = 'archived',
                                   archived_reason = %s,
                                   strength = %s,
                                   updated_at = NOW()
                               WHERE id = %s""",
                            (f"decayed:strength={strength:.4f}", strength, mem["id"]),
                        )
                        result.pruned += 1
                    else:
                        conn2.execute(
                            "UPDATE experiences SET strength = %s WHERE id = %s",
                            (strength, mem["id"]),
                        )
                        result.updated += 1
                finally:
                    conn2.close()

            # ── 衰减后委托给统一引擎（参考 YourMemory run() 调用 _consolidate()）──
            from ..consolidation_engine import ConsolidationEngine
            engine = ConsolidationEngine()
            cr = await engine.run(project_id, source="experiences", mode="nightly")
            result.consolidated = cr.direct_merged

        except Exception as exc:
            result.error = str(exc)
        finally:
            _release_advisory_lock(lock_id, lock_conn)

        result.duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        _write_run_log("decay", project_id,
                       {"pruned": result.pruned, "updated": result.updated,
                        "consolidated": result.consolidated},
                       status="completed" if not result.error else "failed",
                       error=result.error)
        return result

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

