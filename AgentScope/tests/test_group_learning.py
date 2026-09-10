"""Incremental group learning invariants against isolated PostgreSQL schemas."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_memory_repository import repository, access, write
from utils.group_learning_schema import GROUP_LEARNING_DDL
from utils.group_learning_repository import GroupLearningRepository, GroupOutput, GroupCandidate, candidate_targets
from utils.group_learning_service import due, worth_calling, model_input, process_group_job, scan_groups
from utils.learning_repository import LearningRepository
from utils.memory_repository import MemoryError


@pytest.fixture
def groups(repository):
    with repository._connection() as conn:
        conn.execute(GROUP_LEARNING_DDL)
    return GroupLearningRepository(repository)


def snapshot(full=True, start=0, end=1, content='确认：验收会议改到周五下午三点。'):
    now = datetime.now(timezone.utc).isoformat()
    return dict(channel_id=10, project_id='p', title='工程讨论群', full_project=full, members=['1','2'],
        policy_revision=0, observed_revision=end, from_revision=start, to_revision=end, changed_at=now,
        changed_message_ids=[end], has_policy_change=False,
        messages=[dict(id=str(end), text=content, kind='user', user_id='1', agent_id=None,
            created_at=now, audience=['1','2'], project_shared=full, outcome='observed', hash=f'hash{end}', context_only=False)])


def output(**kwargs):
    item = dict(memory_type='fact', target='conversation', topic_key='验收会议时间', title='验收会议时间',
        content='验收会议定于周五下午三点。', evidence_ids=['1'])
    item.update(kwargs)
    return GroupOutput(reason='群里已明确确认会议时间。', candidates=[GroupCandidate(**item)])


def queued(groups, data=None):
    data = data or snapshot()
    groups.observe('t', dict(channel_id=10, project_id='p', title='工程讨论群', revision=data['to_revision']))
    groups.enqueue('t', data, config_owner='owner', daily_limit=100)
    return groups.claim('t')


def complete(groups, job, value=None):
    return groups.complete(job, value or output())


def test_scheduling_idle_count_max_wait_and_no_value():
    settings = SimpleNamespace(group_learning_message_threshold=20, group_learning_batch_size=50,
        group_learning_idle_seconds=600, group_learning_max_wait_seconds=3600)
    data = snapshot()
    assert not due(data, settings)
    assert due(data, settings, datetime.now(timezone.utc)+timedelta(seconds=601))
    data['messages'][0]['created_at'] = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    assert due(data, settings)
    assert not worth_calling(snapshot(content='大家好！'))
    assert worth_calling(snapshot(content='同意'))
    assert not worth_calling({**snapshot(), 'messages': []})


def test_empty_batch_advances_cursor_once(groups):
    job = queued(groups)
    complete(groups, job, GroupOutput(reason='证据不足，不强行生成。'))
    assert groups.claim('t') is None
    assert groups.enqueue('t', snapshot(), config_owner='owner', daily_limit=100) is None
    data = groups.dashboard(access(management=True))
    assert data['channels'][0]['cursor'] == 1
    assert data['batches'][0]['state'] == 'skipped'
    assert groups.memories.list(access(management=True))['total'] == 0


def test_full_group_routes_project_and_requires_live_source_visibility(groups):
    result = complete(groups, queued(groups))
    assert result['candidates'][0]['scope_type'] == 'project'
    assert groups.memories.search(access()) == []
    live = replace(access(user='1'), group_shared_channels=('10',))
    assert groups.memories.search(live)[0]['content'] == output().candidates[0].content
    with pytest.raises(MemoryError):
        groups.memories.get(access(), result['candidates'][0]['memory_id'])


def test_subgroup_fans_out_only_to_evidence_audience_and_cannot_publish(groups):
    data = snapshot(full=False)
    data['members'].append('3')  # A newly joined member cannot inherit historical visibility.
    result = complete(groups, queued(groups, data))
    assert {(r['scope_type'],r['platform_user_id']) for r in result['candidates']} == {('user_project','1'),('user_project','2')}
    actor = replace(access(user='1'), group_source_channels=('10',))
    assert len(groups.memories.search(actor)) == 1
    assert groups.memories.search(replace(actor, user_id='3')) == []
    assert groups.memories.search(replace(actor, private=False)) == []
    with pytest.raises(MemoryError, match='不能调整'):
        groups.memories.manage(access(management=True), result['candidates'][0]['memory_id'], expected_version=1, scope_type='project', publish=True)


def test_historical_subgroup_evidence_never_promotes_after_group_expansion():
    data = snapshot(full=True)
    data['messages'][0]['project_shared'] = False
    targets, _ = candidate_targets(output().candidates[0], data)
    assert all(t[0] == 'user_project' for t in targets)


def test_personal_preference_requires_speaker_and_never_changes_other_members(groups):
    value = output(memory_type='preference', target='personal', user_id='1', topic_key='profile.address', content='用户希望被称呼为雷总。')
    result = complete(groups, queued(groups, snapshot(full=False)), value)
    assert [(r['scope_type'],r['platform_user_id']) for r in result['candidates']] == [('user','1')]
    assert groups.memories.profile(access(user='2')) == []
    assert groups.memories.profile(access(user='1'))[0]['content'] == value.candidates[0].content
    value.candidates[0].user_id = '2'
    with pytest.raises(MemoryError, match='本人发言'):
        candidate_targets(value.candidates[0], snapshot())


def test_atomic_failure_does_not_commit_partial_results_or_cursor(groups):
    job = queued(groups)
    value = output()
    invalid = deepcopy(value.candidates[0])
    invalid.evidence_ids = ['nonexistent']
    value.candidates.append(invalid)
    with pytest.raises(MemoryError):
        complete(groups, job, value)
    assert groups.memories.list(access(management=True))['total'] == 0
    assert groups.dashboard(access(management=True))['channels'][0]['cursor'] == 0


def test_duplicates_do_not_create_versions_or_resurrect_deleted_memories(groups):
    first = complete(groups, queued(groups))['candidates'][0]['memory_id']
    result = complete(groups, queued(groups, snapshot(start=1,end=2)), output(evidence_ids=['2']))
    assert result['candidates'][0]['status'] == 'duplicate'
    assert groups.memories.get(access(management=True), first)['version'] == 1
    groups.memories.manage(access(management=True), first, expected_version=1, status='deleted')
    result = complete(groups, queued(groups, snapshot(start=2,end=3)), output(evidence_ids=['3']))
    assert result['candidates'][0]['status'] == 'suppressed'


def test_failure_retries_and_pause_preserve_cursor(groups):
    job = queued(groups)
    groups.fail(job, 'timeout')
    assert groups.dashboard(access(management=True))['channels'][0]['cursor'] == 0
    groups.action(access(management=True), channel_id=10, action='pause')
    with groups.memories._connection() as conn:
        conn.execute("UPDATE group_learning_batches SET available_at=now()")
    assert groups.claim('t') is None
    groups.action(access(management=True), channel_id=10, action='resume')
    retry = groups.claim('t')
    assert retry['id'] == job['id'] and retry['attempts'] == 2
    assert complete(groups, job)['status'] == 'stale'
    complete(groups, retry)


def test_budget_retains_unprocessed_interval(groups):
    complete(groups, queued(groups), GroupOutput(reason='无价值'))
    assert groups.enqueue('t', snapshot(start=1,end=2), config_owner='owner', daily_limit=1) is None
    assert groups.dashboard(access(management=True))['channels'][0]['cursor'] == 1


def test_group_experience_automatically_activates_and_changed_source_suspends_it(groups):
    value = output(memory_type='experience', conditions='有会议附件清单时', limitations='不能替代质量验收')
    mid = complete(groups, queued(groups), value)['candidates'][0]['memory_id']
    actor = replace(access(user='1'), group_shared_channels=('10',))
    assert groups.memories.search(actor)
    learn = LearningRepository(groups.memories)
    row = groups.memories.get(access(management=True),mid)
    assert row['learning']['validation_method']=='automatic_v1'
    assert row['status'] == 'active' and len(groups.memories.search(actor)) == 1
    derived = learn.derive(access(management=True), [mid], action='skill_compile', note='整理为操作步骤')
    assert derived['status'] == 'queued'
    groups.invalidate('t', 10, changed_ids=[1])
    assert groups.memories.search(actor) == []
    assert groups.memories.get(access(management=True), mid)['learning']['validation_state'] == 'source_changed'


def test_background_process_calls_model_once_or_zero_and_rechecks_sources(groups):
    async def run():
        job = queued(groups)
        runtime = SimpleNamespace(authorize_group=AsyncMock(return_value=SimpleNamespace(memory_write_scopes=['project'])),
            gateway=SimpleNamespace(group_learning_source=AsyncMock(return_value=job['snapshot']), group_learning_validate=AsyncMock()),
            call_model=AsyncMock(return_value=GroupOutput(reason='目前没有可靠结论').model_dump_json()))
        settings = SimpleNamespace(learning_input_char_limit=16000, learning_timeout_seconds=10)
        await process_group_job(groups, job, runtime=runtime, settings=settings)
        assert runtime.call_model.await_count == 1
        assert runtime.gateway.group_learning_validate.await_count == 2
        job = queued(groups, snapshot(start=1,end=2,content='你好'))
        runtime.gateway.group_learning_source.return_value = job['snapshot']
        runtime.call_model.reset_mock()
        await process_group_job(groups, job, runtime=runtime, settings=settings)
        assert runtime.call_model.await_count == 0
    asyncio.run(run())


def test_input_keeps_all_new_message_ids():
    data = snapshot()
    data['messages'] = [{**data['messages'][0], 'id':str(i),'text':'内容'*2000} for i in range(50)]
    import json
    value = json.loads(model_input(data, [], 16000))
    assert len(value['messages']) == 50
    assert all(m['truncated'] for m in value['messages'])


def test_permissions_revoked_during_model_call_cannot_commit(groups):
    async def run():
        job = queued(groups)
        runtime = SimpleNamespace(authorize_group=AsyncMock(side_effect=[SimpleNamespace(memory_write_scopes=['project']),
            MemoryError('permission_revoked','已暂停',status=403)]),
            gateway=SimpleNamespace(group_learning_source=AsyncMock(return_value=job['snapshot']), group_learning_validate=AsyncMock()),
            call_model=AsyncMock(return_value=output().model_dump_json()))
        await process_group_job(groups, job, runtime=runtime, settings=SimpleNamespace(learning_input_char_limit=16000,learning_timeout_seconds=10))
        assert groups.memories.list(access(management=True))['total'] == 0
        assert groups.dashboard(access(management=True))['channels'][0]['cursor'] == 0
    asyncio.run(run())


def test_source_invalidation_progress_is_independent_of_failed_summary(groups):
    async def run():
        mid = complete(groups, queued(groups))['candidates'][0]['memory_id']
        pending = queued(groups, snapshot(start=1,end=2))
        with groups.memories._connection() as conn:
            conn.execute("UPDATE group_learning_batches SET state='failed' WHERE id=%s", (pending['id'],))
        policy = SimpleNamespace(memory_write_scopes=['project'])
        latest = snapshot(start=1,end=3)
        runtime = SimpleNamespace(authorize_group=AsyncMock(return_value=policy),
            gateway=SimpleNamespace(group_learning_channels=AsyncMock(return_value=[dict(channel_id=10,project_id='p',title='工程讨论群',revision=3)]),
                group_learning_changes=AsyncMock(return_value=[dict(revision=3,message_id=1,kind='message')]),
                group_learning_source=AsyncMock(return_value=latest)))
        settings = SimpleNamespace(group_learning_batch_size=50,group_learning_message_threshold=20,group_learning_idle_seconds=600,
            group_learning_max_wait_seconds=3600,group_learning_daily_limit=100)
        await scan_groups(groups,runtime,settings,tenant_id='t',config_owner='owner')
        cursor = groups.dashboard(access(management=True))['channels'][0]
        assert cursor['cursor'] == 1 and cursor['invalidation_cursor'] == 3
        assert groups.memories.get(access(management=True),mid)['status'] == 'inactive'
    asyncio.run(run())


def test_group_derived_skill_retains_source_and_is_invalidated(groups):
    from utils.learning_repository import LearningOutput
    value = output(memory_type='experience',conditions='附件验收',limitations='不能代替质量检查')
    mid = complete(groups,queued(groups,snapshot(full=False)),value)['candidates'][0]['memory_id']
    learn = LearningRepository(groups.memories)
    learn.review(access(management=True),mid,expected_version=1,action='approve',note='核验实际证据')
    learn.derive(access(management=True),[mid],action='skill_compile',note='列出操作步骤')
    job = learn.claim('t')
    assert job['event']['session_id'].startswith('group:')
    result = learn.complete(job,replace(access(user='1'),group_source_channels=('10',)),LearningOutput.model_validate({
        'reason':'依据已验证经验整理步骤','candidates':[dict(memory_type='skill',title='附件验收步骤',content='核对清单后逐项验收。',
            conditions='有附件清单',limitations='不能替代专业检查',steps=['核对清单','逐项验收'],evidence_ids=[job['event']['evidence'][0]['id']])]}))
    derived_id = result['candidates'][0]['memory_id']
    row = groups.memories.get(access(management=True),derived_id)
    assert row['source']['kind']=='group_learning' and row['scope_type']=='user_project'
    assert row['source']['channel_id']=='10'
    groups.invalidate('t',10,changed_ids=[1])
    assert groups.memories.get(access(management=True),derived_id)['status']=='inactive'


def test_main_model_fact_is_visible_for_dedup_and_not_copied(groups):
    saved = write(groups.memories,scope='project',content='验收会议定于周五下午三点。')['memory']
    job = queued(groups)
    assert any(r['id']==saved['id'] for r in groups.existing(job))
    result = complete(groups,job,output(existing_id=saved['id'],expected_version=1))
    assert result['candidates'][0]['status']=='suppressed'
    assert groups.memories.list(access(management=True))['total']==1


def test_subgroup_changed_conclusion_updates_equivalent_member_copies(groups):
    first = complete(groups,queued(groups,snapshot(full=False)))['candidates']
    job = queued(groups,snapshot(full=False,start=1,end=2))
    value = output(content='改为周六下午验收。',evidence_ids=['2'],existing_id=first[0]['memory_id'],expected_version=1)
    result = complete(groups,job,value)
    assert len(result['candidates'])==2
    assert all(r['status']=='active' for r in result['candidates'])
    assert all(groups.memories.get(access(management=True),r['memory_id'])['version']==2 for r in result['candidates'])


def test_existing_context_excludes_new_member_history_and_private_management_edits(groups):
    first = complete(groups,queued(groups,snapshot(full=False)))['candidates']
    job = queued(groups,snapshot(full=False,start=1,end=2))
    assert len(groups.existing(job)) == 2
    job['snapshot']['members'].append('3')
    assert groups.existing(job) == []
    job['snapshot']['members'].remove('3')
    groups.memories.manage(access(management=True),first[0]['memory_id'],expected_version=1,content='仅供该用户查看的私人修订')
    assert all('私人修订' not in row['content'] for row in groups.existing(job))


def test_failed_group_batch_retries_after_daily_cooldown(groups):
    job=queued(groups)
    with groups.memories._connection() as conn:
        conn.execute("UPDATE group_learning_batches SET state='failed',attempts=3,lease_id=NULL,available_at=now()+interval '1 day' WHERE id=%s",(job['id'],))
    assert groups.claim('t') is None
    with groups.memories._connection() as conn:
        conn.execute("UPDATE group_learning_batches SET available_at=now()-interval '1 second' WHERE id=%s",(job['id'],))
    retried=groups.claim('t')
    assert retried['id']==job['id'] and retried['attempts']==4
    groups.fail(retried,'temporary_unavailable')
    assert groups.claim('t') is None
