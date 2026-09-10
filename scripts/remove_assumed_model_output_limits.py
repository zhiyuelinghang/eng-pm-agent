"""Remove generated 8192-token guesses from dynamic chat model metadata.

Run without arguments for a read-only preview; --apply updates catalog arrays
in one transaction. Credentials, explicit inference parameters, embedding models
and other output sizes remain unchanged. No startup compatibility path is added.
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
CATALOG_ARRAYS = ('discovered_models', 'manual_models')


def remove_assumed_limits(entries):
    if entries is None:
        return None, []
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError('模型目录格式不正确。')
    result = deepcopy(entries)
    changed = []
    for entry in result:
        if entry.get('model_type', 'chat') != 'chat':
            continue
        if type(entry.get('output_size')) is int and entry['output_size'] == 8192:
            entry['output_size'] = None
            changed.append(entry.get('name'))
    return result, changed


def migrate(connection, schema, *, apply):
    from psycopg import sql
    from psycopg.types.json import Jsonb

    table = sql.Identifier(schema, 'credentials')
    rows = connection.execute(sql.SQL("""SELECT id,
        payload::jsonb #> '{{data,model_catalog,discovered_models}}' AS discovered_models,
        payload::jsonb #> '{{data,model_catalog,manual_models}}' AS manual_models
        FROM {} ORDER BY id""" + (' FOR UPDATE' if apply else '')).format(table)).fetchall()
    records = []
    for row in rows:
        for array in CATALOG_ARRAYS:
            updated, changed = remove_assumed_limits(row[array])
            if not changed:
                continue
            records.append({'credential_id': row['id'], 'source': array, 'models': changed})
            if apply:
                connection.execute(sql.SQL("""UPDATE {} SET payload=jsonb_set(
                    payload::jsonb, %s::text[], %s::jsonb, false) WHERE id=%s""").format(table),
                    (['data', 'model_catalog', array], Jsonb(updated), row['id']))
    return {
        'applied': apply,
        'read_only': not apply,
        'changed_models': sum(len(row['models']) for row in records),
        'records': records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from dotenv import load_dotenv
    import psycopg
    from psycopg.rows import dict_row
    from sqlalchemy.engine import make_url
    from agentscope.credential._model_catalog import CredentialModelDefinition

    if CredentialModelDefinition(name='unknown-output').output_size is not None:
        raise RuntimeError('请先部署未知输出能力为空的新模型目录契约。')
    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('AGENTSCOPE_DATABASE_URL') or os.environ['DATABASE_URL'])
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('此迁移需要 PostgreSQL 配置存储。')
    dsn = url.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE' if args.apply else 'SET TRANSACTION READ ONLY')
        report = migrate(connection, os.getenv('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope').strip(), apply=args.apply)
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    suffix = 'result' if args.apply else 'preview'
    (ROOT / 'artifacts' / f'remove-assumed-model-output-limits-{suffix}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('清理未确认的模型输出上限失败：' + type(error).__name__)
        raise SystemExit(1) from None
