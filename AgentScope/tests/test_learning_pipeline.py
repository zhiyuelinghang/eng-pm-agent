"""Learning tests use the same disposable PostgreSQL fixture as memory tests."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from test_memory_repository import repository, access, write
from memory_run_test_support import MemoryRunHarness
from utils.learning_repository import LearningRepository, LearningOutput
from utils.memory_repository import MemoryError, MemoryWrite
from utils.learning_service import process_learning_job


async def allow_fixture_context(_event, _access, rows):
    # Source authorization is covered separately by the actual runtime-filter tests.
    return rows


def event(repo,actor=None,kind='explicit',**kwargs):
    return LearningRepository(repo).capture(actor or access(),scope_type='user_project',agent_id='agent',session_id='session',
        config_owner='owner',event_key=kwargs.pop('event_key',str(uuid4())),event_type=kind,
        evidence=[{'id':'user-1','kind':'user','text':'请总结本次复盘：先核对附件清单，然后逐个验收。'}],delay_seconds=0,**kwargs)


def output(kind='experience'):
    return LearningOutput.model_validate({'reason':'用户确认的方法','candidates':[{'memory_type':kind,'title':'附件验收',
        'content':'先核对附件清单再逐个验收。','conditions':'有明确附件清单的验收任务','limitations':'不能替代质量验收',
        'evidence_ids':['user-1'],'steps':['核对清单','逐个验收'] if kind=='skill' else []}]})


def candidate(repo,kind='experience'):
    event(repo)
    learn=LearningRepository(repo)
    result=learn.complete(learn.claim('t'),access(),output(kind))
    return result['candidates'][0]['memory_id']


def test_learning_automatically_publishes_without_human_review(repository):
    learning=LearningRepository(repository)
    mid=candidate(repository)
    row=repository.get(access(management=True),mid)
    assert row['learning']['validation_method']=='automatic_v1'
    assert row['status']=='active'
    found=repository.search(access())[0]
    assert found['origin']=='learning' and found['memory_type']=='experience'
    assert 'evidence' not in found['learning']
    assert 'conditions' in found['learning']
    assert repository.search(replace(access(),learning_use=False))==[]
    with pytest.raises(MemoryError,match='学习流程'):
        write(repository,memory_type='experience')


def test_learning_is_idempotent_and_frozen_to_owner(repository):
    one=event(repository,event_key='same')
    assert event(repository,event_key='same')['status']=='unchanged'
    learning=LearningRepository(repository)
    job=learning.claim('t')
    with pytest.raises(MemoryError,match='归属'):
        learning.complete(job,access(user='b'),output())
    assert learning.complete(job,access(),output())['candidates']
    event(repository)
    assert learning.complete(learning.claim('t'),access(),output())['candidates'][0]['status']=='duplicate'
    assert repository.list(access(),status='active')['total']==1
    assert repository.search(access(user='b'))==[]


def test_pattern_threshold_and_daily_budget_keep_evidence(repository):
    for _ in range(2):
        assert event(repository,kind='repeated_pattern',fingerprint='same-pattern')['status']=='recorded'
    assert event(repository,kind='repeated_pattern',fingerprint='same-pattern')['status']=='queued'
    result=event(repository,daily_limit=1)
    assert result['status']=='recorded'
    dashboard=LearningRepository(repository).dashboard(access(management=True))
    assert dashboard['total']==4


def test_model_evidence_cannot_be_fabricated_and_cancelled_lease_cannot_commit(repository):
    learning=LearningRepository(repository)
    e=event(repository)
    job=learning.claim('t')
    fabricated=output()
    fabricated.candidates[0].evidence_ids=['made-up']
    with pytest.raises(MemoryError,match='不存在'):
        learning.complete(job,access(),fabricated)
    learning.job_action(access(management=True),e['event_id'],'cancel')
    assert learning.complete(job,access(),output())['status']=='stale'
    assert repository.list(access(),status='candidate')['total']==0
    learning.job_action(access(management=True),e['event_id'],'retry')
    assert learning.claim('t')['lease_id']!=job['lease_id']


def test_feedback_and_aging_flag_review_without_promoting_or_losing_facts(repository):
    learning=LearningRepository(repository)
    mid=candidate(repository,'skill')
    learning.review(access(management=True),mid,expected_version=1,action='approve',note='按步骤通过验收')
    write(repository,key='profile.name')
    learning.feedback(access(),mid,expected_version=2,outcome='failure',evidence='实际附件格式不同，步骤未通过',request_id='feedback')
    assert learning.maintain('t')['review_due']==1
    assert repository.get(access(),mid)['learning']['validation_state']=='contradicted'
    assert repository.get(access(),mid)['status']=='inactive'
    assert not repository.search(access(),memory_type='skill')
    assert repository.search(access(),fact_key='profile.name')
    assert not repository.search(access(),memory_type='skill')


def test_revision_and_rollback_require_revalidation(repository):
    learning=LearningRepository(repository)
    mid=candidate(repository)
    learning.review(access(management=True),mid,expected_version=1,action='approve',note='验证通过')
    row=learning.review(access(management=True),mid,expected_version=2,action='revise',note='补充例外',content='新版验收经验')
    assert row['status']=='candidate' and repository.search(access())==[]
    row=learning.review(access(management=True),mid,expected_version=3,action='rollback',restore_version=2,note='回滚并重新检查')
    assert row['content']=='先核对附件清单再逐个验收。' and row['status']=='candidate'
    assert len(repository.history(access(management=True),mid))==4


def test_worker_rechecks_permission_after_model_and_handles_invalid_output(repository):
    learning=LearningRepository(repository)
    event(repository)
    job=learning.claim('t')
    calls=0
    async def auth(_event):
        nonlocal calls
        calls+=1
        return access(learning_enabled=calls==1)
    async def model(*_args):
        return output().model_dump_json()
    result=asyncio.run(process_learning_job(learning,job,authorize=auth,filter_existing=allow_fixture_context,call_model=model,settings=SimpleNamespace(learning_timeout_seconds=10)))
    assert result['status']=='cancelled'
    assert repository.list(access(),status='candidate')['total']==0


def test_actual_middleware_greeting_is_silent_and_correction_queues(repository):
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.message import UserMsg,AssistantMsg
    from agentscope.event import ReplyEndEvent
    async def resolve():
        return access()
    harness=MemoryRunHarness(repository)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='a',agent_id='agent',session_id='s'),
        {'learning_skill_limit':0},access_resolver=resolve,repository=repository,controller=harness.controller(),config_owner='owner')
    agent=SimpleNamespace(state=SimpleNamespace(context=[],tasks_context=SimpleNamespace(tasks=[]),middle_context={}))
    async def handler(**_kwargs):
        yield ReplyEndEvent(session_id='s',reply_id='reply')
    async def run():
        async for _ in middleware.on_reply(agent,{'inputs':[UserMsg('user','你好')]},handler):
            pass
        await harness.finish()
        assert middleware.learning.dashboard(access(management=True))['total']==0
        agent.state.context=[AssistantMsg('assistant','先验收再检查清单')]
        async for _ in middleware.on_reply(agent,{'inputs':[UserMsg('user','不对，应该先检查附件清单再验收')]},handler):
            pass
        await harness.finish()
        assert middleware.learning.dashboard(access(management=True))['events'][0]['event_type']=='correction'
    asyncio.run(run())


def test_expired_learning_worker_and_deleted_candidate_never_resurrect(repository):
    learning=LearningRepository(repository)
    event(repository)
    abandoned=learning.claim('t')
    with repository._connection() as conn:
        conn.execute("UPDATE learning_jobs SET lease_until=now()-interval '1 second'")
    recovered=learning.claim('t')
    assert learning.complete(abandoned,access(),output())['status']=='stale'
    mid=learning.complete(recovered,access(),output())['candidates'][0]['memory_id']
    repository.forget(access(),mid,1)
    event(repository)
    assert learning.complete(learning.claim('t'),access(),output())['candidates'][0]['status']=='suppressed'
    assert repository.list(access(),status='candidate')['total']==0


def test_management_learning_api_and_export_are_real_and_source_safe(repository,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agentscope.app._router import _memory_management as api
    from agentscope.app._auth import AgentScopePrincipal
    from agentscope.app.deps import get_current_principal
    monkeypatch.setattr(api,'get_memory_repository',lambda:repository)
    monkeypatch.setattr(api,'get_memory_runtime',lambda:SimpleNamespace(tenant_id='t'))
    app=FastAPI();app.include_router(api.memory_management_router)
    app.dependency_overrides[get_current_principal]=lambda:AgentScopePrincipal(kind='management',subject='admin')
    mid=candidate(repository,'skill')
    with TestClient(app) as client:
        base=f'/memory-management/memories/{mid}'
        assert client.get('/memory-management/learning').json()['total']==1
        assert client.get(base+'/learning-document').status_code==200
        assert client.post(base+'/learning-review',json={'expected_version':1,'action':'approve','note':'验收通过'}).status_code==409
        document=client.get(base+'/learning-document').json()
        assert document['filename'].endswith('.md') and '## 操作步骤' in document['content']
        assert '请总结本次复盘' not in document['content']
        feedback=client.post(base+'/feedback',json={'expected_version':2,'outcome':'success','evidence':'附件核对通过','request_id':'f'})
        assert feedback.status_code==409
        assert len(client.get(base+'/feedback').json())==0
        result=client.post('/memory-management/learning/derive',json={'memory_ids':[mid],'action':'skill_compile','note':'提炼为可复用的复核步骤'})
        assert result.status_code==409,result.text
        app.dependency_overrides[get_current_principal]=lambda:AgentScopePrincipal(kind='service',subject='service')
        assert client.get('/memory-management/learning').status_code==403
        assert client.post(base+'/learning-review',json={'expected_version':2,'action':'suspend','note':'无权限'}).status_code==403


def test_live_platform_authorization_uses_authoritative_run_validation():
    from unittest.mock import AsyncMock
    from agentscope.app.memory._learning import PlatformLearningRuntime
    from agentscope.app.storage import MemorySettingsData
    validator = AsyncMock(return_value=access())
    runtime=PlatformLearningRuntime(storage=SimpleNamespace(),gateway=SimpleNamespace(),resources=None,
        settings_loader=AsyncMock(return_value=MemorySettingsData(learning_enabled=True, learning_model_config={'type':'custom_openai_credential','credential_id':'test','model':'test','parameters':{}})),tenant_id='t',interaction_validator=validator)
    e={'tenant_id':'t','source_type':'interaction','provenance':{'run_id':'run-1'},'access_snapshot':{}}
    async def run():
        assert (await runtime.authorize(e)).target('user_project',write=True)==('a','p')
        validator.assert_awaited_once_with(e,existing=False)
        validator.side_effect=MemoryError('identity_mismatch','学习来源会话的身份已经改变。',status=403)
        with pytest.raises(MemoryError,match='身份'):
            await runtime.authorize(e)
    asyncio.run(run())


@pytest.mark.parametrize('outcomes,event_type,job_state', [
    (['error', 'success'], 'recovery', 'pending'),
    (['success', 'error'], 'tool_failure', None),
])
def test_real_tool_event_recovery_creates_learning_job(repository, outcomes, event_type, job_state):
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.message import UserMsg,TextBlock,ToolResultState
    from agentscope.tool import ToolChunk
    harness=MemoryRunHarness(repository)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='a',agent_id='agent',session_id='s'),
        {},access_resolver=lambda:asyncio.sleep(0,result=access()),repository=repository,controller=harness.controller())
    middleware._input_sources={'u':'请修复并核对附件'}
    agent=SimpleNamespace(state=SimpleNamespace(context=[UserMsg('user','请修复并核对附件')],tasks_context=SimpleNamespace(tasks=[])))
    async def run():
        await harness.start('请修复并核对附件',mid='u')
        for call_id,outcome in zip(['z-first-call', 'a-second-call'], outcomes):
            state=ToolResultState.ERROR if outcome=='error' else ToolResultState.SUCCESS
            async def handler(**_kwargs):
                yield ToolChunk(content=[TextBlock(text='附件检查实际结果')],state=state,is_last=True)
            async for _ in middleware.on_acting(agent,{'tool_call':SimpleNamespace(id=call_id,name='verify_attachments')},handler):
                pass
        await middleware.capture_learning_turn(agent)
        await harness.finish()
        row=middleware.learning.dashboard(access(management=True))['events'][0]
        assert row['event_type']==event_type and row['state']==job_state
        assert [e['outcome'] for e in row['evidence'] if e['kind']=='tool']==outcomes
    asyncio.run(run())


def test_cross_turn_recovery_uses_only_current_owner_and_stops_repeating(repository):
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    harness=MemoryRunHarness(repository)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='a',agent_id='agent',session_id='s'),
        {},access_resolver=lambda:asyncio.sleep(0,result=access()),repository=repository,controller=harness.controller())
    middleware._input_sources={'u':'检查附件'}
    middleware._learning_trace=[{'id':'failed','kind':'tool','text':'附件缺失','outcome':'error','tool_name':'verify'}]
    agent=SimpleNamespace(state=SimpleNamespace(tasks_context=SimpleNamespace(tasks=[])))
    async def run():
        await harness.start('检查附件',mid='u')
        for evidence in middleware._learning_trace:
            await harness.controller().record_tool(evidence)
        await middleware.capture_learning_turn(agent)
        await harness.finish()
        assert middleware.learning.dashboard(access(management=True))['events'][0]['state'] is None
        assert middleware.learning.recent_failure_events(access(user='b'),scope_type='user_project',agent_id='agent',session_id='s',tool_names=['verify'])==[]
        await harness.start('附件已补充，请重新检查',mid='u2')
        middleware._input_sources={'u2':'附件已补充，请重新检查'}
        middleware._learning_trace=[{'id':'success','kind':'tool','text':'附件齐全','outcome':'success','tool_name':'verify'}]
        for evidence in middleware._learning_trace:
            await harness.controller().record_tool(evidence)
        await middleware.capture_learning_turn(agent)
        await harness.finish()
        rows=middleware.learning.dashboard(access(management=True))['events']
        assert rows[0]['event_type']=='recovery' and rows[0]['state']=='pending'
        assert middleware.learning.recent_failure_events(access(),scope_type='user_project',agent_id='agent',session_id='s',tool_names=['verify'])==[]
        await middleware.capture_learning_turn(agent)
        assert middleware.learning.dashboard(access(management=True))['total']==2
    asyncio.run(run())


def test_model_input_respects_budget_and_successful_worker_publishes_automatically(repository):
    import json
    from utils.learning_service import build_learning_input
    evidence=[{'id':str(i),'kind':'tool','text':'\\\"\n'*1300,'outcome':'success','tool_name':'check'} for i in range(20)]
    value=build_learning_input({'event_type':'explicit','evidence':evidence},[],char_limit=4000)
    assert len(value)<=4000 and json.loads(value)['evidence']
    event(repository)
    learning=LearningRepository(repository)
    async def model(e,system,prompt):
        assert 'user-1' in prompt and '助手说成功不能证明成功' in system
        return output().model_dump_json()
    result=asyncio.run(process_learning_job(learning,learning.claim('t'),authorize=lambda _:asyncio.sleep(0,result=access()),
        filter_existing=allow_fixture_context,call_model=model,settings=SimpleNamespace(learning_timeout_seconds=10)))
    assert result['candidates'][0]['status']=='active' and repository.search(access())


def test_periodic_consolidation_budget_idempotency_and_source_revocation(repository):
    learning=LearningRepository(repository)
    for i in range(3):
        event(repository)
        result=output();result.candidates[0].content+=str(i)
        mid=learning.complete(learning.claim('t'),access(),result)['candidates'][0]['memory_id']
        learning.review(access(management=True),mid,expected_version=1,action='approve',note='逐项核实')
    assert learning.maintain('t',consolidate=True,daily_limit=3)['queued']==0
    with repository._connection() as conn:
        conn.execute('DELETE FROM learning_maintenance')
    # Budget-exhausted event is retained, not silently duplicated next hour.
    assert learning.maintain('t',consolidate=True,daily_limit=30)['queued']==0
    row=learning.dashboard(access(management=True))['events'][0]
    assert row['event_type']=='consolidate'
    learning.job_action(access(management=True),row['id'],'retry')
    job=learning.claim('t')
    learning.review(access(management=True),mid,expected_version=2,action='suspend',note='新增反例')
    model=MagicMock()
    result=asyncio.run(process_learning_job(learning,job,authorize=lambda _:asyncio.sleep(0,result=access()),
        filter_existing=allow_fixture_context,call_model=model,settings=SimpleNamespace(learning_timeout_seconds=10)))
    assert result['status']=='cancelled' and result['code']=='learning_source_changed'
    model.assert_not_called()


def test_published_experience_derives_in_current_drawer_without_private_evidence(repository):
    learning=LearningRepository(repository)
    mid=candidate(repository)
    repository.manage(access(management=True),mid,expected_version=1,scope_type='project',publish=True)
    learning.review(access(management=True),mid,expected_version=2,action='approve',note='内容已脱敏并适用于项目')
    learning.derive(access(management=True),[mid],action='skill_compile',note='生成项目操作步骤')
    job=learning.claim('t')
    assert job['event']['scope_type']=='project' and job['event']['platform_user_id']==''
    assert '请总结本次复盘' not in str(job['event']['evidence'])
    with pytest.raises(MemoryError,match='私人'):
        learning.review(access(management=True),mid,expected_version=3,action='rollback',restore_version=1,note='尝试恢复旧私有版本')


def test_lease_recovery_stops_after_three_attempts(repository):
    learning=LearningRepository(repository)
    event(repository)
    for i in range(3):
        assert learning.claim('t')['attempts']==i+1
        with repository._connection() as conn:
            conn.execute("UPDATE learning_jobs SET lease_until=now()-interval '1 second'")
    assert learning.claim('t') is None
    row=learning.dashboard(access(management=True))['events'][0]
    assert row['state']=='failed' and row['error_code']=='lease_expired'


def test_success_feedback_ranks_equal_matches_without_use_count_or_auto_validation(repository):
    learning=LearningRepository(repository)
    ids=[]
    for i in range(2):
        event(repository);o=output();o.candidates[0].limitations+=str(i)
        mid=learning.complete(learning.claim('t'),access(),o)['candidates'][0]['memory_id']
        learning.review(access(management=True),mid,expected_version=1,action='approve',note='逐项验证')
        ids.append(mid)
    learning.feedback(access(),ids[0],expected_version=2,outcome='success',evidence='按步骤验收通过',request_id='real')
    with repository._connection() as conn:
        conn.execute('UPDATE memory_records SET use_count=1000 WHERE id=%s',(ids[1],))
    results=repository.search(access(),query='附件')
    assert [r['id'] for r in results]==ids
    assert results[0]['feedback_support']==1 and results[1]['feedback_support']==0


def test_platform_learning_uses_configured_model_and_streamed_final_content(monkeypatch):
    from unittest.mock import AsyncMock
    from agentscope.app.memory import _learning as runtime_module
    from agentscope.app.storage import ChatModelConfig,MemorySettingsData
    selected=ChatModelConfig(type='custom_openai_credential',credential_id='learning-model',model='test',parameters={})
    settings=MemorySettingsData(learning_enabled=True, learning_model_config=selected)
    resources=SimpleNamespace(resolve_credential=AsyncMock(return_value=SimpleNamespace(data={})))
    monkeypatch.setattr(runtime_module.CredentialFactory,'from_dict',lambda _:SimpleNamespace(type=selected.type))
    monkeypatch.setattr(runtime_module,'build_credential_model_catalog',lambda _:[SimpleNamespace(name='test',enabled=True)])
    async def model(messages):
        assert messages[0].role=='system' and messages[1].role=='user'
        yield {'content':[{'type':'text','text':'{"reason":'}]}
        yield {'content':[{'type':'text','text':output().model_dump_json()}]}
    factory=AsyncMock(return_value=model)
    monkeypatch.setattr(runtime_module,'get_model',factory)
    runtime=runtime_module.PlatformLearningRuntime(storage=SimpleNamespace(),gateway=None,resources=resources,
        settings_loader=AsyncMock(return_value=settings),tenant_id='t')
    result=asyncio.run(runtime.call_model({'config_owner':'owner','source_type':'interaction'},'学习系统提示','学习证据'))
    assert result==output().model_dump_json()
    assert factory.await_args.args==('owner',selected,resources)


def test_relevant_verified_skill_is_injected_with_profile_and_cleaned_after_reply(repository):
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.message import UserMsg
    from agentscope.event import ReplyStartEvent,ReplyEndEvent
    learning=LearningRepository(repository)
    write(repository,key='profile.name')
    harness=MemoryRunHarness(repository)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='a',agent_id='agent',session_id='s'),
        {},access_resolver=lambda:asyncio.sleep(0,result=access()),repository=repository,controller=harness.controller())
    agent=SimpleNamespace(state=SimpleNamespace(context=[],tasks_context=SimpleNamespace(tasks=[])))
    async def handler(**_kwargs):
        yield ReplyStartEvent(session_id='s',reply_id='r',name='agent')
        texts='\n'.join(m.get_text_content() for m in agent.state.context)
        assert '雷淦文' in texts and '先核对附件清单' in texts and '不授予工具权限' in texts
        yield ReplyEndEvent(session_id='s',reply_id='r')
    async def run():
        await harness.start('请总结本次复盘：先核对附件清单，然后逐个验收。', mid='user-1')
        await harness.controller().request_learning('explicit')
        await harness.finish()
        job=learning.claim('t')
        assert job is not None
        mid=learning.complete(job,access(),output('skill'))['candidates'][0]['memory_id']
        learning.review(access(management=True),mid,expected_version=1,action='approve',note='验收通过')
        async for _ in middleware.on_reply(agent,{'inputs':[UserMsg('user','请帮助我核对附件清单并执行验收')]},handler):
            pass
        return mid
    mid=asyncio.run(run())
    assert agent.state.context==[] and repository.get(access(),mid)['use_count']==1


def test_profile_context_binds_preferred_address_to_authenticated_account(repository):
    import json
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.message import UserMsg,SystemMsg
    from agentscope.event import ReplyStartEvent,ReplyEndEvent
    actor=access(user='17')
    write(repository,actor=actor,key='profile.name',content='用户的姓名是雷淦文')
    write(repository,actor=actor,key='profile.address',content='用户希望被称呼为「雷总」')
    write(repository,actor=access(user='18'),key='profile.address',content='另一个用户的称呼')
    harness=MemoryRunHarness(repository,actor=actor)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='17',agent_id='agent',session_id='s'),
        {'learning_skill_limit':0},access_resolver=lambda:asyncio.sleep(0,result=actor),repository=repository,controller=harness.controller())
    platform=SystemMsg('platform','当前登录用户ID：17；账号显示名：群聊测试甲；系统角色：admin')
    agent=SimpleNamespace(state=SimpleNamespace(context=[platform],tasks_context=SimpleNamespace(tasks=[])))
    async def handler(**_kwargs):
        yield ReplyStartEvent(session_id='s',reply_id='r',name='agent')
        text=agent.state.context[-1].get_text_content()
        payload=json.loads(text.split('\n',1)[1])
        assert payload['owner']=={'identity_type':'business_user','user_id':'17'}
        preferences={r['fact_key']:r for r in payload['preferences']}
        assert preferences['profile.address']['content']=='用户希望被称呼为「雷总」'
        assert preferences['profile.name']['meaning']=='用户自报姓名（非认证身份）'
        assert '仅名称不同不构成身份冲突' in text and '当前用户明确要求的称呼优先' in text
        assert '另一个用户' not in text
        yield ReplyEndEvent(session_id='s',reply_id='r')
    async def run():
        async for _ in middleware.on_reply(agent,{'inputs':[UserMsg('user','今天有什么需要我处理的吗')]},handler):
            pass
    asyncio.run(run())
    assert agent.state.context==[platform]


def test_delegated_agent_only_receives_current_project_preferences(repository):
    import json
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.message import UserMsg
    from agentscope.event import ReplyStartEvent, ReplyEndEvent
    write(repository, key='profile.name', content='不应向协作节点注入的跨项目姓名')
    write(repository, scope='user_project', key='preference.response_detail', content='本项目的报告要求简洁')
    harness = MemoryRunHarness(repository, depth=2)
    controller = harness.controller('child-1')
    middleware = ThreeDrawerMemoryMiddleware(MagicMock(), MemoryRuntime().scope(
        project_id='p', platform_user_id='a', agent_id='agent-1', session_id='child-1'),
        {'learning_skill_limit': 0}, access_resolver=controller.access,
        repository=repository, controller=controller)
    agent = SimpleNamespace(state=SimpleNamespace(context=[], tasks_context=SimpleNamespace(tasks=[])))
    async def handler(**_):
        yield ReplyStartEvent(session_id='child-1', reply_id='child-reply', name='agent-1')
        payload = json.loads(agent.state.context[-1].get_text_content().split('\n', 1)[1])
        assert [(row['scope_type'], row['content']) for row in payload['preferences']] == [
            ('user_project', '本项目的报告要求简洁')]
        yield ReplyEndEvent(session_id='child-1', reply_id='child-reply')
    async def run():
        await harness.start('协助处理本项目的附件清单')
        async for _ in middleware.on_reply(agent, {'inputs': [UserMsg('上级智能体', '执行附件检查')]}, handler):
            pass
    asyncio.run(run())
    assert agent.state.context == []


def test_completion_requires_tool_evidence_and_user_can_decline_learning(repository):
    from unittest.mock import AsyncMock
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    harness=MemoryRunHarness(repository)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='a',agent_id='agent',session_id='s'),
        {},access_resolver=lambda:asyncio.sleep(0,result=access()),repository=repository,controller=harness.controller())
    capture=AsyncMock();middleware.capture_learning=capture
    task=SimpleNamespace(model_dump=lambda **_:dict(id='task1',state='completed',subject='附件验收'))
    agent=SimpleNamespace(state=SimpleNamespace(tasks_context=SimpleNamespace(tasks=[task])))
    async def run():
        middleware._input_sources={'u':'完成附件验收'}
        await middleware.capture_learning_turn(agent)
        capture.assert_not_awaited()
        middleware._learning_trace=[dict(id='check',kind='tool',tool_name='verify',text='附件齐全',outcome='success')]
        await middleware.capture_learning_turn(agent)
        assert capture.await_args.args[0]=='recovery'
        assert not any(e.get('id')=='task:task1' for e in capture.await_args.args[1])
        middleware._learning_trace.extend([dict(id=f'check-{i}',kind='tool',tool_name='verify',text='实际复核成功',outcome='success') for i in (2,3)])
        await middleware.capture_learning_turn(agent)
        assert capture.await_args.args[0]=='recovery'
        assert len([e for e in capture.await_args.args[1] if e['kind']=='tool'])==3
        assert not any(e.get('id')=='task:task1' for e in capture.await_args.args[1])
        capture.reset_mock()
        middleware._input_sources={'u2':'本次不要复盘或学习'}
        await middleware.capture_learning_turn(agent)
        capture.assert_not_awaited()
        middleware._input_sources={'u3':'修复附件检查'}
        middleware._learning_trace.append(dict(id='failed',kind='tool',tool_name='verify',text='附件仍然缺失',outcome='error'))
        await middleware.capture_learning_turn(agent)
        assert capture.await_args.args[0]=='tool_failure' and capture.await_args.kwargs['enqueue'] is False
    asyncio.run(run())


@pytest.mark.parametrize('failure',['timeout','invalid_json'])
def test_background_failures_retry_with_backoff_then_stop(repository,failure):
    learning=LearningRepository(repository)
    event(repository)
    async def model(*_):
        if failure=='timeout':
            await asyncio.sleep(1)
        return 'not a learning result'
    async def run():
        for attempt in range(1,4):
            await process_learning_job(learning,learning.claim('t'),authorize=lambda _:asyncio.sleep(0,result=access()),
                filter_existing=allow_fixture_context,call_model=model,settings=SimpleNamespace(learning_timeout_seconds=0.001))
            row=learning.dashboard(access(management=True))['events'][0]
            assert row['state']==('failed' if attempt==3 else 'pending')
            assert row['attempts']==attempt and row['error_code']
            assert learning.claim('t') is None
            with repository._connection() as conn:
                conn.execute("UPDATE learning_jobs SET available_at=now() WHERE state='pending'")
    asyncio.run(run())
    assert repository.list(access(),status='candidate')['total']==0


@pytest.mark.parametrize('depth', [1, 2])
def test_explicit_fact_correction_is_saved_without_duplicate_learning(repository, depth):
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.message import ToolResultState
    harness=MemoryRunHarness(repository,depth=depth)
    middleware=ThreeDrawerMemoryMiddleware(MagicMock(),MemoryRuntime().scope(project_id='p',platform_user_id='a',agent_id='agent',session_id='s'),
        {},access_resolver=lambda:asyncio.sleep(0,result=access()),repository=repository,controller=harness.controller())
    middleware._input_sources={'u':'名字错了，我叫测试甲'}
    middleware._previous_answer='你好，测试乙'
    agent=SimpleNamespace(state=SimpleNamespace(tasks_context=SimpleNamespace(tasks=[])))
    async def run():
        await harness.start('名字错了，我叫测试甲',mid='u')
        tool=(await middleware.list_tools())[0]
        result=await tool.call(items=[{'scope_type':'user','content':'测试甲','fact_key':'profile.name'}])
        assert result.state==ToolResultState.SUCCESS
        assert bool(repository.search(access(),fact_key='profile.name')) is (depth == 1)
        await middleware.capture_learning_turn(agent)
        assert middleware.learning.dashboard(access(management=True))['total']==0
        await harness.finish()
        assert middleware.learning.dashboard(access(management=True))['total']==0
        assert repository.search(access(),fact_key='profile.name')[0]['content']=='测试甲'
    asyncio.run(run())


def test_idle_worker_does_not_repeat_hourly_maintenance_on_every_poll(monkeypatch):
    from unittest.mock import AsyncMock
    from utils.learning_service import run_learning_worker
    from agentscope.app.storage import MemorySettingsData
    repository=MagicMock()
    repository.maintain.return_value={'review_due':0}
    repository.claim.return_value=None
    sleeps=0
    async def sleep(_):
        nonlocal sleeps
        sleeps+=1
        if sleeps==2:
            raise asyncio.CancelledError
    monkeypatch.setattr(asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_learning_worker(repository,tenant_id='t',settings_loader=AsyncMock(return_value=MemorySettingsData(learning_enabled=True, learning_model_config={'type':'custom_openai_credential','credential_id':'test','model':'test','parameters':{}})),
            authorize=AsyncMock(),authorize_existing=AsyncMock(),filter_existing=AsyncMock(),call_model=AsyncMock()))
    repository.maintain.assert_called_once()
    assert repository.claim.call_count==2


def test_legacy_candidate_automatic_check_uses_live_authorization_and_cas(repository):
    from utils.learning_service import reconcile_automatic_memories
    learning=LearningRepository(repository)
    mid=candidate(repository)
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET status='candidate',learning=learning || '{\"validation_state\":\"unverified\"}'::jsonb WHERE id=%s",(mid,))
    row=learning.automatic_check_queue('t')[0]
    calls=[]
    async def authorize(e):
        calls.append(e['id'])
        return access()
    asyncio.run(reconcile_automatic_memories(learning,'t',authorize,authorize))
    current=repository.get(access(),mid)
    assert calls and current['status']=='active' and current['version']==2
    assert learning.automatic_check_queue('t')==[]
    repository.manage(access(management=True),mid,expected_version=2,status='deleted')
    assert not learning.finish_automatic_check(row,access())
    assert repository.get(access(management=True),mid)['status']=='deleted'


def test_automatic_check_rejects_revoked_sources_and_defers_transient_errors(repository):
    from utils.learning_service import reconcile_automatic_memories
    learning=LearningRepository(repository)
    mid=candidate(repository)
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET status='candidate' WHERE id=%s",(mid,))
    async def unavailable(e):
        raise TimeoutError()
    asyncio.run(reconcile_automatic_memories(learning,'t',unavailable,unavailable))
    assert repository.get(access(),mid)['status']=='candidate'
    assert learning.automatic_check_queue('t')==[]
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET learning=learning-'auto_check_after' WHERE id=%s",(mid,))
    async def revoked(e):
        raise MemoryError('learning_scope_changed','权限已改变',status=403)
    asyncio.run(reconcile_automatic_memories(learning,'t',revoked,revoked))
    assert repository.get(access(),mid)['status']=='inactive'
    assert learning.automatic_check_queue('t')==[]


def test_automatic_check_revalidates_aging_without_waiting_for_a_person(repository):
    from utils.learning_service import reconcile_automatic_memories
    learning=LearningRepository(repository)
    mid=candidate(repository)
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET learning=learning || jsonb_build_object('reviewed_at',(now()-interval '100 days')::text) WHERE id=%s",(mid,))
    assert learning.maintain('t')['review_due']==1
    asyncio.run(reconcile_automatic_memories(learning,'t',lambda _:asyncio.sleep(0,result=access()),lambda _:asyncio.sleep(0,result=access())))
    assert repository.search(access())
    assert repository.get(access(management=True),mid)['learning']['validation_method']=='automatic_v1'


def test_automatic_publication_does_not_treat_failure_as_success(repository):
    learning=LearningRepository(repository)
    learning.capture(access(),scope_type='user_project',agent_id='agent',session_id='s',config_owner='o',event_key='failure',
        event_type='tool_failure',delay_seconds=0,evidence=[{'id':'user-1','kind':'tool','text':'执行失败','outcome':'error'}])
    with pytest.raises(MemoryError,match='失败记录'):
        learning.complete(learning.claim('t'),access(),output())
    assert repository.list(access())['total']==0


def test_failed_learning_job_retries_after_daily_cooldown(repository):
    learning=LearningRepository(repository)
    event(repository)
    job=learning.claim('t')
    with repository._connection() as conn:
        conn.execute("UPDATE learning_jobs SET state='failed',attempts=3,lease_id=NULL,lease_until=NULL WHERE id=%s",(job['id'],))
    assert learning.claim('t') is None
    with repository._connection() as conn:
        conn.execute("UPDATE learning_jobs SET updated_at=now()-interval '2 days' WHERE id=%s",(job['id'],))
    retried=learning.claim('t')
    assert retried['id']==job['id'] and retried['attempts']==4
