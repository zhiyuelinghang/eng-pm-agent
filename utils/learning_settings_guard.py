"""Live learning switches and the PostgreSQL publication barrier.

The settings row is the application's authoritative row. Holding FOR SHARE in
the result transaction serializes publication with the settings CAS write lock.
"""
from __future__ import annotations

import os
from collections import defaultdict

from psycopg import sql

from .memory_repository import MemoryError


SOURCE_SWITCHES = {
    'interaction': 'learning_interactions_enabled',
    'business_event': 'learning_business_events_enabled',
    'group': 'group_learning_enabled',
}


class LearningPaused(MemoryError):
    """A reversible scheduling pause; never consume failure retries."""

    def __init__(self, message='新学习已暂停，待处理任务将在恢复后继续。', *, code='learning_paused'):
        super().__init__(code, message, status=409)


def require_learning_enabled(settings, source_types):
    def enabled(name):
        value = settings.get(name) if isinstance(settings, dict) else getattr(settings, name, None)
        return value is True

    for source in source_types:
        if source not in SOURCE_SWITCHES:
            raise MemoryError('learning_source_invalid', '未知的学习来源。', status=403)
        if not enabled('learning_enabled') or not enabled(SOURCE_SWITCHES[source]):
            raise LearningPaused()


def learning_sources(event):
    """Keep every original source when a result was derived from other results."""
    found = {(event.get('config_owner'), event.get('source_type'))}
    for source in event.get('provenance', {}).get('derived_sources', []):
        found.update(learning_sources(source))
    return found


def lock_learning_settings(conn, sources):
    """Must run inside the same transaction that captures or publishes results."""
    owners = defaultdict(set)
    for owner, source in sources:
        if not isinstance(owner, str) or not owner:
            raise MemoryError('learning_source_invalid', '学习来源缺少配置归属。', status=403)
        owners[owner].add(source)
    if not owners:
        raise MemoryError('learning_source_invalid', '学习来源为空。', status=403)
    schema = os.environ.get('AGENTSCOPE_DATABASE_SCHEMA', 'agentscope').strip()
    if not schema:
        raise MemoryError('learning_storage_invalid', '学习需要明确的 PostgreSQL 配置存储。', status=503)
    query = sql.SQL("SELECT payload->'data'->'memory_settings' AS settings FROM {} WHERE user_id=%s FOR SHARE").format(
        sql.Identifier(schema, 'platform_settings'))
    # Stable ordering also covers consolidation across several configuration owners.
    for owner in sorted(owners):
        row = conn.execute(query, (owner,)).fetchone()
        if not row or not isinstance(row['settings'], dict):
            raise LearningPaused('学习配置尚未就绪，任务保留等待配置完成。', code='learning_settings_unavailable')
        require_learning_enabled(row['settings'], owners[owner])
