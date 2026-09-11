import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from agentscope.app._service._session import SessionService
from agentscope.app._service._chat import ChatService
from agentscope.app.message_bus import MessageBusKeys


@pytest.mark.asyncio
async def test_slow_worker_cleanup_does_not_delay_stopping_other_workers():
    service = SessionService.__new__(SessionService)
    service._storage = SimpleNamespace(get_team=AsyncMock(return_value=object()), delete_team=AsyncMock(return_value=True))
    members = [SimpleNamespace(role="invited", owner_id="owner", agent_id=f"agent-{n}", session_id=f"worker-{n}") for n in range(5)]
    all_started, finish = asyncio.Event(), asyncio.Event()
    started = set()

    async def delete_session(owner, agent, session):
        started.add(session)
        if len(started) == 5:
            all_started.set()
        await finish.wait()

    service.delete_session = delete_session
    with patch('agentscope.app._service._session._ensure_team_members', AsyncMock(return_value=members)):
        task = asyncio.create_task(service.delete_team('owner', 'team'))
        try:
            await asyncio.wait_for(all_started.wait(), timeout=1)
            assert not service._storage.delete_team.called
        finally:
            finish.set()
            await task
    service._storage.delete_team.assert_awaited_once_with('owner', 'team')


@pytest.mark.asyncio
async def test_stop_broadcasts_to_every_worker_before_slow_cleanup_and_returns():
    root = SimpleNamespace(id='root', team_id='team', config=SimpleNamespace(user_stopped_at=None),
                           source='user', source_schedule_id=None)
    members = [SimpleNamespace(owner_id='owner', agent_id=f'agent-{n}', session_id=f'worker-{n}') for n in range(5)]
    service = ChatService.__new__(ChatService)
    service._storage = SimpleNamespace(
        get_session=AsyncMock(side_effect=lambda owner, agent, sid: root if sid == 'root' else SimpleNamespace(team_id='team')),
        get_team=AsyncMock(return_value=SimpleNamespace(session_id='root')),
        upsert_session=AsyncMock())
    published = []
    async def publish(channel, value):
        assert channel == MessageBusKeys.session_cancel_channel()
        published.append(value['session_id'])
    service._message_bus = SimpleNamespace(is_locked=AsyncMock(return_value=True), publish=publish)
    finish = asyncio.Event()
    async def cleanup(*args):
        assert set(published) == {'root', *(m.session_id for m in members)}
        await finish.wait()
    with (patch('agentscope.app._service._session._ensure_team_members', AsyncMock(return_value=members)),
          patch.object(SessionService, 'delete_team', cleanup)):
        try:
            await asyncio.wait_for(service.interrupt('owner', 'root', 'agent'), timeout=1)
            assert set(published) == {'root', *(m.session_id for m in members)}
            assert service._interrupt_cleanup_tasks
        finally:
            finish.set()
            await asyncio.gather(*service._interrupt_cleanup_tasks)


@pytest.mark.asyncio
async def test_repeated_stop_does_not_cancel_interrupted_record_cleanup():
    from agentscope.app._manager._cancel_dispatcher import CancelDispatcher
    entered, cancelled, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def run():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await finish.wait()
    task = asyncio.create_task(run())
    await entered.wait()
    dispatcher = CancelDispatcher.__new__(CancelDispatcher)
    dispatcher._registry = SimpleNamespace(get=lambda sid: task)
    dispatcher._bg_manager = SimpleNamespace(cancel_session_tasks=lambda sid: 0)
    dispatcher._cancel_session('worker')
    await cancelled.wait()
    dispatcher._cancel_session('worker')
    assert task.cancelling() == 1
    finish.set()
    await task
