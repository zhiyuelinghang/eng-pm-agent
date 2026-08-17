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
from agentscope.app.memory._scope_router import route_memory_content
from agentscope.app.storage import ChatModelConfig, MemorySettingsData
from agentscope.app.storage._model._platform_settings import (
    DEFAULT_MEMORY_SCOPE_PROMPT,
)
from agentscope.credential import CustomOpenAICredential
from agentscope.event import ReplyEndEvent, ReplyStartEvent
from agentscope.message import AssistantMsg, SystemMsg, UserMsg
from utils import langgraph_utils
from utils.memory_manager import MemoryManager


class MemoryScopeTest(TestCase):
    def test_project_resources_are_shared_but_personal_memory_is_isolated(self) -> None:
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
        self.assertNotEqual(first.memory_owner_key, second.memory_owner_key)
        self.assertEqual(
            first.memory_target("user").agent_id,
            second.memory_target("user").agent_id,
        )
        self.assertNotEqual(
            first.memory_target("user").user_id,
            second.memory_target("user").user_id,
        )
        self.assertEqual(
            first.memory_target("user").user_id,
            other.memory_target("user").user_id,
        )
        self.assertNotEqual(
            first.memory_target("user_project").agent_id,
            other.memory_target("user_project").agent_id,
        )

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


class MemoryScopeRouterTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.scope = MemoryRuntime(tenant_id="tenant-a").scope(
            project_id="7",
            project_name="机场改造",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
        )

    async def test_classifier_can_split_global_and_project_facts(self) -> None:
        call_model = AsyncMock(
            return_value=AssistantMsg(
                "assistant",
                '{"user":[{"content":"我长期偏好中文",'
                '"evidence":"我长期偏好中文","stable":true,'
                '"confidence":0.98}],'
                '"user_project":["本项目使用 PostgreSQL"]}',
            ),
        )

        routed = await route_memory_content(
            content="我长期偏好中文，本项目使用 PostgreSQL。",
            scope=self.scope,
            prompt_template=DEFAULT_MEMORY_SCOPE_PROMPT,
            call_model=call_model,
        )

        self.assertEqual(
            [(item.scope_type, item.content) for item in routed],
            [
                ("user", "我长期偏好中文"),
                ("user_project", "本项目使用 PostgreSQL"),
            ],
        )
        rendered = call_model.await_args.args[0][-1].get_text_content()
        self.assertIn("机场改造", rendered)

    async def test_invalid_classifier_output_falls_back_to_user_project(self) -> None:
        routed = await route_memory_content(
            content="以后就按这个来。",
            scope=self.scope,
            prompt_template=DEFAULT_MEMORY_SCOPE_PROMPT,
            call_model=AsyncMock(return_value=AssistantMsg("assistant", "不确定")),
        )

        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0].scope_type, "user_project")
        self.assertEqual(routed[0].content, "以后就按这个来。")

    async def test_unverified_user_classification_is_downgraded(self) -> None:
        routed = await route_memory_content(
            content="这次请用中文。",
            scope=self.scope,
            prompt_template=DEFAULT_MEMORY_SCOPE_PROMPT,
            call_model=AsyncMock(
                return_value=AssistantMsg(
                    "assistant",
                    '{"user":[{"content":"用户永远偏好中文",'
                    '"evidence":"并不存在的原文","stable":true,'
                    '"confidence":0.99}],"user_project":[]}',
                ),
            ),
        )

        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0].scope_type, "user_project")
        self.assertEqual(routed[0].content, "这次请用中文。")


