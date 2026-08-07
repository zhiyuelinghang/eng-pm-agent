"""Regression tests for durable team-assignment completion signals."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from agentscope.app.middleware._state_change_middleware import (
    StateChangeMiddleware,
)
from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolResponse


class DurableTeamCompletionTest(IsolatedAsyncioTestCase):
    """A successful terminal platform write wakes the leader immediately."""

    def _middleware(self) -> StateChangeMiddleware:
        return StateChangeMiddleware(
            message_bus=SimpleNamespace(),
            session_id="worker-session",
            storage=SimpleNamespace(),
            user_id="default",
            agent_id="worker-agent",
        )

    async def test_success_metadata_triggers_assignment_report(self) -> None:
        middleware = self._middleware()
        middleware._state_hash = lambda _agent: "unchanged"
        middleware._report_completed_team_assignment = AsyncMock()

        async def next_handler(**_kwargs):
            yield ToolResponse(
                content=[TextBlock(text="ok")],
                state=ToolResultState.SUCCESS,
                metadata={
                    "team_report_on_success": True,
                    "team_report_message": "草稿分区已写入",
                },
            )

        items = [
            item
            async for item in middleware.on_acting(
                SimpleNamespace(),
                {"tool_call": SimpleNamespace(name="submit-section")},
                next_handler,
            )
        ]

        self.assertEqual(len(items), 1)
        middleware._report_completed_team_assignment.assert_awaited_once()

    async def test_failed_tool_does_not_report_completion(self) -> None:
        middleware = self._middleware()
        middleware._state_hash = lambda _agent: "unchanged"
        middleware._report_completed_team_assignment = AsyncMock()

        async def next_handler(**_kwargs):
            yield ToolResponse(
                content=[TextBlock(text="failed")],
                state=ToolResultState.ERROR,
                metadata={"team_report_on_success": True},
            )

        _ = [
            item
            async for item in middleware.on_acting(
                SimpleNamespace(),
                {"tool_call": SimpleNamespace(name="submit-section")},
                next_handler,
            )
        ]

        middleware._report_completed_team_assignment.assert_not_awaited()

    async def test_durable_report_is_delivered_only_when_newly_settled(
        self,
    ) -> None:
        middleware = self._middleware()
        worker_session = SimpleNamespace(team_id="team-1")
        leader_session = SimpleNamespace(
            id="leader-session",
            agent_id="leader-agent",
        )
        middleware._storage = SimpleNamespace(
            get_session=AsyncMock(
                side_effect=[worker_session, leader_session],
            ),
            get_team=AsyncMock(
                return_value=SimpleNamespace(
                    id="team-1",
                    session_id="leader-session",
                ),
            ),
            get_agent=AsyncMock(
                return_value=SimpleNamespace(
                    data=SimpleNamespace(name="WBS与进度专家"),
                ),
            ),
        )

        with patch(
            "agentscope.app.middleware._state_change_middleware."
            "settle_team_member",
            new_callable=AsyncMock,
            return_value=True,
        ) as settle, patch(
            "agentscope.app.middleware._state_change_middleware."
            "deliver_team_message",
            new_callable=AsyncMock,
        ) as deliver:
            await middleware._report_completed_team_assignment(
                {"team_report_message": "WBS 草稿已写入"},
                SimpleNamespace(name="worker"),
            )

        settle.assert_awaited_once()
        deliver.assert_awaited_once_with(
            middleware._bus,
            user_id="default",
            recipient_session_id="leader-session",
            recipient_agent_id="leader-agent",
            sender_name="WBS与进度专家",
            content="WBS 草稿已写入",
        )
