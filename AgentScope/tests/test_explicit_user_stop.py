import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.app._user_stop import input_resumes_stopped_session
from agentscope.app._service._chat import ChatService
from agentscope.app._manager._wakeup_dispatcher import WakeupDispatcher
from agentscope.app.message_bus import MessageBusKeys
from agentscope.message import UserMsg
from agentscope.event import UserInterruptEvent


def test_only_a_later_user_message_clears_the_stop_fence():
    stopped = datetime.now(UTC)
    old = UserMsg(name="用户", content="初始化", created_at=(stopped - timedelta(seconds=1)).isoformat())
    fresh = UserMsg(name="用户", content="继续", created_at=(stopped + timedelta(seconds=1)).isoformat())
    assert not input_resumes_stopped_session(None, stopped)
    assert not input_resumes_stopped_session(old, stopped)
    assert not input_resumes_stopped_session(UserInterruptEvent(reply_id="reply"), stopped)
    assert input_resumes_stopped_session(fresh, stopped)
    assert input_resumes_stopped_session([fresh], stopped)


@pytest.mark.asyncio
async def test_stop_is_persisted_before_cancellation_can_emit_worker_feedback():
    session = SimpleNamespace(config=SimpleNamespace(user_stopped_at=None), team_id=None, source='user', source_schedule_id=None)
    service = ChatService.__new__(ChatService)
    service._storage = SimpleNamespace(get_session=AsyncMock(return_value=session), upsert_session=AsyncMock())
    async def publish(*args):
        assert args[0] == MessageBusKeys.session_cancel_channel()
        assert session.config.user_stopped_at is not None
        service._storage.upsert_session.assert_awaited_once()
    service._message_bus = SimpleNamespace(is_locked=AsyncMock(return_value=True), publish=publish)
    await service.interrupt('user', 'session', 'agent')


@pytest.mark.asyncio
async def test_late_team_and_background_wakeups_do_not_restart_stopped_leader():
    dispatcher = WakeupDispatcher.__new__(WakeupDispatcher)
    dispatcher._bus = SimpleNamespace(is_locked=AsyncMock(return_value=False))
    dispatcher._storage = SimpleNamespace(get_session=AsyncMock(return_value=SimpleNamespace(
        config=SimpleNamespace(user_stopped_at=datetime.now(UTC)), team_id=None)))
    dispatcher._registry = SimpleNamespace(spawn=Mock())
    dispatcher._chat_service = SimpleNamespace(run=AsyncMock())
    for kind in (MessageBusKeys.WAKEUP_KIND_TEAM, MessageBusKeys.WAKEUP_KIND_BACKGROUND, MessageBusKeys.WAKEUP_KIND_WAKE):
        await dispatcher._dispatch_one('user', 'session', 'agent', kind, None)
    dispatcher._registry.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_interruption_finishes_the_stream_even_during_team_cleanup():
    service = ChatService.__new__(ChatService)
    service._message_bus = object()
    service._leader_collaboration_pending = AsyncMock(return_value=True)
    with patch('agentscope.app._service._chat.publish_session_event', AsyncMock()) as publish:
        await service._publish_run_completed(user_id='user', session_id='session', agent_id='agent',
            input_msg=UserMsg(id='input', name='用户', content='初始化'), reply_msg=None, failure=asyncio.CancelledError())
    value = publish.await_args.args[2]['value']
    assert value['runtime_status'] == 'interrupted'
    assert value['collaboration_pending'] is False


@pytest.mark.asyncio
async def test_stopped_root_prevents_a_worker_invited_during_cancellation_from_starting():
    from agentscope.app._user_stop import team_root_was_stopped
    worker = SimpleNamespace(id='worker', config=SimpleNamespace(platform_context=SimpleNamespace(root_session_id='root')))
    root = SimpleNamespace(config=SimpleNamespace(user_stopped_at=datetime.now(UTC)))
    storage = SimpleNamespace(get_session=AsyncMock(return_value=root))
    assert await team_root_was_stopped(storage, 'owner', worker)
    root.config.user_stopped_at = None
    assert not await team_root_was_stopped(storage, 'owner', worker)


@pytest.mark.asyncio
async def test_stopped_idle_leader_is_interrupted_but_live_cleanup_keeps_running_status():
    from agentscope.app._service._session import SessionService, SessionStatus
    storage = SimpleNamespace(get_session=AsyncMock(return_value=SimpleNamespace(config=SimpleNamespace(user_stopped_at=datetime.now(UTC)))))
    bus = SimpleNamespace(is_locked=AsyncMock(return_value=False), registry_getall=AsyncMock(return_value={}))
    service = SessionService(storage, bus)
    assert await service.get_session_status('owner', 'agent', 'root') == SessionStatus.INTERRUPTED
    bus.is_locked.return_value = True
    assert await service.get_session_status('owner', 'agent', 'root') == SessionStatus.RUNNING