class MemoryManagerScopeTest(IsolatedAsyncioTestCase):
    async def test_weknora_search_preserves_documented_source_metadata(
        self,
    ) -> None:
        manager = MemoryManager(project_id="project_7", role_id="agent-a")
        client = SimpleNamespace(
            hybrid_search=MagicMock(
                return_value=[
                    {
                        "knowledge_id": "knowledge-1",
                        "knowledge_title": "VPN 配置手册",
                        "knowledge_filename": "vpn-guide.pdf",
                        "content": "VPN 连接配置步骤",
                        "score": 0.92,
                    },
                ],
            ),
            get_knowledge_batch=MagicMock(
                return_value=[
                    {
                        "id": "knowledge-1",
                        "title": "VPN 配置手册",
                        "file_name": "vpn-guide.pdf",
                        "file_type": "pdf",
                        "file_size": 2048000,
                        "source": "",
                    },
                ],
            ),
        )

        with (
            patch("utils.memory_manager._cfg.WEKNORA_ENABLED", True),
            patch(
                "utils.memory_manager._build_weknora_client",
                return_value=client,
            ),
            patch(
                "utils.memory_manager._get_kb_id_by_name",
                return_value="kb-001",
            ),
        ):
            results = await manager.search_knowledge(
                "如何配置 VPN？",
                top_k=2,
                kb_names=["工程规范"],
            )

        client.hybrid_search.assert_called_once_with(
            kb_id="kb-001",
            query="如何配置 VPN？",
            vector_threshold=0.5,
            keyword_threshold=0.3,
            match_count=2,
        )
        client.get_knowledge_batch.assert_called_once_with(["knowledge-1"])
        self.assertEqual(results[0]["title"], "VPN 配置手册")
        self.assertEqual(results[0]["file_name"], "vpn-guide.pdf")
        self.assertEqual(results[0]["file_type"], "pdf")
        self.assertEqual(results[0]["file_size"], 2048000)

    async def test_recall_queries_only_global_and_current_project_targets(self) -> None:
        scope = MemoryRuntime(tenant_id="tenant-a").scope(
            project_id="7",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
        )
        manager = MemoryManager(project_id=scope.scope_key, role_id="agent-a")

        async def recall(_query, *, top_k, user_id, agent_id):
            self.assertEqual(top_k, 3)
            if agent_id == "memory_v2_user":
                return [{"id": "global", "memory": "跨项目偏好", "score": 0.8}]
            return [{"id": "project", "memory": "项目约定", "score": 0.9}]

        manager.recall = AsyncMock(side_effect=recall)
        results = await manager.recall_scopes(
            "之前怎么约定的？",
            [target.as_dict() for target in scope.memory_targets],
            top_k=3,
        )

        self.assertEqual(manager.recall.await_count, 2)
        self.assertEqual([item["id"] for item in results], ["project", "global"])
        self.assertEqual(results[0]["scope_type"], "user_project")
        self.assertEqual(results[1]["scope_type"], "user")

    async def test_session_lifecycle_uses_exact_target_filters(self) -> None:
        scope = MemoryRuntime(tenant_id="tenant-a").scope(
            project_id="7",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
        )
        manager = MemoryManager(project_id=scope.scope_key, role_id="agent-a")
        decay = AsyncMock(return_value={"pruned": 0, "updated": 1, "scanned": 1})
        reflect = AsyncMock(return_value={"skipped": True})
        audit = SimpleNamespace(log_session_end=AsyncMock())

        with (
            patch("utils.memory_manager.apply_decay", decay),
            patch("utils.memory_manager.reflect_if_needed", reflect),
            patch("utils.memory_manager.get_audit_logger", return_value=audit),
            patch("utils.memory_manager._cfg.EXPERIENCE_EVENT_DRIVEN_ENABLED", False),
        ):
            await manager.end_session({
                "project_id": scope.scope_key,
                "thread_id": scope.session_id,
                "memory_targets": [
                    target.as_dict()
                    for target in scope.memory_targets
                ],
                "tasks": {},
                "messages": [],
            })

        self.assertEqual(decay.await_count, 2)
        for target, call in zip(scope.memory_targets, decay.await_args_list):
            self.assertEqual(call.kwargs["user_id"], target.user_id)
            self.assertEqual(call.kwargs["agent_id"], target.agent_id)
            self.assertTrue(call.args[0].startswith("memory_scope_"))
        for target, call in zip(scope.memory_targets, reflect.await_args_list):
            self.assertEqual(call.kwargs["user_id"], target.user_id)
            self.assertEqual(call.kwargs["agent_id"], target.agent_id)


class DobbyMemoryMiddlewareTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.scope = MemoryRuntime(tenant_id="tenant-a").scope(
            project_id="7",
            project_name="机场改造",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
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
            recall_scopes=AsyncMock(return_value=[]),
            compress_if_needed=AsyncMock(return_value=False),
            end_session=AsyncMock(return_value={}),
        )
        runtime = SimpleNamespace(manager=MagicMock(return_value=self.manager))
        self.middleware = DobbyMemoryMiddleware(
            runtime,
            self.scope,
            MemorySettingsData(),
        )

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
        persisted = agent.state.middle_context["dobby_memory_state"]
        self.assertEqual(
            [item["scope_type"] for item in persisted["memory_targets"]],
            ["user", "user_project"],
        )

    async def test_completed_turn_is_split_into_explicit_personal_scopes(self) -> None:
        agent = self._agent()
        self.middleware._call_agent_model = AsyncMock(
            return_value=AssistantMsg(
                "assistant",
                '{"user":[{"content":"我一直使用中文",'
                '"evidence":"我一直使用中文","stable":true,'
                '"confidence":0.98}],'
                '"user_project":["本项目统一使用 PostgreSQL"]}',
            ),
        )
        self.manager.remember.return_value = [{"id": "memory-a"}]

        stored = await self.middleware._remember_routed(
            agent,
            "我一直使用中文，本项目统一使用 PostgreSQL。",
            importance=0.5,
            memory_type="interaction",
            source="conversation",
        )

        self.assertEqual(stored, 2)
        self.assertEqual(self.manager.remember.await_count, 2)
        calls = self.manager.remember.await_args_list
        self.assertEqual(calls[0].kwargs["agent_id"], "memory_v2_user")
        self.assertIn("memory_v2_user_project_7", calls[1].kwargs["agent_id"])
        self.assertEqual(calls[0].kwargs["metadata"]["scope_type"], "user")
        self.assertEqual(
            calls[1].kwargs["metadata"]["scope_type"],
            "user_project",
        )

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
