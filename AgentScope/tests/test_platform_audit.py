"""Regression tests for the read-only platform interaction audit."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException

from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._platform_audit import (
    get_platform_audit_messages,
    list_platform_audit_tree,
)
from agentscope.app._router._workspace import _resolve_workspace
from agentscope.app._session_access import (
    require_runtime_session_access,
    runtime_session_visible,
)
from agentscope.app.storage import (
    AsyncSQLAlchemyStorage,
    PlatformSessionContext,
    SessionConfig,
    SessionRecord,
    SessionSource,
)
from agentscope.message import AssistantMsg, UserMsg


def _platform_session(
    *,
    session_id: str,
    platform_user_id: str = "7",
    username: str = "zhangsan",
    display_name: str = "张三",
    project_id: str = "12",
    project_name: str = "测试工程",
    session_role: str = "primary",
) -> SessionRecord:
    return SessionRecord(
        id=session_id,
        user_id="default",
        agent_id="agent-1",
        source=SessionSource.PLATFORM,
        config=SessionConfig(
            workspace_id=f"workspace-{session_id}",
            name="工程资料问答",
            platform_context=PlatformSessionContext(
                user_id=platform_user_id,
                username=username,
                display_name=display_name,
                project_id=project_id,
                project_name=project_name,
                conversation_id=f"conversation-{session_id}",
                conversation_title="工程资料问答",
                conversation_type="business",
                agent_name="工程资料助手",
                session_role=session_role,
                root_session_id=(
                    "session-primary"
                    if session_role == "worker"
                    else None
                ),
            ),
        ),
    )


class PlatformSessionBoundaryTest(IsolatedAsyncioTestCase):
    """Management and service callers must not share interactive sessions."""

    def test_interactive_visibility_is_separated_by_source(self) -> None:
        platform_session = _platform_session(session_id="platform-session")
        management_session = SessionRecord(
            id="management-session",
            user_id="default",
            agent_id="agent-1",
            config=SessionConfig(workspace_id="management-workspace"),
        )
        management = AgentScopePrincipal(
            kind="management",
            subject="admin",
        )
        service = AgentScopePrincipal(kind="service", subject="platform")
        legacy = AgentScopePrincipal(kind="legacy", subject="admin")

        self.assertFalse(
            runtime_session_visible(management, platform_session),
        )
        self.assertFalse(runtime_session_visible(legacy, platform_session))
        self.assertTrue(runtime_session_visible(service, platform_session))
        self.assertTrue(
            runtime_session_visible(management, management_session),
        )
        self.assertFalse(
            runtime_session_visible(service, management_session),
        )

        with self.assertRaises(HTTPException) as raised:
            require_runtime_session_access(management, platform_session)
        self.assertEqual(raised.exception.status_code, 403)

    async def test_management_cannot_reach_platform_workspace(self) -> None:
        platform_session = _platform_session(
            session_id="platform-session",
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(return_value=platform_session),
        )
        workspace_manager = SimpleNamespace(
            get_workspace=AsyncMock(return_value=object()),
        )

        with self.assertRaises(HTTPException) as raised:
            await _resolve_workspace(
                "default",
                platform_session.agent_id,
                platform_session.id,
                storage,
                workspace_manager,
                AgentScopePrincipal(
                    kind="management",
                    subject="admin",
                ),
            )

        self.assertEqual(raised.exception.status_code, 403)
        workspace_manager.get_workspace.assert_not_awaited()


class PlatformAuditRouterTest(IsolatedAsyncioTestCase):
    """The audit tree groups primary sessions and loads full transcripts."""

    async def test_tree_groups_by_platform_user_and_project(self) -> None:
        primary = _platform_session(session_id="session-primary")
        worker = _platform_session(
            session_id="session-worker",
            session_role="worker",
        )
        management_session = SessionRecord(
            id="session-management",
            user_id="default",
            agent_id="agent-1",
            config=SessionConfig(workspace_id="management-workspace"),
        )
        storage = SimpleNamespace(
            list_all_sessions=AsyncMock(
                return_value=[management_session, worker, primary],
            ),
        )
        message_bus = SimpleNamespace(
            is_locked=AsyncMock(return_value=True),
        )

        result = await list_platform_audit_tree(
            user_id="default",
            principal=AgentScopePrincipal(
                kind="management",
                subject="admin",
            ),
            storage=storage,
            message_bus=message_bus,
        )

        self.assertEqual(result.total_conversations, 1)
        self.assertEqual(len(result.users), 1)
        self.assertEqual(result.users[0].display_name, "张三")
        self.assertEqual(result.users[0].projects[0].project_name, "测试工程")
        conversations = result.users[0].projects[0].conversations
        self.assertEqual([item.session_id for item in conversations], [
            "session-primary",
        ])
        self.assertTrue(conversations[0].is_running)

    async def test_selected_conversation_returns_complete_history(self) -> None:
        session = _platform_session(session_id="session-primary")
        oldest = UserMsg(
            id="message-1",
            name="平台用户",
            content="<platform-context>内部上下文</platform-context>",
            metadata={
                "platform_display_content": "请分析项目风险",
            },
        )
        middle = AssistantMsg(
            id="message-2",
            name="工程资料助手",
            content="正在分析。",
        )
        newest = AssistantMsg(
            id="message-3",
            name="工程资料助手",
            content="分析完成。",
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            list_messages=AsyncMock(
                side_effect=[
                    ([middle, newest], True),
                    ([oldest], False),
                ],
            ),
        )
        message_bus = SimpleNamespace(
            is_locked=AsyncMock(return_value=False),
        )

        result = await get_platform_audit_messages(
            session_id=session.id,
            user_id="default",
            principal=AgentScopePrincipal(
                kind="management",
                subject="admin",
            ),
            storage=storage,
            message_bus=message_bus,
        )

        self.assertEqual(
            [message["id"] for message in result.messages],
            ["message-1", "message-2", "message-3"],
        )
        self.assertEqual(
            result.messages[0]["content"][0]["text"],
            "请分析项目风险",
        )
        self.assertFalse(result.is_running)
        self.assertEqual(storage.list_messages.await_count, 2)

    async def test_platform_source_and_context_round_trip_through_sqlite(
        self,
    ) -> None:
        storage = AsyncSQLAlchemyStorage(
            "sqlite+aiosqlite:///:memory:",
            create_tables=True,
        )
        context = _platform_session(
            session_id="session-primary",
        ).config.platform_context
        assert context is not None

        async with storage:
            saved = await storage.upsert_session(
                user_id="default",
                agent_id="agent-1",
                config=SessionConfig(
                    workspace_id="platform-workspace",
                    platform_context=context,
                ),
                source=SessionSource.PLATFORM,
            )
            sessions = await storage.list_all_sessions("default")

        self.assertEqual([session.id for session in sessions], [saved.id])
        self.assertEqual(sessions[0].source, SessionSource.PLATFORM)
        self.assertEqual(
            sessions[0].config.platform_context.display_name,
            "张三",
        )
