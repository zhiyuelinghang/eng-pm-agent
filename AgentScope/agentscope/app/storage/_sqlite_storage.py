# -*- coding: utf-8 -*-
# pylint: disable=too-many-lines,too-many-public-methods
"""SQLite-backed AgentScope application storage.

This backend is intended for a single-node deployment that needs durable
metadata without operating Redis.  SQLite stores credentials, agents,
sessions, messages, schedules, teams, and knowledge-base metadata.  Vector
data remains the responsibility of the configured vector store (Qdrant in
the local development application).
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import warnings
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Self, TypeVar

from ._base import StorageBase
from ._model import (
    AgentRecord,
    CredentialRecord,
    KnowledgeBaseRecord,
    KnowledgeDocumentRecord,
    KnowledgeDocumentStatus,
    ScheduleRecord,
    SessionConfig,
    SessionRecord,
    SessionSource,
    TeamRecord,
)
from ._utils import _dump_with_secrets
from ...credential import CredentialBase
from ...message import Msg
from ...state import AgentState


_ResultT = TypeVar("_ResultT")


class SQLiteStorage(StorageBase):
    """Persist AgentScope application records in one SQLite database file.

    All access to the process-local connection is serialised with an
    :class:`asyncio.Lock` and executed in a worker thread, so SQLite I/O does
    not block the event loop.  ``WAL`` mode and a configurable busy timeout
    make normal hot-reload and short-lived multi-connection overlap safe.
    """

    SCHEMA_VERSION = 1
    _EXPECTED_COLUMNS = {
        "credentials": {"user_id", "id", "payload"},
        "agents": {"user_id", "id", "source", "payload"},
        "sessions": {
            "user_id",
            "id",
            "agent_id",
            "source_schedule_id",
            "team_id",
            "created_at",
            "payload",
        },
        "schedules": {"user_id", "id", "agent_id", "payload"},
        "messages": {
            "sequence",
            "user_id",
            "session_id",
            "message_id",
            "payload",
        },
        "teams": {"user_id", "id", "session_id", "payload"},
        "knowledge_bases": {"user_id", "id", "payload"},
        "knowledge_documents": {
            "user_id",
            "knowledge_base_id",
            "id",
            "processing_node",
            "status",
            "lease_expires_at",
            "created_at",
            "payload",
        },
    }

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        busy_timeout_ms: int = 10_000,
    ) -> None:
        """Store the SQLite path; the connection opens in ``__aenter__``.

        Args:
            database_path:
                SQLite database path. ``":memory:"`` is accepted for tests.
            busy_timeout_ms:
                How long SQLite waits for another writer before raising
                ``OperationalError``.
        """
        raw_path = os.fspath(database_path)
        self.database_path = (
            raw_path
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Open the database and initialise its schema."""
        async with self._lock:
            if self._connection is None:
                self._connection = await asyncio.to_thread(
                    self._open_connection,
                )
        return self

    async def aclose(self) -> None:
        """Commit pending work and close the SQLite connection."""
        async with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                await asyncio.to_thread(connection.close)

    def _open_connection(self) -> sqlite3.Connection:
        """Create and configure the process-local SQLite connection."""
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")

            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0],
            )
            if current_version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    "SQLite 数据库版本高于当前 AgentScope 支持版本："
                    f"{current_version} > {self.SCHEMA_VERSION}",
                )

            self._reset_incompatible_empty_schema(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    user_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, id)
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS agents (
                    user_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, id)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_agents_user_source
                    ON agents (user_id, source);

                CREATE TABLE IF NOT EXISTS sessions (
                    user_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    source_schedule_id TEXT,
                    team_id TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, id)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_sessions_user_agent_created
                    ON sessions (user_id, agent_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_sessions_user_schedule_created
                    ON sessions (
                        user_id,
                        source_schedule_id,
                        created_at DESC
                    );

                CREATE TABLE IF NOT EXISTS schedules (
                    user_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, id)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_schedules_user_agent
                    ON schedules (user_id, agent_id);

                CREATE TABLE IF NOT EXISTS messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_sequence
                    ON messages (user_id, session_id, sequence);

                CREATE INDEX IF NOT EXISTS idx_messages_session_message
                    ON messages (
                        user_id,
                        session_id,
                        message_id,
                        sequence DESC
                    );

                CREATE TABLE IF NOT EXISTS teams (
                    user_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, id)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_teams_user_session
                    ON teams (user_id, session_id);

                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    user_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, id)
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    user_id TEXT NOT NULL,
                    knowledge_base_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    processing_node TEXT,
                    status TEXT NOT NULL,
                    lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, knowledge_base_id, id)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_documents_kb
                    ON knowledge_documents (user_id, knowledge_base_id);

                CREATE INDEX IF NOT EXISTS idx_documents_lease
                    ON knowledge_documents (
                        status,
                        processing_node,
                        lease_expires_at
                    );

                CREATE INDEX IF NOT EXISTS idx_documents_pending_created
                    ON knowledge_documents (status, created_at);
                """,
            )
            connection.execute(
                f"PRAGMA user_version={self.SCHEMA_VERSION}",
            )
        except Exception:
            connection.close()
            raise
        return connection

    @classmethod
    def _reset_incompatible_empty_schema(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        """Rebuild an incompatible schema only when it contains no records.

        An earlier local SQLite experiment used the same table names but a
        different message schema (``msg_id`` and no ``user_id``/sequence).
        Its empty database may still exist in ``data/agentscope``.  Reusing
        those tables makes ``CREATE INDEX IF NOT EXISTS`` fail before the app
        can start.  Empty tables are safe to rebuild automatically; any
        populated incompatible database is left untouched and produces an
        actionable error instead of risking data loss.
        """
        incompatible_tables: list[str] = []
        existing_tables: list[str] = []
        for table, expected_columns in cls._EXPECTED_COLUMNS.items():
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists is None:
                continue
            existing_tables.append(table)
            columns = {
                row["name"]
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")',
                ).fetchall()
            }
            if not expected_columns.issubset(columns):
                incompatible_tables.append(table)

        if not incompatible_tables:
            return

        populated = {
            table: int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"',
                ).fetchone()[0],
            )
            for table in existing_tables
        }
        populated = {
            table: count for table, count in populated.items() if count > 0
        }
        if populated:
            details = "，".join(
                f"{table}={count}" for table, count in populated.items()
            )
            raise RuntimeError(
                "检测到含数据的旧版 AgentScope SQLite 表结构，已停止启动以"
                f"避免覆盖数据（{details}）。请先迁移或另设 "
                "AGENTSCOPE_SQLITE_PATH。",
            )

        connection.execute("PRAGMA foreign_keys=OFF")
        try:
            for table in (
                "knowledge_documents",
                "messages",
                "sessions",
                "schedules",
                "teams",
                "knowledge_bases",
                "agents",
                "credentials",
            ):
                connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        finally:
            connection.execute("PRAGMA foreign_keys=ON")

    def _require_connection(self) -> sqlite3.Connection:
        """Return the open connection or explain the lifecycle contract."""
        if self._connection is None:
            raise RuntimeError(
                "SQLiteStorage 尚未启动；请先使用 'async with storage' "
                "或让 create_app() 管理其生命周期。",
            )
        return self._connection

    async def _run(
        self,
        operation: Callable[[sqlite3.Connection], _ResultT],
    ) -> _ResultT:
        """Run one serialised SQLite operation outside the event loop."""
        async with self._lock:
            connection = self._require_connection()
            worker = asyncio.create_task(
                asyncio.to_thread(operation, connection),
            )
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError as cancellation:
                # ``to_thread`` cannot stop work already running. Keep the
                # connection lock until that work ends so shutdown cannot
                # close the connection underneath the worker thread.
                try:
                    await worker
                except Exception:
                    pass
                raise cancellation

    async def _transaction(
        self,
        operation: Callable[[sqlite3.Connection], _ResultT],
    ) -> _ResultT:
        """Run ``operation`` inside an immediate write transaction."""

        def _execute(connection: sqlite3.Connection) -> _ResultT:
            connection.execute("BEGIN IMMEDIATE")
            try:
                result = operation(connection)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

        return await self._run(_execute)

    @staticmethod
    def _record_from_row(
        model: type[_ResultT],
        row: sqlite3.Row | None,
    ) -> _ResultT | None:
        """Validate a Pydantic record from a row's JSON payload."""
        if row is None:
            return None
        return model.model_validate_json(row["payload"])  # type: ignore[attr-defined]

    @staticmethod
    def _document_values(
        record: KnowledgeDocumentRecord,
    ) -> tuple[str | None, str, str | None, str, str]:
        """Return indexed document columns plus its canonical payload."""
        deadline = record.data.lease_expires_at
        return (
            record.processing_node,
            record.data.status,
            deadline.isoformat() if deadline is not None else None,
            record.created_at.isoformat(),
            record.model_dump_json(),
        )

    async def _generate_credential_name(
        self,
        user_id: str,
        credential_data: CredentialBase,
    ) -> str:
        """Generate ``OpenAI``, ``OpenAI (2)``, ... display names."""
        credential_type = getattr(credential_data, "type", "")
        base_name = (
            credential_type.removesuffix("_credential")
            .replace("_", " ")
            .title()
        )
        if not base_name:
            base_name = "Credential"

        existing = await self.list_credentials(user_id)
        same_type_names = [
            item.data.get("name", "")
            for item in existing
            if item.data.get("type") == credential_type
            and item.id != credential_data.id
        ]
        if base_name not in same_type_names:
            return base_name

        index = 2
        while f"{base_name} ({index})" in same_type_names:
            index += 1
        return f"{base_name} ({index})"

    async def upsert_credential(
        self,
        user_id: str,
        credential_data: CredentialBase,
    ) -> str:
        """Create or update a credential while preserving its creation time."""
        if not credential_data.name:
            credential_data.name = await self._generate_credential_name(
                user_id,
                credential_data,
            )

        existing = (
            await self.get_credential(user_id, credential_data.id)
            if credential_data.id
            else None
        )
        if existing is not None:
            record = existing
            record.data = _dump_with_secrets(credential_data)
            record.updated_at = datetime.now()
        else:
            identifier = (
                {"id": credential_data.id} if credential_data.id else {}
            )
            record = CredentialRecord(
                user_id=user_id,
                data=_dump_with_secrets(credential_data),
                **identifier,
            )

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO credentials (user_id, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT (user_id, id)
                DO UPDATE SET payload=excluded.payload
                """,
                (user_id, record.id, record.model_dump_json()),
            )

        await self._transaction(_write)
        return record.id

    async def list_credentials(self, user_id: str) -> list[CredentialRecord]:
        """List credentials owned by ``user_id``."""

        def _read(connection: sqlite3.Connection) -> list[CredentialRecord]:
            rows = connection.execute(
                "SELECT payload FROM credentials "
                "WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [
                CredentialRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def get_credential(
        self,
        user_id: str,
        credential_id: str,
    ) -> CredentialRecord | None:
        """Fetch one credential."""

        def _read(connection: sqlite3.Connection) -> CredentialRecord | None:
            row = connection.execute(
                "SELECT payload FROM credentials WHERE user_id=? AND id=?",
                (user_id, credential_id),
            ).fetchone()
            return self._record_from_row(CredentialRecord, row)

        return await self._run(_read)

    async def delete_credential(
        self,
        user_id: str,
        credential_id: str,
    ) -> bool:
        """Delete one credential."""

        def _delete(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "DELETE FROM credentials WHERE user_id=? AND id=?",
                (user_id, credential_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def upsert_agent(
        self,
        user_id: str,
        agent_record: AgentRecord,
    ) -> str:
        """Create or overwrite an agent record."""

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO agents (user_id, id, source, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, id)
                DO UPDATE SET
                    source=excluded.source,
                    payload=excluded.payload
                """,
                (
                    user_id,
                    agent_record.id,
                    agent_record.source,
                    agent_record.model_dump_json(),
                ),
            )

        await self._transaction(_write)
        return agent_record.id

    async def list_agents(self, user_id: str) -> list[AgentRecord]:
        """List user-created agents, excluding team-spawned workers."""

        def _read(connection: sqlite3.Connection) -> list[AgentRecord]:
            rows = connection.execute(
                "SELECT payload FROM agents "
                "WHERE user_id=? AND source='user' ORDER BY id",
                (user_id,),
            ).fetchall()
            return [
                AgentRecord.model_validate_json(row["payload"]) for row in rows
            ]

        return await self._run(_read)

    async def get_agent(
        self,
        user_id: str,
        agent_id: str,
    ) -> AgentRecord | None:
        """Fetch one agent, including a team-spawned worker."""

        def _read(connection: sqlite3.Connection) -> AgentRecord | None:
            row = connection.execute(
                "SELECT payload FROM agents WHERE user_id=? AND id=?",
                (user_id, agent_id),
            ).fetchone()
            return self._record_from_row(AgentRecord, row)

        return await self._run(_read)

    async def delete_agent(self, user_id: str, agent_id: str) -> bool:
        """Delete an agent and cascade its dependent application records."""
        sessions = await self.list_sessions(user_id, agent_id)
        for session in sessions:
            await self.delete_session(user_id, agent_id, session.id)

        schedules = await self.list_schedules(user_id)
        for schedule in schedules:
            if schedule.agent_id == agent_id:
                await self.delete_schedule(user_id, schedule.id)

        teams = await self.list_teams(user_id)
        for team in teams:
            dirty = False
            legacy_member_ids = team.data.model_dump().get(
                "member_ids",
                [],
            )
            if agent_id in legacy_member_ids:
                filtered_legacy_ids = [
                    member_id
                    for member_id in legacy_member_ids
                    if member_id != agent_id
                ]
                team.data = team.data.model_copy(
                    update={"member_ids": filtered_legacy_ids},
                )
                dirty = True
            members = [
                member
                for member in team.data.members
                if member.agent_id != agent_id
            ]
            if len(members) != len(team.data.members):
                team.data.members = members
                dirty = True
            if dirty:
                await self.upsert_team(user_id, team)

        def _delete(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "DELETE FROM agents WHERE user_id=? AND id=?",
                (user_id, agent_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def upsert_session(
        self,
        user_id: str,
        agent_id: str,
        config: SessionConfig,
        state: AgentState | None = None,
        session_id: str | None = None,
        source: SessionSource = SessionSource.USER,
        source_schedule_id: str | None = None,
    ) -> SessionRecord:
        """Create a session or update an existing session's config/state."""
        existing = (
            await self.get_session(user_id, agent_id, session_id)
            if session_id
            else None
        )
        if existing is not None:
            record = existing
            record.config = config
            if state is not None:
                record.state = state
            record.updated_at = datetime.now()
        else:
            identifier = {"id": session_id} if session_id else {}
            record = SessionRecord(
                user_id=user_id,
                agent_id=agent_id,
                config=config,
                source=source,
                source_schedule_id=source_schedule_id,
                state=state if state is not None else AgentState(),
                **identifier,
            )

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO sessions (
                    user_id,
                    id,
                    agent_id,
                    source_schedule_id,
                    team_id,
                    created_at,
                    payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, id)
                DO UPDATE SET
                    agent_id=excluded.agent_id,
                    source_schedule_id=excluded.source_schedule_id,
                    team_id=excluded.team_id,
                    created_at=excluded.created_at,
                    payload=excluded.payload
                """,
                (
                    user_id,
                    record.id,
                    record.agent_id,
                    record.source_schedule_id,
                    record.team_id,
                    record.created_at.isoformat(),
                    record.model_dump_json(),
                ),
            )

        await self._transaction(_write)
        return record

    async def set_session_team_id(
        self,
        user_id: str,
        session_id: str,
        team_id: str | None,
    ) -> None:
        """Set or clear a session's team relationship."""

        def _update(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE user_id=? AND id=?",
                (user_id, session_id),
            ).fetchone()
            if row is None:
                return
            record = SessionRecord.model_validate_json(row["payload"])
            if record.team_id == team_id:
                return
            record.team_id = team_id
            record.updated_at = datetime.now()
            connection.execute(
                """
                UPDATE sessions
                SET team_id=?, payload=?
                WHERE user_id=? AND id=?
                """,
                (team_id, record.model_dump_json(), user_id, session_id),
            )

        await self._transaction(_update)

    async def update_session_state(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        state: AgentState,
    ) -> None:
        """Update only a session's mutable runtime state."""
        del agent_id

        def _update(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE user_id=? AND id=?",
                (user_id, session_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Session {session_id!r} not found.")
            record = SessionRecord.model_validate_json(row["payload"])
            record.state = state
            record.updated_at = datetime.now()
            connection.execute(
                "UPDATE sessions SET payload=? WHERE user_id=? AND id=?",
                (record.model_dump_json(), user_id, session_id),
            )

        await self._transaction(_update)

    async def list_sessions(
        self,
        user_id: str,
        agent_id: str,
    ) -> list[SessionRecord]:
        """List an agent's sessions, newest first."""

        def _read(connection: sqlite3.Connection) -> list[SessionRecord]:
            rows = connection.execute(
                """
                SELECT payload
                FROM sessions
                WHERE user_id=? AND agent_id=?
                ORDER BY created_at DESC
                """,
                (user_id, agent_id),
            ).fetchall()
            return [
                SessionRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def get_session(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> SessionRecord | None:
        """Fetch one session.

        ``agent_id`` remains part of the public interface for compatibility;
        like ``RedisStorage``, lookup ownership is scoped by user and session
        id because the session record already contains its authoritative
        agent id.
        """
        del agent_id

        def _read(connection: sqlite3.Connection) -> SessionRecord | None:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE user_id=? AND id=?",
                (user_id, session_id),
            ).fetchone()
            return self._record_from_row(SessionRecord, row)

        return await self._run(_read)

    async def delete_session(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> bool:
        """Delete a session, messages, and a team led by this session."""
        record = await self.get_session(user_id, agent_id, session_id)
        if record is None:
            return False

        if record.team_id:
            team = await self.get_team(user_id, record.team_id)
            if team is not None and team.session_id == session_id:
                await self.delete_team(user_id, record.team_id)

        def _delete(connection: sqlite3.Connection) -> bool:
            connection.execute(
                "DELETE FROM messages WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            )
            cursor = connection.execute(
                "DELETE FROM sessions WHERE user_id=? AND id=?",
                (user_id, session_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def list_sessions_by_schedule(
        self,
        user_id: str,
        schedule_id: str,
    ) -> list[SessionRecord]:
        """List schedule-created sessions, newest first."""

        def _read(connection: sqlite3.Connection) -> list[SessionRecord]:
            rows = connection.execute(
                """
                SELECT payload
                FROM sessions
                WHERE user_id=? AND source_schedule_id=?
                ORDER BY created_at DESC
                """,
                (user_id, schedule_id),
            ).fetchall()
            return [
                SessionRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def upsert_schedule(
        self,
        user_id: str,
        record: ScheduleRecord,
    ) -> str:
        """Create or overwrite a schedule."""

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO schedules (user_id, id, agent_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, id)
                DO UPDATE SET
                    agent_id=excluded.agent_id,
                    payload=excluded.payload
                """,
                (
                    user_id,
                    record.id,
                    record.agent_id,
                    record.model_dump_json(),
                ),
            )

        await self._transaction(_write)
        return record.id

    async def get_schedule(
        self,
        user_id: str,
        schedule_id: str,
    ) -> ScheduleRecord | None:
        """Fetch one schedule."""

        def _read(connection: sqlite3.Connection) -> ScheduleRecord | None:
            row = connection.execute(
                "SELECT payload FROM schedules WHERE user_id=? AND id=?",
                (user_id, schedule_id),
            ).fetchone()
            return self._record_from_row(ScheduleRecord, row)

        return await self._run(_read)

    async def list_schedules(self, user_id: str) -> list[ScheduleRecord]:
        """List schedules owned by a user."""

        def _read(connection: sqlite3.Connection) -> list[ScheduleRecord]:
            rows = connection.execute(
                "SELECT payload FROM schedules WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [
                ScheduleRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def delete_schedule(
        self,
        user_id: str,
        schedule_id: str,
    ) -> bool:
        """Delete a schedule and all sessions it created."""
        record = await self.get_schedule(user_id, schedule_id)
        if record is None:
            return False

        sessions = await self.list_sessions_by_schedule(user_id, schedule_id)
        for session in sessions:
            await self.delete_session(user_id, record.agent_id, session.id)

        def _delete(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "DELETE FROM schedules WHERE user_id=? AND id=?",
                (user_id, schedule_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def list_all_schedules(self) -> list[ScheduleRecord]:
        """List every persisted schedule across users."""

        def _read(connection: sqlite3.Connection) -> list[ScheduleRecord]:
            rows = connection.execute(
                "SELECT payload FROM schedules ORDER BY user_id, id",
            ).fetchall()
            return [
                ScheduleRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def upsert_message(
        self,
        user_id: str,
        session_id: str,
        msg: Msg,
    ) -> None:
        """Append a message or replace the final message with the same id."""

        def _write(connection: sqlite3.Connection) -> None:
            last = connection.execute(
                """
                SELECT sequence, message_id
                FROM messages
                WHERE user_id=? AND session_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
            if last is not None and last["message_id"] == msg.id:
                connection.execute(
                    "UPDATE messages SET payload=? WHERE sequence=?",
                    (msg.model_dump_json(), last["sequence"]),
                )
                return
            connection.execute(
                """
                INSERT INTO messages (
                    user_id,
                    session_id,
                    message_id,
                    payload
                )
                VALUES (?, ?, ?, ?)
                """,
                (user_id, session_id, msg.id, msg.model_dump_json()),
            )

        await self._transaction(_write)

    async def get_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> Msg | None:
        """Fetch the newest occurrence of a message id."""

        def _read(connection: sqlite3.Connection) -> Msg | None:
            row = connection.execute(
                """
                SELECT payload
                FROM messages
                WHERE user_id=? AND session_id=? AND message_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (user_id, session_id, message_id),
            ).fetchone()
            return self._record_from_row(Msg, row)

        return await self._run(_read)

    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        **kwargs: Any,
    ) -> tuple[list[Msg], bool]:
        """Return the newest message page in chronological order."""
        if "offset" in kwargs:
            warnings.warn(
                "The 'offset' parameter is deprecated and will be "
                "removed in a future version. Use 'before' for "
                "cursor-based pagination instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        def _read(
            connection: sqlite3.Connection,
        ) -> tuple[list[Msg], bool]:
            if limit <= 0:
                return [], False

            if before is None:
                cursor_sequence: int | None = None
            else:
                cursor = connection.execute(
                    """
                    SELECT sequence
                    FROM messages
                    WHERE
                        user_id=?
                        AND session_id=?
                        AND message_id=?
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (user_id, session_id, before),
                ).fetchone()
                if cursor is None:
                    return [], False
                cursor_sequence = int(cursor["sequence"])

            if cursor_sequence is None:
                rows = connection.execute(
                    """
                    SELECT sequence, payload
                    FROM messages
                    WHERE user_id=? AND session_id=?
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (user_id, session_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT sequence, payload
                    FROM messages
                    WHERE
                        user_id=?
                        AND session_id=?
                        AND sequence<?
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (user_id, session_id, cursor_sequence, limit),
                ).fetchall()

            if not rows:
                return [], False

            oldest_sequence = min(int(row["sequence"]) for row in rows)
            has_more = (
                connection.execute(
                    """
                    SELECT 1
                    FROM messages
                    WHERE
                        user_id=?
                        AND session_id=?
                        AND sequence<?
                    LIMIT 1
                    """,
                    (user_id, session_id, oldest_sequence),
                ).fetchone()
                is not None
            )
            chronological = [
                Msg.model_validate_json(row["payload"])
                for row in reversed(rows)
            ]
            return chronological, has_more

        return await self._run(_read)

    async def upsert_team(
        self,
        user_id: str,
        record: TeamRecord,
    ) -> TeamRecord:
        """Create or overwrite a team record."""
        record.updated_at = datetime.now()

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO teams (user_id, id, session_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, id)
                DO UPDATE SET
                    session_id=excluded.session_id,
                    payload=excluded.payload
                """,
                (
                    user_id,
                    record.id,
                    record.session_id,
                    record.model_dump_json(),
                ),
            )

        await self._transaction(_write)
        return record

    async def get_team(
        self,
        user_id: str,
        team_id: str,
    ) -> TeamRecord | None:
        """Fetch one team."""

        def _read(connection: sqlite3.Connection) -> TeamRecord | None:
            row = connection.execute(
                "SELECT payload FROM teams WHERE user_id=? AND id=?",
                (user_id, team_id),
            ).fetchone()
            return self._record_from_row(TeamRecord, row)

        return await self._run(_read)

    async def list_teams(self, user_id: str) -> list[TeamRecord]:
        """List teams owned by a user."""

        def _read(connection: sqlite3.Connection) -> list[TeamRecord]:
            rows = connection.execute(
                "SELECT payload FROM teams WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [
                TeamRecord.model_validate_json(row["payload"]) for row in rows
            ]

        return await self._run(_read)

    async def delete_team(self, user_id: str, team_id: str) -> bool:
        """Delete a team and clean created/invited members by role."""
        from ._utils import _ensure_team_members

        team = await self.get_team(user_id, team_id)
        if team is None:
            return False

        members = await _ensure_team_members(self, user_id, team)
        for member in members:
            if member.role == "created":
                await self.delete_agent(member.owner_id, member.agent_id)
            else:
                await self.delete_session(
                    member.owner_id,
                    member.agent_id,
                    member.session_id,
                )

        await self.set_session_team_id(user_id, team.session_id, None)

        def _delete(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "DELETE FROM teams WHERE user_id=? AND id=?",
                (user_id, team_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def upsert_knowledge_base(
        self,
        user_id: str,
        record: KnowledgeBaseRecord,
    ) -> KnowledgeBaseRecord:
        """Create or update knowledge-base metadata."""
        if record.user_id != user_id:
            raise ValueError(
                "record.user_id does not match the given user_id.",
            )

        existing = await self.get_knowledge_base(user_id, record.id)
        if existing is not None:
            record.created_at = existing.created_at
        record.updated_at = datetime.now()

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO knowledge_bases (user_id, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT (user_id, id)
                DO UPDATE SET payload=excluded.payload
                """,
                (user_id, record.id, record.model_dump_json()),
            )

        await self._transaction(_write)
        return record

    async def get_knowledge_base(
        self,
        user_id: str,
        knowledge_base_id: str,
    ) -> KnowledgeBaseRecord | None:
        """Fetch one knowledge-base record."""

        def _read(
            connection: sqlite3.Connection,
        ) -> KnowledgeBaseRecord | None:
            row = connection.execute(
                """
                SELECT payload
                FROM knowledge_bases
                WHERE user_id=? AND id=?
                """,
                (user_id, knowledge_base_id),
            ).fetchone()
            return self._record_from_row(KnowledgeBaseRecord, row)

        return await self._run(_read)

    async def list_knowledge_bases(
        self,
        user_id: str,
    ) -> list[KnowledgeBaseRecord]:
        """List knowledge bases owned by a user."""

        def _read(
            connection: sqlite3.Connection,
        ) -> list[KnowledgeBaseRecord]:
            rows = connection.execute(
                """
                SELECT payload
                FROM knowledge_bases
                WHERE user_id=?
                ORDER BY id
                """,
                (user_id,),
            ).fetchall()
            return [
                KnowledgeBaseRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def delete_knowledge_base(
        self,
        user_id: str,
        knowledge_base_id: str,
    ) -> bool:
        """Delete knowledge-base metadata and all document metadata."""

        def _delete(connection: sqlite3.Connection) -> bool:
            connection.execute(
                """
                DELETE FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=?
                """,
                (user_id, knowledge_base_id),
            )
            cursor = connection.execute(
                "DELETE FROM knowledge_bases WHERE user_id=? AND id=?",
                (user_id, knowledge_base_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def upsert_knowledge_document(
        self,
        user_id: str,
        record: KnowledgeDocumentRecord,
    ) -> KnowledgeDocumentRecord:
        """Create or update knowledge-document metadata."""
        if record.user_id != user_id:
            raise ValueError(
                "record.user_id does not match the given user_id.",
            )

        existing = await self.get_knowledge_document(
            user_id,
            record.knowledge_base_id,
            record.id,
        )
        if existing is not None:
            record.created_at = existing.created_at
        record.updated_at = datetime.now()
        (
            processing_node,
            status,
            lease_expires_at,
            created_at,
            payload,
        ) = self._document_values(record)

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO knowledge_documents (
                    user_id,
                    knowledge_base_id,
                    id,
                    processing_node,
                    status,
                    lease_expires_at,
                    created_at,
                    payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, knowledge_base_id, id)
                DO UPDATE SET
                    processing_node=excluded.processing_node,
                    status=excluded.status,
                    lease_expires_at=excluded.lease_expires_at,
                    created_at=excluded.created_at,
                    payload=excluded.payload
                """,
                (
                    user_id,
                    record.knowledge_base_id,
                    record.id,
                    processing_node,
                    status,
                    lease_expires_at,
                    created_at,
                    payload,
                ),
            )

        await self._transaction(_write)
        return record

    async def get_knowledge_document(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> KnowledgeDocumentRecord | None:
        """Fetch one knowledge-document record."""

        def _read(
            connection: sqlite3.Connection,
        ) -> KnowledgeDocumentRecord | None:
            row = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (user_id, knowledge_base_id, document_id),
            ).fetchone()
            return self._record_from_row(KnowledgeDocumentRecord, row)

        return await self._run(_read)

    async def list_knowledge_documents(
        self,
        user_id: str,
        knowledge_base_id: str,
    ) -> list[KnowledgeDocumentRecord]:
        """List all document metadata for one knowledge base."""

        def _read(
            connection: sqlite3.Connection,
        ) -> list[KnowledgeDocumentRecord]:
            rows = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=?
                ORDER BY created_at, id
                """,
                (user_id, knowledge_base_id),
            ).fetchall()
            return [
                KnowledgeDocumentRecord.model_validate_json(row["payload"])
                for row in rows
            ]

        return await self._run(_read)

    async def delete_knowledge_document(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> bool:
        """Delete one knowledge-document record."""

        def _delete(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                """
                DELETE FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (user_id, knowledge_base_id, document_id),
            )
            return cursor.rowcount > 0

        return await self._transaction(_delete)

    async def update_knowledge_document_status(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
        status: KnowledgeDocumentStatus,
        error: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        """Update a document's lifecycle fields atomically."""

        def _update(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (user_id, knowledge_base_id, document_id),
            ).fetchone()
            if row is None:
                return

            record = KnowledgeDocumentRecord.model_validate_json(
                row["payload"],
            )
            record.data.status = status
            if error is not None:
                record.data.error = error
            if chunk_count is not None:
                record.data.chunk_count = chunk_count
            record.updated_at = datetime.now()
            (
                processing_node,
                current_status,
                lease_expires_at,
                created_at,
                payload,
            ) = self._document_values(record)
            connection.execute(
                """
                UPDATE knowledge_documents
                SET
                    processing_node=?,
                    status=?,
                    lease_expires_at=?,
                    created_at=?,
                    payload=?
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (
                    processing_node,
                    current_status,
                    lease_expires_at,
                    created_at,
                    payload,
                    user_id,
                    knowledge_base_id,
                    document_id,
                ),
            )

        await self._transaction(_update)

    async def acquire_knowledge_document_lease(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
        processing_node: str,
        lease_ttl: timedelta,
        now: datetime | None = None,
    ) -> bool:
        """Acquire an absent or expired document-processing lease."""
        reference_time = now or datetime.now()

        def _acquire(connection: sqlite3.Connection) -> bool:
            row = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (user_id, knowledge_base_id, document_id),
            ).fetchone()
            if row is None:
                return False

            record = KnowledgeDocumentRecord.model_validate_json(
                row["payload"],
            )
            deadline = record.data.lease_expires_at
            if (
                record.processing_node is not None
                and deadline is not None
                and deadline > reference_time
            ):
                return False

            record.processing_node = processing_node
            record.data.lease_expires_at = reference_time + lease_ttl
            record.updated_at = reference_time
            (
                holder,
                status,
                lease_expires_at,
                created_at,
                payload,
            ) = self._document_values(record)
            connection.execute(
                """
                UPDATE knowledge_documents
                SET
                    processing_node=?,
                    status=?,
                    lease_expires_at=?,
                    created_at=?,
                    payload=?
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (
                    holder,
                    status,
                    lease_expires_at,
                    created_at,
                    payload,
                    user_id,
                    knowledge_base_id,
                    document_id,
                ),
            )
            return True

        return await self._transaction(_acquire)

    async def renew_knowledge_document_lease(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
        processing_node: str,
        lease_ttl: timedelta,
        now: datetime | None = None,
    ) -> bool:
        """Extend a lease only when it still belongs to the caller."""
        reference_time = now or datetime.now()

        def _renew(connection: sqlite3.Connection) -> bool:
            row = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (user_id, knowledge_base_id, document_id),
            ).fetchone()
            if row is None:
                return False

            record = KnowledgeDocumentRecord.model_validate_json(
                row["payload"],
            )
            if record.processing_node != processing_node:
                return False

            record.data.lease_expires_at = reference_time + lease_ttl
            record.updated_at = reference_time
            (
                holder,
                status,
                lease_expires_at,
                created_at,
                payload,
            ) = self._document_values(record)
            connection.execute(
                """
                UPDATE knowledge_documents
                SET
                    processing_node=?,
                    status=?,
                    lease_expires_at=?,
                    created_at=?,
                    payload=?
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (
                    holder,
                    status,
                    lease_expires_at,
                    created_at,
                    payload,
                    user_id,
                    knowledge_base_id,
                    document_id,
                ),
            )
            return True

        return await self._transaction(_renew)

    async def release_knowledge_document_lease(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
        processing_node: str,
    ) -> None:
        """Release a lease only when it still belongs to the caller."""

        def _release(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (user_id, knowledge_base_id, document_id),
            ).fetchone()
            if row is None:
                return

            record = KnowledgeDocumentRecord.model_validate_json(
                row["payload"],
            )
            if record.processing_node != processing_node:
                return

            record.processing_node = None
            record.data.lease_expires_at = None
            record.updated_at = datetime.now()
            (
                holder,
                status,
                lease_expires_at,
                created_at,
                payload,
            ) = self._document_values(record)
            connection.execute(
                """
                UPDATE knowledge_documents
                SET
                    processing_node=?,
                    status=?,
                    lease_expires_at=?,
                    created_at=?,
                    payload=?
                WHERE user_id=? AND knowledge_base_id=? AND id=?
                """,
                (
                    holder,
                    status,
                    lease_expires_at,
                    created_at,
                    payload,
                    user_id,
                    knowledge_base_id,
                    document_id,
                ),
            )

        await self._transaction(_release)

    async def list_knowledge_documents_with_expired_lease(
        self,
        now: datetime | None = None,
    ) -> list[KnowledgeDocumentRecord]:
        """List non-terminal documents whose processing lease expired."""
        reference_time = now or datetime.now()

        def _read(
            connection: sqlite3.Connection,
        ) -> list[KnowledgeDocumentRecord]:
            rows = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE
                    status NOT IN ('ready', 'error')
                    AND processing_node IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                """,
            ).fetchall()
            records = [
                KnowledgeDocumentRecord.model_validate_json(row["payload"])
                for row in rows
            ]
            return [
                record
                for record in records
                if record.data.lease_expires_at is not None
                and record.data.lease_expires_at < reference_time
            ]

        return await self._run(_read)

    async def list_knowledge_documents_pending_since(
        self,
        threshold: datetime,
    ) -> list[KnowledgeDocumentRecord]:
        """List pending documents created before ``threshold``."""

        def _read(
            connection: sqlite3.Connection,
        ) -> list[KnowledgeDocumentRecord]:
            rows = connection.execute(
                """
                SELECT payload
                FROM knowledge_documents
                WHERE status='pending'
                """,
            ).fetchall()
            records = [
                KnowledgeDocumentRecord.model_validate_json(row["payload"])
                for row in rows
            ]
            return [
                record
                for record in records
                if record.created_at < threshold
            ]

        return await self._run(_read)
