"""New request-level memory lifecycle, using disposable real PostgreSQL storage."""
import asyncio
from dataclasses import replace

import pytest

from test_memory_repository import repository, access
from memory_run_test_support import MemoryRunHarness
from agentscope.app.memory._run_context import resolve_agent_memory_access, session_chain, validate_source_refs, validate_learning_event
from agentscope.message import UserMsg, AssistantMsg
from utils.memory_repository import MemoryError, MemoryWrite


def item(content='周报列出问题、责任人和期限', scope='user_project'):
    return MemoryWrite(scope_type=scope, content=content, fact_key='preference.weekly_report')


@pytest.mark.parametrize('prompt,can_retain,can_learn', [
    ('记住我的周报格式', True, True), ('本次不要学习，记住我的周报格式', True, False),
    ('本次不要记忆', False, False),
])
def test_user_request_controls_this_run_without_deleting_existing_memory(repository, prompt, can_retain, can_learn):
    h = MemoryRunHarness(repository)
    repository.write(access(), [item()], request_id='existing-fact', source={'message_id': 'prior-user'})
    async def run():
        await h.start(prompt)
        resolved = await h.controller().access()
        assert set(resolved.read_scopes) == ({'user', 'user_project', 'project'} if can_retain else set())
        assert resolved.learning_use is can_retain
        assert resolved.learning_enabled is can_learn
        if can_retain:
            assert repository.search(resolved)[0]['content'] == item().content
            assert set(resolved.write_scopes) == {'user', 'user_project', 'project'}
            update = item('按问题清单组织周报').model_copy(update={'expected_version': 1})
            assert (await h.controller().submit('write', [update]))['status'] == 'saved'
        else:
            assert resolved.write_scopes == ()
            assert repository.search(resolved) == []
            with pytest.raises(MemoryError): await h.controller().submit('write', [item()])
            assert repository.search(access())[0]['content'] == item().content
        if not can_learn:
            with pytest.raises(MemoryError): await h.controller().request_learning('explicit')
    asyncio.run(run())


@pytest.mark.parametrize('role_field,expected_read,expected_write,expected_learning', [
    ('global_main_agent_id', {'user', 'user_project', 'project'}, {'user', 'user_project', 'project'}, True),
    ('project_initializer_agent_id', {'project'}, set(), False),
    ('knowledge_agent_id', {'user', 'user_project', 'project'}, {'user_project'}, True),
    ('task_assistant_agent_id', {'user', 'user_project', 'project'}, {'user', 'user_project'}, True),
])
def test_fixed_main_roles_apply_system_memory_rules(repository, role_field, expected_read, expected_write, expected_learning):
    h = MemoryRunHarness(repository)
    setattr(h, role_field, 'agent')
    async def run():
        await h.start()
        resolved = await h.controller().access()
        assert set(resolved.read_scopes) == expected_read
        assert set(resolved.write_scopes) == expected_write
        assert resolved.learning_enabled is expected_learning
        assert resolved.learning_use
    asyncio.run(run())


@pytest.mark.parametrize('role_field,expected_write', [
    ('knowledge_agent_id', {'user_project'}), ('task_assistant_agent_id', {'user', 'user_project'}),
])
def test_business_descendants_cannot_expand_fixed_parent_memory_scope(repository, role_field, expected_write):
    h = MemoryRunHarness(repository, depth=3)
    setattr(h, role_field, 'agent')
    async def run():
        await h.start()
        leaf = await h.controller('child-2').access()
        assert set(leaf.read_scopes) == {'user_project', 'project'}
        assert set(leaf.write_scopes) == expected_write
        for denied_scope in {'user', 'user_project', 'project'} - expected_write:
            with pytest.raises(MemoryError):
                await h.controller('child-2').submit('write', [item(scope=denied_scope)])
    asyncio.run(run())


def test_initialization_is_read_only_through_the_entire_collaboration_chain(repository):
    h = MemoryRunHarness(repository, depth=3)
    h.project_initializer_agent_id = 'agent'
    h.entry_kind = 'initialization'
    async def run():
        await h.start('生成初始化草稿')
        for controller in h.controllers.values():
            resolved = await controller.access()
            assert resolved.read_scopes == ('project',)
            assert resolved.write_scopes == ()
            assert not resolved.learning_enabled and resolved.learning_use
            with pytest.raises(MemoryError): await controller.submit('write', [item(scope='project')])
            with pytest.raises(MemoryError): await controller.request_learning('explicit')
        await h.finish()
        assert h.service.learning.dashboard(access(management=True))['events'] == []
    asyncio.run(run())


