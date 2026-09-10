"""Confirmed business-event consumption against an isolated memory schema."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_memory_repository import repository as memory_repository, access
from test_learning_source_policy import business_source
from agentscope.app.storage import MemorySettingsData
from agentscope.app.memory._settings import RuntimeMemorySettings
from utils.business_learning_service import scan_business_sources, _cursor
from utils.learning_repository import LearningRepository, LearningOutput
from utils.memory_repository import MemoryError
from utils.learning_schema import BUSINESS_LEARNING_DDL


@pytest.fixture
def repository(memory_repository):
    with memory_repository._connection() as conn:
        conn.execute(BUSINESS_LEARNING_DDL)
    return memory_repository


def settings(**kwargs):
    result = SimpleNamespace(**RuntimeMemorySettings(learning_enabled=True, learning_model_config={'type':'custom_openai_credential','credential_id':'test','model':'test','parameters':{}}).model_dump())
    result.learning_model_config = object()
    for key,value in kwargs.items():
        setattr(result,key,value)
    return result


def source_runtime(sources):
    return SimpleNamespace(gateway=SimpleNamespace(
        business_learning_validate=AsyncMock(return_value={'valid':True}),
        business_learning_sources=AsyncMock(return_value={'items':sources,'has_more':False,'next_after_id':sources[-1]['id'] if sources else 0})),
        authorize=AsyncMock())


def run_scan(learning,runtime,config):
    asyncio.run(scan_business_sources(learning,runtime,config,tenant_id='t',config_owner='owner'))


def test_system_business_source_preserves_provenance_and_retries_once(repository):
    learning = LearningRepository(repository)
    source = business_source()
    runtime = source_runtime([source])
    run_scan(learning,runtime,settings())
    run_scan(learning,runtime,settings())
    rows = learning.dashboard(access(management=True))['events']
    assert len(rows) == 1
    assert rows[0]['agent_id'] == '' and rows[0]['source_type'] == 'business_event'
    assert rows[0]['scope_type'] == 'project' and rows[0]['platform_user_id'] == ''
    assert rows[0]['provenance']['business_source']['source_key'] == source['source_key']
    assert _cursor(learning,'t') == 1


def test_private_business_source_only_targets_source_audience(repository):
    learning = LearningRepository(repository)
    source = {**business_source(),'project_shared':False,'audience_user_ids':['a','b']}
    run_scan(learning,source_runtime([source]),settings())
    rows = learning.dashboard(access(management=True))['events']
    assert {(r['scope_type'],r['platform_user_id']) for r in rows} == {('user_project','a'),('user_project','b')}


def test_budget_exhaustion_retains_cursor_and_resumes_same_event(repository):
    learning = LearningRepository(repository)
    source = {**business_source(),'project_shared':False,'audience_user_ids':['a','b']}
    runtime = source_runtime([source])
    run_scan(learning,runtime,settings(learning_daily_job_limit=1))
    assert _cursor(learning,'t') == 0
    assert learning.dashboard(access(management=True))['total'] == 2
    run_scan(learning,runtime,settings(learning_daily_job_limit=2))
    assert _cursor(learning,'t') == 1
    rows = learning.dashboard(access(management=True))['events']
    assert len(rows) == 2 and all(r['job_id'] for r in rows)


@pytest.mark.parametrize('config',[
    {'learning_enabled':False}, {'learning_business_events_enabled':False}, {'learning_model_config':None},
])
def test_paused_or_unconfigured_consumer_does_not_advance_sources(repository,config):
    learning = LearningRepository(repository)
    runtime = source_runtime([business_source()])
    run_scan(learning,runtime,settings(**config))
    runtime.gateway.business_learning_sources.assert_not_awaited()
    assert _cursor(learning,'t') == 0


def test_source_revocation_invalidates_published_result_even_when_learning_paused(repository):
    learning = LearningRepository(repository)
    runtime = source_runtime([business_source()])
    run_scan(learning,runtime,settings())
    job = learning.claim('t')
    result = learning.complete(job, access(), LearningOutput.model_validate({'reason':'依据真实验收结果。','candidates':[
        {'memory_type':'experience','title':'验收经验','content':'先对照任务附件清单，再确认验收。',
         'conditions':'任务附件齐全','limitations':'不能代替现场检查','evidence_ids':['business:1:3'],'steps':[]}]}))
    mid = result['candidates'][0]['memory_id']
    runtime.gateway.business_learning_validate.side_effect = MemoryError('source_revoked','来源撤回',status=403)
    run_scan(learning,runtime,settings(learning_enabled=False))
    assert repository.get(access(management=True),mid)['status'] == 'inactive'


def test_large_business_source_keeps_full_provenance_and_bounded_model_evidence(repository):
    learning = LearningRepository(repository)
    source = business_source()
    source['evidence'][0]['text'] = '验收证据。' * 2000
    run_scan(learning,source_runtime([source]),settings())
    row = learning.dashboard(access(management=True))['events'][0]
    assert len(row['evidence'][0]['text']) == 4000
    assert '不能推断' in row['evidence'][0]['text']
    assert row['provenance']['business_source']['evidence'] == source['evidence']


def test_source_cursor_advances_past_revoked_items_omitted_by_producer(repository):
    learning = LearningRepository(repository)
    runtime = source_runtime([])
    runtime.gateway.business_learning_sources.return_value['next_after_id'] = 7
    run_scan(learning,runtime,settings())
    assert _cursor(learning,'t') == 7


def test_pending_generation_keeps_cursor_and_learns_after_source_run_finishes(repository):
    learning = LearningRepository(repository)
    pending = {**business_source(), 'allow_learning':False, 'learning_state':'pending'}
    runtime = source_runtime([pending])
    run_scan(learning,runtime,settings())
    assert _cursor(learning,'t') == 0
    assert learning.dashboard(access(management=True))['events'] == []
    runtime.authorize.assert_not_awaited()
    runtime.gateway.business_learning_sources.return_value['items'] = [business_source()]
    run_scan(learning,runtime,settings())
    rows = learning.dashboard(access(management=True))['events']
    assert _cursor(learning,'t') == 1
    assert len(rows) == 1 and rows[0]['job_id']
    assert rows[0]['provenance']['business_source']['learning_state'] == 'allowed'
