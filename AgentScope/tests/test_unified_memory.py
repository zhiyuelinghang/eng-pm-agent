from __future__ import annotations

import math
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock

from agentscope.app.memory._middleware import DobbyMemoryMiddleware
from agentscope.app.memory._config import MemorySettings
from agentscope.app.memory._embedding import HashEmbedding
from agentscope.app.memory._runtime import (
    MemoryRuntime,
    MemoryScope,
    ScopedMemoryClient,
)
from agentscope.event import ReplyStartEvent
from agentscope.message import AssistantMsg, UserMsg
from mem0.configs.embeddings.base import BaseEmbedderConfig


class MemoryConfigurationTest(TestCase):
    def test_mem0_url_pins_memory_search_path(self) -> None:
        settings = MemorySettings(
            database_url="postgresql://user:password@localhost/projectcopilot",
        )

        rendered = settings.mem0_connection_string()

        self.assertIn("projectcopilot", rendered)
        self.assertIn("options=", rendered)
        self.assertIn("memory", rendered)

    def test_project_scope_is_shared_by_users_but_not_projects(self) -> None:
        settings = MemorySettings(
            database_url="postgresql://user:password@localhost/projectcopilot",
        )
        runtime = MemoryRuntime(settings)

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
        self.assertNotIn(":", first.scope_key)

    def test_hash_embedding_is_stable_and_normalized(self) -> None:
        embedding = HashEmbedding(BaseEmbedderConfig(embedding_dims=128))

        first = embedding.embed("基坑临边防护栏杆整改", "add")
        second = embedding.embed("基坑临边防护栏杆整改", "search")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 128)
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in first)),
            1.0,
        )


class ScopedMemoryClientTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = MemorySettings(
            database_url="postgresql://user:password@localhost/projectcopilot",
            infer_enabled=False,
        )
        self.scope = MemoryScope(
            tenant_id="tenant-a",
            project_id="7",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
            scope_key="scope_safe",
        )
        self.inner = SimpleNamespace(
            embedding_model=SimpleNamespace(
                embed=MagicMock(return_value=[1.0, 0.0]),
            ),
            search=AsyncMock(
                return_value={
                    "results": [
                        {"id": "b6891879-18cd-4cfb-a62b-992ddde50c31"},
                    ],
                },
            ),
            add=AsyncMock(
                return_value={
                    "results": [
                        {"id": "b6891879-18cd-4cfb-a62b-992ddde50c31"},
                    ],
                },
            ),
        )
        self.audit = MagicMock()
        self.audit.search_experiences.return_value = []
        self.client = ScopedMemoryClient(
            self.inner,
            self.settings,
            self.scope,
            self.audit,
        )

    async def test_search_overrides_caller_scope(self) -> None:
        await self.client.search(
            "基坑",
            filters={"user_id": "attacker", "custom": "value"},
            top_k=3,
        )

        filters = self.inner.search.await_args.kwargs["filters"]
        self.assertEqual(filters["user_id"], "scope_safe")
        self.assertEqual(filters["agent_id"], "scope_safe")
        self.assertEqual(filters["tenant_id"], "tenant-a")
        self.assertEqual(filters["project_id"], "7")
        self.assertEqual(filters["custom"], "value")

    async def test_add_forces_scope_metadata_and_raw_write(self) -> None:
        await self.client.add(
            [{"role": "user", "content": "记住整改要求"}],
            user_id="attacker",
            agent_id="attacker",
        )

        kwargs = self.inner.add.await_args.kwargs
        self.assertEqual(kwargs["user_id"], "scope_safe")
        self.assertEqual(kwargs["agent_id"], "scope_safe")
        self.assertFalse(kwargs["infer"])
        self.assertEqual(kwargs["metadata"]["tenant_id"], "tenant-a")
        self.assertEqual(kwargs["metadata"]["project_id"], "7")
        self.assertEqual(kwargs["metadata"]["source_session_id"], "session-a")


class DobbyMemoryMiddlewareTest(IsolatedAsyncioTestCase):
    async def test_recall_hint_is_removed_after_the_turn(self) -> None:
        scope = MemoryScope(
            tenant_id="tenant-a",
            project_id="7",
            platform_user_id="2",
            agent_id="agent-a",
            session_id="session-a",
            scope_key="scope_safe",
        )
        runtime = SimpleNamespace(
            settings=SimpleNamespace(top_k=3, threshold=0.2),
            scoped_client=MagicMock(
                return_value=SimpleNamespace(
                    search=AsyncMock(),
                    add=AsyncMock(),
                ),
            ),
        )
        middleware = DobbyMemoryMiddleware(runtime, scope)
        middleware._async_search = AsyncMock(
            return_value=["项目已经决定统一使用 PostgreSQL。"],
        )
        middleware._dispatch_write = AsyncMock()

        user_message = UserMsg(name="user", content="数据库采用什么方案？")
        agent = SimpleNamespace(
            state=SimpleNamespace(context=[user_message]),
        )

        async def next_handler(**_kwargs):
            yield ReplyStartEvent(
                session_id="session-a",
                reply_id="reply-a",
                name="agent-a",
            )
            yield AssistantMsg(
                name="agent-a",
                content="统一使用 PostgreSQL。",
            )

        stream = middleware.on_reply(
            agent,
            {"inputs": user_message},
            next_handler,
        )
        first_event = await anext(stream)
        self.assertIsInstance(first_event, ReplyStartEvent)
        self.assertEqual(len(agent.state.context), 2)
        self.assertIn(
            "项目已经决定统一使用 PostgreSQL",
            agent.state.context[-1].content[0].hint,
        )

        final_message = await anext(stream)
        self.assertEqual(final_message.role, "assistant")
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)

        self.assertEqual(agent.state.context, [user_message])
        middleware._dispatch_write.assert_awaited_once_with(
            [
                {"role": "user", "content": "数据库采用什么方案？"},
                {"role": "assistant", "content": "统一使用 PostgreSQL。"},
            ],
            user_id="scope_safe",
            agent_id="scope_safe",
        )
