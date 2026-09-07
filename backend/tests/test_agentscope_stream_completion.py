from types import SimpleNamespace

import pytest

from backend.app.agentscope_client import (
    AgentScopeClient,
    AgentScopeGatewayError,
)
from backend.app.agentscope_stream_completion import (
    AgentScopeCompletionRelay,
)


def _client_helpers() -> AgentScopeClient:
    return SimpleNamespace(
        _message_text=AgentScopeClient._message_text,
        _terminal_reply_status=AgentScopeClient._terminal_reply_status,
    )


def _completion_event(
    *,
    input_ids: list[str],
    reply: dict | None,
    collaboration_pending: bool = False,
    runtime_status: str = "completed",
    error: str | None = None,
) -> dict:
    return {
        "type": "CUSTOM",
        "name": "run_completed",
        "value": {
            "input_message_ids": input_ids,
            "reply": reply,
            "collaboration_pending": collaboration_pending,
            "runtime_status": runtime_status,
            "error": error,
        },
    }


def _reply(message_id: str, text: str) -> dict:
    return {
        "id": message_id,
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "finished_reason": "completed",
    }


def test_completion_relay_ignores_replayed_previous_turn() -> None:
    relay = AgentScopeCompletionRelay(
        client=_client_helpers(),
        user_message_id="current-input",
    )

    result = relay.consume(
        _completion_event(
            input_ids=["previous-input"],
            reply=_reply("previous-reply", "旧回复"),
        ),
    )

    assert result is None
    assert not relay.initial_run_completed
    assert not relay.completion.is_set()
    assert relay.run_messages == []


def test_completion_relay_resolves_durable_reply_without_polling() -> None:
    relay = AgentScopeCompletionRelay(
        client=_client_helpers(),
        user_message_id="current-input",
    )
    reply_end = {"type": "REPLY_END", "reply_id": "reply-1"}
    relay.hold_reply_end(reply_end)

    public_event = relay.consume(
        _completion_event(
            input_ids=["current-input"],
            reply=_reply("reply-1", "处理完成"),
        ),
    )

    assert public_event == reply_end
    result = relay.completion.result()
    assert result.status == "completed"
    assert result.content == "处理完成"
    assert result.message_id == "reply-1"


def test_completion_relay_waits_for_collaborating_leader_to_resume() -> None:
    relay = AgentScopeCompletionRelay(
        client=_client_helpers(),
        user_message_id="current-input",
    )
    relay.hold_reply_end(
        {"type": "REPLY_END", "reply_id": "interim-reply"},
    )

    interim_event = relay.consume(
        _completion_event(
            input_ids=["current-input"],
            reply=_reply("interim-reply", "等待协作者"),
            collaboration_pending=True,
        ),
    )

    assert interim_event == {
        "type": "REPLY_END",
        "reply_id": "interim-reply",
        "platform_collaboration_pending": True,
    }
    assert not relay.completion.is_set()

    relay.hold_reply_end(
        {"type": "REPLY_END", "reply_id": "final-reply"},
    )
    final_event = relay.consume(
        _completion_event(
            input_ids=[],
            reply=_reply("final-reply", "协作完成"),
        ),
    )

    assert final_event == {"type": "REPLY_END", "reply_id": "final-reply"}
    result = relay.completion.result()
    assert result.content == "协作完成"
    assert [item["id"] for item in result.raw_messages] == [
        "interim-reply",
        "final-reply",
    ]
    assert (
        result.raw_messages[0]["platform_collaboration_status"]
        == "continued"
    )


def test_completion_relay_surfaces_run_failure_without_reply() -> None:
    relay = AgentScopeCompletionRelay(
        client=_client_helpers(),
        user_message_id="current-input",
    )

    relay.consume(
        _completion_event(
            input_ids=["current-input"],
            reply=None,
            runtime_status="error",
            error="模型调用失败",
        ),
    )

    with pytest.raises(AgentScopeGatewayError, match="模型调用失败"):
        relay.completion.result()
