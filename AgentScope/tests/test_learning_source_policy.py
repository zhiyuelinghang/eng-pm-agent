"""System learning sources and interaction permissions have separate lifetimes."""
import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentscope.app.memory._learning import PlatformLearningRuntime
from agentscope.app.storage import MemorySettingsData
from utils.memory_repository import MemoryAccess, MemoryError


def runtime(settings=None, *, storage=None, gateway=None, validator=None):
    return PlatformLearningRuntime(storage=storage or SimpleNamespace(get_agent=AsyncMock()),
        gateway=gateway or SimpleNamespace(), resources=MagicMock(),
        settings_loader=AsyncMock(return_value=settings or MemorySettingsData(learning_enabled=True, learning_model_config={'type':'custom_openai_credential','credential_id':'test','model':'test','parameters':{}})), tenant_id='t',
        interaction_validator=validator)


def business_source():
    return dict(id=1, source_key='task:1:accepted:3', source_type='task', source_id='1', source_version='3',
        stage='task_accepted', project_id='p', actor_user_id='a', audience_user_ids=['a','b'], project_shared=True,
        allow_learning=True, learning_state='allowed', evidence=[dict(id='business:1:3',kind='business_event',text='验收通过。',outcome='accepted')],
        evidence_hash='hash', created_at='2026-09-10T00:00:00Z')


def business_event():
    return {'tenant_id':'t','source_type':'business_event','provenance':{'business_source':business_source()},
        'scope_type':'project','access_snapshot':asdict(MemoryAccess('t','','p',project_read=True,project_write=True))}


def test_group_policy_has_no_agent_dependency():
    r = runtime()
    asyncio.run(r.authorize_group({'tenant_id':'t'}))
    r.storage.get_agent.assert_not_called()
    r.settings_loader.return_value.learning_enabled = False
    with pytest.raises(MemoryError, match='暂停'):
        asyncio.run(r.authorize_group({'tenant_id':'t'}))


def test_missing_learning_model_does_not_borrow_agent_or_session():
    r = runtime()
    r.settings_loader.return_value.learning_model_config = None
    with pytest.raises(MemoryError, match='指定后台学习模型'):
        asyncio.run(r.call_model({'config_owner':'owner','source_type':'interaction'}, 'system', 'evidence'))
    r.storage.get_agent.assert_not_called()
    r.resources.resolve_credential.assert_not_called()


def test_confirmed_business_source_is_independent_of_agent_settings():
    r = runtime(gateway=SimpleNamespace(business_learning_validate=AsyncMock()))
    assert asyncio.run(r.authorize(business_event())).target('project', write=True) == ('','p')
    r.storage.get_agent.assert_not_called()


def test_pausing_learning_keeps_existing_result_but_rechecks_source():
    gateway = SimpleNamespace(business_learning_validate=AsyncMock())
    r = runtime(MemorySettingsData(learning_enabled=False,learning_business_events_enabled=False),gateway=gateway)
    with pytest.raises(MemoryError, match='暂停'):
        asyncio.run(r.authorize(business_event()))
    assert asyncio.run(r.authorize_existing(business_event())).project_id == 'p'
    gateway.business_learning_validate.assert_awaited_once()
    gateway.business_learning_validate.side_effect = MemoryError('source_revoked','来源已撤回。',status=403)
    with pytest.raises(MemoryError, match='撤回'):
        asyncio.run(r.authorize_existing(business_event()))


def test_business_source_cannot_promote_private_audience_to_project():
    event = business_event()
    event['provenance']['business_source']['project_shared'] = False
    r = runtime(gateway=SimpleNamespace(business_learning_validate=AsyncMock()))
    with pytest.raises(MemoryError, match='受众'):
        asyncio.run(r.authorize(event))


def test_interaction_run_requires_authoritative_validator():
    event = {'tenant_id':'t','source_type':'interaction','provenance':{'run_id':'run-1'},'access_snapshot':{}}
    with pytest.raises(MemoryError, match='来源校验'):
        asyncio.run(runtime().authorize(event))
    check = AsyncMock(return_value=MemoryAccess('t','a','p',project_read=True,project_write=True))
    assert asyncio.run(runtime(validator=check).authorize(event)).user_id == 'a'
    check.assert_awaited_once_with(event,existing=False)


def test_existing_interaction_rechecks_run_source_without_new_learning_gate():
    settings = MemorySettingsData(learning_enabled=False,learning_interactions_enabled=False)
    validator = AsyncMock(return_value=MemoryAccess('t','a','p'))
    r = runtime(settings,validator=validator)
    event = dict(tenant_id='t',source_type='interaction',provenance={'run_id':'run-1'},access_snapshot={})
    with pytest.raises(MemoryError,match='暂停'):
        asyncio.run(r.authorize(event))
    assert asyncio.run(r.authorize_existing(event)).user_id == 'a'
    validator.assert_awaited_once_with(event,existing=True)
    validator.side_effect = MemoryError('identity_mismatch','身份已改变。',status=403)
    with pytest.raises(MemoryError,match='身份'):
        asyncio.run(r.authorize_existing(event))


def test_interaction_without_run_identity_is_rejected():
    event = dict(tenant_id='t',source_type='interaction',provenance={},access_snapshot={})
    with pytest.raises(MemoryError,match='业务运行来源'):
        asyncio.run(runtime().authorize(event))


def test_derived_result_rechecks_every_original_source():
    one = business_event()
    two = business_event()
    two['provenance']['business_source'] = {**business_source(),'id':2,'source_key':'task:2:accepted:1'}
    one['provenance']['derived_sources'] = [two]
    gateway = SimpleNamespace(business_learning_validate=AsyncMock(side_effect=[None,
        MemoryError('source_revoked','第二条来源已撤回。',status=403)]))
    with pytest.raises(MemoryError,match='第二条'):
        asyncio.run(runtime(gateway=gateway).authorize_existing(one))
    assert gateway.business_learning_validate.await_count == 2


def test_group_invalidation_worker_runs_when_learning_is_paused(monkeypatch):
    from utils import group_learning_service as service
    scan = AsyncMock()
    monkeypatch.setattr(service,'scan_groups',scan)
    async def stop(_):
        raise asyncio.CancelledError
    monkeypatch.setattr(service.asyncio,'sleep',stop)
    repository = MagicMock()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.run_group_learning_worker(repository,runtime=object(),
            settings_loader=AsyncMock(return_value=MemorySettingsData(learning_enabled=False)),tenant_id='t',config_owner='o'))
    scan.assert_awaited_once()
    repository.claim.assert_not_called()
