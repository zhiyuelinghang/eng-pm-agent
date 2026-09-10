"""Explicitly retire reviewer enablement and fallback-model configuration.

The default is a read-only preview. --apply removes exactly four keys from
permission_reviewer_configs.payload.data in one transaction. Configured primary
models, their parameters, policy gates, timestamps and review audits are kept.
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
REMOVED = frozenset({'enabled', 'fallback_credential_id', 'fallback_model', 'fallback_parameters'})
CURRENT = frozenset({'credential_id', 'model', 'parameters', 'confidence_threshold', 'max_auto_risk', 'timeout_seconds'})


def plan_simplification(rows, validate_config):
    report = {'records': [], 'counts': {'remove': 0, 'already_current': 0}, 'manual_review_owners': []}
    changes = []
    for row in rows:
        old = row['config']
        if not isinstance(old, dict):
            raise ValueError('审核配置不是对象。')
        if set(old) - CURRENT - REMOVED:
            raise ValueError('审核配置包含未经审查的字段。')
        if 'enabled' in old and type(old['enabled']) is not bool:
            raise ValueError('原审核启用状态不是布尔值。')
        after = deepcopy({key: value for key, value in old.items() if key not in REMOVED})
        validate_config(after)
        removed = sorted(set(old) & REMOVED)
        status = 'remove' if removed else 'already_current'
        report['counts'][status] += 1
        would_activate = old.get('enabled') is False and bool(after.get('credential_id') and after.get('model'))
        if would_activate:
            report['manual_review_owners'].append(row['user_id'])
        report['records'].append({
            'id': row['id'], 'owner': row['user_id'], 'status': status,
            'removed_fields': removed, 'fields_after': sorted(after),
            'previously_enabled': old.get('enabled'), 'primary_model': after.get('model'),
            'retired_fallback_model': old.get('fallback_model'),
            'would_activate_previously_disabled_model': would_activate,
        })
        if removed:
            changes.append(row['id'])
    return report, changes


def simplify_in_transaction(connection, schema, *, apply, validate_config):
    from psycopg import sql
    table = sql.Identifier(schema, 'permission_reviewer_configs')
    rows = connection.execute(sql.SQL("SELECT id,user_id,payload::jsonb->'data' AS config FROM {} ORDER BY id" +
        (' FOR UPDATE' if apply else '')).format(table)).fetchall()
    report, changes = plan_simplification(rows, validate_config)
    if apply:
        if report['manual_review_owners']:
            raise ValueError('存在已配置主模型但原来停用的审核员，请先逐项确认预览，不能自动启用。')
        for identifier in changes:
            connection.execute(sql.SQL("""UPDATE {} SET payload=payload::jsonb
                #- '{{data,enabled}}' #- '{{data,fallback_credential_id}}'
                #- '{{data,fallback_model}}' #- '{{data,fallback_parameters}}' WHERE id=%s""")
                .format(table), (identifier,))
    return {**report, 'read_only': not apply, 'applied': apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='核验全部审核员配置后，仅移除四个退休字段')
    args = parser.parse_args()
    from dotenv import load_dotenv
    import psycopg
    from psycopg.rows import dict_row
    from sqlalchemy.engine import make_url
    from agentscope.app.storage import PermissionReviewerConfigData

    if set(PermissionReviewerConfigData.model_fields) != CURRENT:
        raise RuntimeError('请先部署仅含主审核模型与审核规则的新契约。')
    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('AGENTSCOPE_DATABASE_URL') or os.environ['DATABASE_URL'])
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('显式迁移需要 PostgreSQL 配置存储。')
    dsn = url.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE' if args.apply else 'SET TRANSACTION READ ONLY')
        report = simplify_in_transaction(connection, os.getenv('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope').strip(),
            apply=args.apply, validate_config=PermissionReviewerConfigData.model_validate)
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    target = ROOT / 'artifacts' / ('simplify-permission-reviewer-result.json' if args.apply else 'simplify-permission-reviewer-preview.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('权限审核配置转换未完成：' + type(error).__name__)
        raise SystemExit(1) from None
