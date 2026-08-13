"""Backfill project-bound AgentScope history into unified long-term memory."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentscope.app.memory._config import MemorySettings  # noqa: E402
from agentscope.app.memory._runtime import MemoryRuntime  # noqa: E402


@dataclass(frozen=True, slots=True)
class SessionBinding:
    """One AgentScope session resolved to immutable platform context."""

    session_id: str
    user_id: str
    agent_id: str
    project_id: str
    platform_user_id: str


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    """One plain-text message eligible for long-term-memory backfill."""

    session_id: str
    message_id: str
    role: str
    text: str
    created_at: Any


@dataclass(frozen=True, slots=True)
class BackfillReport:
    """History backfill counters safe to print without message content."""

    total_messages: int
    eligible_messages: int
    imported_messages: int
    already_imported: int
    skipped_unbound: int
    skipped_non_text: int


def _load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _platform_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    config = payload.get("config")
    if not isinstance(config, dict):
        return None
    context = config.get("platform_context")
    if not isinstance(context, dict):
        return None
    if context.get("project_id") in (None, ""):
        return None
    return context


def _resolve_bindings(
    sessions: list[dict[str, Any]],
    teams: list[dict[str, Any]],
) -> dict[str, SessionBinding]:
    sessions_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        sessions_by_id[str(session["id"])].append(session)
    team_leaders = {
        (str(team["user_id"]), str(team["id"])): str(team["session_id"])
        for team in teams
    }

    bindings: dict[str, SessionBinding] = {}
    for session in sessions:
        context = _platform_context(dict(session["payload"]))
        if context is None and session.get("team_id"):
            leader_session_id = team_leaders.get(
                (str(session["user_id"]), str(session["team_id"])),
            )
            candidates = sessions_by_id.get(leader_session_id or "", [])
            leader = next(
                (
                    candidate
                    for candidate in candidates
                    if str(candidate["user_id"]) == str(session["user_id"])
                    and str(candidate["agent_id"]) == ""
                ),
                None,
            )
            if leader is not None:
                context = _platform_context(dict(leader["payload"]))
        if context is None:
            continue

        session_id = str(session["id"])
        bindings[session_id] = SessionBinding(
            session_id=session_id,
            user_id=str(session["user_id"]),
            agent_id=str(session["agent_id"]),
            project_id=str(context["project_id"]),
            platform_user_id=str(
                context.get("user_id")
                if context.get("user_id") not in (None, "")
                else session["user_id"]
            ),
        )
    return bindings


def _message_text(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    parts = [
        str(block["text"])
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block["text"].strip()
    ]
    rendered = "\n".join(parts).strip()
    if not rendered or "\x00" in rendered:
        return None
    return rendered


def _history_messages(rows: list[dict[str, Any]]) -> list[HistoryMessage]:
    messages: list[HistoryMessage] = []
    for row in rows:
        payload = dict(row["payload"])
        role = str(payload.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        rendered = _message_text(payload)
        if rendered is None:
            continue
        messages.append(
            HistoryMessage(
                session_id=str(row["session_id"]),
                message_id=str(row["msg_id"]),
                role=role,
                text=rendered,
                created_at=row["created_at"],
            ),
        )
    return messages


def _already_backfilled(
    connection: Any,
    settings: MemorySettings,
    binding: SessionBinding,
    message: HistoryMessage,
) -> bool:
    content_hash = hashlib.sha256(message.text.encode("utf-8")).hexdigest()
    return bool(
        connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM memory.memory_audit_log
                    WHERE tenant_id = :tenant_id
                      AND project_id = :project_id
                      AND session_id = :session_id
                      AND agent_id = :agent_id
                      AND content_hash = :content_hash
                      AND action IN ('remember', 'remember_empty')
                )
                """,
            ),
            {
                "tenant_id": settings.tenant_id,
                "project_id": binding.project_id,
                "session_id": binding.session_id,
                "agent_id": binding.agent_id,
                "content_hash": content_hash,
            },
        ).scalar_one(),
    )


async def backfill_history(
    database_url: str,
    *,
    expected_database: str,
    apply: bool,
) -> BackfillReport:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("History backfill requires PostgreSQL")
    if url.database != expected_database:
        raise RuntimeError(
            f"Refusing backfill: connected database is {url.database!r}, "
            f"expected {expected_database!r}",
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            sessions = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT user_id, agent_id, team_id, id, payload "
                        "FROM agentscope.sessions",
                    ),
                ).mappings()
            ]
            teams = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT user_id, id, session_id, payload "
                        "FROM agentscope.teams",
                    ),
                ).mappings()
            ]
            raw_messages = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT session_id, msg_id, created_at, payload "
                        "FROM agentscope.messages "
                        "ORDER BY created_at, msg_id",
                    ),
                ).mappings()
            ]

        bindings = _resolve_bindings(sessions, teams)
        parsed_messages = _history_messages(raw_messages)
        eligible = [
            message
            for message in parsed_messages
            if message.session_id in bindings
        ]
        skipped_non_text = len(raw_messages) - len(parsed_messages)
        skipped_unbound = len(parsed_messages) - len(eligible)
        if not apply:
            return BackfillReport(
                total_messages=len(raw_messages),
                eligible_messages=len(eligible),
                imported_messages=0,
                already_imported=0,
                skipped_unbound=skipped_unbound,
                skipped_non_text=skipped_non_text,
            )

        settings = MemorySettings.from_env()
        runtime = MemoryRuntime(settings)
        imported = 0
        already = 0
        for message in eligible:
            binding = bindings[message.session_id]
            with engine.connect() as connection:
                if _already_backfilled(
                    connection,
                    settings,
                    binding,
                    message,
                ):
                    already += 1
                    continue
            scope = runtime.scope(
                project_id=binding.project_id,
                platform_user_id=binding.platform_user_id,
                agent_id=binding.agent_id,
                session_id=binding.session_id,
            )
            await runtime.scoped_client(scope).add(
                [{"role": message.role, "content": message.text}],
                infer=False,
                metadata={
                    "source": "legacy_agentscope_history",
                    "source_message_id": message.message_id,
                    "source_created_at": str(message.created_at),
                    "backfilled": True,
                },
            )
            imported += 1

        return BackfillReport(
            total_messages=len(raw_messages),
            eligible_messages=len(eligible),
            imported_messages=imported,
            already_imported=already,
            skipped_unbound=skipped_unbound,
            skipped_non_text=skipped_non_text,
        )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将可可靠绑定项目的 AgentScope 历史文本回填到统一记忆",
    )
    parser.add_argument("--expected-database", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际回填；省略时只统计覆盖率",
    )
    args = parser.parse_args()

    _load_project_env()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    report = asyncio.run(
        backfill_history(
            database_url,
            expected_database=args.expected_database,
            apply=args.apply,
        ),
    )
    print(
        f"history total={report.total_messages} "
        f"eligible={report.eligible_messages} "
        f"imported={report.imported_messages} "
        f"already_imported={report.already_imported} "
        f"skipped_unbound={report.skipped_unbound} "
        f"skipped_non_text={report.skipped_non_text}",
    )
    print("mode=" + ("applied" if args.apply else "inventory"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
