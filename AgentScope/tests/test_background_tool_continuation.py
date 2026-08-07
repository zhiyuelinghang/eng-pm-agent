"""Regression tests for offloaded-tool continuation liveness."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from agentscope.app._manager._wakeup_dispatcher import WakeupDispatcher
from agentscope.app._service._session import SessionService, SessionStatus
from agentscope.app.message_bus import MessageBusKeys


class BackgroundToolContinuationTest(IsolatedAsyncioTestCase):
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

    async def test_generic_wakeup_may_still_be_consumed_by_live_run(
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

        dispatcher._schedule_idle_wake_retry.assert_not_called()
        registry.spawn.assert_not_called()
