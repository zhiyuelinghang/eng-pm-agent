"""Regression tests for the durable AgentScope run-completion signal."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agentscope.app._service._chat import ChatService, RUN_COMPLETED_EVENT
from agentscope.event import ReplyEndEvent
from agentscope.message import AssistantMsg, TextBlock, UserMsg
from agentscope.types import ReplyFinishedReason


def test_run_completion_contains_correlated_persisted_reply() -> None:
    service = object.__new__(ChatService)
    service._storage = SimpleNamespace(
        get_session=AsyncMock(return_value=None),
    )
    service._message_bus = object()
    user = UserMsg(
        id="user-1",
        name="测试用户",
        content=[TextBlock(text="你好")],
    )
    reply = AssistantMsg(
        id="reply-1",
        name="Dobby",
        content=[TextBlock(text="你好")],
    )
    reply.append_event(
        ReplyEndEvent(
            session_id="session-1",
            reply_id=reply.id,
            finished_reason=ReplyFinishedReason.COMPLETED,
        ),
    )

    with patch(
        "agentscope.app._service._chat.publish_session_event",
        new=AsyncMock(),
    ) as publish:
        asyncio.run(
            service._publish_run_completed(
                user_id="admin",
                session_id="session-1",
                agent_id="global-main",
                input_msg=user,
                reply_msg=reply,
                failure=None,
            ),
        )

    event = publish.await_args.args[2]
    assert event["type"] == "CUSTOM"
    assert event["name"] == RUN_COMPLETED_EVENT
    assert event["value"]["input_message_ids"] == ["user-1"]
    assert event["value"]["runtime_status"] == "completed"
    assert event["value"]["reply"]["id"] == "reply-1"
    assert event["value"]["collaboration_pending"] is False
