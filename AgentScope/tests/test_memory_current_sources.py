"""Immediate authorization for learned and knowledge-derived memory, before injection."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from psycopg.types.json import Jsonb
import pytest

from test_memory_repository import repository, access, write
from agentscope.app.memory._source_validation import (
    filter_current_memory_results, knowledge_learning_evidence, validate_tool_knowledge_source,
)
from utils.memory_repository import MemoryError


def knowledge_block():
    return SimpleNamespace(name='weknora_query_project_knowledge',
        output=json.dumps({'answer':'不可进入长期记忆的资料原文', 'references':[{'knowledge_id':'doc'}]}),
        metadata={'operation':'weknora_query_project_knowledge','knowledge_ids':['doc'],
            'platform_user_id':'u','platform_project_id':'p','platform_conversation_id':'c','weknora_robot_id':'robot'})


@pytest.mark.asyncio
async def test_tool_knowledge_rechecks_live_document_scope_and_redacts_raw_answer():
    session = SimpleNamespace(id='root', agent_id='knowledge', team_id=None,
        config=SimpleNamespace(platform_context=SimpleNamespace(user_id='u',project_id='p',session_role='primary')))
    storage = SimpleNamespace(get_session=AsyncMock(return_value=session))
    scope={'user_id':'u','project_id':'p','conversation_id':'c','weknora_agent_id':'robot',
        'weknora_query_enabled':True,'weknora_catalogue_ready':True,'weknora_knowledge_ids':['doc']}
    gateway=SimpleNamespace(resolve_knowledge_scope=AsyncMock(return_value=scope))
    block=knowledge_block()
    await validate_tool_knowledge_source(storage,gateway,'owner','root',block)
    assert '不可进入长期记忆的资料原文' not in knowledge_learning_evidence(block)
    gateway.resolve_knowledge_scope.assert_awaited_once_with(session_id='root',actor_agent_id='knowledge')
    scope['weknora_knowledge_ids']=[]
    with pytest.raises(MemoryError,match='权限或绑定'):
        await validate_tool_knowledge_source(storage,gateway,'owner','root',block)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing_ids','unstructured','forged_reference','missing_gateway'])
async def test_tool_knowledge_unverifiable_sources_fail_closed(change):
    block=knowledge_block()
    if change=='missing_ids': block.metadata.pop('knowledge_ids')
    if change=='unstructured': block.output='资料查询成功。'
    if change=='forged_reference': block.output=json.dumps({'references':[{'knowledge_id':'other'}]})
    with pytest.raises(MemoryError):
        await validate_tool_knowledge_source(None,None if change=='missing_gateway' else object(),'owner','root',block)


@pytest.mark.asyncio
async def test_memory_read_authorizes_full_event_and_immediate_revocation(repository):
    memory=write(repository,scope='user_project')['memory']
    event_id=uuid4()
    provenance={'derived_sources':[{'source_type':'interaction','provenance':{'source_refs':[{'hash':'original'}]}}]}
    with repository._connection() as conn:
        conn.execute("INSERT INTO learning_events(id,tenant_id,identity_type,scope_type,platform_user_id,project_id,agent_id,session_id,config_owner,event_key,event_type,evidence,fingerprint,access_snapshot,provenance) VALUES(%s,'t','business_user','user_project','a','p','agent','session','owner','key','verified_task','{}','hash','{}',%s)", (event_id,Jsonb(provenance)))
        conn.execute('UPDATE memory_records SET origin=%s,learning=%s WHERE id=%s',('learning',Jsonb({'event_id':str(event_id)}),memory['id']))
    rows=repository.search(access())
    runtime=SimpleNamespace(authorize_existing=AsyncMock())
    assert await filter_current_memory_results(None,None,'t','owner',rows,repository=repository,learning_runtime=runtime)==rows
    assert runtime.authorize_existing.await_args.args[0]['provenance']==provenance
    runtime.authorize_existing.side_effect=MemoryError('revoked','资料已经撤权',status=403)
    assert await filter_current_memory_results(None,None,'t','owner',rows,repository=repository,learning_runtime=runtime)==[]
    # No background pass or status update is required to block this very next read.
    assert repository.search(access())


@pytest.mark.asyncio
async def test_memory_results_reject_stale_version_missing_event_and_wrong_tenant(repository):
    memory=write(repository,scope='user_project')['memory']
    rows=repository.search(access())
    runtime=SimpleNamespace(authorize_existing=AsyncMock())
    with repository._connection() as conn:
        conn.execute('UPDATE memory_records SET version=version+1 WHERE id=%s',(memory['id'],))
    assert await filter_current_memory_results(None,None,'t','owner',rows,repository=repository,learning_runtime=runtime)==[]
    rows=repository.search(access())
    with repository._connection() as conn:
        conn.execute('UPDATE memory_records SET origin=%s,learning=%s WHERE id=%s',('learning',Jsonb({'event_id':str(uuid4())}),memory['id']))
    assert await filter_current_memory_results(None,None,'t','owner',rows,repository=repository,learning_runtime=runtime)==[]
    assert await filter_current_memory_results(None,None,'other','owner',rows,repository=repository,learning_runtime=runtime)==[]


@pytest.mark.asyncio
async def test_explicit_user_fact_survives_source_session_cleanup(repository):
    memory=write(repository,scope='user_project')['memory']
    with repository._connection() as conn:
        conn.execute('UPDATE memory_records SET source=%s WHERE id=%s',
            (Jsonb({'kind':'run_memory','source_refs':[{'kind':'user','session_id':'deleted','message_id':'deleted','hash':'saved'}]}),memory['id']))
    rows=repository.search(access())
    storage=SimpleNamespace(get_message=AsyncMock(return_value=None))
    runtime=SimpleNamespace(authorize_existing=AsyncMock())
    assert await filter_current_memory_results(storage,None,'t','owner',rows,repository=repository,learning_runtime=runtime)==rows
    storage.get_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('no_memory',[False,True])
async def test_derived_homepage_task_input_is_not_new_user_evidence(repository,no_memory):
    from memory_run_test_support import MemoryRunHarness
    from agentscope.message import UserMsg
    from agentscope.app.memory._run_context import resolve_agent_memory_access
    harness=MemoryRunHarness(repository)
    original_scope=harness.gateway.resolve_memory_scope
    async def scope(sid):
        return {**await original_scope(sid),'input_is_derived':True,'inherited_no_memory':no_memory,'inherited_no_learning':False}
    harness.gateway.resolve_memory_scope=scope
    msg=UserMsg('用户','根据首页复制的上下文生成草稿')
    await harness.persist_inputs([msg])
    controller=harness.controller()
    await controller.begin([msg])
    access,_=await resolve_agent_memory_access(harness.storage,harness.gateway,'t','owner','agent','s')
    assert access.write_scopes==() and not access.learning_enabled
    assert bool(access.read_scopes) is not no_memory
    if no_memory:
        assert not access.learning_use
    assert controller.journal.sources('t',controller.run_id)==[]
    # Suppression of copied input is not itself an explicit no-learning instruction.
    assert not controller.journal.get('t',controller.run_id)['no_learning']
