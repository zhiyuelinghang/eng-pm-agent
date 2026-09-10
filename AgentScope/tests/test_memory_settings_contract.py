"""Public memory choices and concurrent persistence must share one contract."""

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError

from agentscope.app._router import _agent as routes
from agentscope.app._router._schema._agent import UpdateMemorySettingsRequest
from agentscope.app.storage import MemorySettingsData, PlatformSettingsData
from agentscope.app.storage._memory_settings import MemorySettingsConflict
from agentscope.app.storage._redis_storage import RedisStorage
from agentscope.app.storage._sql._storage import AsyncSQLAlchemyStorage


FIELDS = {
    'learning_enabled', 'learning_model_config', 'learning_interactions_enabled',
    'learning_business_events_enabled', 'group_learning_enabled', 'compression_model_config',
}


def settings(**changes):
    return MemorySettingsData(**changes)


def body(**changes):
    return {'settings': settings(**changes).model_dump(), 'expected_revision': 1}


def test_public_contract_has_only_six_decisions_and_internal_defaults_are_safe():
    assert set(MemorySettingsData.model_fields) == FIELDS
    assert settings().learning_enabled is False
    schema = UpdateMemorySettingsRequest.model_json_schema()
    assert set(schema['required']) == {'settings', 'expected_revision'}
    assert set(schema['$defs']['UpdateMemorySettingsData']['required']) == FIELDS


@pytest.mark.parametrize('field', sorted(FIELDS))
def test_replacement_requires_each_of_the_six_fields(field):
    request = body()
    del request['settings'][field]
    with pytest.raises(ValidationError):
        UpdateMemorySettingsRequest.model_validate(request)


@pytest.mark.parametrize('old_field', [
    'memory_model_config', 'learning_daily_job_limit', 'group_learning_daily_limit',
    'memory_profile_enabled', 'recall_top_k', 'compression_trigger_ratio',
])
def test_removed_fields_are_rejected_instead_of_silently_ignored(old_field):
    request = body()
    request['settings'][old_field] = None
    with pytest.raises(ValidationError):
        UpdateMemorySettingsRequest.model_validate(request)


def test_revision_and_unknown_envelope_keys_are_rejected():
    for request in ({'settings': body()['settings']}, {**body(), 'reset': True}):
        with pytest.raises(ValidationError):
            UpdateMemorySettingsRequest.model_validate(request)


def test_enabled_learning_requires_model_and_at_least_one_source():
    with pytest.raises(ValidationError, match='学习模型'):
        settings(learning_enabled=True)
    with pytest.raises(ValidationError, match='学习来源'):
        settings(learning_enabled=True,
            learning_model_config={'type': 'model', 'credential_id': 'c', 'model': 'm', 'parameters': {}},
            learning_interactions_enabled=False, learning_business_events_enabled=False,
            group_learning_enabled=False)


@pytest_asyncio.fixture(params=['sqlite', 'redis', 'postgres'])
async def stores(request, tmp_path):
    if request.param == 'sqlite':
        url = 'sqlite+aiosqlite:///' + (tmp_path / 'settings.db').as_posix()
        first, second = AsyncSQLAlchemyStorage(url), AsyncSQLAlchemyStorage(url)
        await first.__aenter__()
        await second.__aenter__()
        yield first, second
        await second.aclose()
        await first.aclose()
    elif request.param == 'redis':
        import fakeredis.aioredis
        server = fakeredis.FakeServer()
        first, second = RedisStorage(), RedisStorage()
        first._client = fakeredis.aioredis.FakeRedis(server=server)
        second._client = fakeredis.aioredis.FakeRedis(server=server)
        yield first, second
        await first._client.aclose()
        await second._client.aclose()
    else:
        import psycopg
        from psycopg import sql
        from sqlalchemy.engine import make_url
        from agentscope.app.storage._sql._tables import PlatformSettingsRow
        dsn = os.getenv('DOBBY_MEMORY_TEST_DATABASE_URL')
        if not dsn:
            pytest.skip('An isolated PostgreSQL schema needs DOBBY_MEMORY_TEST_DATABASE_URL')
        schema = 'memory_settings_test_' + uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as setup:
            setup.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        url = make_url(dsn).set(drivername='postgresql+asyncpg').render_as_string(hide_password=False)
        first = AsyncSQLAlchemyStorage(url, create_tables=False, schema=schema)
        second = AsyncSQLAlchemyStorage(url, create_tables=False, schema=schema)
        await first.__aenter__()
        await second.__aenter__()
        try:
            async with first._engine.begin() as connection:
                await connection.run_sync(PlatformSettingsRow.__table__.create)
            yield first, second
        finally:
            await first.aclose()
            await second.aclose()
            with psycopg.connect(dsn, autocommit=True) as cleanup:
                cleanup.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.mark.asyncio
