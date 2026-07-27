"""Regression tests for the durable SQLite application storage."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest import IsolatedAsyncioTestCase

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app.storage import (
    AgentData,
    AgentRecord,
    ChatModelConfig,
    EmbeddingModelConfig,
    KnowledgeBaseRecord,
    KnowledgeDocumentData,
    KnowledgeDocumentRecord,
    ScheduleData,
    ScheduleRecord,
    SessionConfig,
    SQLiteStorage,
    TeamData,
    TeamMember,
    TeamRecord,
)
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg


USER_ID = "sqlite-test-user"
AGENT_ID = "sqlite-test-agent"


def _agent(
    agent_id: str = AGENT_ID,
    *,
    source: Literal["user", "team"] = "user",
) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        user_id=USER_ID,
        source=source,
        data=AgentData(
            name="SQLite 测试智能体",
            context_config=ContextConfig(),
            react_config=ReActConfig(),
        ),
    )


def _session_config(name: str = "SQLite 会话") -> SessionConfig:
    return SessionConfig(
        workspace_id="sqlite-workspace",
        name=name,
        chat_model_config=ChatModelConfig(
            type="openai_credential",
            credential_id="credential",
            model="test-model",
            parameters={},
        ),
    )


class SQLiteStorageTest(IsolatedAsyncioTestCase):
    """Exercise records, pagination, leases, cascades, and reopen durability."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "agentscope.db"
        self.storage = SQLiteStorage(self.database_path)
        await self.storage.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.storage.aclose()
        self.temp_dir.cleanup()

    async def test_records_survive_storage_reopen(self) -> None:
        credential = OpenAICredential(api_key="durable-secret")
        credential_id = await self.storage.upsert_credential(
            USER_ID,
            credential,
        )
        await self.storage.upsert_agent(USER_ID, _agent())
        session = await self.storage.upsert_session(
            USER_ID,
            AGENT_ID,
            _session_config(),
            session_id="durable-session",
        )
        message = UserMsg(
            name="user",
            content="重启后仍应存在",
            id="durable-message",
        )
        await self.storage.upsert_message(USER_ID, session.id, message)

        schedule = ScheduleRecord(
            id="durable-schedule",
            user_id=USER_ID,
            agent_id=AGENT_ID,
            data=ScheduleData(
                name="持久化计划",
                cron_expression="0 9 * * *",
                chat_model_config=ChatModelConfig(
                    type="openai_credential",
                    credential_id=credential_id,
                    model="test-model",
                    parameters={},
                ),
            ),
        )
        await self.storage.upsert_schedule(USER_ID, schedule)

        team = TeamRecord(
            id="durable-team",
            user_id=USER_ID,
            session_id=session.id,
            data=TeamData(name="持久化团队"),
        )
        await self.storage.upsert_team(USER_ID, team)
        await self.storage.set_session_team_id(
            USER_ID,
            session.id,
            team.id,
        )

        knowledge_base = KnowledgeBaseRecord(
            id="durable-kb",
            user_id=USER_ID,
            name="持久化知识库",
            embedding_model_config=EmbeddingModelConfig(
                type="openai_credential",
                credential_id=credential_id,
                model="text-embedding-test",
                dimensions=8,
            ),
            collection_name="kb_durable",
        )
        await self.storage.upsert_knowledge_base(USER_ID, knowledge_base)
        document = KnowledgeDocumentRecord(
            id="durable-document",
            user_id=USER_ID,
            knowledge_base_id=knowledge_base.id,
            data=KnowledgeDocumentData(
                filename="持久化.txt",
                size=12,
                content_type="text/plain",
                blob_uri="local://durable.txt",
            ),
        )
        await self.storage.upsert_knowledge_document(USER_ID, document)

        await self.storage.aclose()
        self.storage = SQLiteStorage(self.database_path)
        await self.storage.__aenter__()

        stored_credential = await self.storage.get_credential(
            USER_ID,
            credential_id,
        )
        self.assertIsNotNone(stored_credential)
        assert stored_credential is not None
        self.assertEqual(
            stored_credential.data["api_key"],
            "durable-secret",
        )
        self.assertIsNotNone(
            await self.storage.get_agent(USER_ID, AGENT_ID),
        )
        stored_session = await self.storage.get_session(
            USER_ID,
            AGENT_ID,
            session.id,
        )
        self.assertIsNotNone(stored_session)
        assert stored_session is not None
        self.assertEqual(stored_session.team_id, team.id)
        stored_message = await self.storage.get_message(
            USER_ID,
            session.id,
            message.id,
        )
        self.assertIsNotNone(stored_message)
        assert stored_message is not None
        self.assertEqual(
            stored_message.get_text_content(),
            "重启后仍应存在",
        )
        self.assertIsNotNone(
            await self.storage.get_schedule(USER_ID, schedule.id),
        )
        self.assertIsNotNone(await self.storage.get_team(USER_ID, team.id))
        self.assertIsNotNone(
            await self.storage.get_knowledge_base(
                USER_ID,
                knowledge_base.id,
            ),
        )
        self.assertIsNotNone(
            await self.storage.get_knowledge_document(
                USER_ID,
                knowledge_base.id,
                document.id,
            ),
        )

    async def test_empty_legacy_schema_is_rebuilt_safely(self) -> None:
        await self.storage.aclose()
        self.database_path.unlink()
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """
                CREATE TABLE messages (
                    session_id TEXT NOT NULL,
                    msg_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, msg_id)
                )
                """,
            )
            connection.commit()
        finally:
            connection.close()

        self.storage = SQLiteStorage(self.database_path)
        await self.storage.__aenter__()
        columns = await self.storage._run(
            lambda database: {
                row["name"]
                for row in database.execute(
                    'PRAGMA table_info("messages")',
                ).fetchall()
            },
        )
        self.assertIn("sequence", columns)
        self.assertIn("user_id", columns)
        self.assertIn("message_id", columns)

    async def test_populated_legacy_schema_is_never_overwritten(self) -> None:
        await self.storage.aclose()
        self.database_path.unlink()
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """
                CREATE TABLE messages (
                    session_id TEXT NOT NULL,
                    msg_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, msg_id)
                )
                """,
            )
            connection.execute(
                """
                INSERT INTO messages (
                    session_id,
                    msg_id,
                    created_at,
                    payload
                )
                VALUES ('session', 'message', '2026-07-24', '{}')
                """,
            )
            connection.commit()
        finally:
            connection.close()

        self.storage = SQLiteStorage(self.database_path)
        with self.assertRaisesRegex(
            RuntimeError,
            "已停止启动以避免覆盖数据",
        ):
            await self.storage.__aenter__()

        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM messages",
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 1)

    async def test_message_upsert_and_cursor_pagination(self) -> None:
        for index in range(5):
            await self.storage.upsert_message(
                USER_ID,
                "message-session",
                UserMsg(
                    name="user",
                    content=f"消息 {index}",
                    id=f"message-{index}",
                ),
            )

        await self.storage.upsert_message(
            USER_ID,
            "message-session",
            UserMsg(
                name="user",
                content="更新后的消息 4",
                id="message-4",
            ),
        )

        latest, has_more = await self.storage.list_messages(
            USER_ID,
            "message-session",
            limit=2,
        )
        self.assertEqual(
            [message.id for message in latest],
            ["message-3", "message-4"],
        )
        self.assertEqual(
            latest[-1].get_text_content(),
            "更新后的消息 4",
        )
        self.assertTrue(has_more)

        older, has_more = await self.storage.list_messages(
            USER_ID,
            "message-session",
            limit=2,
            before="message-3",
        )
        self.assertEqual(
            [message.id for message in older],
            ["message-1", "message-2"],
        )
        self.assertTrue(has_more)

        oldest, has_more = await self.storage.list_messages(
            USER_ID,
            "message-session",
            limit=2,
            before="message-1",
        )
        self.assertEqual(
            [message.id for message in oldest],
            ["message-0"],
        )
        self.assertFalse(has_more)

    async def test_document_lease_is_atomic_across_connections(self) -> None:
        document = KnowledgeDocumentRecord(
            id="lease-document",
            user_id=USER_ID,
            knowledge_base_id="lease-kb",
            data=KnowledgeDocumentData(
                filename="lease.txt",
                size=1,
                content_type="text/plain",
                blob_uri="local://lease.txt",
            ),
        )
        await self.storage.upsert_knowledge_document(USER_ID, document)

        second_storage = SQLiteStorage(self.database_path)
        await second_storage.__aenter__()
        try:
            now = datetime(2026, 7, 24, 10, 0, 0)
            acquired = await asyncio.gather(
                self.storage.acquire_knowledge_document_lease(
                    USER_ID,
                    "lease-kb",
                    document.id,
                    "worker-a",
                    timedelta(seconds=30),
                    now,
                ),
                second_storage.acquire_knowledge_document_lease(
                    USER_ID,
                    "lease-kb",
                    document.id,
                    "worker-b",
                    timedelta(seconds=30),
                    now,
                ),
            )
            self.assertEqual(sum(acquired), 1)

            stored = await self.storage.get_knowledge_document(
                USER_ID,
                "lease-kb",
                document.id,
            )
            self.assertIsNotNone(stored)
            assert stored is not None
            holder = stored.processing_node
            self.assertIn(holder, {"worker-a", "worker-b"})
            assert holder is not None
            other = "worker-b" if holder == "worker-a" else "worker-a"
            self.assertFalse(
                await self.storage.renew_knowledge_document_lease(
                    USER_ID,
                    "lease-kb",
                    document.id,
                    other,
                    timedelta(seconds=30),
                    now,
                ),
            )
            self.assertTrue(
                await self.storage.renew_knowledge_document_lease(
                    USER_ID,
                    "lease-kb",
                    document.id,
                    holder,
                    timedelta(seconds=30),
                    now,
                ),
            )

            expired = (
                await self.storage.list_knowledge_documents_with_expired_lease(
                    now + timedelta(seconds=31),
                )
            )
            self.assertEqual([item.id for item in expired], [document.id])

            await self.storage.release_knowledge_document_lease(
                USER_ID,
                "lease-kb",
                document.id,
                holder,
            )
            released = await self.storage.get_knowledge_document(
                USER_ID,
                "lease-kb",
                document.id,
            )
            self.assertIsNotNone(released)
            assert released is not None
            self.assertIsNone(released.processing_node)
        finally:
            await second_storage.aclose()

    async def test_delete_agent_cascades_sessions_messages_and_schedules(
        self,
    ) -> None:
        await self.storage.upsert_agent(USER_ID, _agent())
        session = await self.storage.upsert_session(
            USER_ID,
            AGENT_ID,
            _session_config(),
            session_id="cascade-session",
        )
        await self.storage.upsert_message(
            USER_ID,
            session.id,
            UserMsg(name="user", content="待级联删除", id="cascade-message"),
        )
        await self.storage.upsert_schedule(
            USER_ID,
            ScheduleRecord(
                id="cascade-schedule",
                user_id=USER_ID,
                agent_id=AGENT_ID,
                data=ScheduleData(
                    name="待级联删除",
                    cron_expression="0 9 * * *",
                    chat_model_config=ChatModelConfig(
                        type="openai_credential",
                        credential_id="credential",
                        model="test-model",
                        parameters={},
                    ),
                ),
            ),
        )

        self.assertTrue(await self.storage.delete_agent(USER_ID, AGENT_ID))
        self.assertIsNone(
            await self.storage.get_session(USER_ID, AGENT_ID, session.id),
        )
        self.assertIsNone(
            await self.storage.get_message(
                USER_ID,
                session.id,
                "cascade-message",
            ),
        )
        self.assertEqual(await self.storage.list_schedules(USER_ID), [])

    async def test_delete_team_respects_created_and_invited_roles(
        self,
    ) -> None:
        leader_id = "leader"
        created_id = "created-worker"
        invited_id = "invited-worker"
        for agent in (
            _agent(leader_id),
            _agent(created_id, source="team"),
            _agent(invited_id),
        ):
            await self.storage.upsert_agent(USER_ID, agent)

        leader_session = await self.storage.upsert_session(
            USER_ID,
            leader_id,
            _session_config("队长会话"),
            session_id="leader-session",
        )
        created_session = await self.storage.upsert_session(
            USER_ID,
            created_id,
            _session_config("新建成员会话"),
            session_id="created-session",
        )
        invited_regular_session = await self.storage.upsert_session(
            USER_ID,
            invited_id,
            _session_config("受邀者原会话"),
            session_id="invited-regular-session",
        )
        invited_team_session = await self.storage.upsert_session(
            USER_ID,
            invited_id,
            _session_config("受邀者团队会话"),
            session_id="invited-team-session",
        )

        team = TeamRecord(
            id="role-aware-team",
            user_id=USER_ID,
            session_id=leader_session.id,
            data=TeamData(
                name="角色级联测试",
                member_ids=[created_id, invited_id],
                members=[
                    TeamMember(
                        owner_id=USER_ID,
                        agent_id=created_id,
                        session_id=created_session.id,
                        role="created",
                    ),
                    TeamMember(
                        owner_id=USER_ID,
                        agent_id=invited_id,
                        session_id=invited_team_session.id,
                        role="invited",
                    ),
                ],
            ),
        )
        await self.storage.upsert_team(USER_ID, team)
        for session_id in (
            leader_session.id,
            created_session.id,
            invited_team_session.id,
        ):
            await self.storage.set_session_team_id(
                USER_ID,
                session_id,
                team.id,
            )

        self.assertTrue(await self.storage.delete_team(USER_ID, team.id))
        self.assertIsNone(await self.storage.get_team(USER_ID, team.id))
        self.assertIsNone(
            await self.storage.get_agent(USER_ID, created_id),
        )
        self.assertIsNotNone(
            await self.storage.get_agent(USER_ID, invited_id),
        )
        self.assertIsNone(
            await self.storage.get_session(
                USER_ID,
                invited_id,
                invited_team_session.id,
            ),
        )
        self.assertIsNotNone(
            await self.storage.get_session(
                USER_ID,
                invited_id,
                invited_regular_session.id,
            ),
        )
        surviving_leader = await self.storage.get_session(
            USER_ID,
            leader_id,
            leader_session.id,
        )
        self.assertIsNotNone(surviving_leader)
        assert surviving_leader is not None
        self.assertIsNone(surviving_leader.team_id)
