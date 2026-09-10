"""Real message/bus contracts for archives independent of the platform stream."""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from agentscope.app._service._collaboration_archive import (
    ARCHIVE_KEY, archive_member_progress, archive_before_worker_delete,
    patch_message_metadata, save_message_with_collaboration_progress,
)
from agentscope.app._service._session import SessionService
from agentscope.app._service._session_projection import SessionProjection
from agentscope.app._team_lifecycle import settle_team_member
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import TeamData, TeamMember, TeamRecord
from agentscope.message import AssistantMsg, ToolCallBlock, ToolResultBlock


def assignment(message_id="assigned", revision=1, worker="worker", state="success"):
    member = {"team_id": "team", "worker_session_id": worker, "worker_agent_id": worker + "-agent", "work_revision": revision}
    return AssistantMsg(id=message_id, name="leader", metadata={"keep": "preserved"}, content=[
        ToolCallBlock(id="invite-" + worker, name="AgentInvite", input="{}", state="finished"),
        ToolResultBlock(id="invite-" + worker, name="AgentInvite", output="Accepted", state=state, metadata={"collaboration_member": member}),
    ])


def progress(revision=1, worker="worker", status="completed", updated="2026-09-10T14:00:00+00:00"):
    return {"team_id": "team", "team_name": "团队", "worker_session_id": worker,
            "worker_agent_id": worker + "-agent", "worker_agent_name": "专家", "work_revision": revision,
            "work_status": status, "reply_id": "reply-1", "updated_at": updated,
            "activities": [{"kind": "tool", "label": "工具执行完成", "state": "success", "tool_name": "read_rows",
                            "input": "PRIVATE INPUT", "output": "PRIVATE OUTPUT", "presentation": {"label": "读取资料", "source": "declaration", "extra": "PRIVATE EXTRA"}}],
            "thinking": "PRIVATE THINKING"}


class Storage:
    def __init__(self):
        self.messages = {}
        member = TeamMember(owner_id="u", agent_id="worker-agent", session_id="worker", role="invited",
                            work_revision=1, active_revision=1, work_status="running")
        self.team = TeamRecord(id="team", user_id="u", session_id="leader", data=TeamData(name="团队", members=[member]))

    async def get_team(self, _user, team_id):
        return self.team if team_id == "team" else None

    async def upsert_team(self, _user, team):
        self.team = team.model_copy(deep=True)

    async def get_agent(self, _user, _agent):
        return SimpleNamespace(data=SimpleNamespace(name="专家"))

    async def get_session(self, _user, _agent, sid):
        return SimpleNamespace(id=sid, team_id="team")

    async def get_message(self, _user, sid, mid):
        value = self.messages.get((sid, mid))
        return value.model_copy(deep=True) if value else None

    async def upsert_message(self, _user, sid, message):
        await asyncio.sleep(0)
        self.messages[(sid, message.id)] = message.model_copy(deep=True)

    async def update_message_if_exists(self, user, sid, message):
        if (sid, message.id) not in self.messages:
            return False
        await self.upsert_message(user, sid, message)
        return True

    async def list_messages(self, _user, sid, **kwargs):
        return [value.model_copy(deep=True) for (owner, _), value in self.messages.items() if owner == sid], False


class CollaborationArchiveTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage, self.bus = Storage(), InMemoryMessageBus()

    async def test_settlement_archives_without_sse_and_survives_team_cleanup(self):
        await self.storage.upsert_message("u", "leader", assignment())
        projection = SessionProjection(self.bus)
        await projection.upsert("leader", "collaboration_progress", "worker", progress())
        settled = await settle_team_member(self.storage, self.bus, user_id="u", team_id="team", member_session_id="worker", status="completed", revision=1, reply_id="reply-1")
        self.assertTrue(settled)
        service = SessionService(storage=self.storage, message_bus=self.bus)
        await service._purge_team_projections("u", "worker-agent", "worker")
        self.assertEqual(await projection.list("leader", "collaboration_progress"), [])
        saved = await self.storage.get_message("u", "leader", "assigned")
        self.assertEqual(saved.metadata[ARCHIVE_KEY][0]["progress"]["work_status"], "completed")
        self.assertEqual(saved.metadata["keep"], "preserved")
        self.assertNotIn("PRIVATE", str(saved.metadata))
        self.assertEqual(saved.metadata[ARCHIVE_KEY][0]["progress"]["activities"][0]["presentation"]["label"], "读取资料")

    async def test_old_invite_anchor_is_updated_without_attaching_to_later_turn(self):
        await self.storage.upsert_message("u", "leader", assignment())
        await self.storage.upsert_message("u", "leader", assignment("later", revision=2))
        await archive_member_progress(self.storage, self.bus, "u", "leader", progress())
        self.assertIn(ARCHIVE_KEY, (await self.storage.get_message("u", "leader", "assigned")).metadata)
        self.assertNotIn(ARCHIVE_KEY, (await self.storage.get_message("u", "leader", "later")).metadata)
        self.assertFalse(await archive_member_progress(self.storage, self.bus, "u", "other-session", progress()))
        self.assertFalse(await archive_member_progress(self.storage, self.bus, "u", "leader", progress(revision=3)))

    async def test_failed_or_missing_tool_call_is_never_an_assignment_anchor(self):
        await self.storage.upsert_message("u", "leader", assignment(state="error"))
        self.assertFalse(await archive_member_progress(self.storage, self.bus, "u", "leader", progress()))
        message = assignment(); message.content = message.content[1:]
        await self.storage.upsert_message("u", "leader", message)
        self.assertFalse(await archive_member_progress(self.storage, self.bus, "u", "leader", progress()))

    async def test_stale_checkpoint_and_concurrent_workers_preserve_archives_and_platform_metadata(self):
        message = assignment()
        message.content.extend(assignment(worker="second").content)
        await self.storage.upsert_message("u", "leader", message)
        stale = await self.storage.get_message("u", "leader", message.id)
        await asyncio.gather(archive_member_progress(self.storage, self.bus, "u", "leader", progress()), archive_member_progress(self.storage, self.bus, "u", "leader", progress(worker="second")))
        await patch_message_metadata(self.storage, self.bus, "u", "leader", message.id, {"platform_status": "completed"})
        await save_message_with_collaboration_progress(self.storage, self.bus, "u", "leader", stale)
        saved = await self.storage.get_message("u", "leader", message.id)
        self.assertEqual(len(saved.metadata[ARCHIVE_KEY]), 2)
        self.assertEqual(saved.metadata["platform_status"], "completed")
        self.assertEqual(len(self.storage.messages), 1)

    async def test_fast_worker_snapshot_is_archived_when_invite_result_first_saves(self):
        member = self.storage.team.data.members[0]
        member.active_revision = 0; member.settled_revision = 1; member.work_status = "completed"
        await SessionProjection(self.bus).upsert("leader", "collaboration_progress", "worker", progress())
        self.assertFalse(await archive_member_progress(self.storage, self.bus, "u", "leader", progress()))
        saved = await save_message_with_collaboration_progress(self.storage, self.bus, "u", "leader", assignment())
        self.assertEqual(saved.metadata[ARCHIVE_KEY][0]["progress"]["work_status"], "completed")

    async def test_nested_worker_archive_belongs_to_inviter_not_team_root(self):
        self.storage.team.data.members[0].inviter_session_id = "parent-worker"
        await self.storage.upsert_message("u", "parent-worker", assignment())
        await self.storage.upsert_message("u", "leader", AssistantMsg(id="root", name="root", content=[]))
        await SessionProjection(self.bus).upsert("leader", "collaboration_progress", "worker", progress(status="running"))
        await archive_before_worker_delete(self.storage, self.bus, "u", self.storage.team, "worker")
        saved = await self.storage.get_message("u", "parent-worker", "assigned")
        self.assertEqual(saved.metadata[ARCHIVE_KEY][0]["leader_session_id"], "parent-worker")
        self.assertNotIn(ARCHIVE_KEY, (await self.storage.get_message("u", "leader", "root")).metadata or {})

    async def test_local_reply_end_does_not_archive_completion_while_delegations_pending(self):
        await self.storage.upsert_message("u", "leader", assignment())
        await SessionProjection(self.bus).upsert("leader", "collaboration_progress", "worker", progress(status="completed"))
        await archive_before_worker_delete(self.storage, self.bus, "u", self.storage.team, "worker")
        saved = await self.storage.get_message("u", "leader", "assigned")
        self.assertEqual(saved.metadata[ARCHIVE_KEY][0]["progress"]["work_status"], "running")

    async def test_archive_failure_does_not_block_projection_cleanup(self):
        await self.storage.upsert_message("u", "leader", assignment())
        self.storage.update_message_if_exists = AsyncMock(side_effect=RuntimeError("storage unavailable"))
        projection = SessionProjection(self.bus)
        await projection.upsert("leader", "collaboration_progress", "worker", progress(status="running"))
        service = SessionService(storage=self.storage, message_bus=self.bus)
        await service._purge_team_projections("u", "worker-agent", "worker")
        self.assertEqual(await projection.list("leader", "collaboration_progress"), [])

    async def test_deleted_anchor_is_not_reinserted_by_archive(self):
        await self.storage.upsert_message("u", "leader", assignment())
        async def concurrently_deleted(*_args):
            self.storage.messages.clear()
            return False
        self.storage.update_message_if_exists = concurrently_deleted
        self.assertFalse(await archive_member_progress(self.storage, self.bus, "u", "leader", progress()))
        self.assertEqual(self.storage.messages, {})

    async def test_later_queued_activity_cannot_downgrade_settled_previous_revision(self):
        await self.storage.upsert_message("u", "leader", assignment())
        await archive_member_progress(self.storage, self.bus, "u", "leader", progress(status="reported"))
        await archive_member_progress(self.storage, self.bus, "u", "leader", progress(status="queued", updated="2026-09-10T14:01:00+00:00"))
        saved = await self.storage.get_message("u", "leader", "assigned")
        self.assertEqual(saved.metadata[ARCHIVE_KEY][0]["progress"]["work_status"], "reported")


