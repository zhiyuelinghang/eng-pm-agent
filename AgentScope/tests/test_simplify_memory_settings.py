"""Explicit six-field migration must be atomic, idempotent and narrowly scoped."""
from copy import deepcopy
from datetime import datetime
import json
import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json
import pytest

from agentscope.app.storage import MemorySettingsData
from scripts.simplify_memory_settings import NEW_FIELDS, plan_simplification, simplify_in_transaction


def old_settings():
    return {
        'learning_enabled': True,
        'learning_model_config': {'type': 'test', 'credential_id': 'private-credential', 'model': 'learning-model',
                                  'parameters': {'custom_secret': 'never-audit-this'}},
        'learning_interactions_enabled': False,
        'learning_business_events_enabled': True,
        'group_learning_enabled': True,
        'memory_model_config': {'type': 'test', 'credential_id': 'private-compression-credential',
                                'model': 'compression-model', 'parameters': {}},
        'compression_system_prompt': 'private-prompt-content',
        'learning_daily_job_limit': 23,
    }


def row(identifier='first', **changes):
    return {'id': identifier, 'user_id': identifier, 'settings': {**old_settings(), **changes},
            'revision': 8, 'data_type': 'object'}


def test_preserves_choices_and_models_without_exposing_credentials_or_prompts():
    original = row()
    before = deepcopy(original)
    report, changes = plan_simplification([original], MemorySettingsData.model_validate)
    assert original == before
    after = changes[0]['settings']
    assert set(after) == NEW_FIELDS
    assert after['compression_model_config'] == before['settings']['memory_model_config']
    assert after['learning_model_config'] == before['settings']['learning_model_config']
    assert after['learning_interactions_enabled'] is False
    assert changes[0]['revision'] == 9
    audit = json.dumps(report)
    for private_value in ['private-credential', 'private-compression-credential', 'never-audit-this', 'private-prompt-content']:
        assert private_value not in audit
    assert 'learning-model' in audit and 'compression-model' in audit


def test_new_format_is_unchanged_and_does_not_increment_revision():
    current = row()
    current['settings'] = MemorySettingsData().model_dump()
    report, changes = plan_simplification([current], MemorySettingsData.model_validate)
    assert changes == []
    assert report['counts'] == {'migrate': 0, 'already_current': 1}
    assert report['records'][0]['revision_after'] == 8


def test_equal_new_and_old_model_fields_can_be_consolidated():
    source = row()
    source['settings']['compression_model_config'] = deepcopy(source['settings']['memory_model_config'])
    _, changes = plan_simplification([source], MemorySettingsData.model_validate)
    assert changes[0]['settings']['compression_model_config'] == source['settings']['memory_model_config']


@pytest.mark.parametrize('changes', [
    {'unknown_technical_setting': True},
    {'compression_model_config': None},
    {'learning_enabled': 'true'},
    {'learning_model_config': None},
    {'learning_interactions_enabled': False, 'learning_business_events_enabled': False, 'group_learning_enabled': False},
])
def test_unknown_conflicting_or_invalid_values_stop_migration(changes):
    with pytest.raises(ValueError):
        plan_simplification([row(**changes)], MemorySettingsData.model_validate)


@pytest.fixture
def database():
    dsn = os.getenv('DOBBY_MEMORY_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('PostgreSQL required for an isolated JSON-column migration test')
    schema = 'simplify_settings_test_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as setup:
        setup.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        setup.execute(sql.SQL('''CREATE TABLE {}.platform_settings (
            id text PRIMARY KEY,user_id text UNIQUE NOT NULL,payload json NOT NULL,
            updated_at timestamp NOT NULL)''').format(sql.Identifier(schema)))
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            yield connection, schema
    finally:
        with psycopg.connect(dsn, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def insert(connection, schema, identifier='first', *, extra=None):
    payload = {'data': {
        'memory_settings': {**old_settings(), **(extra or {})},
        'memory_settings_revision': 8,
        'weknora_connection': {'api_key': 'must-remain-private'},
        'global_main_agent_id': 'main',
    }, 'unrelated_payload': {'keep': ['exactly', 'as', 'saved']}}
    connection.execute(sql.SQL('INSERT INTO {}.platform_settings VALUES (%s,%s,%s,%s)').format(sql.Identifier(schema)),
        (identifier, identifier, Json(payload), datetime(2020, 1, 1)))
    connection.commit()
    return payload


def read(connection, schema):
    return connection.execute(sql.SQL('SELECT * FROM {}.platform_settings ORDER BY id').format(sql.Identifier(schema))).fetchall()


def test_preview_changes_nothing_and_apply_changes_only_two_paths_and_timestamp(database):
    connection, schema = database
    original_payload = insert(connection, schema)
    initial = read(connection, schema)
    preview = simplify_in_transaction(connection, schema, apply=False, validate_settings=MemorySettingsData.model_validate)
    connection.commit()
    assert preview['applied'] is False
    assert read(connection, schema) == initial
    result = simplify_in_transaction(connection, schema, apply=True, validate_settings=MemorySettingsData.model_validate)
    connection.commit()
    saved = read(connection, schema)[0]
    current = saved['payload']
    assert set(current['data']['memory_settings']) == NEW_FIELDS
    assert current['data']['memory_settings_revision'] == 9
    assert saved['updated_at'] > initial[0]['updated_at']
    restored = deepcopy(current)
    restored['data']['memory_settings'] = original_payload['data']['memory_settings']
    restored['data']['memory_settings_revision'] = 8
    assert restored == original_payload
    assert 'must-remain-private' not in json.dumps(result)
    once = read(connection, schema)
    second = simplify_in_transaction(connection, schema, apply=True, validate_settings=MemorySettingsData.model_validate)
    connection.commit()
    assert second['counts'] == {'migrate': 0, 'already_current': 1}
    assert read(connection, schema) == once


def test_all_rows_validate_before_any_update(database):
    connection, schema = database
    insert(connection, schema, 'first-valid')
    insert(connection, schema, 'last-invalid', extra={'unreviewed_field': True})
    before = read(connection, schema)
    with pytest.raises(ValueError):
        simplify_in_transaction(connection, schema, apply=True, validate_settings=MemorySettingsData.model_validate)
    # Even before rolling back, the earlier valid row must be untouched.
    assert read(connection, schema) == before
    connection.rollback()
