import asyncio
import json
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from task_engine.domain.models import Assignee
from task_engine.generator.llm import AIFlowGenerationError

from backend.app import chat_api
from backend.app.agentscope_client import AgentScopeReply
from backend.app.task_assistant_generation import TaskAssistantGenerator, flow_from_mcp
from backend.app.task_engine_gateway import get_generator
from backend.app import task_session_binding
from backend.app.db import Base
from backend.app.models import AgentConversation, Project, ProjectMember, User


@pytest.fixture(autouse=True)
def bound_identity(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Project(id=1, name='项目'), User(id=12, username='user', real_name='甲',
            password_hash='test', role='user', identity_card_no='generation-user')])
        db.flush()
        db.add(ProjectMember(project_id=1, user_id=12))
        db.commit()
    monkeypatch.setattr(task_session_binding, 'SessionLocal', lambda: Session(engine))
    yield engine
    engine.dispose()


def native_flow():
    return {'title': '现场检查', 'summary': '检查并复核', 'origin': 'ai',
        'trigger': {'run_mode': 'calendar', 'first_at': '2026-09-10T02:00:00Z',
                    'calendar_mode': 'weekly', 'calendar_weekdays': [2, 4], 'max_fires': 3},
        'steps': [{'name': '检查', 'assignee': {'ref': '12', 'name': '甲'}, 'deliverable': '检查记录'}],
        'confirmer': {'ref': '13', 'name': '乙'}, 'site': {'ref': '14', 'name': '工点'}}


def options():
    return {'now': datetime(2026, 9, 9, tzinfo=ZoneInfo('Asia/Shanghai')),
        'assignees': [Assignee('12', '甲'), Assignee('13', '乙')], 'generation_id': 'generation-test',
        'context': {'project': {'id': 1, 'name': '项目'},
                    'current_user': {'ref': '12', 'username': 'user', 'display_name': '甲'},
                    'wbs_items': [{'id': 14, 'name': '工点'}], 'chat_channels': []}}


def reply():
    return AgentScopeReply(status='completed', content='已生成草稿', message_id='reply', raw_message=None,
        raw_messages=[{'role': 'assistant', 'content': [
            {'type': 'tool_call', 'id': 'call', 'name': 'mcp__task-engine__generate_task_flow'},
            {'type': 'tool_result', 'tool_call_id': 'call', 'state': 'success',
             'result': [{'type': 'text', 'text': json.dumps({'flow': native_flow(), 'saved': False})}]}]}])


def client_fixture(monkeypatch):
    client = SimpleNamespace(create_session=Mock(return_value='session'), trigger_chat=Mock(return_value='input'),
        wait_for_chat_reply=Mock(return_value=reply()), interrupt=Mock())
    selected = {'id': 'fixed-task-assistant', 'enabled': True, 'model_ready': True}
    monkeypatch.setattr(chat_api, '_configured_task_assistant', lambda: selected)
    monkeypatch.setattr(chat_api, '_agentscope_client', lambda: client)
    return client, selected


@pytest.mark.asyncio
async def test_task_editor_uses_fixed_assistant_and_keeps_calendar_and_people(monkeypatch):
    client, selected = client_fixture(monkeypatch)
    assert isinstance(get_generator(), TaskAssistantGenerator)
    flow = await get_generator().generate_async('检查现场并提交记录', **options())
    assert client.create_session.call_args.kwargs['agent'] is selected
    entry = client.create_session.call_args.kwargs['platform_context']
    assert entry['user_id'] == '12' and entry['project_id'] == '1'
    assert entry['agent_name'] == '任务助手'
    assert entry['conversation_type'] == 'task_editor'
    assert 'save=false' in client.trigger_chat.call_args.kwargs['content']
    assert flow.trigger.calendar_weekdays == (2, 4)
    assert flow.trigger.max_fires == 3 and flow.trigger.first_at.hour == 10
    assert flow.confirmer.ref == '13' and flow.site.ref == '14'
    assert flow.steps[0].assignee.ref == '12'
    client.interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_binding_exists_before_trigger_and_cannot_write_shared_memory(monkeypatch, bound_identity):
    from backend.app.agent_context_gateway import get_agent_memory_scope
    client, _ = client_fixture(monkeypatch)
    def submitted(**kwargs):
        with Session(bound_identity) as db:
            scope = get_agent_memory_scope(kwargs['session_id'], db)['data']
            assert scope['entry_kind'] == 'task_editor'
            assert scope['user_id'] == '12' and scope['private']
            assert not scope['project_write']
        return 'input'
    client.trigger_chat.side_effect = submitted
    await TaskAssistantGenerator().generate_async('检查现场', **options())
    with Session(bound_identity) as db:
        assert db.scalar(select(AgentConversation)).status == 'completed'


@pytest.mark.asyncio
async def test_task_editor_rejects_reply_without_assigned_mcp_call(monkeypatch):
    client, _ = client_fixture(monkeypatch)
    client.wait_for_chat_reply.return_value = AgentScopeReply(status='completed', content=json.dumps(native_flow()),
        message_id='reply', raw_message=None)
    with pytest.raises(AIFlowGenerationError, match='没有调用'):
        await TaskAssistantGenerator().generate_async('检查现场并提交记录', **options())


@pytest.mark.asyncio
async def test_stop_during_submission_interrupts_after_submission_finishes(monkeypatch):
    client, _ = client_fixture(monkeypatch)
    started, release = threading.Event(), threading.Event()
    order = []
    def submit(**kwargs):
        started.set()
        assert release.wait(5)
        order.append('submitted')
        return 'input'
    client.trigger_chat.side_effect = submit
    client.interrupt.side_effect = lambda **kwargs: order.append('interrupted')
    running = asyncio.create_task(TaskAssistantGenerator().generate_async('检查现场并提交记录', **options()))
    assert await asyncio.to_thread(started.wait, 5)
    running.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert order == ['submitted', 'interrupted']
    client.wait_for_chat_reply.assert_not_called()


def test_mcp_cannot_supply_people_from_another_project():
    raw = native_flow()
    raw['steps'][0]['assignee']['ref'] = '999'
    data = options()
    facts = {**data['context'], 'assignees': [{'ref': '12'}, {'ref': '13'}]}
    with pytest.raises(ValueError, match='项目之外'):
        flow_from_mcp(raw, now=data['now'], context=facts)