async def test_two_independent_clients_cannot_both_save_the_same_revision(stores):
    first, second = stores
    await first.upsert_platform_settings('owner', PlatformSettingsData())
    changes = [settings(group_learning_enabled=False), settings(learning_interactions_enabled=False)]
    results = await asyncio.gather(
        first.update_memory_settings('owner', changes[0], 1),
        second.update_memory_settings('owner', changes[1], 1), return_exceptions=True)
    assert sum(isinstance(result, MemorySettingsConflict) for result in results) == 1
    winner = next(result for result in results if not isinstance(result, Exception))
    stored = await first.get_platform_settings('owner')
    assert stored.data.memory_settings_revision == 2
    assert stored.data.memory_settings == winner.data.memory_settings


@pytest.mark.asyncio
async def test_general_settings_save_cannot_overwrite_concurrent_memory_change(stores):
    first, second = stores
    initial = await first.upsert_platform_settings('owner', PlatformSettingsData())
    stale = initial.data.model_copy(update={'global_main_agent_id': 'new-main'})
    changed = settings(group_learning_enabled=False)
    await asyncio.gather(first.update_memory_settings('owner', changed, 1),
        second.upsert_platform_settings('owner', stale))
    # Repeat a previously prepared general-settings form after the memory save.
    await second.upsert_platform_settings('owner', stale)
    stored = await first.get_platform_settings('owner')
    assert stored.data.global_main_agent_id == 'new-main'
    assert stored.data.memory_settings == changed
    assert stored.data.memory_settings_revision == 2


@pytest.mark.asyncio
async def test_memory_save_preserves_other_settings_and_conflict_changes_nothing(stores):
    first, second = stores
    await first.upsert_platform_settings('owner', PlatformSettingsData(global_main_agent_id='main'))
    saved = await second.update_memory_settings('owner', settings(group_learning_enabled=False), 1)
    with pytest.raises(MemorySettingsConflict):
        await first.update_memory_settings('owner', settings(), 1)
    current = await first.get_platform_settings('owner')
    assert current.data == saved.data
    assert current.data.global_main_agent_id == 'main'


@pytest.mark.asyncio
async def test_initial_concurrent_memory_saves_create_one_revision(stores):
    first, second = stores
    results = await asyncio.gather(
        first.update_memory_settings('new-owner', settings(group_learning_enabled=False), 1),
        second.update_memory_settings('new-owner', settings(learning_interactions_enabled=False), 1),
        return_exceptions=True)
    assert sum(isinstance(result, MemorySettingsConflict) for result in results) == 1
    assert (await first.get_platform_settings('new-owner')).data.memory_settings_revision == 2


@pytest.mark.asyncio
async def test_invalid_memory_value_rolls_back_the_entire_save(stores):
    first, _ = stores
    saved = await first.upsert_platform_settings('owner', PlatformSettingsData())
    malformed = settings().model_copy(update={'learning_enabled': True})
    with pytest.raises(ValidationError):
        await first.update_memory_settings('owner', malformed, 1)
    current = await first.get_platform_settings('owner')
    assert current.data == saved.data
    assert current.updated_at == saved.updated_at


