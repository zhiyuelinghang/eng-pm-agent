"""Remove the retired per-agent memory choice after an explicit preview.

Only agents.payload.data.platform_config.memory_policy is removed. The global
learning settings, runtime authorization snapshots and stored memories are not
read or changed. By default this script opens a read-only transaction.
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "AgentScope"))


def plan_removal(rows, validate_config):
    report = {'agents': [], 'counts': {'remove': 0, 'already_absent': 0}}
    changes = []
    for row in rows:
        data = row['payload']['data']
        config = data.get('platform_config', {})
        if not isinstance(config, dict):
            raise ValueError('智能体配置不是对象，停止处理')
        after = deepcopy(config)
        present = 'memory_policy' in after
        before = after.pop('memory_policy', None)
        # Validate every final configuration before performing any write.
        validate_config(after)
        status = 'remove' if present else 'already_absent'
        report['counts'][status] += 1
        report['agents'].append({
            'id': row['id'], 'name': data.get('name', ''), 'status': status,
            'before': ({'memory_policy': before if before in ('standard', 'no_learning', 'no_retention') else '(非标准值)'} if present else {}),
            'after': {},
        })
        if present:
            changes.append(row['id'])
    return report, changes


def remove_in_transaction(connection, schema, *, apply, validate_config):
    """The caller owns transaction commit/rollback; no database migration is hidden."""
    from psycopg import sql

    rows = connection.execute(sql.SQL('SELECT id,payload FROM {}.agents ORDER BY id' + (' FOR UPDATE' if apply else ''))
        .format(sql.Identifier(schema))).fetchall()
    report, changes = plan_removal(rows, validate_config)
    if apply:
        for agent_id in changes:
            # Production agents.payload is json, so the jsonb operator needs an
            # explicit cast. Deleting the exact path preserves every other key.
            connection.execute(sql.SQL("UPDATE {}.agents SET payload=payload::jsonb #- '{{data,platform_config,memory_policy}}' WHERE id=%s")
                .format(sql.Identifier(schema)), (agent_id,))
    report.update({'read_only': not apply, 'applied': apply})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='核验全部配置后，在单一事务中移除人工记忆策略字段')
    args = parser.parse_args()

    from dotenv import load_dotenv
    import psycopg
    from psycopg.rows import dict_row
    from sqlalchemy.engine import make_url
    from agentscope.app.storage._model._agent import PlatformAgentConfig

    if args.apply and 'memory_policy' in PlatformAgentConfig.model_fields:
        raise RuntimeError('请先部署已删除人工记忆策略字段的新配置契约')
    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('AGENTSCOPE_DATABASE_URL') or os.environ['DATABASE_URL'])
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('需要已配置的 PostgreSQL 数据库')
    dsn = url.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE' if args.apply else 'SET TRANSACTION READ ONLY')
        report = remove_in_transaction(connection, os.getenv('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope'),
            apply=args.apply, validate_config=PlatformAgentConfig.model_validate)
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    target = ROOT / 'artifacts' / ('agent-memory-policy-removal-result.json' if args.apply else 'agent-memory-policy-removal-preview.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Neither connection strings nor configuration validation inputs belong
        # in a user-visible error report.
        print('人工记忆策略字段移除未完成：' + type(error).__name__)
        raise SystemExit(1) from None
