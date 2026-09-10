"""Background comparison context must retain its current source authority."""
import asyncio
from dataclasses import asdict
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from agentscope.app.memory._learning import PlatformLearningRuntime
from agentscope.app.memory._run_context import validate_learning_event
from agentscope.app.storage import MemorySettingsData
from memory_run_test_support import MemoryRunHarness
from test_memory_repository import access, repository, write
from test_learning_source_policy import business_source
from utils.group_learning_schema import GROUP_LEARNING_DDL
from utils.learning_repository import LearningRepository
from utils.learning_service import process_learning_job
from utils.memory_repository import MemoryError


def job():
    return {'id': 'current-job', 'event': {
        'tenant_id': 't', 'config_owner': 'owner', 'scope_type': 'user_project',
        'event_type': 'explicit', 'evidence': [
            {'id': 'current-user', 'kind': 'user', 'text': '复盘本次实际核对过程。'},
        ],
    }}


def worker_repository(memories):
    return SimpleNamespace(memories=memories, validate_sources=MagicMock(),
        related_evidence=lambda event: event['evidence'],
        complete=MagicMock(return_value={'status': 'done'}), fail=MagicMock())


def settings(limit=16000):
    return SimpleNamespace(learning_timeout_seconds=10, learning_input_char_limit=limit)


def row(index):
    return {'id': str(index), 'version': 1, 'memory_type': 'experience', 'content': '已验证经验。' * 100}


@pytest.mark.parametrize('changed', ['revoked', 'version'])
def test_context_changed_during_model_cannot_commit(changed):
    record = row(1)
    learning = worker_repository(SimpleNamespace(search=lambda *_args, **_kwargs: [record]))
    after_model = False
    async def filter_existing(_event, _access, rows):
        if after_model:
            return [] if changed == 'revoked' else [{**record, 'version': 2}]
        return rows
    async def model(_event, _system, prompt):
        nonlocal after_model
        assert json.loads(prompt)['existing'][0]['id'] == '1'
        after_model = True
        return '{"reason":"已检查证据","candidates":[]}'
    result = asyncio.run(process_learning_job(learning, job(), authorize=AsyncMock(return_value=access()),
        filter_existing=filter_existing, call_model=model, settings=settings()))
    assert result == {'status': 'cancelled', 'code': 'learning_context_changed'}
    learning.complete.assert_not_called()


def test_budget_omitted_context_does_not_cancel_an_unrelated_result():
    records = [row(index) for index in range(10)]
    learning = worker_repository(SimpleNamespace(search=lambda *_args, **_kwargs: records))
    checks = []
    actual = set()
    async def filter_existing(_event, _access, rows):
        checks.append([item['id'] for item in rows])
        return [item for item in rows if len(checks) == 1 or item['id'] != '9']
    async def model(_event, _system, prompt):
        actual.update(item['id'] for item in json.loads(prompt)['existing'])
        assert actual and len(actual) < 5 and '9' not in actual
        return '{"reason":"没有额外成果","candidates":[]}'
    result = asyncio.run(process_learning_job(learning, job(), authorize=AsyncMock(return_value=access()),
        filter_existing=filter_existing, call_model=model, settings=settings(1500)))
    assert result == {'status': 'done'}
    assert set(checks[1]) == actual
    learning.complete.assert_called_once()


def test_context_authorizer_failure_never_calls_model():
    learning = worker_repository(SimpleNamespace(search=lambda *_args, **_kwargs: [row(1)]))
    model = AsyncMock()
    result = asyncio.run(process_learning_job(learning, job(), authorize=AsyncMock(return_value=access()),
        filter_existing=AsyncMock(side_effect=TimeoutError()), call_model=model, settings=settings()))
    assert result['status'] == 'failed'
    model.assert_not_awaited()
    learning.complete.assert_not_called()