class ConditionalMessageStorageTest(IsolatedAsyncioTestCase):
    async def test_redis_updates_non_tail_message_without_duplicate_and_never_reinserts_deleted(self):
        from fakeredis.aioredis import FakeRedis
        from agentscope.app.storage import RedisStorage
        client = FakeRedis(decode_responses=True)
        async with RedisStorage(connection_pool=client.connection_pool) as storage:
            first, later = assignment(), assignment("later", revision=2)
            await storage.upsert_message("u", "leader", first)
            await storage.upsert_message("u", "leader", later)
            first.metadata["archive_test"] = True
            self.assertTrue(await storage.update_message_if_exists("u", "leader", first))
            messages, _ = await storage.list_messages("u", "leader")
            self.assertEqual([message.id for message in messages], ["assigned", "later"])
            await client.delete(storage._message_key("u", "leader"))
            self.assertFalse(await storage.update_message_if_exists("u", "leader", first))
            self.assertEqual((await storage.list_messages("u", "leader"))[0], [])
        await client.aclose()

    async def test_sql_updates_non_tail_message_and_never_reinserts_deleted(self):
        from agentscope.app.storage import AsyncSQLAlchemyStorage
        from agentscope.app.storage._sql._tables import MessageRow
        from sqlalchemy import delete
        async with AsyncSQLAlchemyStorage("sqlite+aiosqlite:///:memory:", create_tables=True, auto_migrate=False) as storage:
            first, later = assignment(), assignment("later", revision=2)
            await storage.upsert_message("u", "leader", first)
            await storage.upsert_message("u", "leader", later)
            self.assertTrue(await storage.update_message_if_exists("u", "leader", first))
            self.assertEqual([message.id for message in (await storage.list_messages("u", "leader"))[0]], ["assigned", "later"])
            async with storage._session() as db:
                await db.execute(delete(MessageRow)); await db.commit()
            self.assertFalse(await storage.update_message_if_exists("u", "leader", first))
