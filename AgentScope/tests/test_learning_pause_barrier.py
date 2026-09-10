"""Pauses retain work and serialize publication with the actual settings row."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from psycopg.types.json import Jsonb
import pytest

from test_memory_repository import repository, access
from test_learning_pipeline import event, output, allow_fixture_context
from test_group_learning import groups, queued, output as group_output
from utils.learning_repository import LearningRepository
from utils.learning_service import process_learning_job, reconcile_automatic_memories
from utils.group_learning_service import process_group_job
from utils.learning_settings_guard import LearningPaused, lock_learning_settings
from utils.memory_repository import MemoryError


def update_settings(repository, **changes):
    with repository._connection() as conn:
        patch_settings(conn, **changes)


def patch_settings(conn, **changes):
    # Updating payload takes a row write lock, as the application's CAS does.
    conn.execute('''UPDATE platform_settings SET payload=jsonb_set(payload::jsonb,
        '{data,memory_settings}', payload::jsonb->'data'->'memory_settings' || %s)
        WHERE user_id='owner' ''', (Jsonb(changes),))


def job_state(repository, job, table='learning_jobs'):
    assert table in {'learning_jobs', 'group_learning_batches'}
    with repository._connection() as conn:
        return conn.execute(f'SELECT * FROM {table} WHERE id=%s', (job['id'],)).fetchone()


def ready(repository, job, table='learning_jobs'):
    assert table in {'learning_jobs', 'group_learning_batches'}
    with repository._connection() as conn:
        conn.execute(f'UPDATE {table} SET available_at=now() WHERE id=%s', (job['id'],))


def process(repository, job, *, authorize=None, call_model=None):
    return asyncio.run(process_learning_job(LearningRepository(repository), job,
        authorize=authorize or AsyncMock(return_value=access()),
        filter_existing=allow_fixture_context,
        call_model=call_model or AsyncMock(return_value=output().model_dump_json()),
        settings=SimpleNamespace(learning_timeout_seconds=5)))


@pytest.mark.parametrize('switch', ['learning_enabled', 'learning_interactions_enabled'])
def test_inflight_result_is_deferred_at_commit_and_resumes_once(repository, switch):
    learning = LearningRepository(repository)
    event(repository)
    job = learning.claim('t')

    async def model(*_):
        # Deliberately keep both injected authorization calls successful. Only
        # the transaction's fresh database row can prevent this publication.
        update_settings(repository, **{switch:False})
        return output().model_dump_json()

    assert process(repository, job, call_model=model) == {'status':'pending', 'code':'learning_paused'}
    row = job_state(repository, job)
    assert (row['state'], row['attempts'], row['lease_id']) == ('pending', 0, None)
    assert repository.search(access()) == []
    update_settings(repository, **{switch:True})
    ready(repository, job)
    resumed = learning.claim('t')
    assert resumed['id'] == job['id']
    assert process(repository, resumed)['candidates']
    assert job_state(repository, resumed)['state'] == 'done'
    assert len(repository.search(access())) == 1
    assert learning.claim('t') is None


def test_repeated_pause_never_exhausts_retries_but_source_revocation_cancels(repository):
    learning = LearningRepository(repository)
    event(repository)
    for _ in range(5):
        job = learning.claim('t')
        result = process(repository, job, authorize=AsyncMock(side_effect=LearningPaused()))
        assert result['status'] == 'pending'
        assert job_state(repository, job)['attempts'] == 0
        ready(repository, job)
    job = learning.claim('t')
    result = process(repository, job, authorize=AsyncMock(side_effect=MemoryError(
        'learning_source_revoked', '来源授权已撤回。', status=403)))
    assert result == {'status':'cancelled', 'code':'learning_source_revoked'}
    assert job_state(repository, job)['state'] == 'cancelled'
    assert repository.search(access()) == []


@pytest.mark.parametrize('source,switch', [
    ('interaction','learning_interactions_enabled'),
    ('business_event','learning_business_events_enabled'),
    ('group','group_learning_enabled'),
])
def test_guard_uses_live_row_and_only_relevant_source_switch(repository, source, switch):
    update_settings(repository, **{switch:False})
    with repository._connection() as conn:
        with pytest.raises(LearningPaused):
            lock_learning_settings(conn, {('owner',source)})
    other = next(s for s in ('interaction','business_event','group') if s != source)
    with repository._connection() as conn:
        lock_learning_settings(conn, {('owner',other)})


def test_paused_derived_source_cannot_be_published_through_enabled_interaction(repository):
    learning = LearningRepository(repository)
    event(repository, provenance={'derived_sources':[{'config_owner':'owner',
        'source_type':'business_event', 'provenance':{}}]})
    job = learning.claim('t')
    update_settings(repository, learning_business_events_enabled=False)
    assert process(repository, job)['status'] == 'pending'
    assert repository.search(access()) == []


def test_pause_stops_new_capture_without_consuming_existing_jobs(repository):
    event(repository)
    update_settings(repository, learning_interactions_enabled=False)
    with pytest.raises(LearningPaused):
        event(repository)
    learning = LearningRepository(repository)
    assert learning.claim('t', enabled_sources=['business_event', 'group']) is None
    with repository._connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM learning_events').fetchone()['n'] == 1
        row = conn.execute('SELECT state,attempts FROM learning_jobs').fetchone()
    assert row == {'state':'pending', 'attempts':0}


@pytest.mark.parametrize('switch', ['learning_enabled', 'group_learning_enabled'])
def test_group_inflight_pause_preserves_cursor_and_batch_for_resume(groups, switch):
    repository = groups.memories
    job = queued(groups)

    async def model(*_):
        update_settings(repository, **{switch:False})
        return group_output().model_dump_json()

    runtime = SimpleNamespace(authorize_group=AsyncMock(), call_model=model,
        gateway=SimpleNamespace(group_learning_source=AsyncMock(return_value=job['snapshot']),
            group_learning_validate=AsyncMock()))
    result = asyncio.run(process_group_job(groups, job, runtime=runtime,
        settings=SimpleNamespace(learning_input_char_limit=16000,learning_timeout_seconds=5)))
    assert result == {'status':'pending', 'code':'learning_paused'}
    row = job_state(repository, job, 'group_learning_batches')
    assert (row['state'], row['attempts'], row['lease_id']) == ('pending',0,None)
    with repository._connection() as conn:
        assert conn.execute('SELECT cursor FROM group_learning_cursors').fetchone()['cursor'] == 0
    assert repository.search(access()) == []
    update_settings(repository, **{switch:True})
    ready(repository, job, 'group_learning_batches')
    resumed = groups.claim('t')
    assert resumed['id'] == job['id']
    groups.complete(resumed, group_output())
    assert len(repository.search(access(user='1', group_source_channels=('10',),
        group_shared_channels=('10',)))) == 1
    assert repository.search(access(user='unrelated')) == []
    with repository._connection() as conn:
        assert conn.execute('SELECT cursor FROM group_learning_cursors').fetchone()['cursor'] == 1
    assert groups.claim('t') is None


def wait_for_database_lock(repository, pid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with repository._connection() as conn:
            if conn.execute('SELECT pg_blocking_pids(%s) AS blockers',(pid,)).fetchone()['blockers']:
                return
        time.sleep(.01)
    pytest.fail('The expected settings row lock was not observed in PostgreSQL')


def test_pause_write_commits_before_waiting_publication_so_result_cannot_publish(repository, monkeypatch):
    import utils.learning_repository as module
    learning = LearningRepository(repository)
    event(repository)
    job = learning.claim('t')
    started = Event()
    pids = []
    real_guard = module.lock_learning_settings

    def observed_guard(conn, sources):
        pids.append(conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
        started.set()
        return real_guard(conn, sources)

    monkeypatch.setattr(module, 'lock_learning_settings', observed_guard)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with repository._connection() as setting_tx:
            patch_settings(setting_tx, learning_enabled=False)
            pending = pool.submit(learning.complete, job, access(), output())
            assert started.wait(5)
            wait_for_database_lock(repository, pids[0])
            assert not pending.done()
        # The paused value becomes visible only when the settings transaction
        # commits. SELECT FOR SHARE must then return this value, not an old copy.
        with pytest.raises(LearningPaused):
            pending.result(timeout=5)
    assert repository.search(access()) == []


def test_publication_holds_settings_share_lock_until_commit_then_pause_can_return(repository, monkeypatch):
    import utils.learning_repository as module
    learning = LearningRepository(repository)
    event(repository)
    job = learning.claim('t')
    locked, release, writer_started = Event(), Event(), Event()
    writer_pids = []
    real_guard = module.lock_learning_settings

    def held_guard(conn, sources):
        real_guard(conn, sources)
        locked.set()
        assert release.wait(5)

    def pause():
        with repository._connection() as conn:
            writer_pids.append(conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
            writer_started.set()
            patch_settings(conn, learning_enabled=False)

    monkeypatch.setattr(module, 'lock_learning_settings', held_guard)
    with ThreadPoolExecutor(max_workers=2) as pool:
        publication = pool.submit(learning.complete, job, access(), output())
        assert locked.wait(5)
        paused = pool.submit(pause)
        try:
            assert writer_started.wait(5)
            wait_for_database_lock(repository, writer_pids[0])
            assert not paused.done()
        finally:
            release.set()
        assert publication.result(timeout=5)['candidates']
        paused.result(timeout=5)
    # This one result completed before pause was acknowledged; subsequent
    # publication/capture observes the paused authoritative row.
    assert len(repository.search(access())) == 1
    with pytest.raises(LearningPaused):
        event(repository)


def test_paused_candidate_check_is_deferred_without_rejecting_candidate(repository):
    from test_learning_pipeline import candidate
    learning = LearningRepository(repository)
    mid = candidate(repository)
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET status='candidate' WHERE id=%s", (mid,))
    update_settings(repository, learning_interactions_enabled=False)
    asyncio.run(reconcile_automatic_memories(learning, 't', AsyncMock(return_value=access()),
        AsyncMock(return_value=access()), allow_new=True))
    row = repository.get(access(management=True), mid)
    assert row['status'] == 'candidate'
    assert row['learning']['auto_check_error'] == 'learning_paused'


def test_missing_owner_settings_fails_closed_and_does_not_insert_event(repository):
    with repository._connection() as conn:
        conn.execute("DELETE FROM platform_settings WHERE user_id='owner'")
    with pytest.raises(LearningPaused, match='配置尚未就绪'):
        event(repository)
    with repository._connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM learning_events').fetchone()['n'] == 0


@pytest.mark.parametrize('source,switch', [('interaction','learning_interactions_enabled'),
    ('business_event','learning_business_events_enabled'), ('group','group_learning_enabled')])
def test_pause_during_model_resolution_stops_model_dispatch(monkeypatch, source, switch):
    from agentscope.app.memory import _learning as module
    from agentscope.app.storage import ChatModelConfig, MemorySettingsData
    from unittest.mock import MagicMock
    selected = ChatModelConfig(type='custom_openai_credential', credential_id='credential', model='test', parameters={})
    settings = MemorySettingsData(learning_enabled=True, learning_model_config=selected)
    dispatched = MagicMock()

    async def resolve(*_):
        setattr(settings, switch, False)
        return dispatched

    monkeypatch.setattr(module, 'get_model', resolve)
    monkeypatch.setattr(module.CredentialFactory, 'from_dict', lambda _:SimpleNamespace(type=selected.type))
    monkeypatch.setattr(module, 'build_credential_model_catalog', lambda _:[SimpleNamespace(name='test',enabled=True)])
    runtime = module.PlatformLearningRuntime(storage=None, gateway=None,
        resources=SimpleNamespace(resolve_credential=AsyncMock(return_value=SimpleNamespace(data={}))),
        settings_loader=AsyncMock(return_value=settings), tenant_id='t')
    with pytest.raises(LearningPaused):
        asyncio.run(runtime.call_model({'config_owner':'owner','source_type':source}, 'system', 'evidence'))
    dispatched.assert_not_called()


def test_group_pause_stops_enqueue_and_preserves_observed_messages(groups):
    from test_group_learning import snapshot
    data = snapshot()
    groups.observe('t', dict(channel_id=10, project_id='p', title='工程讨论群', revision=1))
    update_settings(groups.memories, group_learning_enabled=False)
    with pytest.raises(LearningPaused):
        groups.enqueue('t', data, config_owner='owner', daily_limit=100)
    with groups.memories._connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM group_learning_batches').fetchone()['n'] == 0
        row = conn.execute('SELECT cursor,observed_revision FROM group_learning_cursors').fetchone()
    assert row == {'cursor':0, 'observed_revision':1}


@pytest.mark.parametrize('mutation', ['owner', 'source', 'derived'])
def test_changed_execution_snapshot_cannot_bypass_original_source_pause(repository, mutation):
    provenance = {'derived_sources':[{'config_owner':'owner','source_type':'business_event','provenance':{}}]} if mutation == 'derived' else {}
    event(repository, provenance=provenance)
    learning = LearningRepository(repository)
    job = learning.claim('t')
    if mutation == 'owner':
        job['event']['config_owner'] = 'default'
        update_settings(repository, learning_enabled=False)
    elif mutation == 'source':
        job['event']['source_type'] = 'business_event'
        update_settings(repository, learning_interactions_enabled=False)
    else:
        job['event']['provenance']['derived_sources'] = []
        update_settings(repository, learning_business_events_enabled=False)
    with pytest.raises(LearningPaused):
        learning.complete(job, access(), output())
    assert repository.search(access()) == []


def test_group_execution_snapshot_cannot_change_persisted_settings_owner(groups):
    job = queued(groups)
    job['config_owner'] = 'default'
    update_settings(groups.memories, group_learning_enabled=False)
    with pytest.raises(LearningPaused):
        groups.complete(job, group_output())
    with groups.memories._connection() as conn:
        assert conn.execute('SELECT cursor FROM group_learning_cursors').fetchone()['cursor'] == 0
        assert conn.execute('SELECT count(*) AS n FROM memory_records').fetchone()['n'] == 0


def test_competing_group_completions_use_one_lease_without_share_lock_upgrade(groups):
    job = queued(groups)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(groups.complete, job, group_output()) for _ in range(2)]
        outcomes = [future.result(timeout=5) for future in futures]
    assert sum(result.get('status') == 'stale' for result in outcomes) == 1
    assert sum(bool(result.get('candidates')) for result in outcomes) == 1
    with groups.memories._connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM memory_records').fetchone()['n'] == 1
