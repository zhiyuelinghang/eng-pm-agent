"""Regression tests for durable asynchronous team lifecycle state."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from agentscope.app._team_lifecycle import (
    assign_team_member,
    mark_team_leader_completed,
    mark_team_leader_running,
    mark_team_member_running,
    settle_team_member,
    team_work_is_pending,
)
from agentscope.app._tool._team_say import TeamSay
from agentscope.app.storage import TeamData, TeamMember, TeamRecord


class _Bus:
    @asynccontextmanager
    async def acquire_lock(self, _key: str, *, ttl_secs: int = 600):
        del ttl_secs
        yield


class _Storage:
    def __init__(self, team: TeamRecord) -> None:
        self.team = team

    async def get_team(self, _user_id: str, team_id: str):
        return self.team if self.team.id == team_id else None

    async def upsert_team(self, _user_id: str, team: TeamRecord):
        self.team = team.model_copy(deep=True)
        return self.team


class TeamLifecycleTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.team = TeamRecord(
            id="team-1",
            user_id="default",
            session_id="leader-session",
            data=TeamData(
                name="初始化团队",
                members=[
                    TeamMember(
                        owner_id="default",
                        agent_id="worker-agent",
                        session_id="worker-session",
                        role="invited",
                    ),
                ],
            ),
        )
        self.storage = _Storage(self.team)
        self.bus = _Bus()

    async def test_idle_queued_member_remains_pending(self) -> None:
        revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )

        self.assertEqual(revision, 1)
        member = self.storage.team.data.members[0]
        self.assertEqual(member.work_status, "queued")
        self.assertTrue(team_work_is_pending(self.storage.team))

    async def test_team_finishes_only_after_worker_and_leader_settle(self) -> None:
        revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        running_revision = await mark_team_member_running(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        self.assertEqual(running_revision, revision)

        # An interim leader reply cannot close the business turn.
        acknowledged = await mark_team_leader_completed(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
            observed_settlement_revision=(
                await mark_team_leader_running(
                    self.storage,
                    self.bus,
                    user_id="default",
                    team_id="team-1",
                    leader_session_id="leader-session",
                )
            ),
        )
        self.assertFalse(acknowledged)

        await settle_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
            status="reported",
            revision=running_revision,
            reply_id="worker-reply",
        )
        self.assertTrue(team_work_is_pending(self.storage.team))

        final_snapshot = await mark_team_leader_running(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
        )
        acknowledged = await mark_team_leader_completed(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
            observed_settlement_revision=final_snapshot,
        )
        self.assertTrue(acknowledged)
        self.assertFalse(team_work_is_pending(self.storage.team))

    async def test_later_assignment_is_not_settled_by_older_run(self) -> None:
        first_revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        await mark_team_member_running(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        second_revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        await settle_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
            status="completed",
            revision=first_revision,
        )

        member = self.storage.team.data.members[0]
        self.assertEqual(member.work_revision, second_revision)
        self.assertEqual(member.settled_revision, first_revision)
        self.assertEqual(member.active_revision, 0)
        self.assertEqual(member.work_status, "queued")
        self.assertTrue(team_work_is_pending(self.storage.team))

    async def test_later_assignment_is_not_settled_by_explicit_report(
        self,
    ) -> None:
        first_revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        await mark_team_member_running(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        second_revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        await settle_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
            status="reported",
        )

        member = self.storage.team.data.members[0]
        self.assertEqual(member.settled_revision, first_revision)
        self.assertEqual(member.work_revision, second_revision)
        self.assertEqual(member.active_revision, 0)
        self.assertEqual(member.work_status, "queued")

    async def test_turn_that_creates_team_cannot_acknowledge_fast_report(
        self,
    ) -> None:
        revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        await settle_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
            status="reported",
            revision=revision,
        )

        acknowledged = await mark_team_leader_completed(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
            observed_settlement_revision=None,
        )

        self.assertFalse(acknowledged)
        self.assertTrue(team_work_is_pending(self.storage.team))

    async def test_leader_turn_started_before_report_cannot_finish_team(
        self,
    ) -> None:
        revision = await assign_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
        )
        observed_settlements = await mark_team_leader_running(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
        )
        await settle_team_member(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            member_session_id="worker-session",
            status="reported",
            revision=revision,
        )

        acknowledged = await mark_team_leader_completed(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
            observed_settlement_revision=observed_settlements,
        )

        self.assertFalse(acknowledged)
        self.assertTrue(team_work_is_pending(self.storage.team))

        fresh_snapshot = await mark_team_leader_running(
            self.storage,
            self.bus,
            user_id="default",
            team_id="team-1",
            leader_session_id="leader-session",
        )
        self.assertTrue(
            await mark_team_leader_completed(
                self.storage,
                self.bus,
                user_id="default",
                team_id="team-1",
                leader_session_id="leader-session",
                observed_settlement_revision=fresh_snapshot,
            ),
        )

    async def test_worker_default_team_say_targets_only_leader(self) -> None:
        peer = TeamMember(
            owner_id="default",
            agent_id="peer-agent",
            session_id="peer-session",
            role="invited",
        )
        team = self.storage.team.model_copy(deep=True)
        team.data.members.append(peer)
        storage = SimpleNamespace()
        storage.get_team = AsyncMock(return_value=team)

        async def get_session(_user_id: str, _agent_id: str, sid: str):
            if sid == "worker-session":
                return SimpleNamespace(
                    id=sid,
                    agent_id="worker-agent",
                    team_id="team-1",
                )
            if sid == "leader-session":
                return SimpleNamespace(
                    id=sid,
                    agent_id="leader-agent",
                    team_id="team-1",
                )
            return None

        async def get_agent(_user_id: str, agent_id: str):
            names = {
                "leader-agent": "初始化主智能体",
                "worker-agent": "WBS 专家",
                "peer-agent": "风险专家",
            }
            return SimpleNamespace(data=SimpleNamespace(name=names[agent_id]))

        storage.get_session = AsyncMock(side_effect=get_session)
        storage.get_agent = AsyncMock(side_effect=get_agent)
        tool = TeamSay(
            storage=storage,
            message_bus=SimpleNamespace(),
            workspace_manager=SimpleNamespace(),
            user_id="default",
            session_id="worker-session",
            agent_id="worker-agent",
            role="worker",
        )

        with patch(
            "agentscope.app._tool._team_say.deliver_team_message",
            new_callable=AsyncMock,
        ) as deliver, patch(
            "agentscope.app._tool._team_say.settle_team_member",
            new_callable=AsyncMock,
        ) as settle:
            result = await tool(content="WBS 核验完成")

        deliver.assert_awaited_once()
        self.assertEqual(
            deliver.await_args.kwargs["recipient_session_id"],
            "leader-session",
        )
        settle.assert_awaited_once()
        self.assertIn("leader", result.content[0].text)