@pytest.mark.parametrize('group_learning_enabled', [True, False])
def test_group_interactions_never_read_private_drawers_or_bypass_group_learning_pipeline(repository, group_learning_enabled):
    h = MemoryRunHarness(repository, actor=access(private=False), depth=3)
    h.entry_kind = 'group_chat'
    h.settings = h.settings.model_copy(update={'group_learning_enabled':group_learning_enabled})
    async def run():
        await h.start('记住群聊确认的项目周报格式')
        for controller in h.controllers.values():
            resolved = await controller.access()
            assert resolved.read_scopes == resolved.write_scopes == ('project',)
            assert not resolved.learning_enabled and resolved.learning_use
            with pytest.raises(MemoryError): await controller.request_learning('explicit')
            for scope in ('user', 'user_project'):
                with pytest.raises(MemoryError): resolved.target(scope)
                with pytest.raises(MemoryError): await controller.submit('write', [item(scope=scope)])
        assert (await h.controller('child-2').submit('write', [item(scope='project')]))['status'] == 'pending'
        await h.finish()
        assert repository.search(access(private=False))[0]['scope_type'] == 'project'
        assert h.service.learning.dashboard(access(management=True))['events'] == []
    asyncio.run(run())


def test_three_level_candidates_are_unified_after_completion(repository):
    h = MemoryRunHarness(repository, depth=3)
    async def run():
        await h.start()
        leaf = h.controller('child-2')
        first = await leaf.submit('write', [item()])
        repeated = await h.controller('child-1').submit('write', [item()])
        assert first['status'] == repeated['status'] == 'pending'
        assert first['proposal_id'] == repeated['proposal_id']
        assert repository.list(access())['total'] == 0
        await h.finish()
        assert repository.list(access())['total'] == 1
        proposal = h.service.journal.pending('t', leaf.run_id)
        assert proposal == []
    asyncio.run(run())


def test_delegation_excludes_cross_project_profile_and_rechecks_live_project_authority(repository):
    h = MemoryRunHarness(repository, depth=3)
    async def run():
        await h.start()
        resolved, chain = await resolve_agent_memory_access(h.storage, h.gateway, 't', 'owner', 'agent-2', 'child-2', write=True)
        assert [s.id for s in chain] == ['child-2', 'child-1', 's']
        assert set((await h.controller().access()).read_scopes) == {'user', 'user_project', 'project'}
        assert set(resolved.read_scopes) == {'user_project', 'project'}
        assert set(resolved.write_scopes) == {'user', 'user_project', 'project'}
        h.actor = replace(h.actor, project_write=False)
        restricted = await h.controller('child-2').access()
        assert restricted.read_scopes == resolved.read_scopes and restricted.learning_use
        with pytest.raises(MemoryError): await h.controller('child-2').submit('write', [item(scope='project')])
        # A project permission change cannot erase the authenticated user's
        # private project drawer or turn it into a shared write grant.
        assert restricted.target('user_project', write=True) == ('a', 'p')
    asyncio.run(run())


@pytest.mark.parametrize('tamper', ['user', 'project', 'role', 'root', 'roster', 'cycle'])
def test_saved_chain_rejects_identity_and_membership_forgery(repository, tamper):
    h = MemoryRunHarness(repository, depth=3)
    child = h.sessions['child-2']
    if tamper == 'user': child.config.platform_context.user_id = 'other'
    if tamper == 'project': child.config.platform_context.project_id = 'other'
    if tamper == 'role': child.config.platform_context.session_role = 'primary'
    if tamper == 'root': child.config.platform_context.root_session_id = 'forged'
    if tamper == 'roster': h.team.data.members[-1].agent_id = 'forged'
    if tamper == 'cycle': h.team.data.members[-1].inviter_session_id = 'child-2'
    with pytest.raises(MemoryError):
        asyncio.run(session_chain(h.storage, 'owner', child))


def test_gateway_identity_is_rechecked_and_private_data_stays_out_of_groups(repository):
    h = MemoryRunHarness(repository, depth=3)
    async def run():
        await h.start()
        h.actor = replace(h.actor, private=False)
        resolved = await h.controller('child-2').access()
        with pytest.raises(MemoryError): resolved.target('user')
        assert resolved.target('project') == ('', 'p')
        h.actor = replace(h.actor, user_id='another')
        with pytest.raises(MemoryError, match='身份'):
            await h.controller('child-2').access()
    asyncio.run(run())


