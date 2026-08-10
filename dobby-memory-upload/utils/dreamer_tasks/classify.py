# utils/dreamer_tasks/classify.py
"""ClassifyTask — 参考 Magic Context dreamer.ts DREAMER_CLASSIFIER_AGENT:
   prompt → manifest, ZERO tools, HOST applies"""

from datetime import datetime, timezone

from ..dreamer import DreamerTask, DreamerResult
from .. import config as _cfg
from .base import (
    _call_llm, _parse_json_response,
    _get_advisory_lock, _release_advisory_lock, _write_run_log,
)

BATCH_SIZE = _cfg.DREAMER_CLASSIFY_BATCH_SIZE  # 100

CLASSIFY_SYSTEM = """你是 Dobby 记忆分类器。分析每条经验的文本内容，输出评分。

**评分维度** (importance 0-1):
- 0.9: 关键安全规范引用、不可违反的约束
- 0.7: 重要决策记录、已验证的最佳实践
- 0.5: 有用的经验教训
- 0.3: 一般性观察、可选的建议
- 0.1: 琐碎记录

**评分依据**（仅从文本判断）:
- 包含规范编号/版本号 → 重要性高
- 描述"必须""禁止""不得" → 重要性高
- 描述具体操作步骤 → 中等
- 描述一般性观察 → 低

**输出格式** — 严格 JSON:
{
  "classifications": [
    {"id": "UUID", "importance": 0.85, "reason": "引用了强制性规范"}
  ]
}
只输出 JSON。"""

CLASSIFY_USER = """项目: {project_id}

以下经验需要评分:

{memories_text}

评估每条经验的重要性，输出 JSON。"""


class ClassifyTask(DreamerTask):
    """记忆重要性自动评分 — 参考 Magic Context DREAMER_CLASSIFIER_AGENT"""

    async def run(self, project_id: str) -> DreamerResult:
        started = datetime.now(timezone.utc)
        result = DreamerResult(task_name="classify")

        lock_id, lock_conn = _get_advisory_lock(project_id, "classify")
        if lock_conn is None:
            result.skipped = True
            result.reason = "locked"
            return result

        try:
            # ── 加载未分类的记忆 ──
            memories = self._load_unclassified(project_id)
            if not memories:
                result.skipped = True
                result.reason = "nothing_to_classify"
                return result

            # ── 分批处理 ──
            for i in range(0, len(memories), BATCH_SIZE):
                batch = memories[i:i + BATCH_SIZE]
                classified = await self._classify_batch(project_id, batch)
                result.classified += classified

        except Exception as exc:
            result.error = str(exc)
        finally:
            _release_advisory_lock(lock_id, lock_conn)

        result.duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        _write_run_log("classify", project_id,
                       {"classified": result.classified},
                       status="completed" if not result.error else "failed",
                       error=result.error)
        return result

    def _load_unclassified(self, project_id: str) -> list[dict]:
        conn = self._get_db_conn()
        try:
            cur = conn.execute(
                """SELECT id, bucket, body_md, importance
                   FROM experiences
                   WHERE project_id = %s
                     AND status = 'active'
                     AND classified_at IS NULL
                   ORDER BY created_at
                   LIMIT %s""",
                (project_id, BATCH_SIZE * 3),  # 一次最多3批
            )
            cols = ["id", "bucket", "body_md", "importance"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    async def _classify_batch(self, project_id: str, batch: list[dict]) -> int:
        mem_lines = []
        for m in batch:
            mem_lines.append(
                f"[{m['id']}] bucket={m['bucket']}\n"
                f"  内容: {m['body_md'][:300]}"
            )
        user_text = CLASSIFY_USER.format(
            project_id=project_id,
            memories_text="\n\n".join(mem_lines),
        )

        from agentscope.message import SystemMsg, UserMsg
        msgs = [SystemMsg("classify", CLASSIFY_SYSTEM), UserMsg("classify", user_text)]

        try:
            text = await _call_llm(msgs, task_name="classify")
            manifest = _parse_json_response(text)
        except Exception:
            return 0

        return self._apply_classifications(manifest)

    def _apply_classifications(self, manifest: dict) -> int:
        """HOST端批量更新 — 缓存中立"""
        items = manifest.get("classifications", [])
        if not isinstance(items, list):
            return 0

        conn = self._get_db_conn()
        count = 0
        try:
            for item in items:
                cid = str(item.get("id", ""))
                importance = float(item.get("importance", 0.5))
                if cid:
                    conn.execute(
                        """UPDATE experiences
                           SET importance = %s, classified_at = NOW()
                           WHERE id = %s""",
                        (min(1.0, max(0.0, importance)), cid),
                    )
                    count += 1
        finally:
            conn.close()
        return count
