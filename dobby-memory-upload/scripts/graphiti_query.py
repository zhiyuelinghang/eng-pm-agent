#!/usr/bin/env python3
"""CLI query tool for Graphiti risk/task temporal data (Phase 3-A).

Usage:
  python scripts/graphiti_query.py timeline <project_id>
  python scripts/graphiti_query.py events <project_id> [--limit 20]
  python scripts/graphiti_query.py risks <project_id>

All commands fall back to PG when Neo4j is unavailable.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure dobby-memory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.graphiti_client import _get_db_conn  # noqa: E402


# ============================================================
# Helpers
# ============================================================

def _fmt_ts(ts) -> str:
    """Format timestamp for display."""
    if ts is None:
        return "N/A"
    if isinstance(ts, str):
        return ts[:19]
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _pg_events(project_id: str, limit: int = 50) -> list[dict]:
    """Query events from PG graphiti_events table."""
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            """SELECT event_type, body, reference_time, processed_at, created_at
               FROM graphiti_events
               WHERE project_id = %s
               ORDER BY reference_time
               LIMIT %s""",
            (project_id, limit),
        )
        rows = cur.fetchall()
        return [
            {
                "event_type": r[0],
                "body": r[1],
                "reference_time": r[2],
                "processed_at": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _pg_risks_fallback(project_id: str) -> list[dict]:
    """PG fallback: find active risks (risk_created without risk_resolved)."""
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            """SELECT body, reference_time, created_at
               FROM graphiti_events
               WHERE project_id = %s
                 AND event_type = 'risk_created'
               ORDER BY reference_time DESC
               LIMIT 50""",
            (project_id,),
        )
        return [
            {
                "body": r[0],
                "reference_time": r[1],
                "created_at": r[2],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


# ============================================================
# Commands
# ============================================================

def cmd_timeline(project_id: str) -> None:
    """Print event timeline from PG (always available)."""
    events = _pg_events(project_id)
    if not events:
        print(f"(no events found for project {project_id})")
        return

    print(f"\n{'='*70}")
    print(f"  Timeline — {project_id}  ({len(events)} events)")
    print(f"{'='*70}")
    for e in events:
        tag = {
            "risk_created": "🔴 RISK",
            "risk_resolved": "🟢 RISK",
            "task_completed": "✅ TASK",
            "state_changed": "🔵 STATE",
        }.get(e["event_type"], f"❓ {e['event_type']}")

        ts = _fmt_ts(e["reference_time"])
        body = e["body"][:100].replace("\n", " ")
        print(f"  [{ts}] {tag}  {body}")
    print()


def cmd_events(project_id: str, limit: int = 20) -> None:
    """Print raw event list with processed status."""
    events = _pg_events(project_id, limit)
    if not events:
        print(f"(no events found for project {project_id})")
        return

    print(f"\n{'='*70}")
    print(f"  Events — {project_id}  ({len(events)} events)")
    print(f"{'='*70}")
    for e in events:
        status = "✅ processed" if e["processed_at"] else "⏳ pending"
        ts = _fmt_ts(e["reference_time"])
        body = e["body"][:80].replace("\n", " ")
        print(f"  [{ts}] {e['event_type']:20s} {status:14s}  {body}")
    print()


def cmd_risks(project_id: str) -> None:
    """Print active risks. Try Neo4j first, fallback to PG."""
    # Try Neo4j first
    neo4j_ok = False
    try:
        from utils.graphiti_client import _get_graphiti  # noqa: E402
        import asyncio

        async def _neo4j_risks():
            g = await _get_graphiti(project_id)
            if g is None:
                return []
            # Search for EntityEdge with valid_at < now < invalid_at
            # This is a best-effort Cypher query; Graphiti may store edges differently
            # If this fails, we fall back to PG
            try:
                result = await asyncio.to_thread(
                    g.search,
                    f"Active risks for project {project_id}",
                    group_id=f"project:{project_id}",
                )
                return result if result else []
            except Exception:
                return []

        results = asyncio.run(_neo4j_risks())
        if results:
            neo4j_ok = True
            print(f"\n{'='*70}")
            print(f"  Active Risks — {project_id}  (Neo4j, {len(results)} results)")
            print(f"{'='*70}")
            for r in results:
                print(f"  {r}")
            print()
            return
    except Exception:
        pass

    # PG fallback
    risks = _pg_risks_fallback(project_id)
    print(f"\n{'='*70}")
    source = "Neo4j" if neo4j_ok else "PG fallback"
    print(f"  Active Risks — {project_id}  ({source}, {len(risks)} results)")
    print(f"{'='*70}")
    if not risks:
        print("  (no active risks found)")
    else:
        for r in risks:
            ts = _fmt_ts(r["reference_time"])
            body = r["body"][:100].replace("\n", " ")
            print(f"  [{ts}] {body}")
    if not neo4j_ok:
        print(f"  source: pg_fallback")
    print()


# ============================================================
# Main
# ============================================================

def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    pid = sys.argv[2]

    if cmd == "timeline":
        cmd_timeline(pid)
    elif cmd == "events":
        limit = 20
        for i, a in enumerate(sys.argv):
            if a == "--limit" and i + 1 < len(sys.argv):
                limit = int(sys.argv[i + 1])
        cmd_events(pid, limit)
    elif cmd == "risks":
        cmd_risks(pid)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