@pytest.mark.parametrize('text,no_memory,no_learning', [
    ('本次不要记忆', True, True), ('本次不要学习', False, True),
    ('本次不需要记忆', True, True), ('本次不需要学习，记住我的周报格式', False, True),
])
def test_user_exclusions_apply_to_every_child(repository, text, no_memory, no_learning):
    h = MemoryRunHarness(repository, depth=3)
    async def run():
        await h.start(text)
        for controller in h.controllers.values():
            resolved = await controller.access()
            assert resolved.learning_enabled is not no_learning
            if no_memory:
                assert resolved.read_scopes == resolved.write_scopes == ()
                with pytest.raises(MemoryError): await controller.submit('write', [item()])
            with pytest.raises(MemoryError): await controller.request_learning('explicit')
        if not no_memory:
            assert (await h.controller().submit('write', [item()]))['status'] == 'pending'
            await h.finish()
            assert repository.list(access())['total'] == 1
    asyncio.run(run())


@pytest.mark.parametrize('text,learning_enabled', [
    ('本次不要学习，记住我的周报格式', False),
    ('本次不要学习但记住我的周报格式', False),
    ('本次不需要学习，记住我的周报格式', False),
    ('不要调用工具，记住我的周报格式', True),
])
def test_no_learning_still_allows_direct_user_facts_immediately(repository, text, learning_enabled):
    h = MemoryRunHarness(repository)
    async def run():
        await h.start(text)
        assert (await h.controller().submit('write', [item()]))['status'] == 'saved'
        assert repository.list(access())['total'] == 1
        assert (await h.controller().access()).learning_enabled is learning_enabled
    asyncio.run(run())


def test_worker_scans_past_fifty_waiting_runs(repository, monkeypatch):
    h = MemoryRunHarness(repository)
    journal = h.service.journal
    for index in range(51):
        journal.begin('t', f'waiting-{index:02}', 'owner', f's-{index}', 'agent')
    processed = []
    async def waiting_process(run, settings):
        processed.append(run['run_id'])
    monkeypatch.setattr(h.service, 'process', waiting_process)
    async def run():
        await h.service.scan(h.settings)
        assert len(set(processed)) == 50
        assert 'waiting-50' not in processed
        await h.service.scan(h.settings)
        assert len(set(processed)) == 51
        assert processed[50] == 'waiting-50'
        assert all(journal.get('t', key)['state'] == 'active' for key in set(processed))
    asyncio.run(run())


def test_debug_uses_separate_identity_and_never_learns(repository):
    h = MemoryRunHarness(repository, debug=True)
    async def run():
        await h.start('记住我的称呼是测试用户')
        debug = await h.controller().access()
        assert debug.user_id == 'debug:owner:s' and debug.identity_type == 'management_user'
        assert not debug.learning_enabled
        await h.controller().submit('write', [item(scope='user')])
        assert repository.list(access())['total'] == 0
        assert repository.list(debug)['total'] == 1
    asyncio.run(run())


def test_changed_original_source_prevents_candidate_commit(repository):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        msg = await h.start()
        await h.controller('child-1').submit('write', [item()])
        h.messages[('s', msg.id)] = UserMsg('user', '已撤回原先的要求', id=msg.id)
        with pytest.raises(MemoryError, match='修改'):
            await h.finish()
        assert repository.list(access())['total'] == 0
    asyncio.run(run())


def test_cancelled_root_does_not_commit_children(repository):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start()
        await h.controller('child-1').submit('write', [item()])
        result = await h.finish(reason='interrupted')
        assert result['state'] == 'cancelled'
        assert repository.list(access())['total'] == 0
        with pytest.raises(MemoryError): await h.controller('child-1').submit('write', [item()])
    asyncio.run(run())


def test_old_child_cannot_write_when_root_has_a_new_request(repository):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start()
        h.sessions['s'].config.memory_run_id = 'new-request'
        with pytest.raises(MemoryError, match='替代'):
            await h.controller('child-1').submit('write', [item()])
    asyncio.run(run())


def test_old_controller_cannot_write_after_its_session_is_rebound_to_a_new_run(repository):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start(mid='old-request')
        old_child=h.controller('child-1')
        original_run=old_child.run_id
        await h.controller().begin([UserMsg('user', '新一轮任务', id='new-request')])
        assert h.sessions['s'].config.memory_run_id == h.sessions['child-1'].config.memory_run_id
        assert h.sessions['child-1'].config.memory_run_id != original_run
        with pytest.raises(MemoryError) as exc:
            await old_child.submit('write', [item()])
        assert exc.value.code == 'run_superseded'
        assert repository.list(access())['total'] == 0
    asyncio.run(run())


