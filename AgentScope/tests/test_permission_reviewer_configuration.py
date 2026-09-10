"""Single-model reviewer contract and explicit retirement of four old keys."""
import asyncio
from copy import deepcopy
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import ValidationError
import pytest

from agentscope.app._router._schema._credential import UpdatePermissionReviewerConfigRequest, TestPermissionReviewerConfigRequest as ReviewerTestRequest
from agentscope.app._service._permission_review import ModelPermissionReviewer, PermissionReviewService
from agentscope.app.storage import PermissionReviewerConfigData, PermissionReviewerConfigRecord
from agentscope.permission import PermissionReviewAction, PermissionReviewRequest
from scripts.simplify_permission_reviewer import CURRENT, REMOVED, plan_simplification, simplify_in_transaction


@pytest.mark.parametrize('field', sorted(REMOVED))
def test_removed_fields_are_not_accepted_by_config_save_or_model_test(field):
    for schema in (PermissionReviewerConfigData, UpdatePermissionReviewerConfigRequest, ReviewerTestRequest):
        with pytest.raises(ValidationError):
            schema.model_validate({'credential_id': 'credential', 'model': 'model', field: None})


@pytest.mark.parametrize('binding', [{}, {'credential_id': 'c'}, {'model': 'm'},
    {'credential_id': None, 'model': None}, {'credential_id': ' ', 'model': 'm'}])
def test_save_and_test_require_a_complete_nonblank_primary_binding(binding):
    for schema in (UpdatePermissionReviewerConfigRequest, ReviewerTestRequest):
        with pytest.raises(ValidationError):
            schema.model_validate(binding)


def test_internal_unconfigured_record_remains_valid_and_has_only_six_fields():
    assert set(PermissionReviewerConfigData.model_fields) == CURRENT
    default = PermissionReviewerConfigData()
    assert default.credential_id is None and default.model is None
    with pytest.raises(ValidationError):
        PermissionReviewerConfigData(credential_id='only-one-field')


@pytest.mark.asyncio
@pytest.mark.parametrize('configured', [False, True])
async def test_unconfigured_or_unavailable_model_keeps_human_confirmation(configured):
    config = PermissionReviewerConfigData(credential_id='c', model='m') if configured else PermissionReviewerConfigData()
    storage = SimpleNamespace(get_permission_reviewer_config=AsyncMock(
        return_value=PermissionReviewerConfigRecord(user_id='owner', data=config)))
    service = PermissionReviewService(storage, SimpleNamespace())
    service._resolve_model = AsyncMock(side_effect=RuntimeError('model unavailable'))
    assert await service.build_reviewer(user_id='owner', agent_id='agent', session_id='session') is None
    assert service._resolve_model.await_count == int(configured)


@pytest.mark.asyncio
async def test_service_builds_only_the_configured_primary_model():
    config = PermissionReviewerConfigData(credential_id='c', model='m')
    storage = SimpleNamespace(get_permission_reviewer_config=AsyncMock(
        return_value=PermissionReviewerConfigRecord(user_id='owner', data=config)))
    service = PermissionReviewService(storage, SimpleNamespace())
    model = SimpleNamespace()
    service._resolve_model = AsyncMock(return_value=model)
    reviewer = await service.build_reviewer(user_id='owner', agent_id='agent', session_id='session')
    assert reviewer._model is model and reviewer._model_name == 'm'
    service._resolve_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_falls_back_to_human_without_another_model_call():
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    model = SimpleNamespace(generate_structured_output=AsyncMock(side_effect=slow))
    config = PermissionReviewerConfigData(credential_id='c', model='m').model_copy(update={'timeout_seconds': .01})
    reviewer = ModelPermissionReviewer(model_name='m', model=model, config=config)
    result = await reviewer.review(PermissionReviewRequest(agent_name='worker', tool_name='WriteFile',
        tool_input={'path': 'report.md'}, user_intent='Write a report', permission_mode='auto'))
    assert result.action == PermissionReviewAction.HUMAN_REQUIRED
    assert result.source == 'model_error'
    model.generate_structured_output.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('unavailable', [False, True])
async def test_model_test_distinguishes_unavailability_from_valid_human_required(unavailable):
    model = SimpleNamespace(generate_structured_output=AsyncMock(
        side_effect=RuntimeError('model offline') if unavailable else None,
        return_value=SimpleNamespace(content={'action': 'human_required', 'risk': 'high',
            'confidence': .9, 'reason': '有效审核结果，需要人工确认。'})))
    service = PermissionReviewService(SimpleNamespace(), SimpleNamespace())
    service._resolve_model = AsyncMock(return_value=model)
    result = await service.test_config('owner', PermissionReviewerConfigData(credential_id='c', model='m'))
    assert result.success is (not unavailable)
    if unavailable:
        assert result.error and '不可用' in result.error
    else:
        assert result.action == 'human_required' and result.error is None


