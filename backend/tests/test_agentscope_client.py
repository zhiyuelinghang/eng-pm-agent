"""Unit tests for the main platform's AgentScope gateway client."""

import asyncio
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import HTTPException

from backend.app.agentscope_client import (
    AgentScopeClient,
    AgentScopeGatewayError,
    AgentScopeReply,
)
from backend.app.api import (
    _agent_conversation_or_404,
    _agent_reply_extra_data,
    _catalog_agent_for_conversation,
    _sse_frame,
)
from backend.app.config import Settings


def _client() -> AgentScopeClient:
    return AgentScopeClient(
        Settings(
            agentscope_base_url="http://127.0.0.1:18642",
            agentscope_service_token="platform-service-token-for-tests",
            agentscope_request_timeout_seconds=2,
            agentscope_poll_interval_seconds=0.1,
        ),
    )


class AgentScopeClientTest(TestCase):
    """Exercise the server-side catalogue/session/chat protocol."""

    def test_uses_dedicated_service_bearer_token(self) -> None:
        client = _client()

        self.assertEqual(
            client.headers,
            {
                "Authorization": (
                    "Bearer platform-service-token-for-tests"
                ),
            },
        )
        self.assertNotIn("X-User-ID", client.headers)

    def test_agent_conversation_is_private_even_from_platform_admin(
        self,
    ) -> None:
        conversation = SimpleNamespace(
            id=7,
            user_id=2,
            project_id=5,
        )
        database = Mock()
        database.get.return_value = conversation
        admin = SimpleNamespace(id=1, role="superadmin")

        with self.assertRaises(HTTPException) as caught:
            _agent_conversation_or_404(database, conversation.id, admin)

        self.assertEqual(caught.exception.status_code, 403)

    def test_create_session_applies_knowledge_and_permission_config(self) -> None:
        client = _client()
        client._request = Mock(  # type: ignore[method-assign]
            side_effect=[{"session_id": "session-1"}, {}],
        )
        agent = {
            "id": "agent-1",
            "name": "进度分析师",
            "model_ready": True,
            "permission_mode": "explore",
            "knowledge_config": {
                "knowledge_base_ids": ["kb-1"],
                "parameters": {"mode": "agentic", "top_k": 5},
            },
        }

        session_id = client.create_session(
            agent=agent,
            workspace_id="platform-u1-p2-c3",
            name="测试会话",
        )

        self.assertEqual(session_id, "session-1")
        create_call, patch_call = client._request.call_args_list
        self.assertEqual(create_call.args, ("POST", "/sessions/"))
        self.assertEqual(
            create_call.kwargs["json"]["knowledge_config"],
            agent["knowledge_config"],
        )
        self.assertEqual(
            patch_call.kwargs["json"],
            {
                "permission_mode": "explore",
                "knowledge_config": agent["knowledge_config"],
            },
        )

    def test_chat_returns_new_finished_assistant_message(self) -> None:
        client = _client()
        before = {"messages": [{"id": "old", "role": "assistant"}]}
        finished = {
            "id": "new",
            "role": "assistant",
            "finished_at": "2026-07-28T10:00:00+08:00",
            "content": [{"type": "text", "text": "处理完成"}],
        }
        client.list_messages = Mock(  # type: ignore[method-assign]
            side_effect=[
                before,
                {"messages": [*before["messages"], finished]},
                {"messages": [*before["messages"], finished]},
            ],
        )
        client.session_status = Mock(return_value="idle")  # type: ignore[method-assign]
        client.session_team_state = Mock(  # type: ignore[method-assign]
            return_value=(False, False),
        )
        client._request = Mock(return_value={"status": "started"})  # type: ignore[method-assign]

        with (
            patch("backend.app.agentscope_client.uuid4") as uuid_factory,
            patch(
                "backend.app.agentscope_client.time.monotonic",
                side_effect=[0, 0.1, 0.1, 0.2, 1.0],
            ),
            patch("backend.app.agentscope_client.time.sleep"),
        ):
            uuid_factory.return_value.hex = "user-message"
            reply = client.chat(
                agent_id="agent-1",
                session_id="session-1",
                content="测试",
                sender_name="测试用户",
                metadata={"source": "test"},
            )

        self.assertEqual(reply.status, "completed")
        self.assertEqual(reply.content, "处理完成")
        self.assertEqual(reply.message_id, "new")
        self.assertEqual(reply.raw_messages, [finished])
        request_body = client._request.call_args.kwargs["json"]
        self.assertEqual(request_body["input"]["id"], "user-message")
        self.assertEqual(request_body["input"]["metadata"]["source"], "test")

    def test_chat_waits_for_team_follow_up_before_returning(self) -> None:
        client = _client()
        before = {"messages": []}
        interim = {
            "id": "interim",
            "role": "assistant",
            "finished_at": "2026-07-28T10:00:00+08:00",
            "content": [{"type": "text", "text": "等待成员回复"}],
        }
        final = {
            "id": "final",
            "role": "assistant",
            "finished_at": "2026-07-28T10:00:10+08:00",
            "content": [{"type": "text", "text": "成员已核验，最终结论"}],
        }
        client.list_messages = Mock(  # type: ignore[method-assign]
            side_effect=[
                before,
                {"messages": [interim]},
                {"messages": [interim, final]},
                {"messages": [interim, final]},
            ],
        )
        client.session_status = Mock(return_value="idle")  # type: ignore[method-assign]
        client.session_team_state = Mock(  # type: ignore[method-assign]
            side_effect=[
                (True, True),
                (False, False),
                (False, False),
            ],
        )
        client._request = Mock(return_value={"status": "started"})  # type: ignore[method-assign]

        with (
            patch(
                "backend.app.agentscope_client.time.monotonic",
                side_effect=[0, 0.1, 0.2, 0.2, 0.3, 1.0],
            ),
            patch("backend.app.agentscope_client.time.sleep"),
        ):
            reply = client.chat(
                agent_id="leader",
                session_id="session",
                content="协同验证",
                sender_name="测试用户",
                metadata={},
            )

        self.assertEqual(reply.message_id, "final")
        self.assertEqual(reply.content, "成员已核验，最终结论")
        self.assertEqual(reply.raw_messages, [interim, final])

    def test_chat_does_not_require_team_deletion_after_members_settle(
        self,
    ) -> None:
        client = _client()
        final = {
            "id": "final",
            "role": "assistant",
            "finished_at": "2026-07-28T10:00:10+08:00",
            "content": [{"type": "text", "text": "协同任务已完成"}],
        }
        client.list_messages = Mock(  # type: ignore[method-assign]
            side_effect=[
                {"messages": []},
                {"messages": [final]},
                {"messages": [final]},
            ],
        )
        client.session_status = Mock(return_value="idle")  # type: ignore[method-assign]
        client.session_team_state = Mock(  # type: ignore[method-assign]
            return_value=(True, False),
        )
        client._request = Mock(return_value={"status": "started"})  # type: ignore[method-assign]

        with (
            patch(
                "backend.app.agentscope_client.time.monotonic",
                side_effect=[0, 0.1, 0.1, 0.2, 1.0],
            ),
            patch("backend.app.agentscope_client.time.sleep"),
        ):
            reply = client.chat(
                agent_id="leader",
                session_id="session",
                content="协同验证",
                sender_name="测试用户",
                metadata={},
            )

        self.assertEqual(reply.message_id, "final")
        self.assertEqual(reply.content, "协同任务已完成")

    def test_event_stream_parser_preserves_structured_sse_payloads(self) -> None:
        class FakeResponse:
            async def aiter_lines(self):
                for line in (
                    ": heartbeat",
                    'data: {"type":"REPLY_START",',
                    'data: "reply_id":"reply-1"}',
                    "",
                    'data: {"type":"TEXT_BLOCK_DELTA","delta":"你好"}',
                ):
                    yield line

        async def collect() -> list[dict]:
            return [
                event
                async for event in AgentScopeClient._iter_sse_events(
                    FakeResponse(),  # type: ignore[arg-type]
                )
            ]

        self.assertEqual(
            asyncio.run(collect()),
            [
                {"type": "REPLY_START", "reply_id": "reply-1"},
                {"type": "TEXT_BLOCK_DELTA", "delta": "你好"},
            ],
        )

    def test_event_stream_parser_rejects_invalid_json(self) -> None:
        class FakeResponse:
            async def aiter_lines(self):
                yield "data: not-json"
                yield ""

        async def collect() -> None:
            async for _ in AgentScopeClient._iter_sse_events(
                FakeResponse(),  # type: ignore[arg-type]
            ):
                pass

        with self.assertRaises(AgentScopeGatewayError):
            asyncio.run(collect())

    def test_projected_confirmation_returns_without_polling_leader(self) -> None:
        client = _client()
        parked = {
            "id": "worker-reply",
            "role": "assistant",
            "content": [],
        }
        client.list_messages = Mock(return_value={"messages": [parked]})  # type: ignore[method-assign]
        client.session_status = Mock()  # type: ignore[method-assign]
        client._request = Mock(  # type: ignore[method-assign]
            return_value={
                "status": "started",
                "session_id": "worker-session",
            },
        )

        reply = client.confirm_tool_call(
            agent_id="leader",
            session_id="leader-session",
            reply_id="worker-reply",
            tool_call={
                "type": "tool_call",
                "id": "call-1",
                "name": "Write",
                "input": "{}",
                "state": "asking",
            },
            confirmed=True,
        )

        self.assertTrue(reply.projected)
        self.assertEqual(reply.status, "running")
        client.session_status.assert_not_called()

    def test_runtime_payload_keeps_all_agent_messages_and_trace(self) -> None:
        first = {
            "id": "reply-1",
            "role": "assistant",
            "content": [{"type": "text", "text": "准备协同"}],
        }
        final = {
            "id": "reply-2",
            "role": "assistant",
            "content": [{"type": "text", "text": "最终结论"}],
        }
        payload = _agent_reply_extra_data(
            AgentScopeReply(
                status="completed",
                content="最终结论",
                message_id="reply-2",
                raw_message=final,
                raw_messages=[first, final],
            ),
            {
                "model_names": ["qwen-plus"],
                "tasks_context": {"tasks": []},
                "team_update_count": 1,
                "subagent_hitl": [],
            },
        )

        self.assertEqual(payload["agentscope_messages"], [first, final])
        self.assertEqual(
            payload["runtime_trace"]["model_names"],
            ["qwen-plus"],
        )
        self.assertEqual(
            _sse_frame("agent_event", {"type": "TEXT_BLOCK_DELTA", "delta": "中"}),
            'event: agent_event\ndata: {"type":"TEXT_BLOCK_DELTA","delta":"中"}\n\n',
        )

    def test_message_text_hides_internal_hint_blocks(self) -> None:
        text = AgentScopeClient._message_text(
            {
                "content": [
                    {"type": "text", "text": "结论"},
                    {"type": "hint", "hint": "依据"},
                ],
            },
        )
        self.assertEqual(text, "结论")

    def test_message_text_returns_only_post_tool_final_answer(self) -> None:
        text = AgentScopeClient._message_text(
            {
                "content": [
                    {"type": "text", "text": "正在邀请成员"},
                    {
                        "type": "tool_call",
                        "id": "invite",
                        "name": "AgentInvite",
                    },
                    {
                        "type": "tool_result",
                        "id": "invite",
                        "name": "AgentInvite",
                    },
                    {"type": "thinking", "thinking": "整理成员结果"},
                    {"type": "text", "text": "最终结论第一部分"},
                    {"type": "text", "text": "最终结论第二部分"},
                ],
            },
        )
        self.assertEqual(
            text,
            "最终结论第一部分\n最终结论第二部分",
        )

    def test_stale_global_main_conversation_is_rejected(self) -> None:
        conversation = SimpleNamespace(
            conversation_type="general",
            agent_id="old-main",
        )

        with self.assertRaises(HTTPException) as raised:
            _catalog_agent_for_conversation(
                {
                    "global_main": {
                        "id": "new-main",
                        "name": "新主智能体",
                        "model_ready": True,
                    },
                    "business_agents": [],
                },
                conversation,
            )

        self.assertEqual(raised.exception.status_code, 409)
