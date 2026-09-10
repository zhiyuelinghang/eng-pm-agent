"""Source access must be checked before SQL ranking, profiles and direct ID reads."""
from dataclasses import replace

from psycopg.types.json import Jsonb
import pytest

from test_memory_repository import repository, access, write
from utils.memory_repository import MemoryError


def source_memory(repository, kind='business_learning', scope='project', key=None, **source):
    saved = write(repository, scope=scope, key=key, content='当前来源允许的记忆')['memory']
    metadata = {'kind': kind, 'source_id': 'event-1', 'source_ids': ['event-1'],
                'audience': ['a', 'b'], **source}
    with repository._connection() as conn:
        conn.execute('UPDATE memory_records SET source=%s WHERE id=%s', (Jsonb(metadata), saved['id']))
    return saved['id']


def test_business_event_needs_fresh_authorization_for_get_search_and_list(repository):
    mid = source_memory(repository)
    actor = access(business_source_ids=('event-1',))
    assert repository.get(actor, mid)['id'] == mid
    assert len(repository.search(actor)) == 1
    assert repository.list(actor)['total'] == 1
    assert repository.search(access()) == []
    assert repository.list(access())['total'] == 0
    with pytest.raises(MemoryError):
        repository.get(access(), mid)


def test_private_source_profile_disappears_when_permission_revoked(repository):
    mid = source_memory(repository, scope='user_project', key='profile.name')
    actor = access(business_source_ids=('event-1',))
    assert repository.profile(actor)[0]['id'] == mid
    assert repository.profile(access()) == []


def test_business_source_cannot_reach_wider_group_via_authorized_initiator(repository):
    mid = source_memory(repository)
    allowed = access(private=False, audience_user_ids=('a', 'b'), business_source_ids=('event-1',))
    assert len(repository.search(allowed)) == 1
    broader = replace(allowed, audience_user_ids=('a', 'b', 'c'))
    assert repository.search(broader) == []
    assert repository.list(broader)['total'] == 0
    with pytest.raises(MemoryError):
        repository.get(broader, mid)
    assert repository.search(replace(allowed, audience_user_ids=())) == []


def test_derived_memory_requires_every_business_source(repository):
    mid = source_memory(repository, source_ids=['event-1', 'event-2'])
    full = access(business_source_ids=('event-1', 'event-2'))
    assert repository.get(full, mid)['id'] == mid
    partial = replace(full, business_source_ids=('event-1',))
    assert repository.search(partial) == []
    with pytest.raises(MemoryError):
        repository.get(partial, mid)


def test_group_source_requires_original_audience_in_addition_to_live_channel(repository):
    mid = source_memory(repository, kind='group_learning', channel_id='channel', source_ids=[])
    group = access(private=False, audience_user_ids=('a', 'b'), group_shared_channels=('channel',))
    assert len(repository.search(group)) == 1
    assert repository.search(replace(group, audience_user_ids=('a', 'c'))) == []
    with pytest.raises(MemoryError):
        repository.get(replace(group, audience_user_ids=('c',)), mid)
    # Personal profiles do not become a way to avoid original audience checks.
    own = source_memory(repository, kind='group_learning', scope='user', key='profile.name', audience=['b'])
    assert repository.profile(access()) == []
    with pytest.raises(MemoryError):
        repository.get(access(), own)


def test_management_cannot_reassign_business_source_to_another_drawer(repository):
    mid = source_memory(repository, scope='user_project')
    with pytest.raises(MemoryError, match='不能调整'):
        repository.manage(access(management=True), mid, expected_version=1, scope_type='project', publish=True)