def old_config(enabled=True):
    return {**PermissionReviewerConfigData(credential_id='private-credential', model='review-model',
        parameters={'private_parameter': 'must-not-be-audited'}).model_dump(),
        'enabled': enabled, 'fallback_credential_id': 'private-fallback-credential',
        'fallback_model': 'retired-model', 'fallback_parameters': {'secret': 'preserve-no-audit'}}


def row(config=None, owner='owner'):
    return {'id': owner, 'user_id': owner, 'config': old_config() if config is None else config}


def test_migration_plan_only_removes_retired_keys_and_audits_no_credentials():
    source = row()
    initial = deepcopy(source)
    report, changes = plan_simplification([source], PermissionReviewerConfigData.model_validate)
    assert source == initial and changes == ['owner']
    assert set(report['records'][0]['fields_after']) == CURRENT
    assert report['manual_review_owners'] == []
    audit = json.dumps(report)
    for secret in ['private-credential', 'private-fallback-credential', 'must-not-be-audited', 'preserve-no-audit']:
        assert secret not in audit


def test_previously_disabled_primary_model_is_reported_for_manual_review():
    report, _ = plan_simplification([row(old_config(False))], PermissionReviewerConfigData.model_validate)
    assert report['manual_review_owners'] == ['owner']
    assert report['records'][0]['would_activate_previously_disabled_model'] is True


@pytest.fixture
def database():
    dsn = os.getenv('DOBBY_MEMORY_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('PostgreSQL required for isolated reviewer migration')
    schema = 'reviewer_simplification_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as setup:
        setup.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        for name in ['permission_reviewer_configs', 'permission_review_audits']:
            setup.execute(sql.SQL('CREATE TABLE {} (id text PRIMARY KEY,user_id text,payload json,updated_at timestamp DEFAULT now())')
                .format(sql.Identifier(schema, name)))
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            yield connection, schema
    finally:
        with psycopg.connect(dsn, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def insert(connection, schema, owner='owner', config=None):
    payload = {'data': old_config() if config is None else config, 'untouched': {'credential': 'never-print'}}
    connection.execute(sql.SQL('INSERT INTO {} (id,user_id,payload) VALUES (%s,%s,%s)')
        .format(sql.Identifier(schema, 'permission_reviewer_configs')), (owner, owner, Json(payload)))
    connection.commit()
    return payload


def read(connection, schema, table='permission_reviewer_configs'):
    return connection.execute(sql.SQL('SELECT * FROM {} ORDER BY id').format(sql.Identifier(schema, table))).fetchall()


def test_real_json_migration_preserves_primary_configuration_audits_and_timestamps(database):
    connection, schema = database
    original = insert(connection, schema)
    connection.execute(sql.SQL("INSERT INTO {} (id,user_id,payload) VALUES ('audit','owner',%s)")
        .format(sql.Identifier(schema, 'permission_review_audits')), (Json({'reason': 'historical-review'}),))
    connection.commit()
    before, audits = read(connection, schema), read(connection, schema, 'permission_review_audits')
    preview = simplify_in_transaction(connection, schema, apply=False, validate_config=PermissionReviewerConfigData.model_validate)
    assert preview['read_only'] and read(connection, schema) == before
    simplify_in_transaction(connection, schema, apply=True, validate_config=PermissionReviewerConfigData.model_validate)
    connection.commit()
    after = read(connection, schema)
    expected = deepcopy(original)
    for field in REMOVED:
        expected['data'].pop(field)
    assert after[0]['payload'] == expected
    assert after[0]['updated_at'] == before[0]['updated_at']
    assert read(connection, schema, 'permission_review_audits') == audits
    second = simplify_in_transaction(connection, schema, apply=True, validate_config=PermissionReviewerConfigData.model_validate)
    connection.commit()
    assert second['counts'] == {'remove': 0, 'already_current': 1}
    assert read(connection, schema) == after


@pytest.mark.parametrize('invalid', [{'unknown_field': True}, {'enabled': False}])
def test_all_owners_validate_before_any_write_and_disabled_models_cannot_be_activated(database, invalid):
    connection, schema = database
    insert(connection, schema, 'first-valid')
    insert(connection, schema, 'last-blocked', {**old_config(), **invalid})
    before = read(connection, schema)
    with pytest.raises(ValueError):
        simplify_in_transaction(connection, schema, apply=True, validate_config=PermissionReviewerConfigData.model_validate)
    assert read(connection, schema) == before
    connection.rollback()
