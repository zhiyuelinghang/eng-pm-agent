"""Read-only verification of unified policy and retained runtime boundaries."""
from pathlib import Path
import json
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('AGENTSCOPE_DATABASE_URL') or os.environ['DATABASE_URL'])
    schema = os.getenv('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope')
    report = {'read_only': True, 'agents': []}
    with psycopg.connect(url.set(drivername='postgresql').render_as_string(hide_password=False),
            row_factory=dict_row, options='-c default_transaction_read_only=on') as conn:
        records = conn.execute(sql.SQL('SELECT id,payload FROM {}.agents ORDER BY id').format(sql.Identifier(schema))).fetchall()
        for row in records:
            agent = row['payload']['data']
            config = agent['platform_config']
            assert not {'agent_level', 'learning_capture', 'learning_process', 'project_knowledge_enabled',
                'memory_read_scopes', 'memory_write_scopes', 'learning_enabled', 'learning_use', 'memory_policy'} & config.keys()
            report['agents'].append({'id': row['id'], 'name': agent['name'],
                'memory_control': 'system_scenario_rules'})
        settings = conn.execute(sql.SQL('SELECT payload FROM {}.platform_settings').format(sql.Identifier(schema))).fetchall()
        report['settings'] = []
        for row in settings:
            data = row['payload']['data']
            memory = data['memory_settings']
            assert 'learning_capture_verified_tasks' not in memory
            assert memory['learning_model_config']
            for field in ('global_main_agent_id', 'project_initializer_agent_id',
                    'knowledge_assistant_agent_id', 'task_assistant_agent_id'):
                if data.get(field):
                    main_agent = next(a for a in report['agents'] if a['id'] == data[field])
                    assert main_agent['memory_control'] == 'system_scenario_rules'
            report['settings'].append({
                'learning_model': memory['learning_model_config']['model'],
                'learning_enabled': memory['learning_enabled'],
                'learning_interactions_enabled': memory['learning_interactions_enabled'],
                'learning_business_events_enabled': memory['learning_business_events_enabled'],
            })
        report['migration'] = conn.execute(sql.SQL('SELECT version_num FROM {}.alembic_version')
            .format(sql.Identifier(os.getenv('DATABASE_SCHEMA', 'public')))).fetchone()['version_num']
        report['memory_status_counts'] = [dict(row) for row in conn.execute(
            'SELECT status,count(*) AS count FROM memory.memory_records GROUP BY status ORDER BY status')]
        # Metadata only: retain the before/after audit without exposing memory text.
        report['memory_history_metadata'] = [dict(row) for row in conn.execute(
            'SELECT id,status,version,created_at,updated_at FROM memory.memory_records ORDER BY created_at')]
        snapshots = conn.execute('SELECT id,access_snapshot FROM memory.learning_events').fetchall()
        for row in snapshots:
            snapshot = row['access_snapshot']
            for key in ('read_scopes', 'write_scopes'):
                assert isinstance(snapshot[key], list)
                assert set(snapshot[key]) <= {'user', 'user_project', 'project'}
            assert isinstance(snapshot['learning_enabled'], bool)
            assert isinstance(snapshot['learning_use'], bool)
        report['preserved_runtime_snapshots'] = len(snapshots)
    report['status'] = 'passed'
    path = ROOT / 'artifacts/agent-memory-policy-removal-verification.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'agents': len(report['agents']),
        'migration': report['migration'], 'memory_status_counts': report['memory_status_counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
