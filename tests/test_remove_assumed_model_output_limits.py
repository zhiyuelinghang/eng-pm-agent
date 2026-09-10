"""Offline review of the one-time catalog cleanup; never opens a database."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts import remove_assumed_model_output_limits as script


class CatalogConnection:
    def __init__(self, credentials):
        self.credentials = deepcopy(credentials)
        self.calls = []
        self.read_only = False
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        self.before = deepcopy(self.credentials)
        return self

    def __exit__(self, kind, *_):
        if kind:
            self.credentials = self.before
            self.rollbacks += 1
        else:
            self.commits += 1

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else query.as_string()
        self.calls.append((text, params))
        if text.startswith('SET TRANSACTION'):
            self.read_only = 'READ ONLY' in text
            return SimpleNamespace(fetchall=lambda:[])
        if text.startswith('SELECT'):
            assert 'payload::jsonb #>' in text
            assert 'SELECT *' not in text
            rows = []
            for record in self.credentials:
                catalog = record['payload']['data'].get('model_catalog') or {}
                rows.append({'id':record['id'], **{
                    key:deepcopy(catalog.get(key)) for key in script.CATALOG_ARRAYS}})
            return SimpleNamespace(fetchall=lambda:rows)
        assert text.startswith('UPDATE') and not self.read_only
        assert 'SET payload=jsonb_set(' in text and 'WHERE id=%s' in text
        assert '%s::text[], %s::jsonb, false' in text
        path, encoded, record_id = params
        assert path[:2] == ['data','model_catalog']
        assert len(path) == 3 and path[2] in script.CATALOG_ARRAYS
        for record in self.credentials:
            if record['id'] == record_id:
                record['payload']['data']['model_catalog'][path[2]] = deepcopy(encoded.obj)
        return SimpleNamespace()


def credentials():
    return [{'id':'credential-1', 'payload':{'data':{
        'api_key':'fake-private-key',
        'model_default_parameters':{'max_tokens':8192, 'reasoning_effort':'high'},
        'model_catalog':{
            'discovered_models':[
                {'name':'generated', 'model_type':'chat', 'output_size':8192,
                    'parameters':{'max_tokens':8192, 'reasoning_effort':'high'}},
                {'name':'embed', 'model_type':'embedding', 'output_size':8192},
                {'name':'explicit-other-size', 'model_type':'chat', 'output_size':32768}],
            'manual_models':[
                {'name':'manual-generated', 'model_type':'chat', 'output_size':8192},
                {'name':'manual-known', 'model_type':'chat', 'output_size':4096}],
            'model_default_parameters':{'max_output_tokens':8192},
        }}}}, {'id':'credential-2', 'payload':{'data':{
            'secret':'another-private-field', 'model_catalog':None}}}]


def test_only_integer_8192_chat_limits_change_and_input_stays_independent():
    original = credentials()[0]['payload']['data']['model_catalog']['discovered_models']
    original += [{'name':'implicit-chat','output_size':8192}]
    before = deepcopy(original)
    updated, names = script.remove_assumed_limits(original)
    assert names == ['generated','implicit-chat']
    assert updated[0]['output_size'] is None and updated[-1]['output_size'] is None
    assert updated[1:3] == original[1:3]
    assert updated[0]['parameters'] == {'max_tokens':8192,'reasoning_effort':'high'}
    updated[0]['parameters']['max_tokens'] = 1
    assert original == before


@pytest.mark.parametrize('value', [None, 4096, 16384, '8192', 8192.0, True])
def test_other_values_are_not_reinterpreted(value):
    entries = [{'name':'unchanged','model_type':'chat','output_size':value}]
    assert script.remove_assumed_limits(entries) == (entries, [])


@pytest.mark.parametrize('entries', [{}, 'not-a-list', [None], [{'name':'valid'}, 'bad-entry']])
def test_malformed_catalog_fails_without_mutating_input(entries):
    before = deepcopy(entries)
    with pytest.raises(ValueError, match='目录格式'):
        script.remove_assumed_limits(entries)
    assert entries == before


def test_missing_catalog_is_not_created():
    assert script.remove_assumed_limits(None) == (None, [])


def test_preview_projects_only_catalog_arrays_and_performs_no_update():
    original = credentials()
    connection = CatalogConnection(original)
    result = script.migrate(connection, 'agentscope', apply=False)
    assert result['read_only'] is True and result['applied'] is False
    assert result['changed_models'] == 2
    assert connection.credentials == original
    assert len(connection.calls) == 1
    query, params = connection.calls[0]
    assert 'FOR UPDATE' not in query and params is None
    assert 'api_key' not in query and 'model_default_parameters' not in query
    assert '{data,model_catalog,discovered_models}' in query
    assert '{data,model_catalog,manual_models}' in query
    assert 'fake-private-key' not in json.dumps(result)


def test_apply_updates_only_two_array_paths_is_idempotent_and_preserves_parameters():
    original = credentials()
    expected = deepcopy(original)
    catalog = expected[0]['payload']['data']['model_catalog']
    catalog['discovered_models'][0]['output_size'] = None
    catalog['manual_models'][0]['output_size'] = None
    connection = CatalogConnection(original)
    report = script.migrate(connection, 'agentscope', apply=True)
    assert report['changed_models'] == 2 and report['applied'] is True
    assert connection.credentials == expected
    assert original == credentials()
    assert 'FOR UPDATE' in connection.calls[0][0]
    assert [call[1][0] for call in connection.calls[1:]] == [
        ['data','model_catalog','discovered_models'], ['data','model_catalog','manual_models']]
    first_calls = len(connection.calls)
    second = script.migrate(connection, 'agentscope', apply=True)
    assert second['changed_models'] == 0 and second['records'] == []
    assert len(connection.calls) == first_calls + 1
    assert connection.credentials == expected


def configure_main(monkeypatch, tmp_path, connection, *, apply=False):
    import dotenv
    import psycopg
    from agentscope.credential import _model_catalog
    monkeypatch.setattr(script, 'ROOT', tmp_path)
    (tmp_path / 'artifacts').mkdir()
    monkeypatch.setattr(script.sys, 'argv', ['remove_assumed_model_output_limits.py'] + (['--apply'] if apply else []))
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *_:None)
    monkeypatch.setenv('AGENTSCOPE_DATABASE_URL', 'postgresql://fake:fake-password@never-connect.invalid/review')
    monkeypatch.setenv('AGENTSCOPE_DATABASE_SCHEMA', 'review_schema')
    monkeypatch.setattr(_model_catalog, 'CredentialModelDefinition', lambda **_:SimpleNamespace(output_size=None))
    opened = []

    def connect(dsn, **_):
        assert 'never-connect.invalid' in dsn
        opened.append(True)
        return connection

    monkeypatch.setattr(psycopg, 'connect', connect)
    return opened


def test_cli_without_apply_is_read_only_and_report_contains_no_credentials(monkeypatch, tmp_path, capsys):
    connection = CatalogConnection(credentials())
    opened = configure_main(monkeypatch, tmp_path, connection)
    script.main()
    assert opened == [True]
    assert connection.calls[0] == ('SET TRANSACTION READ ONLY', None)
    assert connection.credentials == credentials()
    report = json.loads((tmp_path / 'artifacts/remove-assumed-model-output-limits-preview.json').read_text('utf-8'))
    assert report['read_only'] is True and report['changed_models'] == 2
    stdout = capsys.readouterr().out
    assert 'fake-password' not in stdout and 'fake-private-key' not in stdout


def test_cli_apply_uses_one_transaction_and_rolls_back_all_arrays_on_invalid_catalog(monkeypatch, tmp_path):
    rows = credentials()
    rows[1]['payload']['data']['model_catalog'] = {'manual_models':'malformed'}
    connection = CatalogConnection(rows)
    configure_main(monkeypatch, tmp_path, connection, apply=True)
    with pytest.raises(ValueError, match='目录格式'):
        script.main()
    assert connection.calls[0] == ('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE', None)
    assert connection.commits == 0 and connection.rollbacks == 1
    assert connection.credentials == rows
    assert not (tmp_path / 'artifacts/remove-assumed-model-output-limits-result.json').exists()
