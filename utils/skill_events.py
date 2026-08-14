"""
Runtime skill event capture (Step 10).

Records tool errors, user corrections, and success patterns during agent
execution. All writes are synchronous PG inserts — events must not be lost.

Design decisions (ref: Agentica hooks.py ExperienceCaptureHooks):
  - 3 event types: tool_error | user_correction | success_pattern
  - Writes to skill_events PG table (not JSONL — unified storage)
  - Reuses _get_db_conn() connection pattern from lifecycle.py
  - is_compiled flag for incremental compilation
"""

from __future__ import annotations

import psycopg
from uuid import UUID

from . import config as _cfg


def _get_db_conn():
    """Create a fresh psycopg connection (same pattern as lifecycle.py:117-125)."""
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )


async def record_tool_error(
    project_id: str,
    role_id: str,
    tool_name: str,
    error_message: str,
) -> UUID | None:
    """Record a tool invocation failure.

    Called from build_role_node() after a tool call returns an error.

    Args:
        project_id: project identifier
        role_id: role name (e.g. "safety_director")
        tool_name: tool function name (e.g. "search_knowledge")
        error_message: the error text (first 2000 chars)

    Returns:
        UUID of the inserted row, or None on failure
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _record_tool_error_sync, project_id, role_id, tool_name, error_message,
    )


def _record_tool_error_sync(
    project_id: str, role_id: str, tool_name: str, error_message: str,
) -> UUID | None:
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """INSERT INTO skill_events (project_id, role_id, event_type, tool_name, error_message)
               VALUES (%s, %s, 'tool_error', %s, %s)
               RETURNING id""",
            (project_id, role_id, tool_name, error_message[:2000]),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


async def record_user_correction(
    project_id: str,
    role_id: str,
    user_message: str,
    previous_response: str,
) -> UUID | None:
    """Record a user correction of the agent's response.

    Called when user message contains correction patterns like
    "不对"/"应该是"/"记住" etc.

    Args:
        project_id: project identifier
        role_id: role name
        user_message: the user's correction message (first 500 chars)
        previous_response: the agent's response being corrected (first 500 chars)

    Returns:
        UUID of the inserted row, or None on failure
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _record_user_correction_sync,
        project_id, role_id, user_message, previous_response,
    )


def _record_user_correction_sync(
    project_id: str, role_id: str, user_message: str, previous_response: str,
) -> UUID | None:
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """INSERT INTO skill_events (project_id, role_id, event_type, user_message, previous_response)
               VALUES (%s, %s, 'user_correction', %s, %s)
               RETURNING id""",
            (project_id, role_id, user_message[:500], previous_response[:500]),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


async def record_success_pattern(
    project_id: str,
    role_id: str,
    tool_sequence: list[str],
    tool_count: int,
) -> UUID | None:
    """Record a successful multi-tool invocation sequence.

    Called when a role successfully uses >= 3 distinct tools in one run.

    Args:
        project_id: project identifier
        role_id: role name
        tool_sequence: ordered list of distinct tool names used
        tool_count: total number of tool calls in the run

    Returns:
        UUID of the inserted row, or None on failure
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _record_success_pattern_sync,
        project_id, role_id, tool_sequence, tool_count,
    )


def _record_success_pattern_sync(
    project_id: str, role_id: str, tool_sequence: list[str], tool_count: int,
) -> UUID | None:
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """INSERT INTO skill_events (project_id, role_id, event_type, tool_sequence, tool_count)
               VALUES (%s, %s, 'success_pattern', %s, %s)
               RETURNING id""",
            (project_id, role_id, tool_sequence[:10], tool_count),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


async def get_uncompiled_events(project_id: str) -> list[dict]:
    """Retrieve all uncompiled events for a project.

    Used by SkillCompiler to find new events that need compilation.

    Returns:
        list of event dicts ordered by created_at ASC
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_uncompiled_events_sync, project_id)


def _get_uncompiled_events_sync(project_id: str) -> list[dict]:
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """SELECT id, project_id, role_id, event_type, tool_name,
                      error_message, user_message, previous_response,
                      tool_sequence, tool_count, created_at
               FROM skill_events
               WHERE project_id = %s AND is_compiled = FALSE
               ORDER BY created_at""",
            (project_id,),
        )
        rows = cur.fetchall()
        conn.close()
        col_names = [
            "id", "project_id", "role_id", "event_type", "tool_name",
            "error_message", "user_message", "previous_response",
            "tool_sequence", "tool_count", "created_at",
        ]
        return [
            {col_names[i]: row[i] for i in range(len(col_names))}
            for row in rows
        ]
    except Exception:
        return []


async def mark_compiled(event_ids: list[str], skill_slug: str) -> int:
    """Mark events as compiled.

    Args:
        event_ids: list of event UUID strings
        skill_slug: the skill slug these events compiled into

    Returns:
        number of rows updated
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _mark_compiled_sync, event_ids, skill_slug,
    )


def _mark_compiled_sync(event_ids: list[str], skill_slug: str) -> int:
    if not event_ids:
        return 0
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """UPDATE skill_events
               SET is_compiled = TRUE, compiled_to_skill = %s
               WHERE id = ANY(%s::uuid[])""",
            (skill_slug, event_ids),
        )
        count = cur.rowcount
        conn.close()
        return count if count else 0
    except Exception:
        return 0