@pytest.mark.asyncio
async def test_update_endpoint_returns_conflict_and_has_no_reset(stores):
    first, _ = stores
    app = FastAPI()
    app.include_router(routes.agent_router)
    app.dependency_overrides[routes.get_current_user_id] = lambda: 'owner'
    app.dependency_overrides[routes.get_storage] = lambda: first
    app.dependency_overrides[routes.get_resource_access_service] = lambda: SimpleNamespace()
    await first.upsert_platform_settings('owner', PlatformSettingsData())
    path = routes.agent_router.prefix + '/platform/memory-settings'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put(path, json=body(group_learning_enabled=False))
        assert response.status_code == 200, response.text
        assert response.json()['revision'] == 2
        assert set(response.json()['settings']) == FIELDS
        stale = await client.put(path, json=body())
        assert stale.status_code == 409, stale.text
        reset = await client.post(path + '/reset', json={'expected_revision': 2})
        assert reset.status_code == 404


@pytest.mark.asyncio
async def test_model_validation_checks_catalog_without_loading_legacy_adapters(monkeypatch):
    config = SimpleNamespace(type='valid', model='model', credential_id='credential', parameters={})
    config.model_copy = lambda update: SimpleNamespace(**{**vars(config), **update})
    async def resolve(_owner, _credential):
        return SimpleNamespace(data={})
    monkeypatch.setattr(routes.CredentialFactory, 'from_dict', lambda _data: SimpleNamespace(type='valid'))
    monkeypatch.setattr(routes, 'build_credential_model_catalog',
        lambda _credential: [SimpleNamespace(name='model', enabled=True)])
    monkeypatch.setattr(routes, 'normalize_credential_model_parameters', lambda *_args: {'temperature': 0.2})
    result = await routes._validate_memory_model_config('owner', config, SimpleNamespace(resolve_credential=resolve))
    assert result.parameters == {'temperature': 0.2}


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['wrong_type', 'disabled', 'missing'])
async def test_model_validation_rejects_unusable_selection(monkeypatch, fault):
    from fastapi import HTTPException
    from agentscope.app.storage import ChatModelConfig
    config = ChatModelConfig(type='valid', model='model', credential_id='credential', parameters={})
    async def resolve(_owner, _credential):
        return SimpleNamespace(data={})
    monkeypatch.setattr(routes.CredentialFactory, 'from_dict',
        lambda _data: SimpleNamespace(type='wrong' if fault == 'wrong_type' else 'valid'))
    monkeypatch.setattr(routes, 'build_credential_model_catalog', lambda _credential:
        [] if fault == 'missing' else [SimpleNamespace(name='model', enabled=fault != 'disabled')])
    with pytest.raises(HTTPException) as error:
        await routes._validate_memory_model_config('owner', config, SimpleNamespace(resolve_credential=resolve))
    assert error.value.status_code == 422


@pytest.mark.parametrize('dialect', ['sqlite', 'redis'])
def test_learning_rejects_storage_without_shared_postgres_lock(dialect):
    storage = RedisStorage() if dialect == 'redis' else AsyncSQLAlchemyStorage('sqlite+aiosqlite:///:memory:')
    with pytest.raises(ValueError, match='PostgreSQL'):
        storage.validate_memory_learning_storage('postgresql://host/db', 'agentscope')


def test_learning_requires_matching_database_and_schema():
    from sqlalchemy.engine import make_url
    storage = AsyncSQLAlchemyStorage('postgresql+asyncpg://host:5432/db', schema='agentscope')
    storage._engine = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'), url=make_url(storage._url))
    storage.validate_memory_learning_storage('postgresql://host/db', 'agentscope')
    for dsn, schema in [('postgresql://other/db', 'agentscope'), ('postgresql://host/other', 'agentscope'),
                        ('postgresql://host/db', 'wrong_schema')]:
        with pytest.raises(ValueError):
            storage.validate_memory_learning_storage(dsn, schema)
