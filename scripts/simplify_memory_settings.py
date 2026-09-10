"""Preview the explicit migration from technical memory settings to six choices.

--apply locks and validates every platform-settings row before changing the
memory_settings, memory_settings_revision and updated_at paths. Stored memories,
learning jobs, other settings and credentials are never changed.
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

PRESERVED_FIELDS = frozenset({
    'learning_enabled', 'learning_model_config', 'learning_interactions_enabled',
    'learning_business_events_enabled', 'group_learning_enabled',
})
NEW_FIELDS = PRESERVED_FIELDS | {'compression_model_config'}
RETIRED_FIELDS = frozenset('''
memory_model_config recall_top_k memory_profile_enabled memory_semantic_search_enabled
memory_index_enabled group_learning_scan_seconds group_learning_message_threshold
group_learning_idle_seconds group_learning_max_wait_seconds group_learning_batch_size
group_learning_daily_limit learning_auto_consolidate learning_capture_corrections
learning_capture_failures learning_capture_verified_tasks learning_capture_patterns
learning_daily_job_limit learning_cooldown_seconds learning_pattern_threshold
learning_timeout_seconds learning_input_char_limit learning_review_days learning_skill_limit
recall_threshold recall_reinforce_threshold fusion_weight_mem0 fusion_weight_kb
fusion_weight_timeline fusion_weight_experience fusion_weight_graphrag fusion_mmr_lambda rrf_k
mem0_infer_enabled mem0_infer_async compression_trigger_ratio compression_keep_messages
compression_mode emergency_compression_ratio compression_background historian_trigger_ratio
compression_max_consecutive compression_quality_threshold compression_min_rounds_between
token_budget_system_prompt token_budget_skill_injection token_budget_summary
token_budget_ltm_kb_timeline token_budget_runtime token_budget_recent_history
token_budget_output_reserve dreamer_enabled experience_event_driven_enabled
compression_system_prompt compression_user_prompt compression_incremental_prompt historian_system_prompt
'''.split())


def safe_settings(settings):
    """The audit must not contain credential IDs, parameters or prompt content."""
    result = {'fields': sorted(settings)}
    for key in sorted(NEW_FIELDS | {'memory_model_config'}):
        if key not in settings:
            continue
        value = settings[key]
        if key.endswith('_model_config'):
            result[key] = None if value is None else {'model': value.get('model')}
        else:
            result[key] = value
    return result


def plan_simplification(rows, validate_settings):
    """Return safe audit information and fully validated in-memory changes."""
    defaults = {
        'learning_enabled': False, 'learning_model_config': None,
        'learning_interactions_enabled': True, 'learning_business_events_enabled': True,
        'group_learning_enabled': True, 'compression_model_config': None,
    }
    report = {'records': [], 'counts': {'migrate': 0, 'already_current': 0}}
    changes = []
    for row in rows:
        if row.get('data_type', 'object') != 'object':
            raise ValueError('平台配置 data 不是对象，停止转换。')
        old = row['settings'] if row['settings'] is not None else {}
        if not isinstance(old, dict):
            raise ValueError('记忆配置不是对象，停止转换。')
        unknown = set(old) - NEW_FIELDS - RETIRED_FIELDS
        if unknown:
            raise ValueError('发现未审查的记忆配置字段：' + ', '.join(sorted(unknown)))
        revision = row['revision'] if row['revision'] is not None else 1
        if type(revision) is not int or revision < 1:
            raise ValueError('记忆配置版本不是有效正整数。')
        if ('memory_model_config' in old and 'compression_model_config' in old
                and old['memory_model_config'] != old['compression_model_config']):
            raise ValueError('新旧压缩模型配置不一致，停止转换。')
        after = deepcopy(defaults)
        after.update({key: deepcopy(old[key]) for key in NEW_FIELDS if key in old})
        if 'memory_model_config' in old:
            after['compression_model_config'] = deepcopy(old['memory_model_config'])
        for field in NEW_FIELDS - {'learning_model_config', 'compression_model_config'}:
            if type(after[field]) is not bool:
                raise ValueError('学习开关必须是布尔值：' + field)
        # Do not normalize or drop nested model settings during a field-only
        # migration. Validation succeeds before any database row is updated.
        validate_settings(after)
        changed = old != after or row['revision'] is None
        status = 'migrate' if changed else 'already_current'
        report['counts'][status] += 1
        report['records'].append({
            'id': row['id'], 'owner': row['user_id'], 'status': status,
            'revision_before': revision, 'revision_after': revision + int(changed),
            'removed_fields': sorted(set(old) & RETIRED_FIELDS),
            'before': safe_settings(old), 'after': safe_settings(after),
        })
        if changed:
            changes.append({'id': row['id'], 'settings': after, 'revision': revision + 1})
    return report, changes


def simplify_in_transaction(connection, schema, *, apply, validate_settings):
    """The caller owns a single transaction and its commit/rollback."""
    from psycopg import sql
    from psycopg.types.json import Jsonb

    table = sql.Identifier(schema, 'platform_settings')
    rows = connection.execute(sql.SQL('''SELECT id,user_id,
        jsonb_typeof(payload::jsonb->'data') AS data_type,
        payload::jsonb->'data'->'memory_settings' AS settings,
        payload::jsonb->'data'->'memory_settings_revision' AS revision
        FROM {} ORDER BY id''' + (' FOR UPDATE' if apply else '')).format(table)).fetchall()
    report, changes = plan_simplification(rows, validate_settings)
    if apply:
        for change in changes:
            connection.execute(sql.SQL('''UPDATE {} SET payload=jsonb_set(
                jsonb_set(payload::jsonb,'{{data,memory_settings}}',%s,true),
                '{{data,memory_settings_revision}}',%s,true),
                updated_at=timezone('UTC',now()) WHERE id=%s''').format(table),
                (Jsonb(change['settings']), Jsonb(change['revision']), change['id']))
    return {**report, 'read_only': not apply, 'applied': apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='在单一事务中转换全部记忆配置')
    args = parser.parse_args()
    from dotenv import load_dotenv
    import psycopg
    from psycopg.rows import dict_row
    from sqlalchemy.engine import make_url
    from agentscope.app.storage import MemorySettingsData

    if set(MemorySettingsData.model_fields) != NEW_FIELDS:
        raise RuntimeError('请先部署仅含六项公开字段的记忆配置契约。')
    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('AGENTSCOPE_DATABASE_URL') or os.environ['DATABASE_URL'])
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('显式转换需要 PostgreSQL 配置存储。')
    dsn = url.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE' if args.apply else 'SET TRANSACTION READ ONLY')
        report = simplify_in_transaction(connection, os.getenv('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope').strip(),
            apply=args.apply, validate_settings=MemorySettingsData.model_validate)
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    target = ROOT / 'artifacts' / ('simplify-memory-settings-result.json' if args.apply else 'simplify-memory-settings-preview.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Pydantic and connection exceptions can contain the original input.
        print('记忆配置转换未完成：' + type(error).__name__)
        raise SystemExit(1) from None
