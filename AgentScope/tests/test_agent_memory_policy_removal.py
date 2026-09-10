"""Explicit migration must remove one key and retain every unrelated payload."""
from copy import deepcopy
import os
import re
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json
import pytest

from scripts.remove_agent_memory_policy import plan_removal, remove_in_transaction


def agent(index=1, policy='standard'):
    return {'id': str(index), 'payload': {'data': {
        'name': '迁移验证智能体', 'platform_config': {'role': 'business', 'enabled': True, 'memory_policy': policy},
        'model_policy': {'mode': 'fixed', 'credential_id': 'never-print-this'},
    }, 'extension': {'preserve': ['all', 'other', 'keys']}}}


@pytest.mark.parametrize('policy', ['standard', 'no_learning', 'no_retention', None])
def test_removal_handles_all_stored_values_without_touching_source(policy):
    rows = [agent(policy=policy)]
    original = deepcopy(rows)
    checked = []
    report, changes = plan_removal(rows, checked.append)
    assert changes == ['1']
    assert checked == [{'role': 'business', 'enabled': True}]
    assert rows == original
    assert 'never-print-this' not in str(report)


def test_removal_discovers_all_agents_and_skips_already_absent_fields():
    rows = [agent(index) for index in range(17)]
    rows[-1]['payload']['data']['platform_config'].pop('memory_policy')
    report, changes = plan_removal(rows, lambda _config: None)
    assert len(changes) == 16
    assert report['counts'] == {'remove': 16, 'already_absent': 1}


@pytest.fixture
def migration_connection():
    dsn = os.getenv('DOBBY_MEMORY_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('PostgreSQL connection required for an isolated JSON-column migration test')
    schema = 'policy_removal_test_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as setup:
        setup.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        setup.execute(sql.SQL('CREATE TABLE {}.agents(id text PRIMARY KEY,payload json NOT NULL)').format(sql.Identifier(schema)))
        setup.execute(sql.SQL('CREATE TABLE {}.untouched(payload json NOT NULL)').format(sql.Identifier(schema)))
        setup.execute(sql.SQL('INSERT INTO {}.untouched VALUES (%s)').format(sql.Identifier(schema)),
            (Json({'memory_policy': 'not-agent-config', 'read_scopes': ['project'], 'learning_enabled': True}),))
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            yield connection, schema
    finally:
        assert re.fullmatch(r'policy_removal_test_[a-f0-9]{32}', schema)
        with psycopg.connect(dsn, autocommit=True) as teardown:
            teardown.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_json_column_migration_preserves_all_other_data_and_is_idempotent(migration_connection):
    connection, schema = migration_connection
    original = agent()['payload']
    connection.execute(sql.SQL('INSERT INTO {}.agents VALUES (%s,%s)').format(sql.Identifier(schema)), ('1', Json(original)))
    preview = remove_in_transaction(connection, schema, apply=False, validate_config=lambda _config: None)
    assert preview['read_only'] and preview['counts']['remove'] == 1
    assert connection.execute(sql.SQL('SELECT payload FROM {}.agents').format(sql.Identifier(schema))).fetchone()['payload'] == original
    report = remove_in_transaction(connection, schema, apply=True, validate_config=lambda _config: None)
    expected = deepcopy(original)
    expected['data']['platform_config'].pop('memory_policy')
    assert report['applied']
    assert connection.execute(sql.SQL('SELECT payload FROM {}.agents').format(sql.Identifier(schema))).fetchone()['payload'] == expected
    assert connection.execute(sql.SQL('SELECT payload FROM {}.untouched').format(sql.Identifier(schema))).fetchone()['payload'] == {
        'memory_policy': 'not-agent-config', 'read_scopes': ['project'], 'learning_enabled': True}
    assert remove_in_transaction(connection, schema, apply=True, validate_config=lambda _config: None)['counts'] == {
        'remove': 0, 'already_absent': 1}


def test_validation_failure_blocks_every_write(migration_connection):
    connection, schema = migration_connection
    rows = [agent(1), agent(2)]
    for row in rows:
        connection.execute(sql.SQL('INSERT INTO {}.agents VALUES (%s,%s)').format(sql.Identifier(schema)), (row['id'], Json(row['payload'])))
    count = 0
    def validate(_config):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError('invalid second configuration')
    with pytest.raises(ValueError):
        remove_in_transaction(connection, schema, apply=True, validate_config=validate)
    assert connection.execute(sql.SQL("SELECT count(*) AS n FROM {}.agents WHERE payload->'data'->'platform_config'->'memory_policy' IS NOT NULL")
        .format(sql.Identifier(schema))).fetchone()['n'] == 2