async def seeded_context(repository, kind):
    actor = access()
    gateway = SimpleNamespace(group_learning_validate=AsyncMock(), business_learning_validate=AsyncMock())
    storage = SimpleNamespace()
    validator = None
    revoke = None
    learning = LearningRepository(repository)
    if kind == 'knowledge':
        harness = MemoryRunHarness(repository)
        harness.entry_kind = 'knowledge'
        await harness.start('复盘资料查询中的实际检索步骤', mid='source-user')
        await harness.controller().record_tool(harness.knowledge_evidence())
        await harness.controller().request_learning('explicit')
        await harness.finish()
        source_event = learning.dashboard(access(management=True))['events'][0]
        source_id = source_event['id']
        storage, gateway = harness.storage, harness.gateway
        async def validator(event, *, existing=False):
            return await validate_learning_event(storage, gateway, 't', event, existing=existing)
        def revoke():
            harness.knowledge_ids = []
    else:
        if kind == 'group':
            batch_id = str(uuid4())
            with repository._connection() as conn:
                conn.execute(GROUP_LEARNING_DDL)
                conn.execute('''INSERT INTO group_learning_batches
                    (id,tenant_id,channel_id,from_revision,to_revision,snapshot,config_owner)
                    VALUES (%s,'t',1,1,1,%s,'owner')''',
                    (batch_id, Jsonb({'members': ['a', 'b'], 'full_project': False})))
            provenance = {'batch_id': batch_id}
            def revoke():
                gateway.group_learning_validate.side_effect = MemoryError('source_revoked', '群聊来源已撤回', status=403)
        else:
            provenance = {'business_source': business_source()}
            def revoke():
                gateway.business_learning_validate.side_effect = MemoryError('source_revoked', '业务来源已撤回', status=403)
        source_id = learning.capture(actor, scope_type='user_project', agent_id='', session_id='source',
            config_owner='owner', event_key='context-source', event_type='explicit', enqueue=False,
            evidence=[{'id': 'source-user', 'kind': 'user', 'text': '实际核验过的原始来源'}],
            source_type='group' if kind == 'group' else 'business_event', provenance=provenance)['event_id']

    known = write(repository, scope='user_project', content='旧来源中的受限检验经验')['memory']
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET memory_type='experience',origin='learning',source=%s,learning=%s WHERE id=%s",
            (Jsonb({'kind': 'learning', 'event_id': source_id}),
             Jsonb({'event_id': source_id, 'validation_state': 'verified'}), known['id']))
    runtime = PlatformLearningRuntime(storage=storage, gateway=gateway, resources=None,
        settings_loader=AsyncMock(return_value=MemorySettingsData(learning_enabled=True, learning_model_config={'type':'custom_openai_credential','credential_id':'test','model':'test','parameters':{}})), tenant_id='t',
        memory_repository=repository, interaction_validator=validator)
    return runtime, revoke, known['id']


@pytest.mark.parametrize('kind', ['knowledge', 'group', 'business'])
def test_revoked_sources_are_not_sent_as_background_comparison_context(repository, kind):
    async def run():
        runtime, revoke, memory_id = await seeded_context(repository, kind)
        rows = repository.search(access(), scope_type='user_project')
        assert [item['id'] for item in await runtime.filter_existing(job()['event'], access(), rows)] == [memory_id]
        revoke()
        learning = worker_repository(repository)
        async def model(_event, system, prompt):
            assert json.loads(prompt)['existing'] == []
            assert '旧来源中的受限检验经验' not in prompt
            assert '不能作为新事实或新成果的证据' in system
            return '{"reason":"无新成果","candidates":[]}'
        result = await process_learning_job(learning, job(), authorize=AsyncMock(return_value=access()),
            filter_existing=runtime.filter_existing, call_model=model, settings=settings())
        assert result == {'status': 'done'}
    asyncio.run(run())


def test_actual_runtime_rejects_a_context_source_revoked_during_model(repository):
    async def run():
        runtime, revoke, _ = await seeded_context(repository, 'knowledge')
        learning = worker_repository(repository)
        async def model(_event, _system, prompt):
            assert json.loads(prompt)['existing']
            revoke()
            return '{"reason":"已检查","candidates":[]}'
        result = await process_learning_job(learning, job(), authorize=AsyncMock(return_value=access()),
            filter_existing=runtime.filter_existing, call_model=model, settings=settings())
        assert result['code'] == 'learning_context_changed'
        learning.complete.assert_not_called()
    asyncio.run(run())


def test_runtime_context_rechecks_scope_even_when_given_previously_visible_rows(repository):
    known = write(repository, scope='user_project', content='个人项目中的已知事实')['memory']
    runtime = PlatformLearningRuntime(storage=SimpleNamespace(), gateway=SimpleNamespace(), resources=None,
        settings_loader=AsyncMock(return_value=MemorySettingsData(learning_enabled=True, learning_model_config={'type':'custom_openai_credential','credential_id':'test','model':'test','parameters':{}})), tenant_id='t', memory_repository=repository)
    assert asyncio.run(runtime.filter_existing(job()['event'], access(user='other'), [known])) == []
    with pytest.raises(MemoryError):
        asyncio.run(runtime.filter_existing({**job()['event'], 'tenant_id': 'other'}, access(), [known]))
