"""
Graphiti client for Dobby (Step 7 — Phase 3-A).

Risk/task temporal tracking via Neo4j bi-temporal model.
Provides event queue (PG graphiti_events) + fire-and-forget Neo4j ingestion.

Graceful degradation: if Neo4j is unavailable, events remain queued in PG
and are processed on the next attempt. Callers never need to handle Neo4j errors.

Usage:
  from utils.graphiti_client import record_event, process_pending_events

  # Enqueue an event (always succeeds — PG is a hard dependency)
  event_id = await record_event(pid, "risk_resolved", "隐患已关闭")

  # Process pending events → Neo4j (fire-and-forget)
  result = await process_pending_events(pid)
  # → {"processed": 5, "failed": 0, "neo4j_available": True}
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from uuid import UUID

from . import config as _cfg


# ============================================================
# DB Connection (same pattern as lifecycle._get_db_conn)
# ============================================================

def _get_db_conn():
    """Create a fresh psycopg connection for graphiti_events writes."""
    import psycopg
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )


# ============================================================
# Neo4j / Graphiti Connection
# ============================================================

async def _get_graphiti(project_id: str):
    """Return a Graphiti instance for the given project.

    Returns None if Neo4j is unavailable (graceful degradation).
    group_id is passed per-episode via add_episode(), not at construction.

    Uses DeepSeek for LLM + local BGE-large-zh-v1.5 for embeddings.
    Graphiti internally creates an OpenAIRerankerClient which also needs
    OPENAI_API_KEY set — we point everything at DeepSeek's API.
    """
    try:
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.openai_client import OpenAIClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from neo4j import GraphDatabase
        from neo4j.exceptions import ServiceUnavailable

        # Health check: verify Neo4j is reachable
        driver = GraphDatabase.driver(
            _cfg.NEO4J_URI,
            auth=(_cfg.NEO4J_USER, _cfg.NEO4J_PASSWORD),
        )
        driver.verify_connectivity()
        driver.close()

        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")

        # Graphiti internally creates OpenAIRerankerClient which reads OPENAI_API_KEY.
        # Set it temporarily so all internal clients use DeepSeek.
        os.environ.setdefault("OPENAI_API_KEY", deepseek_key)

        # DeepSeek as LLM backend (OpenAI-compatible API)
        llm_config = LLMConfig(
            api_key=deepseek_key,
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash",
        )
        llm_client = OpenAIClient(config=llm_config)

        # Local BGE-large-zh-v1.5 for embeddings (OpenAI-compatible API on :9999)
        embedder_config = OpenAIEmbedderConfig(
            api_key="not-needed",
            base_url="http://localhost:9999/v1",
            model="BAAI/bge-large-zh-v1.5",
        )
        embedder = OpenAIEmbedder(config=embedder_config)

        return Graphiti(
            uri=_cfg.NEO4J_URI,
            user=_cfg.NEO4J_USER,
            password=_cfg.NEO4J_PASSWORD,
            llm_client=llm_client,
            embedder=embedder,
        )
    except (ServiceUnavailable, OSError, Exception):
        return None


# ============================================================
# Event Recording (PG queue — always succeeds)
# ============================================================

async def record_event(
    project_id: str,
    event_type: str,
    body: str,
    reference_time: datetime | None = None,
) -> UUID:
    """Enqueue an event to the graphiti_events table.

    Always succeeds — PG is a hard dependency for Dobby.

    Args:
        project_id: project identifier
        event_type: one of risk_created | risk_resolved | task_completed | state_changed
        body: free-text episode body (Chinese descriptions OK)
        reference_time: event time (→ Graphiti valid_at), defaults to NOW()

    Returns:
        UUID of the newly created event row
    """
    import psycopg

    conn = _get_db_conn()
    try:
        cur = conn.execute(
            """INSERT INTO graphiti_events (project_id, event_type, body, reference_time)
               VALUES (%s, %s, %s, %s)
               RETURNING id""",
            (project_id, event_type, body, reference_time or datetime.now(timezone.utc)),
        )
        row = cur.fetchone()
        return row[0] if row else UUID("00000000-0000-0000-0000-000000000000")
    finally:
        conn.close()


async def record_task_events(
    project_id: str,
    tasks: dict,
) -> int:
    """Batch-import task_completed events from a tasks dict.

    Mirrors the extract_experiences(tasks=...) parameter format.
    Only processes tasks with status == "done" and non-empty description.

    Args:
        project_id: project identifier
        tasks: {task_id: {status, description, ...}} dict

    Returns:
        Number of events written
    """
    count = 0
    for task_id, task_info in tasks.items():
        if not isinstance(task_info, dict):
            continue
        if task_info.get("status") != "done":
            continue
        desc = str(task_info.get("description", "")).strip()
        if not desc:
            continue
        try:
            await record_event(
                project_id=project_id,
                event_type="task_completed",
                body=desc,
            )
            count += 1
        except Exception:
            pass
    return count


# ============================================================
# Neo4j Ingestion (fire-and-forget, graceful degradation)
# ============================================================

async def process_pending_events(
    project_id: str,
    max_events: int | None = None,
    timeout_per_event: float | None = None,
) -> dict:
    """Process unprocessed events → fire-and-forget to Neo4j via Graphiti.

    1. SELECT pending events from PG queue (ORDER BY created_at)
    2. Connect to Neo4j → None? Return {"neo4j_available": False}
    3. For each event: asyncio.to_thread(graphiti.add_episode(...))
    4. On success: UPDATE processed_at = NOW()
    5. On failure: skip, retry next run

    Args:
        project_id: project identifier
        max_events: max events per run (default from config)
        timeout_per_event: seconds per add_episode call (default from config)

    Returns:
        {"processed": N, "failed": N, "neo4j_available": bool}
    """
    max_events = max_events or _cfg.GRAPHITI_MAX_EVENTS_PER_RUN
    timeout_per_event = timeout_per_event or _cfg.GRAPHITI_EVENT_TIMEOUT_SECONDS

    # ── 1. Load pending events ──
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            """SELECT id, event_type, body, reference_time
               FROM graphiti_events
               WHERE project_id = %s AND processed_at IS NULL
               ORDER BY created_at
               LIMIT %s""",
            (project_id, max_events),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {"processed": 0, "failed": 0, "neo4j_available": True}

    # ── 2. Connect to Neo4j ──
    graphiti = await _get_graphiti(project_id)
    if graphiti is None:
        return {"processed": 0, "failed": 0, "neo4j_available": False}

    # ── 3. Process each event ──
    processed = 0
    failed = 0

    for row in rows:
        event_id, event_type, body, reference_time = row

        try:
            # Graphiti add_episode is synchronous (5+ LLM calls internally)
            # Wrap in asyncio.to_thread to avoid blocking the event loop
            await asyncio.wait_for(
                asyncio.to_thread(
                    graphiti.add_episode,
                    name=f"evt_{event_id}",
                    episode_body=body,
                    source_description=_cfg.GRAPHITI_SOURCE_DESCRIPTION,
                    reference_time=reference_time or datetime.now(timezone.utc),
                    group_id=f"project:{project_id}",
                ),
                timeout=timeout_per_event,
            )

            # Mark processed
            conn2 = _get_db_conn()
            try:
                conn2.execute(
                    "UPDATE graphiti_events SET processed_at = %s WHERE id = %s",
                    (datetime.now(timezone.utc), event_id),
                )
            finally:
                conn2.close()

            processed += 1

        except asyncio.TimeoutError:
            failed += 1  # will retry next run
        except Exception:
            failed += 1  # will retry next run

    return {
        "processed": processed,
        "failed": failed,
        "neo4j_available": True,
    }


# ============================================================
# Hybrid Temporal Search (Phase 3-B)
# ============================================================


async def graphiti_search(
    project_id: str,
    query: str,
    limit: int | None = None,
) -> dict:
    """PG-first + Neo4j enrichment hybrid search for temporal data.

    Step 1 — PG timeline (always runs, <1ms):
        Query graphiti_events table for timeline + active risks.
    Step 2 — Neo4j enrichment (if available):
        Call graphiti.search() for bi-temporal precision.
    Step 3 — Merge and return structured dict.

    Args:
        project_id: project identifier
        query: search query for Neo4j semantic search
        limit: max results (default from config)

    Returns:
        {
            "timeline": [{"type": str, "body": str, "time": ISO8601 str}, ...],
            "active_risks": [str, ...],
            "source": "pg+neo4j" | "pg_only",
            "neo4j_available": bool,
        }
    """
    limit = limit or _cfg.GRAPHITI_SEARCH_LIMIT

    # ── Step 1: PG timeline (always runs) ──
    conn = _get_db_conn()
    try:
        # Timeline: recent events ordered by reference_time DESC
        cur = conn.execute(
            """SELECT event_type, body, reference_time
               FROM graphiti_events
               WHERE project_id = %s
               ORDER BY reference_time DESC
               LIMIT %s""",
            (project_id, limit),
        )
        timeline_rows = cur.fetchall()

        # Active risks: risk_created without a later risk_resolved (approximate)
        # PG lacks bi-temporal valid_at/invalid_at, uses event ordering heuristic:
        # a risk is "active" if the latest event for that risk is risk_created
        # (no risk_resolved with a later reference_time).
        cur = conn.execute(
            """SELECT body
               FROM graphiti_events AS created
               WHERE project_id = %s AND event_type = 'risk_created'
                 AND NOT EXISTS (
                   SELECT 1 FROM graphiti_events AS resolved
                   WHERE resolved.project_id = %s
                     AND resolved.event_type = 'risk_resolved'
                     AND resolved.reference_time > created.reference_time
                 )
               ORDER BY reference_time DESC
               LIMIT %s""",
            (project_id, project_id, limit),
        )
        risk_rows = cur.fetchall()
    finally:
        conn.close()

    # Build PG timeline
    timeline: list[dict] = []
    for row in timeline_rows:
        event_type, body, reference_time = row
        ref_time = reference_time
        if isinstance(ref_time, datetime):
            ref_time = ref_time.isoformat()
        timeline.append({
            "type": event_type,
            "body": body,
            "time": ref_time,
        })

    active_risks: list[str] = [row[0] for row in risk_rows]

    # ── Step 2: Neo4j enrichment (if available) ──
    neo4j_available = False
    source = "pg_only"

    graphiti = await _get_graphiti(project_id)
    if graphiti is not None:
        neo4j_available = True
        try:
            # graphiti.search() is async — await directly, not via to_thread
            await asyncio.wait_for(
                graphiti.search(
                    query,
                    group_ids=[f"project:{project_id}"],
                    num_results=limit,
                ),
                timeout=_cfg.GRAPHITI_SEARCH_TIMEOUT,
            )
            # Neo4j search succeeded — bi-temporal enrichment available
            source = "pg+neo4j"
        except (asyncio.TimeoutError, Exception):
            # Graceful degradation: PG results already captured
            pass

    return {
        "timeline": timeline,
        "active_risks": active_risks,
        "source": source,
        "neo4j_available": neo4j_available,
    }


def _format_timeline_context(data: dict) -> str:
    """Format graphiti_search() result dict into a context text block.

    The caller wraps this inside <system-reminder>...</system-reminder>.

    Tag mapping:
        risk_created   → 🔴 风险出现
        risk_resolved  → 🟢 风险关闭
        task_completed → ✅ 任务完成
        state_changed  → 🔵 状态变更

    Example output:
        【项目时间线】
          [2026-07-20] 🟢 风险关闭 — 安全隐患已排除
          [2026-07-18] ✅ 任务完成 — 完成安全巡检
        【活跃风险】
          ⚠️ 施工区域未设置围栏
        (来源: pg_only)
    """
    tag_map = {
        "risk_created": "🔴 风险出现",
        "risk_resolved": "🟢 风险关闭",
        "task_completed": "✅ 任务完成",
        "state_changed": "🔵 状态变更",
    }

    lines: list[str] = []

    # ── Timeline ──
    timeline: list[dict] = data.get("timeline", [])
    if timeline:
        lines.append("【项目时间线】")
        for event in timeline:
            event_type = event.get("type", "")
            tag = tag_map.get(event_type, f"❓ {event_type}")
            # Extract date portion (YYYY-MM-DD) from ISO8601 string
            time_str = event.get("time", "")[:10]
            body = event.get("body", "")
            lines.append(f"  [{time_str}] {tag} — {body}")

    # ── Active risks ──
    active_risks: list[str] = data.get("active_risks", [])
    if active_risks:
        lines.append("【活跃风险】")
        for risk in active_risks:
            lines.append(f"  ⚠️ {risk}")

    # ── Source ──
    source = data.get("source", "pg_only")
    lines.append(f"(来源: {source})")

    return "\n".join(lines)
