from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('align_platform_chat_model', ROOT / 'scripts/align_platform_chat_model.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TARGET = {'credential_id': 'current-credential', 'model': 'current-model', 'type': 'custom_openai_credential'}


def test_chat_binding_changes_identity_and_inherits_model_parameters_without_mutating_input():
    old = {'type': 'old-type', 'credential_id': 'old-credential', 'model': 'old-model',
           'parameters': {'thinking_enable': False, 'max_tokens': 8192}}
    snapshot = deepcopy(old)
    result = module.aligned_binding(old, TARGET)
    assert result == {**TARGET, 'parameters': {}}
    assert old == snapshot


def test_reviewer_keeps_rules_and_does_not_add_chat_type():
    old = {'credential_id': 'old', 'model': 'old', 'parameters': {'temperature': 0},
           'confidence_threshold': .85, 'max_auto_risk': 'medium', 'timeout_seconds': 60}
    result = module.aligned_binding(old, TARGET, reviewer=True)
    assert result == {**old, 'credential_id': TARGET['credential_id'], 'model': TARGET['model'], 'parameters': {}}
    assert 'type' not in result


@pytest.mark.parametrize('value', [None, {}, {'credential_id': None, 'model': None}, {'parameters': {}}])
def test_unconfigured_or_inherited_bindings_are_not_enabled(value):
    assert module.aligned_binding(value, TARGET) == value


def test_same_model_is_idempotent_and_fallback_is_retired():
    binding = {**TARGET, 'parameters': {}}
    assert module.aligned_binding(binding, TARGET) == binding
    assert module.aligned_binding(binding, TARGET, fallback=True) is None
    assert module.aligned_binding(None, TARGET, fallback=True) is None


def test_malformed_binding_fails_before_migration_writes():
    with pytest.raises(ValueError):
        module.aligned_binding('bad-binding', TARGET)


class FakeConnection:
    def __init__(self, extra_enabled=False, manual_models=None):
        self.calls = []
        self.extra_enabled = extra_enabled
        self.manual_models = manual_models or []
        self.rows = []
    def execute(self, statement, arguments=()):
        query = statement.as_string()
        self.calls.append((query, arguments))
        if 'SELECT' in query and '"credentials"' in query:
            entries = [{'name': TARGET['model'], 'input_types': ['text/plain']}]
            if self.extra_enabled:
                entries.append({'name': 'another-enabled-model'})
            self.rows = [{'id': TARGET['credential_id'], 'type': TARGET['type'],
                          'catalog': {'discovered_models': entries, 'manual_models': self.manual_models}}]
        elif 'SELECT' in query and '"agents"' in query:
            self.rows = [{'id': 'agent', 'user_id': 'owner', 'binding': {'type': TARGET['type'],
                'credential_id': TARGET['credential_id'], 'model': 'old-model', 'parameters': {}}}]
        elif 'SELECT' in query:
            self.rows = []
        return self
    def fetchone(self):
        return self.rows[0] if self.rows else None
    def fetchall(self):
        return self.rows


def test_preview_reads_only_binding_metadata_and_does_not_write():
    connection = FakeConnection()
    result = module.migrate(connection, 'agentscope', TARGET['credential_id'], TARGET['model'], apply=False)
    assert result['changed_bindings'] == 1
    assert result['capability_changed']
    assert all(not query.lstrip().startswith('UPDATE') for query, _ in connection.calls)
    assert all("payload::jsonb->'data'" not in query for query, _ in connection.calls)


def test_apply_only_changes_manual_capability_and_named_current_chat_binding_paths():
    connection = FakeConnection()
    module.migrate(connection, 'agentscope', TARGET['credential_id'], TARGET['model'], apply=True)
    updates = [(query, args) for query, args in connection.calls if query.lstrip().startswith('UPDATE')]
    assert len(updates) == 2
    assert '{data,model_catalog,manual_models}' in updates[0][0]
    manual = updates[0][1][0].obj
    assert manual[0]['input_types'] == module.IMAGE_TYPES
    assert manual[0]['output_size'] is None
    assert updates[1][1][0] == ['data', 'model_policy', 'chat_model_config']
    assert updates[1][1][1].obj == {**TARGET, 'parameters': {}}
    assert all('audits' not in query and 'messages' not in query for query, _ in connection.calls)


def test_non_unique_enabled_model_aborts_without_changes():
    connection = FakeConnection(extra_enabled=True)
    with pytest.raises(ValueError, match='唯一目标'):
        module.migrate(connection, 'agentscope', TARGET['credential_id'], TARGET['model'], apply=True)
    assert all(not query.lstrip().startswith('UPDATE') for query, _ in connection.calls)


def test_same_named_embedding_definition_is_preserved():
    connection = FakeConnection(manual_models=[{
        'name': TARGET['model'], 'model_type': 'embedding', 'dimensions': 1024,
        'input_types': ['text/plain'],
    }, {
        'name': TARGET['model'], 'model_type': 'chat', 'input_types': ['text/plain'],
    }])
    module.migrate(connection, 'agentscope', TARGET['credential_id'], TARGET['model'], apply=True)
    updates = [(query, args) for query, args in connection.calls if query.lstrip().startswith('UPDATE')]
    manual = updates[0][1][0].obj
    assert len(manual) == 2
    assert manual[0]['model_type'] == 'embedding'
    assert manual[0]['dimensions'] == 1024
    assert manual[0]['input_types'] == ['text/plain']
    assert manual[1]['model_type'] == 'chat'
    assert manual[1]['input_types'] == module.IMAGE_TYPES
