"""Dreamer Task 共享工具函数"""

import json
from datetime import datetime, timezone
from typing import Any

from .. import config as _cfg
from ..langgraph_utils import _call_model
from ..compression import _extract_text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(s: Any) -> datetime:
    """安全解析 datetime 字符串。失败时返回 epoch。"""
    if s is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        ts = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


async def _call_llm(msgs: list, task_name: str = "dreamer") -> str:
    """统一的 LLM 调用包装 — 委托给 langgraph_utils._call_model"""
    resp = await _call_model(msgs, intent="dreamer")
    return _extract_text(resp)


def _parse_json_response(text: str) -> dict:
    """解析 LLM JSON 响应，处理 markdown fences"""
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


def _get_advisory_lock(project_id: str, task_name: str) -> tuple[int, Any]:
    """获取 PG advisory lock — 参考 lifecycle.py:709-725

    Returns:
        (lock_id, lock_conn) — 调用者负责在 finally 中释放
    """
    import psycopg

    lock_id = hash(f"{project_id}:{task_name}") & 0x7FFFFFFF
    lock_conn = psycopg.Connection.connect(
        _cfg.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )
    cur = lock_conn.execute(
        "SELECT pg_try_advisory_lock(%s)", (lock_id,),
    )
    acquired = cur.fetchone()[0]
    if not acquired:
        lock_conn.close()
        return lock_id, None  # None 表示获取失败
    return lock_id, lock_conn


def _release_advisory_lock(lock_id: int, lock_conn) -> None:
    """释放 PG advisory lock — 参考 lifecycle.py:809-817"""
    try:
        lock_conn.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    except Exception:
        pass
    finally:
        try:
            lock_conn.close()
        except Exception:
            pass


def _write_run_log(task_name: str, project_id: str, result: dict,
                   status: str = "completed", error: str = "",
                   run_mode: str = "scheduled") -> None:
    """写入 dreamer_run_log — 参考 Magic Context 的 run history"""
    import psycopg

    try:
        conn = psycopg.Connection.connect(
            _cfg.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
        )
        try:
            conn.execute(
                """INSERT INTO dreamer_run_log
                   (project_id, task_name, status, result_json, error_message, run_mode, finished_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (project_id, task_name, status,
                 json.dumps(result, default=str) if result else None,
                 error[:2000] if error else None,
                 run_mode,
                 _now_iso()),
            )
        finally:
            conn.close()
    except Exception:
        pass