def test_candidate_and_memory_write_rollback_together(repository, monkeypatch):
    h = MemoryRunHarness(repository)
    original = repository.write
    def fail_after_memory_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated commit failure')
    async def run():
        await h.start()
        monkeypatch.setattr(repository, 'write', fail_after_memory_write)
        with pytest.raises(RuntimeError, match='simulated'):
            await h.controller().submit('write', [item()])
        assert repository.list(access())['total'] == 0
        assert len(h.service.journal.pending('t', h.controller().run_id)) == 1
        monkeypatch.setattr(repository, 'write', original)
        saved = await h.controller().submit('write', [item()])
        assert saved['status'] == 'saved'
        assert repository.list(access())['total'] == 1
        repeated = await h.controller().submit('write', [item()])
        assert repeated['status'] == 'unchanged'
        assert repository.list(access())['total'] == 1
    asyncio.run(run())


def test_root_cannot_relay_a_candidate_after_contributor_is_disabled(repository):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start()
        await h.controller('child-1').submit('write', [item()])
        await h.controller('child-1').reply_started('child-reply')
        h.messages[('child-1', 'child-reply')] = AssistantMsg('agent-1', '完成', id='child-reply',
            finished_at='2026-09-10T10:00:00+08:00', finished_reason='completed')
        h.agents['agent-1'].data.platform_config.enabled = False
        with pytest.raises(MemoryError): await h.controller().submit('write', [item()])
        assert repository.list(access())['total'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('target_sid', ['s', 'child-2'])
def test_user_memory_exclusion_cannot_be_laundered_by_a_new_parent_or_sibling_payload(repository, target_sid):
    h = MemoryRunHarness(repository, depth=3)
    # Changing the reporting path must not create a fresh business request.
    h.team.data.members[-1].inviter_session_id = 's'
    async def run():
        await h.start('本次不要记忆。请专家检查项目资料，并汇总执行结果')
        for sid in ('child-1', 'child-2'):
            child = h.controller(sid)
            await child.reply_started(f'{sid}-reply')
            h.messages[(sid, child.reply_id)] = AssistantMsg(h.sessions[sid].agent_id,
                '专家检查结果：这段材料属于不长期保留的交互。', id=child.reply_id,
                finished_at='2026-09-10T10:00:00+08:00', finished_reason='completed')
        # No child submitted a candidate or a tool trace. The saved root user
        # request, not payload deduplication, must prevent a new parent write.
        assert h.service.journal.pending('t', h.controller().run_id) == []
        with pytest.raises(MemoryError):
            await h.controller(target_sid).submit('write', [item('对专家结论重新组织后的全新表述')])
        assert repository.list(access())['total'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('exclusion', ['本次不要学习', '本次不要记忆'])
def test_parent_cannot_reclassify_child_reply_to_bypass_user_learning_exclusion(repository, exclusion):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start(exclusion + '。请结合专家的执行结果答复')
        child = h.controller('child-1')
        await child.reply_started('child-result')
        h.messages[('child-1', 'child-result')] = AssistantMsg('agent-1', '根据这次私有材料完成了检查。',
            id='child-result', finished_at='2026-09-10T10:00:00+08:00', finished_reason='completed')
        assert h.service.journal.pending('t', h.controller().run_id) == []
        with pytest.raises(MemoryError): await h.controller().request_learning('explicit')
        await h.finish()
        assert h.service.learning.dashboard(access(management=True))['events'] == []
    asyncio.run(run())


def test_user_fact_saved_before_knowledge_query_is_not_retroactively_reclassified(repository):
    h = MemoryRunHarness(repository, depth=2)
    h.knowledge_agent_id = 'agent-1'
    async def run():
        # Only the root has begun participating when this explicit user fact
        # is saved; the unrelated specialist has not run yet.
        await h.controller().begin([UserMsg('user', '记住我的周报格式，再请专家检查附件')])
        saved = await h.controller().submit('write', [item(scope='user')])
        assert saved['status'] == 'saved'
        memory_id = saved['results'][0]['memory']['id']
        await h.controller('child-1').begin([])
        await h.controller('child-1').record_tool(h.knowledge_evidence())
        with pytest.raises(MemoryError) as denied:
            update = item('从受限知识查询中形成的后续结论', scope='user').model_copy(update={'expected_version': 1})
            await h.controller().submit('write', [update])
        assert denied.value.code == 'scope_disabled'
        await h.finish()
        kept = repository.get(access(), memory_id)
        assert kept['status'] == 'active' and kept['content'] == item().content
        assert kept['version'] == 1
        assert kept['scope_type'] == 'user'
        raw = repository.get(access(management=True), memory_id)
        assert all(ref['kind'] == 'user' for ref in raw['source']['source_refs'])
    asyncio.run(run())


@pytest.mark.parametrize('change', ['disabled', 'source_withdrawn'])
@pytest.mark.parametrize('reparent', [False, True])
def test_queued_learning_rechecks_all_participants_and_current_sources(repository, change, reparent):
    h = MemoryRunHarness(repository, depth=3)
    async def run():
        msg = await h.start('请复盘附件核验方法：先确认完整清单，再检查每一项')
        await h.controller('child-2').request_learning('explicit')
        await h.finish()
        event = h.service.learning.dashboard(access(management=True))['events'][0]
        assert {node['session_id'] for node in event['provenance']['contributors']} == {'s', 'child-1', 'child-2'}
        assert (await validate_learning_event(h.storage, h.gateway, 't', event)).learning_enabled
        # This middle node need not contribute evidence itself: it remains an
        # authority ancestor of the leaf that supplied the material.
        if change == 'disabled':
            h.agents['agent-1'].data.platform_config.enabled = False
        else:
            h.messages[('s', msg.id)] = UserMsg('user', '已撤回原先的复盘材料', id=msg.id)
        if reparent:
            h.team.data.members[-1].inviter_session_id = 's'
        with pytest.raises(MemoryError):
            await validate_learning_event(h.storage, h.gateway, 't', event)
        if change == 'disabled':
            existing = await validate_learning_event(h.storage, h.gateway, 't', event, existing=True)
            assert existing.target(event['scope_type'])
        else:
            with pytest.raises(MemoryError, match='原始用户消息'):
                await validate_learning_event(h.storage, h.gateway, 't', event, existing=True)
    asyncio.run(run())


@pytest.mark.parametrize('reason', ['error', 'interrupted'])
def test_failed_or_interrupted_contributor_does_not_commit_a_pending_fact(repository, reason):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start()
        proposed = await h.controller('child-1').submit('write', [item()])
        await h.finish(node_reasons={'child-1': reason})
        assert repository.list(access())['total'] == 0
        with repository._connection() as conn:
            row = conn.execute('SELECT state,error_code FROM memory_proposals WHERE id=%s', (proposed['proposal_id'],)).fetchone()
        assert row == {'state': 'rejected', 'error_code': 'source_run_failed'}
    asyncio.run(run())


def test_original_tool_version_is_sealed_and_rechecked(repository):
    h = MemoryRunHarness(repository)
    async def run():
        await h.start('实际核对附件')
        await h.controller().record_tool({'id':'tool-1','kind':'tool','text':'附件齐全','outcome':'success','tool_name':'verify'})
        await h.finish()
        rows = h.service.journal.sources('t', h.controller().run_id)
        refs = [r['source_ref'] for r in rows]
        await validate_source_refs(h.storage, 'owner', refs)
        h.messages[('s', h.controller().reply_id)].get_content_blocks('tool_result')[0].output = '附件缺失'
        with pytest.raises(MemoryError, match='工具结果已修改'):
            await validate_source_refs(h.storage, 'owner', refs)
    asyncio.run(run())


def test_commit_rejects_a_proposal_id_from_another_run(repository):
    h = MemoryRunHarness(repository, depth=2)
    async def run():
        await h.start(mid='source-1')
        await h.controller('child-1').submit('write', [item()])
        first = h.service.journal.pending('t', h.controller().run_id)[0]
        journal = h.service.journal
        journal.begin('t', 'another-run', 'owner', 's', 'agent')
        journal.evidence('t', 'another-run', 'agent', 's', {'id':'source-2','kind':'user','text':'another'})
        other = journal.propose('t','another-run','write',[item().model_dump(mode='json')],['source-2'],[{'agent_id':'agent','session_id':'s'}])
        with pytest.raises(MemoryError, match='归属'):
            journal.commit({**first, 'id': other['id']}, access(), {})
        assert repository.list(access())['total'] == 0
    asyncio.run(run())


def test_completed_run_can_finish_background_learning_after_next_turn_begins(repository):
    h = MemoryRunHarness(repository)
    async def run():
        await h.start('请复盘：周报先列问题再列责任人', mid='original-turn')
        old_run = h.controller().run_id
        await h.controller().request_learning('explicit')
        h.settings = h.settings.model_copy(update={'learning_model_config':None})
        saved = await h.finish()
        assert saved['state'] == 'completed' and saved['learning_state'] == 'pending'
        await h.start('现在讨论另一个话题', mid='new-turn')
        h.settings = h.settings.model_copy(update={'learning_model_config': {'model':'test'}})
        await h.service.process(h.service.journal.get('t', old_run), h.settings)
        event = h.service.learning.dashboard(access(management=True))['events'][0]
        assert [e['id'] for e in event['evidence']] == ['original-turn']
        assert event['provenance']['run_id'] == old_run
    asyncio.run(run())


@pytest.mark.parametrize('success_count', [1, 3])
def test_actual_tool_success_is_not_assumed_to_be_completed_business_work(repository, success_count):
    h = MemoryRunHarness(repository)
    async def run():
        await h.start('请检查附件')
        for i in range(success_count):
            await h.controller().record_tool({'id':f'check-{i}','kind':'tool','text':'实际附件复核结果',
                'outcome':'success','tool_name':'verify'})
        await h.controller().request_learning('recovery')
        await h.finish()
        events = h.service.learning.dashboard(access(management=True))['events']
        if success_count == 1:
            assert events == []
        else:
            assert len(events) == 1 and events[0]['event_type'] == 'repeated_pattern'
            assert len([e for e in events[0]['evidence'] if e['kind']=='tool']) == 3
        assert not any(event['event_type']=='verified_task' for event in events)
    asyncio.run(run())


def test_knowledge_entry_cannot_promote_information_to_cross_project_or_shared_memory(repository):
    h = MemoryRunHarness(repository)
    h.entry_kind = 'knowledge'
    async def run():
        await h.start('请查询这个项目的受限资料')
        resolved = await h.controller().access(write=True)
        assert resolved.write_scopes == ('user_project',)
        for scope in ('user', 'project'):
            with pytest.raises(MemoryError):
                await h.controller().submit('write', [item(scope=scope)])
        assert repository.list(access())['total'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('no_learning', [False, True])
def test_delegated_knowledge_refs_restrict_writes_and_revoked_sources_cannot_be_read(repository, no_learning):
    from agentscope.app.memory._source_validation import filter_current_memory_results
    h = MemoryRunHarness(repository, depth=3)
    h.knowledge_agent_id = 'agent-2'
    async def run():
        await h.start(('本次不要学习。' if no_learning else '') + '请查询受限资料，记住本项目的使用经验')
        leaf = h.controller('child-2')
        await leaf.record_tool(h.knowledge_evidence())
        for scope in ('user', 'project'):
            with pytest.raises(MemoryError):
                await h.controller().submit('write', [item(scope=scope)])
        submitted = await h.controller().submit('write', [item()])
        assert submitted['status'] == 'pending'
        await h.finish()
        rows = repository.search(access())
        assert len(rows) == 1 and rows[0]['scope_type'] == 'user_project'
        raw = repository.get(access(management=True), rows[0]['id'])
        refs = raw['source']['source_refs']
        assert any(ref.get('tool_call_id') == 'knowledge-call' for ref in refs)
        visible = await filter_current_memory_results(h.storage,h.gateway,'t','owner',rows,repository=repository)
        assert len(visible) == 1
        h.knowledge_ids = []
        hidden = await filter_current_memory_results(h.storage,h.gateway,'t','owner',rows,repository=repository)
        assert hidden == []
        assert repository.list(access(management=True))['total'] == 1
    asyncio.run(run())


def test_knowledge_original_text_is_not_sent_as_learning_material(repository):
    h = MemoryRunHarness(repository)
    h.entry_kind = 'knowledge'
    async def run():
        await h.start('复盘本次资料查询过程')
        await h.controller().record_tool(h.knowledge_evidence())
        await h.controller().request_learning('explicit')
        await h.finish()
        event = h.service.learning.dashboard(access(management=True))['events'][0]
        assert not any('受限合同中的私有条款' in evidence['text'] for evidence in event['evidence'])
        assert any('原文' in evidence['text'] for evidence in event['evidence'] if evidence['kind']=='tool')
    asyncio.run(run())
