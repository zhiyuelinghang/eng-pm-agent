# utils/dreamer_tasks/verify.py
"""VerifyTask — 参考 Magic Context verify.ts: 分批验证 + HOST端解析 + 缓存中立"""

from datetime import datetime, timezone

from ..dreamer import DreamerTask, DreamerResult
from .. import config as _cfg
from .base import (
    _call_llm, _parse_dt, _now_iso, _parse_json_response,
    _get_advisory_lock, _release_advisory_lock, _write_run_log,
)

BATCH_SIZE = _cfg.DREAMER_VERIFY_BATCH_SIZE  # 50
BROAD_INTERVAL = _cfg.DREAMER_VERIFY_BROAD_INTERVAL_DAYS  # 7

VERIFY_SYSTEM = """你是 Dobby 记忆验证器。任务是检查经验记忆中引用的规范/事实是否仍然有效。

**验证规则**:
1. 如果经验引用了具体规范编号(如 JGJ 130-2011)，判断该规范是否仍为现行版本
2. 如果经验描述了操作流程，判断是否可能已过时
3. 如果是通用程序性知识(无特定版本依赖)，标记为 verified

**输出格式** — 严格 JSON:
{
  "actions": [
    {"id": "经验UUID", "action": "verified|update|archive",
     "reason": "简短原因",
     "new_content": "仅 action=update 时需要，提供更新后的内容"}
  ]
}
每条经验必须出现在 actions 中。只输出 JSON，不要其他文字。"""

VERIFY_USER = """项目: {project_id}
验证模式: {mode}

以下经验需要验证时效性:

{memories_text}

对每条经验判断其内容是否仍然准确有效，输出 JSON。"""


class VerifyTask(DreamerTask):
    """记忆时效验证 — 参考 Magic Context verify.ts"""

    async def run(self, project_id: str) -> DreamerResult:
        started = datetime.now(timezone.utc)
        result = DreamerResult(task_name="verify")

        lock_id, lock_conn = _get_advisory_lock(project_id, "verify")
        if lock_conn is None:
            result.skipped = True
            result.reason = "locked"
            return result

        mode = "unknown"
        try:
            # ── Step 1: 确定验证范围 ──
            mode, items = self._partition_scope(project_id)
            if not items:
                result.skipped = True
                result.reason = f"nothing_to_verify (mode={mode})"
                return result

            # ── Step 2: 分批验证 ──
            for i in range(0, len(items), BATCH_SIZE):
                batch = items[i:i + BATCH_SIZE]
                counts = await self._verify_batch(project_id, batch, mode)
                result.verified += counts["verified"]
                result.updated += counts["updated"]
                result.archived += counts["archived"]

        except Exception as exc:
            result.error = str(exc)
        finally:
            _release_advisory_lock(lock_id, lock_conn)

        result.duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        _write_run_log("verify", project_id,
                       {"verified": result.verified, "updated": result.updated,
                        "archived": result.archived, "mode": mode},
                       status="completed" if not result.error else "failed",
                       error=result.error)
        return result

    def _partition_scope(self, project_id: str) -> tuple[str, list[dict]]:
        """参考 verify-gate.ts partitionVerifyScope: 增量 vs 全量"""
        conn = self._get_db_conn()
        try:
            # 检查上次全量验证时间
            cur = conn.execute(
                """SELECT MAX(finished_at) FROM dreamer_run_log
                   WHERE project_id = %s AND task_name = 'verify'
                     AND status = 'completed'
                     AND result_json->>'mode' = 'broad'""",
                (project_id,),
            )
            row = cur.fetchone()
            last_broad = _parse_dt(row[0]) if row and row[0] else None
            days_since = (
                (datetime.now(timezone.utc) - last_broad).total_seconds() / 86400
                if last_broad else 999
            )

            if days_since >= BROAD_INTERVAL:
                # Broad: 加载所有活跃经验
                cur = conn.execute(
                    """SELECT id, bucket, body_md, importance, verified_at
                       FROM experiences
                       WHERE project_id = %s AND status = 'active'
                       ORDER BY importance DESC""",
                    (project_id,),
                )
                items = self._rows_to_dicts(cur)
                return ("broad", items)
            else:
                # Incremental: 只加载 verified_at IS NULL 或超过7天未验证的
                cur = conn.execute(
                    """SELECT id, bucket, body_md, importance, verified_at
                       FROM experiences
                       WHERE project_id = %s AND status = 'active'
                         AND (verified_at IS NULL
                              OR verified_at < NOW() - INTERVAL '7 days')
                       ORDER BY verified_at ASC NULLS FIRST""",
                    (project_id,),
                )
                items = self._rows_to_dicts(cur)
                return ("incremental", items)
        finally:
            conn.close()

    @staticmethod
    def _rows_to_dicts(cur) -> list[dict]:
        cols = ["id", "bucket", "body_md", "importance", "verified_at"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    async def _verify_batch(self, project_id: str, batch: list[dict],
                             mode: str) -> dict[str, int]:
        """参考 verify.ts verifyOneBatch: prompt → LLM → HOST端 apply"""
        # ── 构建 prompt ──
        mem_lines = []
        for m in batch:
            mem_lines.append(
                f"[{m['id']}] bucket={m['bucket']} importance={m['importance']}\n"
                f"  内容: {m['body_md'][:500]}"
            )
        user_text = VERIFY_USER.format(
            project_id=project_id,
            mode=mode,
            memories_text="\n\n".join(mem_lines),
        )

        from agentscope.message import SystemMsg, UserMsg
        msgs = [
            SystemMsg("verify", VERIFY_SYSTEM),
            UserMsg("verify", user_text),
        ]

        try:
            text = await _call_llm(msgs, task_name="verify")
            manifest = _parse_json_response(text)
        except Exception:
            return {"verified": 0, "updated": 0, "archived": 0}

        # ── HOST 端 apply（Agent 不写 DB）──
        return self._apply_manifest(project_id, manifest, {m["id"]: m for m in batch})

    def _apply_manifest(self, project_id: str, manifest: dict,
                         batch_map: dict) -> dict[str, int]:
        """参考 verify.ts applyVerifyManifest: HOST端解析并执行写入"""
        counts = {"verified": 0, "updated": 0, "archived": 0}
        actions = manifest.get("actions", [])
        if not isinstance(actions, list):
            return counts

        conn = self._get_db_conn()
        try:
            for action in actions:
                aid = str(action.get("id", ""))
                act = action.get("action", "")
                if aid not in batch_map:
                    continue

                now = _now_iso()
                if act == "verified":
                    conn.execute(
                        "UPDATE experiences SET verified_at = %s WHERE id = %s",
                        (now, aid),
                    )
                    counts["verified"] += 1
                elif act == "update":
                    new_content = str(action.get("new_content", ""))[:20000]
                    if new_content:
                        conn.execute(
                            """UPDATE experiences
                               SET body_md = %s, verified_at = %s,
                                   classified_at = NULL, updated_at = NOW()
                               WHERE id = %s""",
                            (new_content, now, aid),
                        )
                        counts["updated"] += 1
                    else:
                        # 空内容 → fallback 为 verify
                        conn.execute(
                            "UPDATE experiences SET verified_at = %s WHERE id = %s",
                            (now, aid),
                        )
                        counts["verified"] += 1
                elif act == "archive":
                    conn.execute(
                        """UPDATE experiences
                           SET status = 'archived',
                               archived_reason = %s,
                               updated_at = NOW()
                           WHERE id = %s""",
                        (f"verify:{action.get('reason', 'outdated')[:500]}", aid),
                    )
                    counts["archived"] += 1
        finally:
            conn.close()

        return counts
