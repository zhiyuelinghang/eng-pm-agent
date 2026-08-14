from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from agentscope.app.memory._model import (
    build_memory_model_runtime_config,
    configure_platform_memory_model,
)
from agentscope.app.memory._middleware import DobbyMemoryMiddleware
from agentscope.app.memory._runtime import MemoryRuntime, MemoryScope
from agentscope.app.storage import ChatModelConfig, MemorySettingsData
from agentscope.credential import CustomOpenAICredential
from agentscope.event import ReplyEndEvent, ReplyStartEvent
from agentscope.message import AssistantMsg, SystemMsg, UserMsg
from utils import langgraph_utils


class MemoryScopeTest(TestCase):
    def test_project_scope_is_shared_by_users_but_not_projects(self) -> None:
        runtime = MemoryRuntime(tenant_id="tenant-a")

        first = runtime.scope(
            project_id="7",
            platform_user_id="1",
            agent_id="agent-a",
            session_id="session-a",
        )
        second = runtime.scope(
            project_id="7",
            platform_user_id="2",
            agent_id="agent-b",
            session_id="session-b",
        )
        other = runtime.scope(
            project_id="8",
            platform_user_id="1",
            agent_id="agent-a",
            session_id="session-c",
        )

        self.assertEqual(first.scope_key, second.scope_key)
        self.assertNotEqual(first.scope_key, other.scope_key)
        self.assertEqual(first.scope_key, "project_7")
        self.assertNotIn(":", first.scope_key)

    def test_platform_model_is_translated_for_all_memory_clients(self) -> None:
        config = ChatModelConfig(
            type="custom_openai_credential",
            credential_id="credential-memory",
            model="memory-fast",
            parameters={"temperature": 0.2},
        )
        runtime = build_memory_model_runtime_config(
            config,
            CustomOpenAICredential(
                id="credential-memory",
                api_key="secret",
                base_url="https://models.example.com/v1",
            ),
            context_size=131_072,
        )

        self.assertEqual(runtime.mem0_llm["provider"], "openai")
        self.assertEqual(
            runtime.mem0_llm["config"]["openai_base_url"],
            "https://models.example.com/v1",
        )
        self.assertEqual(runtime.graph_llm["model"], "memory-fast")
        self.assertEqual(runtime.context_size, 131_072)

    def test_management_memory_is_user_private(self) -> None:
        runtime = MemoryRuntime(tenant_id="tenant-a")
        first = runtime.scope(
            project_id=None,
            platform_user_id="user:1",
            agent_id="agent-a",
            session_id="session-a",
        )
        second = runtime.scope(
            project_id=None,
            platform_user_id="user:2",
            agent_id="agent-a",
            session_id="session-b",
        )
        self.assertNotEqual(first.scope_key, second.scope_key)
        self.assertNotIn(":", first.scope_key)


