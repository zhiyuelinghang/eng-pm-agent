"""Regression tests for reliable team-worker completion reporting."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from agentscope.app._service._chat import ChatService
from agentscope.message import (
    AssistantMsg,
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
)
from agentscope.types import ReplyFinishedReason


class WorkerReportDetectionTest(TestCase):
    """Only a successful TeamSay to the leader suppresses the fallback."""

    def test_successful_broadcast_counts_as_a_leader_report(self) -> None:
        reply = AssistantMsg(
            name="worker",
            content=[
                ToolCallBlock(
                    id="team-say",
                    name="TeamSay",
                    input='{"content":"完成","to":null}',
                    state=ToolCallState.FINISHED,
                ),
                ToolResultBlock(
                    id="team-say",
                    name="TeamSay",
                    output="Delivered.",
                    state=ToolResultState.SUCCESS,
                ),
            ],
        )

        self.assertTrue(
            ChatService._reported_to_leader(reply, "leader"),
        )

    def test_message_to_a_peer_does_not_count_as_leader_report(self) -> None:
        reply = AssistantMsg(
            name="worker",
            content=[
                ToolCallBlock(
                    id="team-say",
                    name="TeamSay",
                    input='{"content":"同步","to":"peer"}',
                    state=ToolCallState.FINISHED,
                ),
                ToolResultBlock(
                    id="team-say",
                    name="TeamSay",
                    output="Delivered.",
                    state=ToolResultState.SUCCESS,
                ),
            ],
        )

        self.assertFalse(
            ChatService._reported_to_leader(reply, "leader"),
        )


class WorkerAutoReportTest(IsolatedAsyncioTestCase):
    """A terminal worker turn is delivered even if the model skipped TeamSay."""

    def _service(self) -> tuple[ChatService, SimpleNamespace]:
        service = object.__new__(ChatService)
        worker_session = SimpleNamespace(team_id="team-1")
        leader_session = SimpleNamespace(
            id="leader-session",
            agent_id="leader-agent",
        )
        service._storage = SimpleNamespace(
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
                    data=SimpleNamespace(name="主智能体"),
                ),
            ),
        )
        service._message_bus = SimpleNamespace()
        worker_agent = SimpleNamespace(
            data=SimpleNamespace(name="核验智能体"),
        )
        return service, worker_agent

    async def test_completed_worker_reply_is_forwarded_to_leader(self) -> None:
        service, worker_agent = self._service()
        reply = AssistantMsg(
            id="reply-1",
            name="核验智能体",
            content=[
                TextBlock(text="中间说明"),
                TextBlock(text="最终核验结论"),
            ],
            finished_reason=ReplyFinishedReason.COMPLETED,
        )

        with patch(
            "agentscope.app._service._chat.deliver_team_message",
            new_callable=AsyncMock,
        ) as deliver, patch(
            "agentscope.app._service._chat.settle_team_member",
            new_callable=AsyncMock,
        ) as settle:
            await service._auto_report_worker_reply(
                user_id="default",
                session_id="worker-session",
                agent_id="worker-agent",
                agent_record=worker_agent,
                reply_msg=reply,
            )

        deliver.assert_awaited_once_with(
            service._message_bus,
            user_id="default",
            recipient_session_id="leader-session",
            recipient_agent_id="leader-agent",
            sender_name="核验智能体",
            content="最终核验结论",
        )
        settle.assert_awaited_once()

    async def test_max_iteration_worker_reply_is_still_forwarded(self) -> None:
        service, worker_agent = self._service()
        reply = AssistantMsg(
            id="reply-max-iters",
            name="核验智能体",
            content=[TextBlock(text="已取得部分但可用的核验结果")],
            finished_reason=ReplyFinishedReason.EXCEED_MAX_ITERS,
        )

        with patch(
            "agentscope.app._service._chat.deliver_team_message",
            new_callable=AsyncMock,
        ) as deliver, patch(
            "agentscope.app._service._chat.settle_team_member",
            new_callable=AsyncMock,
        ) as settle:
            await service._auto_report_worker_reply(
                user_id="default",
                session_id="worker-session",
                agent_id="worker-agent",
                agent_record=worker_agent,
                reply_msg=reply,
            )

        self.assertEqual(
            deliver.await_args.kwargs["content"],
            "已取得部分但可用的核验结果",
        )
        self.assertEqual(settle.await_args.kwargs["status"], "completed")

    async def test_interrupted_worker_is_reported_and_settled(self) -> None:
        service, worker_agent = self._service()
        reply = AssistantMsg(
            id="reply-interrupted",
            name="核验智能体",
            content=[TextBlock(text="已完成一部分")],
            finished_reason=ReplyFinishedReason.INTERRUPTED,
        )

        with patch(
            "agentscope.app._service._chat.deliver_team_message",
            new_callable=AsyncMock,
        ) as deliver, patch(
            "agentscope.app._service._chat.settle_team_member",
            new_callable=AsyncMock,
        ) as settle:
            await service._auto_report_worker_reply(
                user_id="default",
                session_id="worker-session",
                agent_id="worker-agent",
                agent_record=worker_agent,
                reply_msg=reply,
                work_revision=3,
            )

        self.assertIn("已中断", deliver.await_args.kwargs["content"])
        self.assertEqual(settle.await_args.kwargs["status"], "interrupted")
        self.assertEqual(settle.await_args.kwargs["revision"], 3)
