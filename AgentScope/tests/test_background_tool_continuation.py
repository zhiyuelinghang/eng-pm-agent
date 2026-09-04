"""Regression tests for offloaded-tool continuation liveness."""

import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._manager._wakeup_dispatcher import WakeupDispatcher
from agentscope.app._router._session import get_session_status
from agentscope.app._service._session import SessionService, SessionStatus
from agentscope.app.message_bus import MessageBusKeys
from agentscope.app.storage import SessionSource


class BackgroundToolContinuationTest(IsolatedAsyncioTestCase):
    async def test_session_delete_does_not_wait_for_lifecycle_hook(
        self,
    ) -> None:
        hook_started = asyncio.Event()
        release_hook = asyncio.Event()

        async def slow_session_end_hook(*_args: object) -> None:
            hook_started.set()
            await release_hook.wait()

        record = SimpleNamespace(id="session", agent_id="agent")
        storage = SimpleNamespace(
            list_all_sessions=AsyncMock(return_value=[record]),
            delete_session=AsyncMock(return_value=True),
        )
        service = SessionService(
            storage,
            SimpleNamespace(),
            session_end_handler=slow_session_end_hook,
        )
        service._team_worker_session_ids = AsyncMock(return_value=[])
        service._purge_team_projections = AsyncMock()
        service._cancel_runs = AsyncMock()
        service._purge_bus = AsyncMock()

        try:
            deleted = await asyncio.wait_for(
                service.delete_session("user", "agent", "session"),
                timeout=0.5,
            )
            await asyncio.wait_for(hook_started.wait(), timeout=0.5)

            self.assertTrue(deleted)
            storage.delete_session.assert_awaited_once_with(
                "user",
                "agent",
                "session",
            )
            self.assertTrue(service._session_end_tasks)
        finally:
            release_hook.set()
            if service._session_end_tasks:
                await asyncio.gather(*service._session_end_tasks)

    async def test_local_chat_task_keeps_status_running_until_exit(
        self,
    ) -> None:
        storage = SimpleNamespace(
            get_session=AsyncMock(
                return_value=SimpleNamespace(source=SessionSource.USER),
            ),
        )
        session_service = SimpleNamespace(
            get_session_status=AsyncMock(return_value=SessionStatus.IDLE),
        )
        blocker = asyncio.Event()
        local_task = asyncio.create_task(blocker.wait())
        registry = SimpleNamespace(get=Mock(return_value=local_task))

        try:
            response = await get_session_status(
                session_id="session",
                agent_id="agent",
                user_id="user",
                principal=AgentScopePrincipal(
                    kind="management",
                    subject="admin",
                ),
                storage=storage,
                session_service=session_service,
                chat_run_registry=registry,
            )
        finally:
            local_task.cancel()
            await asyncio.gather(local_task, return_exceptions=True)

        self.assertEqual(response.status, SessionStatus.RUNNING)
        session_service.get_session_status.assert_not_awaited()

    async def test_background_tool_keeps_session_running_until_result(
        self,
    ) -> None:
        storage = SimpleNamespace(get_session=AsyncMock())
        bus = SimpleNamespace(
            is_locked=AsyncMock(return_value=False),
            registry_getall=AsyncMock(return_value={"task-1": "{}"}),
        )
        service = SessionService(storage, bus)

        status = await service.get_session_status(
            "user",
            "agent",
            "session",
        )

        self.assertEqual(status, SessionStatus.RUNNING)
        storage.get_session.assert_not_awaited()
        bus.registry_getall.assert_awaited_once_with(
            MessageBusKeys.bg_tasks("session"),
        )

    async def test_background_wakeup_is_retried_while_session_finishes(
        self,
    ) -> None:
        bus = SimpleNamespace(is_locked=AsyncMock(return_value=True))
        registry = SimpleNamespace(spawn=Mock())
        dispatcher = WakeupDispatcher(
            message_bus=bus,
            storage=SimpleNamespace(),
            chat_service=SimpleNamespace(),
            chat_run_registry=registry,
        )
        dispatcher._schedule_idle_wake_retry = Mock()

        await dispatcher._dispatch_one(
            user_id="user",
            session_id="session",
            agent_id="agent",
            kind=MessageBusKeys.WAKEUP_KIND_BACKGROUND,
            raw_input=None,
        )

        dispatcher._schedule_idle_wake_retry.assert_called_once_with(
            "user",
            "session",
            "agent",
            MessageBusKeys.WAKEUP_KIND_BACKGROUND,
        )
        registry.spawn.assert_not_called()

    async def test_generic_wakeup_is_retried_until_live_run_finishes(
        self,
    ) -> None:
        bus = SimpleNamespace(is_locked=AsyncMock(return_value=True))
        registry = SimpleNamespace(spawn=Mock())
        dispatcher = WakeupDispatcher(
            message_bus=bus,
            storage=SimpleNamespace(),
            chat_service=SimpleNamespace(),
            chat_run_registry=registry,
        )
        dispatcher._schedule_idle_wake_retry = Mock()

        await dispatcher._dispatch_one(
            user_id="user",
            session_id="session",
            agent_id="agent",
            kind=MessageBusKeys.WAKEUP_KIND_WAKE,
            raw_input=None,
        )

        dispatcher._schedule_idle_wake_retry.assert_called_once_with(
            "user",
            "session",
            "agent",
            MessageBusKeys.WAKEUP_KIND_WAKE,
        )
        registry.spawn.assert_not_called()