class MemoryModelConfigurationTest(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        langgraph_utils.configure_runtime_memory_model(
            signature="environment",
        )

    async def test_saved_selection_activates_all_runtime_model_paths(self) -> None:
        config = ChatModelConfig(
            type="custom_openai_credential",
            credential_id="credential-memory",
            model="memory-fast",
            parameters={"temperature": 0.2},
        )
        settings = MemorySettingsData(memory_model_config=config)
        access = SimpleNamespace(
            resolve_credential=AsyncMock(
                return_value=SimpleNamespace(
                    data={
                        "type": "custom_openai_credential",
                        "id": "credential-memory",
                        "name": "记忆模型",
                        "api_key": "secret",
                        "base_url": "https://models.example.com/v1",
                    },
                ),
            ),
        )
        selected_model = object()
        model_card = SimpleNamespace(
            name="memory-fast",
            enabled=True,
            context_size=131_072,
        )

        with (
            patch(
                "agentscope.app._service.build_credential_model_catalog",
                return_value=[model_card],
            ),
            patch(
                "agentscope.app._service.get_model",
                AsyncMock(return_value=selected_model),
            ),
        ):
            changed = await configure_platform_memory_model(
                "default",
                settings,
                access,
            )
            resolved = await langgraph_utils._resolve_model("compress")

        self.assertTrue(changed)
        self.assertIs(resolved, selected_model)
        self.assertEqual(
            langgraph_utils._build_mem0_config().llm.config["model"],
            "memory-fast",
        )
        self.assertEqual(
            langgraph_utils.get_runtime_graph_llm_config()["model"],
            "memory-fast",
        )


class DobbyMemoryMiddlewareTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.scope = MemoryScope(
            tenant_id="tenant-a",
            project_id="7",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
            scope_key="project_7",
        )
        self.manager = SimpleNamespace(
            start_session=AsyncMock(
                return_value={
                    "thread_id": "session-a",
                    "project_id": "project_7",
                    "current_role": "agent-a",
                    "messages": [],
                    "summary": "",
                    "tasks": {},
                },
            ),
            assemble_context=AsyncMock(
                return_value=SimpleNamespace(
                    messages=[
                        SystemMsg("system", "平台系统提示"),
                        SystemMsg(
                            "system",
                            "<system-reminder>原版五源融合结果</system-reminder>",
                        ),
                        UserMsg("user", "数据库采用什么方案？"),
                    ],
                    mode_used="standard",
                    token_estimate=128,
                    budget_warnings=[],
                ),
            ),
            remember=AsyncMock(return_value=[]),
            compress_if_needed=AsyncMock(return_value=False),
            end_session=AsyncMock(return_value={}),
        )
        runtime = SimpleNamespace(manager=MagicMock(return_value=self.manager))
        self.middleware = DobbyMemoryMiddleware(runtime, self.scope)

    @staticmethod
    def _agent() -> SimpleNamespace:
        return SimpleNamespace(
            _system_prompt="平台系统提示",
            model=SimpleNamespace(context_size=131_072),
            state=SimpleNamespace(
                summary="",
                context=[],
                middle_context={},
                tasks_context=SimpleNamespace(tasks=[]),
            ),
        )

    async def test_exposes_all_six_upstream_tools(self) -> None:
        tools = await self.middleware.list_tools()
        self.assertEqual(
            [tool.name for tool in tools],
            [
                "search_memory",
                "add_memory",
                "search_knowledge_base",
                "search_experiences",
                "get_session_summary",
                "search_graph_rag",
            ],
        )

    async def test_context_layers_are_injected_then_removed(self) -> None:
        agent = self._agent()
        self.middleware._record_completed_turn = AsyncMock()
        user_message = UserMsg("user", "数据库采用什么方案？")
        assistant_message = AssistantMsg("agent-a", "统一使用 PostgreSQL。")

        async def next_handler(**_kwargs):
            agent.state.context.append(user_message)
            yield ReplyStartEvent(
                session_id="session-a",
                reply_id="reply-a",
                name="agent-a",
            )
            agent.state.context.append(assistant_message)
            yield assistant_message

        stream = self.middleware.on_reply(
            agent,
            {"inputs": user_message},
            next_handler,
        )
        first_event = await anext(stream)
        self.assertIsInstance(first_event, ReplyStartEvent)
        self.assertEqual(len(agent.state.context), 2)
        self.assertIn(
            "原版五源融合结果",
            agent.state.context[-1].get_text_content() or "",
        )

        await anext(stream)
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)

        self.assertEqual(agent.state.context, [user_message, assistant_message])
        self.manager.assemble_context.assert_awaited_once()
        self.middleware._record_completed_turn.assert_awaited_once()
        self.assertIn("dobby_memory_state", agent.state.middle_context)

    async def test_reply_end_waits_until_memory_state_is_persisted(self) -> None:
        agent = self._agent()
        user_message = UserMsg("user", "数据库采用什么方案？")
        assistant_message = AssistantMsg("agent-a", "统一使用 PostgreSQL。")
        record_started = asyncio.Event()
        allow_record_to_finish = asyncio.Event()

        async def record_turn(*_args, **_kwargs) -> None:
            record_started.set()
            await allow_record_to_finish.wait()

        self.middleware._record_completed_turn = AsyncMock(side_effect=record_turn)

        async def next_handler(**_kwargs):
            agent.state.context.append(user_message)
            yield ReplyStartEvent(
                session_id="session-a",
                reply_id="reply-a",
                name="agent-a",
            )
            yield ReplyEndEvent(
                session_id="session-a",
                reply_id="reply-a",
            )
            agent.state.context.append(assistant_message)
            yield assistant_message

        stream = self.middleware.on_reply(
            agent,
            {"inputs": user_message},
            next_handler,
        )

        self.assertIsInstance(await anext(stream), ReplyStartEvent)
        self.assertIs(await anext(stream), assistant_message)

        terminal_task = asyncio.create_task(anext(stream))
        await record_started.wait()
        await asyncio.sleep(0)
        self.assertFalse(terminal_task.done())

        allow_record_to_finish.set()
        terminal_event = await terminal_task
        self.assertIsInstance(terminal_event, ReplyEndEvent)
        self.assertIn("dobby_memory_state", agent.state.middle_context)
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)

    async def test_persisted_session_calls_upstream_end_session(self) -> None:
        agent = self._agent()
        agent.state.middle_context["dobby_memory_state"] = {
            "thread_id": "session-a",
            "project_id": "project_7",
            "current_role": "agent-a",
            "messages": [],
        }

        await self.middleware.end_persisted_session(agent.state)

        self.manager.end_session.assert_awaited_once()

    async def test_dobby_compression_is_authoritative_and_model_sized(self) -> None:
        agent = self._agent()
        next_handler = AsyncMock()

        await self.middleware.on_compress_context(agent, {}, next_handler)

        next_handler.assert_not_awaited()
        state = self.manager.compress_if_needed.await_args.args[0]
        self.assertEqual(state["max_token_budget"], 131_072)
        self.assertEqual(state["compression_trigger_ratio"], 0.8)
        self.assertIn("call_model", self.manager.compress_if_needed.await_args.kwargs)

    async def test_compression_prefers_configured_memory_model(self) -> None:
        agent = self._agent()
        expected = AssistantMsg("assistant", "专用模型摘要")
        memory_call = AsyncMock(return_value=expected)

        with (
            patch(
                "utils.langgraph_utils.has_runtime_memory_model",
                return_value=True,
            ),
            patch("utils.langgraph_utils._call_model", memory_call),
        ):
            result = await self.middleware._call_agent_model(
                agent,
                [UserMsg("user", "需要压缩的内容")],
            )

        self.assertIs(result, expected)
        memory_call.assert_awaited_once()
        self.assertEqual(memory_call.await_args.kwargs["intent"], "compress")
