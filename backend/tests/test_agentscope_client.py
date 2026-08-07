"""Unit tests for the main platform's AgentScope gateway client."""

import asyncio
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import HTTPException

from backend.app.agentscope_client import (
    AgentScopeClient,
    AgentScopeConfirmationSubmission,
    AgentScopeGatewayError,
    AgentScopeReply,
)
from backend.app.api import (
    _annotate_collaboration_event,
    _agent_conversation_or_404,
    _agent_reply_extra_data,
    _agentscope_assistant_groups,
    _agentscope_platform_messages,
    _agentscope_reply_from_group,
    _catalog_agent_for_conversation,
    _platform_session_context,
    _project_agentscope_user_message,
    _sse_frame,
    create_agent_conversation,
    list_agent_conversations,
    list_agent_conversation_messages,
    stream_agent_conversation_tool_confirmation,
)
from backend.app.config import Settings
from backend.app.models import AgentConversation
from backend.app.schemas import (
    AgentConversationConfirmInput,
    AgentConversationInput,
)


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

    def test_platform_sessions_never_auto_allow_initialization_tools(self) -> None:
        user = SimpleNamespace(id=1, username="admin", real_name="管理员")
        project = SimpleNamespace(id=2, name="测试项目")
        conversation = SimpleNamespace(
            id=3,
            title="项目初始化",
            conversation_type="initialization",
            agent_name="初始化助手",
        )

        context = _platform_session_context(user, project, conversation)

        names = context["auto_allowed_tool_names"]
        self.assertEqual(names, [])

        conversation.conversation_type = "business"
        business_context = _platform_session_context(
            user,
            project,
            conversation,
        )
        self.assertEqual(business_context["auto_allowed_tool_names"], [])

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
        admin = SimpleNamespace(id=1, role="admin")

        with self.assertRaises(HTTPException) as caught:
            _agent_conversation_or_404(database, conversation.id, admin)

        self.assertEqual(caught.exception.status_code, 403)

    def test_history_reads_agentscope_without_querying_message_mirror(
        self,
    ) -> None:
        conversation = SimpleNamespace(
            id=7,
            user_id=2,
            project_id=5,
            agent_id="initializer",
            conversation_type="business",
            agentscope_session_id="session-7",
            status="running",
            last_error=None,
            updated_at=None,
        )
        database = Mock()
        database.get.return_value = conversation
        user = SimpleNamespace(id=2, role="admin")
        gateway = Mock()
        gateway.session_status.return_value = "idle"
        gateway.list_all_messages.return_value = {
            "messages": [
                {
                    "id": "user-1",
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "<user-request>读取人员表</user-request>",
                        },
                    ],
                },
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "已读取"}],
                    "finished_at": "2026-07-31T10:00:00+08:00",
                },
            ],
        }

        with (
            patch("backend.app.api.project_for_user_or_403"),
            patch("backend.app.api._agentscope_client", return_value=gateway),
        ):
            result = list_agent_conversation_messages(
                conversation_id=7,
                db=database,
                user=user,
            )

        self.assertEqual(
            [item["content"] for item in result["data"]],
            ["读取人员表", "已读取"],
        )
        gateway.list_all_messages.assert_called_once_with(
            "session-7",
            "initializer",
        )
        database.scalars.assert_not_called()
        self.assertEqual(conversation.status, "completed")
        database.commit.assert_called_once()

    def test_initialization_conversation_list_serializes_conversations(
        self,
    ) -> None:
        conversation = AgentConversation(
            id=9,
            project_id=5,
            user_id=2,
            agent_id="initializer",
            agent_name="Dobby 项目初始化助手",
            conversation_type="initialization",
            title="测试项目 · 项目初始化",
            agentscope_session_id="session-9",
            status="completed",
        )
        database = Mock()
        database.scalars.return_value.all.return_value = [conversation]
        user = SimpleNamespace(id=2, role="admin")
        with patch("backend.app.api.project_for_user_or_403"):
            result = list_agent_conversations(
                project_id=5,
                conversation_type="initialization",
                agent_id=None,
                db=database,
                user=user,
            )

        self.assertEqual(result["data"][0]["id"], 9)
        self.assertEqual(
            result["data"][0]["agentscope_session_id"],
            "session-9",
        )
        self.assertEqual(
            result["data"][0]["conversation_type"],
            "initialization",
        )

    def test_initialization_conversation_creation_reuses_existing_row(
        self,
    ) -> None:
        conversation = AgentConversation(
            id=9,
            project_id=5,
            user_id=2,
            agent_id="initializer",
            agent_name="Dobby 项目初始化助手",
            conversation_type="initialization",
            title="测试项目 · 项目初始化",
            agentscope_session_id="session-9",
            status="completed",
        )
        database = Mock()
        database.scalar.return_value = conversation
        user = SimpleNamespace(id=2, role="admin")
        project = SimpleNamespace(id=5, name="测试项目")
        gateway = Mock()

        with (
            patch(
                "backend.app.api.project_for_user_or_403",
                return_value=project,
            ),
            patch("backend.app.api._agentscope_client", return_value=gateway),
        ):
            result = create_agent_conversation(
                project_id=5,
                payload=AgentConversationInput(
                    conversation_type="initialization",
                ),
                db=database,
                user=user,
            )

        self.assertEqual(result["data"]["id"], 9)
        gateway.get_catalog.assert_not_called()
        gateway.create_session.assert_not_called()
        database.add.assert_not_called()

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
        platform_context = {
            "user_id": "u1",
            "username": "zhangsan",
            "display_name": "张三",
            "project_id": "p2",
            "project_name": "测试项目",
            "conversation_id": "c3",
            "conversation_title": "测试会话",
            "conversation_type": "primary",
            "agent_name": "进度分析师",
        }

        session_id = client.create_session(
            agent=agent,
            workspace_id="platform-u1-p2-c3",
            name="测试会话",
            platform_context=platform_context,
        )

        self.assertEqual(session_id, "session-1")
        create_call, patch_call = client._request.call_args_list
        self.assertEqual(create_call.args, ("POST", "/sessions/"))
        self.assertEqual(
            create_call.kwargs["json"]["knowledge_config"],
            agent["knowledge_config"],
        )
        self.assertEqual(
            create_call.kwargs["json"]["platform_context"],
            platform_context,
        )
        self.assertEqual(
            patch_call.kwargs["json"],
            {
                "permission_mode": "explore",
                "knowledge_config": agent["knowledge_config"],
                "platform_context": platform_context,
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
                side_effect=[0, 1.0],
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
                content_blocks=[
                    {
                        "type": "data",
                        "name": "资料.pdf",
                        "source": {
                            "type": "base64",
                            "data": "ZGF0YQ==",
                            "media_type": "application/pdf",
                        },
                    },
                ],
            )

        self.assertEqual(reply.status, "completed")
        self.assertEqual(reply.content, "处理完成")
        self.assertEqual(reply.message_id, "new")
        self.assertEqual(reply.raw_messages, [finished])
        request_body = client._request.call_args.kwargs["json"]
        self.assertEqual(request_body["input"]["id"], "user-message")
        self.assertEqual(request_body["input"]["metadata"]["source"], "test")
        self.assertEqual(request_body["input"]["content"][0]["text"], "测试")
        self.assertEqual(
            request_body["input"]["content"][1]["name"],
            "资料.pdf",
        )

    def test_team_state_keeps_idle_queued_member_pending(self) -> None:
        client = _client()
        client._request = Mock(  # type: ignore[method-assign]
            return_value={
                "sessions": [
                    {
                        "session": {
                            "id": "leader-session",
                            "team_id": "team-1",
                        },
                        "team": {
                            "team": {
                                "data": {
                                    "work_revision": 2,
                                    "leader_completed_revision": 0,
                                },
                            },
                            "members": [
                                {
                                    "session_id": "worker-session",
                                    "work_revision": 2,
                                    "settled_revision": 1,
                                    "work_status": "queued",
                                },
                            ],
                        },
                    },
                ],
            },
        )

        detail = client.session_team_state_detail(
            "leader-session",
            "leader-agent",
        )

        self.assertTrue(detail.team_exists)
        self.assertTrue(detail.members_pending)
        self.assertTrue(detail.leader_summary_pending)
        self.assertTrue(detail.pending)

    def test_team_remains_pending_until_leader_summarizes(self) -> None:
        client = _client()
        client._request = Mock(  # type: ignore[method-assign]
            return_value={
                "sessions": [
                    {
                        "session": {
                            "id": "leader-session",
                            "team_id": "team-1",
                        },
                        "team": {
                            "team": {
                                "data": {
                                    "work_revision": 3,
                                    "leader_completed_revision": 2,
                                },
                            },
                            "members": [
                                {
                                    "work_revision": 3,
                                    "settled_revision": 3,
                                    "work_status": "reported",
                                },
                            ],
                        },
                    },
                ],
            },
        )

        exists, pending = client.session_team_state(
            "leader-session",
            "leader-agent",
        )

        self.assertTrue(exists)
        self.assertTrue(pending)
        self.assertFalse(
            client.session_team_state_detail(
                "leader-session",
                "leader-agent",
            ).members_pending,
        )
        self.assertTrue(
            client.session_team_work_pending(
                "leader-session",
                "leader-agent",
            ),
        )

    def test_reply_end_is_annotated_while_collaboration_is_pending(
        self,
    ) -> None:
        client = _client()
        client.session_team_work_pending = Mock(  # type: ignore[method-assign]
            return_value=True,
        )

        event = asyncio.run(
            _annotate_collaboration_event(
                client,
                session_id="leader-session",
                agent_id="leader-agent",
                runtime_event={
                    "type": "REPLY_END",
                    "finished_reason": "completed",
                },
            ),
        )

        self.assertTrue(event["platform_collaboration_pending"])

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
                side_effect=[0, 1.0],
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
        self.assertEqual(
            interim["platform_collaboration_status"],
            "continued",
        )

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
                side_effect=[0, 1.0],
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

    def test_chat_has_no_wall_clock_deadline(self) -> None:
        client = _client()
        client._request_timeout = 0.01
        finished = {
            "id": "finished-after-long-run",
            "role": "assistant",
            "finished_at": "2026-07-28T10:30:00+08:00",
            "content": [{"type": "text", "text": "长任务处理完成"}],
        }
        client.list_messages = Mock(  # type: ignore[method-assign]
            side_effect=[
                {"messages": []},
                {"messages": []},
                {"messages": []},
                {"messages": []},
                {"messages": []},
                {"messages": [finished]},
                {"messages": [finished]},
            ],
        )
        client.session_status = Mock(  # type: ignore[method-assign]
            side_effect=["running", "running", "running", "running", "idle", "idle"],
        )
        client.session_team_state = Mock(  # type: ignore[method-assign]
            return_value=(False, False),
        )
        client._request = Mock(return_value={"status": "started"})  # type: ignore[method-assign]

        with (
            patch(
                "backend.app.agentscope_client.time.monotonic",
                side_effect=[0, 10_000],
            ),
            patch("backend.app.agentscope_client.time.sleep"),
        ):
            reply = client.chat(
                agent_id="agent-1",
                session_id="session-1",
                content="执行长任务",
                sender_name="测试用户",
                metadata={},
            )

        self.assertEqual(reply.status, "completed")
        self.assertEqual(reply.message_id, "finished-after-long-run")
        self.assertEqual(reply.content, "长任务处理完成")

    def test_chat_returns_generated_content_with_interrupted_status(
        self,
    ) -> None:
        client = _client()
        interrupted = {
            "id": "interrupted-reply",
            "role": "assistant",
            "finished_at": "2026-07-28T10:00:00+08:00",
            "finished_reason": "interrupted",
            "content": [
                {"type": "text", "text": "已完成的第一段"},
                {
                    "type": "tool_call",
                    "id": "tool-1",
                    "name": "LongTool",
                },
                {"type": "text", "text": "中断前生成的第二段"},
            ],
        }
        client.list_messages = Mock(  # type: ignore[method-assign]
            side_effect=[
                {"messages": []},
                {"messages": [interrupted]},
                {"messages": [interrupted]},
            ],
        )
        client.session_status = Mock(return_value="idle")  # type: ignore[method-assign]
        client.session_team_state = Mock(  # type: ignore[method-assign]
            return_value=(False, False),
        )
        client._request = Mock(return_value={"status": "started"})  # type: ignore[method-assign]

        with (
            patch(
                "backend.app.agentscope_client.time.monotonic",
                side_effect=[0, 1.0],
            ),
            patch("backend.app.agentscope_client.time.sleep"),
        ):
            reply = client.chat(
                agent_id="agent-1",
                session_id="session-1",
                content="执行后停止",
                sender_name="测试用户",
                metadata={},
            )

        self.assertEqual(reply.status, "interrupted")
        self.assertEqual(
            reply.content,
            "已完成的第一段\n中断前生成的第二段",
        )

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
        client.list_messages = Mock(return_value={"messages": []})  # type: ignore[method-assign]
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

    def test_stale_confirmation_is_rejected_before_submission(self) -> None:
        client = _client()
        client.list_messages = Mock(  # type: ignore[method-assign]
            return_value={
                "messages": [
                    {
                        "id": "reply-1",
                        "role": "assistant",
                        "finished_at": "2026-07-30T12:00:00Z",
                        "content": [
                            {
                                "type": "tool_call",
                                "id": "call-1",
                                "name": "PowerShell",
                                "input": "{}",
                                "state": "finished",
                            },
                        ],
                    },
                ],
            },
        )
        client._request = Mock()  # type: ignore[method-assign]

        with self.assertRaises(AgentScopeGatewayError) as raised:
            client.submit_tool_confirmation(
                agent_id="agent-1",
                session_id="session-1",
                reply_id="reply-1",
                tool_call={
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "PowerShell",
                    "input": "{}",
                    "state": "asking",
                },
                confirmed=True,
            )

        self.assertEqual(raised.exception.status_code, 409)
        client._request.assert_not_called()

    def test_confirmation_stream_acknowledges_after_submission_is_accepted(
        self,
    ) -> None:
        class FakeEvents:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def __anext__(self):
                await asyncio.Future()

        conversation = SimpleNamespace(
            id=7,
            agent_id="initializer",
            agentscope_session_id="session-7",
            status="awaiting_permission",
            last_error=None,
            updated_at=None,
        )
        database = Mock()
        gateway = Mock()
        gateway.get_catalog.return_value = {"agents": []}
        gateway.event_stream.return_value = FakeEvents()
        gateway.submit_tool_confirmation.return_value = (
            AgentScopeConfirmationSubmission(
                existing_ids=set(),
                routed_session_id="session-7",
            )
        )
        gateway.wait_for_tool_confirmation.return_value = AgentScopeReply(
            status="running",
            content="正在继续执行。",
            message_id="reply-7",
            raw_message=None,
            projected=True,
        )
        payload = AgentConversationConfirmInput(
            reply_id="reply-7",
            tool_call={
                "type": "tool_call",
                "id": "call-7",
                "name": "PowerShell",
                "input": "{}",
                "state": "asking",
            },
            confirmed=True,
        )

        with (
            patch(
                "backend.app.api._agent_conversation_or_404",
                return_value=conversation,
            ),
            patch(
                "backend.app.api._agentscope_client",
                return_value=gateway,
            ),
            patch("backend.app.api._catalog_agent_for_conversation"),
        ):
            response = stream_agent_conversation_tool_confirmation(
                conversation_id=conversation.id,
                payload=payload,
                db=database,
                user=SimpleNamespace(id=1),
            )

        async def read_first_frame() -> str:
            iterator = response.body_iterator
            frame = await anext(iterator)
            await iterator.aclose()
            return str(frame)

        first_frame = asyncio.run(read_first_frame())

        self.assertIn("event: accepted", first_frame)
        self.assertIn("已允许", first_frame)
        gateway.submit_tool_confirmation.assert_called_once()

    def test_runtime_payload_keeps_all_agent_messages_and_trace(self) -> None:
        first = {
            "id": "reply-1",
            "role": "assistant",
            "content": [{"type": "text", "text": "准备协同"}],
            "created_at": "2026-07-31T10:00:01+08:00",
            "finished_at": "2026-07-31T10:00:03+08:00",
        }
        final = {
            "id": "reply-2",
            "role": "assistant",
            "content": [{"type": "text", "text": "最终结论"}],
            "created_at": "2026-07-31T10:00:08+08:00",
            "finished_at": "2026-07-31T10:00:12+08:00",
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
                "turn_started_at": "2026-07-31T10:00:00+08:00",
            },
        )

        self.assertEqual(payload["agentscope_messages"], [first, final])
        self.assertEqual(
            payload["runtime_trace"]["model_names"],
            ["qwen-plus"],
        )
        self.assertEqual(
            payload["runtime_trace"]["turn_started_at"],
            "2026-07-31T10:00:00+08:00",
        )
        self.assertEqual(
            payload["runtime_trace"]["turn_finished_at"],
            "2026-07-31T10:00:12+08:00",
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

    def test_interrupted_reply_preserves_every_generated_text_block(
        self,
    ) -> None:
        messages = [
            {
                "id": "reply-interrupted",
                "role": "assistant",
                "finished_at": "2026-07-30T10:00:00+08:00",
                "finished_reason": "interrupted",
                "content": [
                    {"type": "text", "text": "已经完成第一部分"},
                    {
                        "type": "tool_call",
                        "id": "tool-1",
                        "name": "LongTool",
                    },
                    {"type": "text", "text": "中断前生成的第二部分"},
                ],
            },
        ]

        reply = _agentscope_reply_from_group(messages, "idle")

        self.assertEqual(reply.status, "interrupted")
        self.assertEqual(
            reply.content,
            "已经完成第一部分\n中断前生成的第二部分",
        )
        self.assertEqual(reply.raw_messages, messages)

    def test_assistant_messages_are_grouped_by_user_turn(self) -> None:
        first = {"id": "a-1", "role": "assistant", "content": []}
        follow_up = {"id": "a-2", "role": "assistant", "content": []}
        final = {"id": "a-3", "role": "assistant", "content": []}

        groups = _agentscope_assistant_groups(
            [
                {"id": "u-1", "role": "user", "content": []},
                first,
                follow_up,
                {"id": "u-2", "role": "user", "content": []},
                final,
            ],
        )

        self.assertEqual(groups, [[first, follow_up], [final]])

    def test_complete_history_is_loaded_page_by_page(self) -> None:
        client = _client()
        client.list_messages = Mock(  # type: ignore[method-assign]
            side_effect=[
                {
                    "messages": [
                        {"id": "message-3"},
                        {"id": "message-4"},
                    ],
                    "is_running": True,
                    "has_more": True,
                },
                {
                    "messages": [
                        {"id": "message-1"},
                        {"id": "message-2"},
                    ],
                    "is_running": False,
                    "has_more": False,
                },
            ],
        )

        result = client.list_all_messages("session-1", "agent-1")

        self.assertEqual(
            [item["id"] for item in result["messages"]],
            ["message-1", "message-2", "message-3", "message-4"],
        )
        self.assertTrue(result["is_running"])
        client.list_messages.assert_any_call(
            "session-1",
            "agent-1",
            before="message-3",
        )

    def test_message_metadata_is_updated_in_agentscope(self) -> None:
        client = _client()
        client._request = Mock(  # type: ignore[method-assign]
            return_value={"id": "reply-1", "metadata": {"status": "done"}},
        )

        result = client.update_message_metadata(
            "session-1",
            "agent-1",
            "reply-1",
            {"status": "done"},
        )

        self.assertEqual(result["metadata"], {"status": "done"})
        client._request.assert_called_once_with(
            "PATCH",
            "/sessions/session-1/messages/reply-1/metadata",
            params={"agent_id": "agent-1"},
            json={"metadata": {"status": "done"}},
        )

    def test_user_message_projection_uses_agentscope_metadata(self) -> None:
        projected = _project_agentscope_user_message(
            7,
            {
                "id": "user-1",
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "<platform-context>内部上下文</platform-context>"
                            "<user-request>请分析附件</user-request>"
                        ),
                    },
                ],
                "metadata": {
                    "platform_display_content": "请分析附件",
                },
                "created_at": "2026-07-31T10:00:00+08:00",
            },
        )

        self.assertEqual(projected["id"], "user-1")
        self.assertEqual(projected["content"], "请分析附件")
        self.assertEqual(projected["extra_data"]["initialization_files"], [])

    def test_agentscope_history_projects_one_platform_turn(self) -> None:
        messages = [
            {
                "id": "user-1",
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "<user-request>开始初始化</user-request>",
                    },
                ],
                "metadata": {},
            },
            {
                "id": "assistant-interim",
                "role": "assistant",
                "content": [{"type": "text", "text": "等待专家"}],
                "finished_at": "2026-07-31T10:00:01+08:00",
            },
            {
                "id": "assistant-final",
                "role": "assistant",
                "content": [{"type": "text", "text": "初始化完成"}],
                "finished_at": "2026-07-31T10:00:02+08:00",
                "metadata": {
                    "platform_status": "completed",
                    "platform_runtime_trace": {"team_update_count": 2},
                    "platform_collaboration_statuses": {
                        "assistant-interim": "continued",
                    },
                },
            },
        ]

        projected = _agentscope_platform_messages(7, messages, "idle")

        self.assertEqual(len(projected), 2)
        self.assertEqual(projected[0]["content"], "开始初始化")
        self.assertEqual(projected[1]["content"], "初始化完成")
        self.assertEqual(
            projected[1]["extra_data"]["agentscope_messages"][0][
                "platform_collaboration_status"
            ],
            "continued",
        )
        self.assertEqual(
            projected[1]["extra_data"]["runtime_trace"],
            {"team_update_count": 2},
        )

    def test_latest_interim_reply_remains_running(self) -> None:
        projected = _agentscope_platform_messages(
            7,
            [
                {
                    "id": "user-1",
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "<user-request>协同处理</user-request>",
                        },
                    ],
                },
                {
                    "id": "assistant-interim",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "等待成员汇报"}],
                    "finished_at": "2026-07-31T10:00:01+08:00",
                },
            ],
            "running",
        )

        self.assertEqual(
            projected[-1]["extra_data"]["status"],
            "running",
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
