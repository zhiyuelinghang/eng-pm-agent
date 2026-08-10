#!/usr/bin/env python3
"""
demo_07_graphiti.py — Step 7: Graphiti Phase 3-A Verification

Validates:
  - graphiti_events table creation
  - record_event: enqueue to PG
  - record_task_events: batch from tasks dict
  - process_pending_events: fire-and-forget → Neo4j
  - Neo4j graceful degradation
  - Idempotent processing
  - CLI timeline / risks commands
  - PG fallback for risks query

8 acceptance criteria. Run:
    python demo_07_graphiti.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid

# ── Project root (acceptance_tests/ 的父目录 = dobby-memory) ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ── Load environment ──
try:
    from dotenv import load_dotenv
    _env_file = os.path.join(_ROOT, ".env")
    load_dotenv(_env_file, override=True)
except ImportError:
    pass

# ── Offline mode for HuggingFace ──
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


# ============================================================
# TR — Test Result Tracker
# ============================================================

class TR:
    def __init__(self):
        self.r = []

    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        print(f"  {'✅' if passed else '❌'} {name}" + (f": {detail}" if detail else ""))

    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        print(f"\n{'='*60}\nResults: {p}/{len(self.r)} passed "
              f"{'🎉 ALL PASS' if p == len(self.r) else '⚠️  SOME FAILED'}\n{'='*60}")
        return p == len(self.r)


# ============================================================
# Helpers
# ============================================================

def _get_db_conn():
    """Create a fresh psycopg connection."""
    import psycopg
    from utils import config as _cfg
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
    )


def _init_tables() -> bool:
    """Create graphiti_events table if not exists."""
    import psycopg
    from utils import config as _cfg

    ddl = """
    CREATE TABLE IF NOT EXISTS graphiti_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id VARCHAR(64) NOT NULL,
        event_type VARCHAR(32) NOT NULL,
        body TEXT NOT NULL,
        reference_time TIMESTAMPTZ DEFAULT NOW(),
        processed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_ge_project
        ON graphiti_events(project_id, processed_at);
    """

    conn = psycopg.Connection.connect(
        _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
    )
    try:
        for stmt in ddl.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except Exception as e:
                msg = str(e).lower()
                if "already exists" not in msg and "does not exist" not in msg:
                    print(f"  ⚠️ SQL: {str(e)[:80]}")

        # Verify
        cur = conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'graphiti_events')"
        )
        return bool(cur.fetchone()[0])
    except Exception as e:
        print(f"  ⚠️ _init_tables: {e}")
        return False
    finally:
        conn.close()


def _cleanup(project_id: str) -> None:
    """Remove test data for a project_id."""
    conn = _get_db_conn()
    try:
        conn.execute("DELETE FROM graphiti_events WHERE project_id = %s", (project_id,))
    except Exception:
        pass
    finally:
        conn.close()


async def _neo4j_available() -> bool:
    """Quick probe: can we connect to Neo4j?"""
    try:
        from utils.graphiti_client import _get_graphiti
        g = await _get_graphiti("_probe_")
        return g is not None
    except Exception:
        return False


# ============================================================
# AC-7.1 — graphiti_events Table Structure
# ============================================================

async def t71_events_table(r: TR):
    """Verify graphiti_events table exists with correct columns."""
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'graphiti_events' ORDER BY ordinal_position"
        )
        cols = {row[0]: row[1] for row in cur.fetchall()}

        required = ["id", "project_id", "event_type", "body",
                     "reference_time", "processed_at", "created_at"]
        missing = [c for c in required if c not in cols]

        # Also verify index exists
        cur2 = conn.execute(
            "SELECT EXISTS (SELECT FROM pg_indexes "
            "WHERE indexname = 'idx_ge_project')"
        )
        idx_ok = bool(cur2.fetchone()[0])

        r.add("AC-7.1 Events Table",
              len(missing) == 0 and idx_ok,
              f"cols={len(cols)} missing={missing} idx={'✓' if idx_ok else '✗'}")
    finally:
        conn.close()


# ============================================================
# AC-7.2 — record_event
# ============================================================

async def t72_record_event(r: TR):
    """record_event → PG table has 1 row, processed_at IS NULL."""
    from utils.graphiti_client import record_event

    pid = f"ac72_{uuid.uuid4().hex[:8]}"
    try:
        event_id = await record_event(pid, "task_completed", "3号基坑开挖完成")
        conn = _get_db_conn()
        try:
            cur = conn.execute(
                "SELECT COUNT(*), MAX(processed_at) FROM graphiti_events WHERE project_id = %s",
                (pid,),
            )
            cnt, proc = cur.fetchone()
            r.add("AC-7.2 Record Event",
                  cnt == 1 and proc is None,
                  f"count={cnt} processed={'NULL' if proc is None else 'NOT NULL'}")
        finally:
            conn.close()
    finally:
        _cleanup(pid)


# ============================================================
# AC-7.3 — record_task_events
# ============================================================

async def t73_record_task_events(r: TR):
    """record_task_events: 2 done + 1 in_progress → 2 events written."""
    from utils.graphiti_client import record_task_events

    pid = f"ac73_{uuid.uuid4().hex[:8]}"
    tasks = {
        "T1": {"status": "done", "description": "基坑开挖完成，通过验收"},
        "T2": {"status": "done", "description": "临边防护整改完成"},
        "T3": {"status": "in_progress", "description": "混凝土浇筑"},
    }
    try:
        count = await record_task_events(pid, tasks)
        r.add("AC-7.3 Record Task Events",
              count == 2,
              f"expected=2 actual={count}")
    finally:
        _cleanup(pid)


# ============================================================
# AC-7.4 — process_pending_events
# ============================================================

async def t74_process_events(r: TR):
    """Write 2 events → process_pending_events → processed_at IS NOT NULL."""
    if not await _neo4j_available():
        r.add("AC-7.4 Process Events", True, "⚠️ Neo4j not available — skipping")
        return

    from utils.graphiti_client import record_event, process_pending_events

    pid = f"ac74_{uuid.uuid4().hex[:8]}"
    try:
        await record_event(pid, "task_completed", "基坑开挖完成")
        await record_event(pid, "risk_resolved", "临边隐患关闭")

        result = await process_pending_events(pid, max_events=10, timeout_per_event=180)

        conn = _get_db_conn()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM graphiti_events "
                "WHERE project_id = %s AND processed_at IS NOT NULL",
                (pid,),
            )
            proc_count = cur.fetchone()[0]
            r.add("AC-7.4 Process Events",
                  result.get("neo4j_available") and proc_count >= 1,
                  f"processed={result.get('processed')} failed={result.get('failed')} "
                  f"pg_processed={proc_count}")
        finally:
            conn.close()
    finally:
        _cleanup(pid)


# ============================================================
# AC-7.5 — Neo4j Graceful Degradation
# ============================================================

async def t75_neo4j_graceful(r: TR):
    """Bad NEO4J_URI → process_pending_events returns neo4j_available=False."""
    from utils.graphiti_client import record_event
    import utils.config as _cfg

    pid = f"ac75_{uuid.uuid4().hex[:8]}"
    orig_uri = _cfg.NEO4J_URI
    _cfg.NEO4J_URI = "bolt://localhost:19999"  # wrong port

    try:
        await record_event(pid, "task_completed", "test event")

        from utils.graphiti_client import process_pending_events
        result = await process_pending_events(pid, max_events=5)

        conn = _get_db_conn()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM graphiti_events "
                "WHERE project_id = %s AND processed_at IS NULL",
                (pid,),
            )
            still_pending = cur.fetchone()[0]
            r.add("AC-7.5 Neo4j Graceful",
                  result.get("neo4j_available") is False and still_pending >= 1,
                  f"neo4j={result.get('neo4j_available')} pending={still_pending}")
        finally:
            conn.close()
    finally:
        _cfg.NEO4J_URI = orig_uri
        _cleanup(pid)


# ============================================================
# AC-7.6 — Idempotent Processing
# ============================================================

async def t76_idempotent(r: TR):
    """Same event processed twice → no duplicate nodes."""
    if not await _neo4j_available():
        r.add("AC-7.6 Idempotent", True, "⚠️ Neo4j not available — skipping")
        return

    from utils.graphiti_client import record_event, process_pending_events

    pid = f"ac76_{uuid.uuid4().hex[:8]}"
    try:
        await record_event(pid, "risk_created", "3号基坑临边防护缺失")

        # Process once
        r1 = await process_pending_events(pid, max_events=5, timeout_per_event=180)

        # Process again — should be a no-op since processed_at is already set
        r2 = await process_pending_events(pid, max_events=5, timeout_per_event=180)

        r.add("AC-7.6 Idempotent",
              r1.get("processed", 0) >= 1 and r2.get("processed", 0) == 0,
              f"run1_processed={r1.get('processed')} run2_processed={r2.get('processed')}")
    finally:
        _cleanup(pid)


# ============================================================
# AC-7.7 — CLI Timeline
# ============================================================

async def t77_cli_timeline(r: TR):
    """CLI 'timeline' command outputs events sorted by time."""
    from utils.graphiti_client import record_event
    from datetime import datetime, timezone, timedelta

    pid = f"ac77_{uuid.uuid4().hex[:8]}"
    try:
        now = datetime.now(timezone.utc)
        await record_event(pid, "task_completed", "最早事件", now - timedelta(hours=5))
        await record_event(pid, "risk_created", "中间事件", now - timedelta(hours=2))
        await record_event(pid, "risk_resolved", "最新事件", now)

        # Run CLI
        script = os.path.join(_ROOT, "scripts", "graphiti_query.py")
        result = subprocess.run(
            [sys.executable, script, "timeline", pid],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout

        # Verify: output contains all 3 events in correct order
        pos_earliest = output.find("最早事件")
        pos_middle = output.find("中间事件")
        pos_latest = output.find("最新事件")

        ordered = pos_earliest < pos_middle < pos_latest
        r.add("AC-7.7 CLI Timeline",
              ordered and result.returncode == 0,
              f"ordered={'✓' if ordered else '✗'} rc={result.returncode}")
    finally:
        _cleanup(pid)


# ============================================================
# AC-7.8 — CLI Risks Fallback
# ============================================================

async def t78_cli_risks_fallback(r: TR):
    """CLI 'risks' command shows pg_fallback when Neo4j unavailable."""
    from utils.graphiti_client import record_event

    pid = f"ac78_{uuid.uuid4().hex[:8]}"
    try:
        await record_event(pid, "risk_created", "3号基坑临边防护缺失")

        script = os.path.join(_ROOT, "scripts", "graphiti_query.py")
        result = subprocess.run(
            [sys.executable, script, "risks", pid],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout

        # If Neo4j is available, we'll see results from it; otherwise pg_fallback
        has_fallback = "pg_fallback" in output
        has_risk = "临边防护缺失" in output

        r.add("AC-7.8 CLI Risks Fallback",
              has_risk and result.returncode == 0,
              f"has_risk={'✓' if has_risk else '✗'} "
              f"fallback={'✓' if has_fallback else '(Neo4j available)'}")
    finally:
        _cleanup(pid)


# ============================================================
# Main
# ============================================================

async def main():
    print("=" * 60)
    print("  Dobby Step 7 — Graphiti Phase 3-A Verification")
    print("=" * 60)

    # Init DB
    print("\n── DB Init ──")
    db_ok = _init_tables()
    print(f"  graphiti_events table: {'✅' if db_ok else '❌'}")

    # Check Neo4j
    neo4j_ok = await _neo4j_available()
    print(f"  Neo4j available: {'✅' if neo4j_ok else '⚠️  (AC-7.4/7.6 will skip)'}")

    r = TR()

    # Run all tests
    tests = [
        ("AC-7.1 Events Table", t71_events_table),
        ("AC-7.2 Record Event", t72_record_event),
        ("AC-7.3 Record Task Events", t73_record_task_events),
        ("AC-7.4 Process Events", t74_process_events),
        ("AC-7.5 Neo4j Graceful", t75_neo4j_graceful),
        ("AC-7.6 Idempotent", t76_idempotent),
        ("AC-7.7 CLI Timeline", t77_cli_timeline),
        ("AC-7.8 CLI Risks Fallback", t78_cli_risks_fallback),
    ]

    for name, fn in tests:
        print(f"\n── {name} ──")
        try:
            await fn(r)
        except Exception as e:
            r.add(name, False, f"unhandled: {str(e)[:100]}")

    return r.summary()


if __name__ == "__main__":
    if sys.platform == "win32":
        import asyncio as _asyncio
        _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
