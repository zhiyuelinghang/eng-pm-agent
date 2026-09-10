"""Explicitly align saved chat bindings with the sole enabled platform model.

Preview is read-only. --apply updates only current binding paths and one manual
capability definition. Conversation state, historical audits, credentials,
embedding/TTS settings and unconfigured bindings are untouched.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'AgentScope')]
IMAGE_TYPES = ['text/plain', 'image/png', 'image/jpeg', 'image/webp', 'image/gif']
BINDINGS = {
    'agents': [('data', 'model_policy', 'chat_model_config')],
    'sessions': [('config', 'chat_model_config'), ('config', 'fallback_chat_model_config')],
    'schedules': [('data', 'chat_model_config')],
    'platform_settings': [('data', 'memory_settings', 'learning_model_config'),
                          ('data', 'memory_settings', 'compression_model_config')],
    'permission_reviewer_configs': [('data',)],
}


def aligned_binding(value, target, *, fallback=False, reviewer=False):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('模型绑定不是对象。')
    if fallback:
        return None
    if not value.get('model') or not value.get('credential_id'):
        return deepcopy(value)
    result = deepcopy(value)
    result['credential_id'] = target['credential_id']
    result['model'] = target['model']
    result['parameters'] = {}
    if not reviewer:
        result['type'] = target['type']
    return result


def migrate(connection, schema, credential_id, model, *, apply):
    from psycopg import sql
    from psycopg.types.json import Jsonb
    from agentscope.credential import CustomOpenAICredential, CredentialModelCatalog
    from agentscope.app._service._credential_models import build_credential_model_catalog

    credential_table = sql.Identifier(schema, 'credentials')
    row = connection.execute(sql.SQL("""SELECT id,
        payload::jsonb #>> '{{data,type}}' AS type,
        payload::jsonb #> '{{data,model_catalog}}' AS catalog
        FROM {} WHERE id=%s""" + (' FOR UPDATE' if apply else '')).format(credential_table), (credential_id,)).fetchone()
    if not row or row['type'] != 'custom_openai_credential':
        raise ValueError('当前迁移只适用于已核验的自定义模型凭证。')
    catalog = CredentialModelCatalog.model_validate(row['catalog'] or {})
    # Metadata-only construction; no saved API key or endpoint is selected.
    credential = CustomOpenAICredential(api_key='metadata-only', base_url='https://example.invalid/v1', model_catalog=catalog)
    enabled = [item for item in build_credential_model_catalog(credential) if item.enabled]
    if len(enabled) != 1 or enabled[0].name != model:
        raise ValueError('已启用模型不再是预期的唯一目标。')
    target = {'credential_id': credential_id, 'type': row['type'], 'model': model}
    report = {'target': target, 'bindings': [], 'unchanged': {}, 'unconfigured': {}, 'applied': apply}

    definition = next((item for item in reversed(catalog.discovered_models + catalog.manual_models)
        if item.name == model and item.model_type == 'chat'), None)
    if definition is None:
        raise ValueError('找不到目标模型的能力定义。')
    definition = definition.model_copy(update={'input_types': IMAGE_TYPES})
    manual = [item.model_dump(mode='json') for item in catalog.manual_models
              if not (item.name == model and item.model_type == 'chat')]
    manual.append(definition.model_dump(mode='json'))
    capability_changed = manual != [item.model_dump(mode='json') for item in catalog.manual_models]
    report['capability_changed'] = capability_changed
    report['input_types'] = IMAGE_TYPES
    if apply and capability_changed:
        connection.execute(sql.SQL("""UPDATE {} SET payload=jsonb_set(payload::jsonb,
            '{{data,model_catalog,manual_models}}', %s::jsonb, true) WHERE id=%s""").format(credential_table),
            (Jsonb(manual), credential_id))

    for table_name, paths in BINDINGS.items():
        table = sql.Identifier(schema, table_name)
        settings_changed = set()
        for path in paths:
            rows = connection.execute(sql.SQL('SELECT id,user_id,payload::jsonb #> %s::text[] AS binding FROM {} ORDER BY id'
                + (' FOR UPDATE' if apply else '')).format(table), (list(path),)).fetchall()
            label = table_name + '.' + '.'.join(path)
            for binding_row in rows:
                value = binding_row['binding']
                next_value = aligned_binding(value, target, fallback=path[-1] == 'fallback_chat_model_config',
                    reviewer=table_name == 'permission_reviewer_configs')
                if value == next_value:
                    counter = report['unconfigured'] if value is None or not value.get('model') else report['unchanged']
                    counter[label] = counter.get(label, 0) + 1
                    continue
                report['bindings'].append({'table': table_name, 'id': binding_row['id'], 'path': list(path),
                    'previous_model': value.get('model'), 'previous_credential_id': value.get('credential_id'),
                    'cleared_parameter_keys': sorted(value.get('parameters') or {}),
                    'next_model': next_value.get('model') if next_value else None})
                if apply:
                    connection.execute(sql.SQL('UPDATE {} SET payload=jsonb_set(payload::jsonb, %s::text[], %s::jsonb, false) WHERE id=%s').format(table),
                        (list(path), Jsonb(next_value), binding_row['id']))
                    if table_name == 'platform_settings':
                        settings_changed.add(binding_row['id'])
        for identifier in settings_changed:
            connection.execute(sql.SQL("""UPDATE {} SET payload=jsonb_set(payload::jsonb,
                '{{data,memory_settings_revision}}',
                to_jsonb(COALESCE((payload::jsonb #>> '{{data,memory_settings_revision}}')::integer, 1)+1), true)
                WHERE id=%s""").format(table), (identifier,))
    report['changed_bindings'] = len(report['bindings'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential-id', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from dotenv import load_dotenv
    import psycopg
    from psycopg.rows import dict_row
    from sqlalchemy.engine import make_url

    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('AGENTSCOPE_DATABASE_URL') or os.environ['DATABASE_URL'])
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('此迁移需要 PostgreSQL。')
    with psycopg.connect(url.set(drivername='postgresql').render_as_string(hide_password=False), row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE' if args.apply else 'SET TRANSACTION READ ONLY')
        report = migrate(connection, os.getenv('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope'),
            args.credential_id, args.model, apply=args.apply)
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    suffix = 'result' if args.apply else 'preview'
    (ROOT / 'artifacts' / f'align-platform-chat-model-{suffix}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('统一模型配置未完成：' + type(error).__name__)
        raise SystemExit(1) from None
