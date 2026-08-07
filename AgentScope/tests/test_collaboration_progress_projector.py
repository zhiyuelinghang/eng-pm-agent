"""Tests for leader-side collaboration progress projection."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from agentscope.app._service._projectors import (
    CollaborationProgressProjector,
)
from agentscope.app.storage import TeamData, TeamMember, TeamRecord
from agentscope.event import (
    ModelCallStartEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
)


class _Storage:
    def __init__(self) -> None:
        self.team = TeamRecord(
            id="team-1",
            user_id="default",
            session_id="leader-session",
            data=TeamData(
                name="项目初始化团队",
                members=[
                    TeamMember(
                        owner_id="default",
                        agent_id="worker-agent",
                        session_id="worker-session",
                        role="invited",
                        work_revision=3,
                        active_revision=3,
                        work_status="running",
                    ),
                ],
            ),
        )

    async def get_team(self, _user_id: str, team_id: str):
        return self.team if team_id == self.team.id else None


class _Projection:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str], dict] = {}
        self.published: list[tuple[str, str, dict]] = []

    async def list(self, target: str, kind: str):
        return [
            value
            for (stored_target, stored_kind, _), value in self.entries.items()
            if stored_target == target and stored_kind == kind
        ]

    async def upsert(self, target: str, kind: str, entry: str, value: dict):
        self.entries[(target, kind, entry)] = value

    async def publish(self, target: str, event: str, value: dict):
        self.published.append((target, event, value))

    async def delete(self, target: str, kind: str, entry: str):
        self.entries.pop((target, kind, entry), None)

    async def purge(self, target: str, kind: str):
        for key in list(self.entries):
            if key[0] == target and key[1] == kind:
                self.entries.pop(key)


class CollaborationProgressProjectorTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.storage = _Storage()
        self.projection = _Projection()
        self.projector = CollaborationProgressProjector(self.storage)
        self.session = SimpleNamespace(
            id="worker-session",
            team_id="team-1",
        )
        self.agent = SimpleNamespace(
            id="worker-agent",
            data=SimpleNamespace(name="WBS 与进度专家"),
        )

    async def project(self, event) -> dict:
        await self.projector.maybe_project(
            "default",
            self.session,
            self.agent,
            event,
            self.projection,
        )
        return self.projection.entries[
            (
                "leader-session",
                CollaborationProgressProjector.KIND,
                "worker-session",
            )
        ]

    async def test_projects_only_safe_operational_progress(self) -> None:
        payload = await self.project(
            ReplyStartEvent(
                session_id="worker-session",
                reply_id="reply-1",
                name="WBS 与进度专家",
            ),
        )
        self.assertEqual(payload["work_status"], "running")
        self.assertEqual(payload["activities"][0]["kind"], "started")

        payload = await self.project(
            ModelCallStartEvent(
                reply_id="reply-1",
                model_name="test-model",
            ),
        )
        payload = await self.project(
            ToolCallStartEvent(
                reply_id="reply-1",
                tool_call_id="tool-1",
                tool_call_name="initialization_submit_section",
            ),
        )
        payload = await self.project(
            ToolResultEndEvent(
                reply_id="reply-1",
                tool_call_id="tool-1",
                state="success",
            ),
        )

        self.assertEqual(
            payload["current_activity"]["tool_name"],
            "initialization_submit_section",
        )
        self.assertEqual(payload["current_activity"]["state"], "success")
        serialized = str(payload)
        self.assertNotIn("thinking", serialized.lower())
        self.assertNotIn("input", serialized.lower())

    async def test_terminal_event_is_persisted_and_replayed(self) -> None:
        await self.project(
            ReplyStartEvent(
                session_id="worker-session",
                reply_id="reply-1",
                name="WBS 与进度专家",
            ),
        )
        payload = await self.project(
            ReplyEndEvent(
                session_id="worker-session",
                reply_id="reply-1",
                finished_reason="completed",
            ),
        )

        self.assertEqual(payload["work_status"], "completed")
        self.assertIsNotNone(payload["settled_at"])
        self.assertEqual(
            self.projection.published[-1][1],
            CollaborationProgressProjector.EVT_UPDATE,
        )

    async def test_leader_events_are_not_projected_back_to_itself(self) -> None:
        leader = SimpleNamespace(id="leader-session", team_id="team-1")
        await self.projector.maybe_project(
            "default",
            leader,
            self.agent,
            ReplyStartEvent(
                session_id="leader-session",
                reply_id="reply-1",
                name="主智能体",
            ),
            self.projection,
        )

        self.assertEqual(self.projection.entries, {})
