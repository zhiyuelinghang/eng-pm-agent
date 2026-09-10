"""Consume durable confirmed business events without running a business agent."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import logging

from .memory_repository import MemoryAccess
from .learning_repository import _digest

logger = logging.getLogger(__name__)


def source_targets(source: dict) -> list[tuple[str, str]]:
    if source['project_shared']:
        return [('project', '')]
    return [('user_project', user) for user in sorted(set(source['audience_user_ids']))]


def bounded_evidence(source: dict) -> list[dict]:
    result = []
    suffix = '\n[原始证据较长，此处仅展示开头；未展示部分不能推断。]'
    for item in source['evidence'][:20]:
        text = item['text']
        if len(text) > 4000:
            text = text[:4000-len(suffix)] + suffix
        result.append({**item,'text':text})
    return result


def _cursor(repository, tenant_id):
    with repository.memories._connection() as conn:
        row = conn.execute('SELECT after_id FROM business_learning_cursors WHERE tenant_id=%s', (tenant_id,)).fetchone()
        return row['after_id'] if row else 0


def _advance(repository, tenant_id, source_id):
    with repository.memories._connection() as conn:
        conn.execute('''INSERT INTO business_learning_cursors(tenant_id,after_id) VALUES (%s,%s)
            ON CONFLICT(tenant_id) DO UPDATE SET after_id=greatest(business_learning_cursors.after_id,excluded.after_id),updated_at=now()''',
            (tenant_id, source_id))


def _recorded_sources(repository, tenant_id):
    with repository.memories._connection() as conn:
        return conn.execute('''WITH active_events AS (SELECT e.* FROM learning_events e
            WHERE e.tenant_id=%s AND EXISTS
            (SELECT 1 FROM memory_records r WHERE r.tenant_id=e.tenant_id AND r.learning->>'event_id'=e.id::text
                AND r.status IN ('active','candidate')))
            SELECT provenance->'business_source' AS source FROM active_events WHERE source_type='business_event'
            UNION SELECT s->'provenance'->'business_source' AS source FROM active_events,
                jsonb_array_elements(coalesce(provenance->'derived_sources','[]'::jsonb)) s
                WHERE s->>'source_type'='business_event' ''', (tenant_id,)).fetchall()


def _invalidate(repository, tenant_id, source_id, code):
    with repository.memories._connection() as conn:
        rows = conn.execute('''SELECT r.* FROM memory_records r JOIN learning_events e ON e.id::text=r.learning->>'event_id'
            WHERE r.tenant_id=%s AND e.tenant_id=r.tenant_id AND r.status IN ('active','candidate')
                AND ((e.source_type='business_event' AND e.provenance->'business_source'->>'id'=%s) OR EXISTS
                    (SELECT 1 FROM jsonb_array_elements(coalesce(e.provenance->'derived_sources','[]'::jsonb)) s
                        WHERE s->>'source_type'='business_event' AND s->'provenance'->'business_source'->>'id'=%s))
            FOR UPDATE OF r''',
            (tenant_id, str(source_id), str(source_id))).fetchall()
        for row in rows:
            changed = conn.execute('''UPDATE memory_records SET status='inactive',version=version+1,updated_at=now(),
                embedding=NULL,indexed_version=NULL,index_status='pending',learning=learning ||
                jsonb_build_object('validation_state','source_changed','review_note',%s::text) WHERE id=%s RETURNING *''',
                ('业务来源已撤回或改变：'+code, row['id'])).fetchone()
            repository.memories._version(conn, changed, 'system', 'business_source_invalidated')
            repository.memories._queue(conn, changed)


async def scan_business_sources(repository, runtime, settings, *, tenant_id, config_owner):
    # Revocation is independent from learning switches and model availability.
    for row in await asyncio.to_thread(_recorded_sources, repository, tenant_id):
        source = row['source']
        try:
            await runtime.gateway.business_learning_validate(source)
        except Exception as exc:
            if getattr(exc, 'status', getattr(exc, 'status_code', None)) in {403, 404, 409}:
                await asyncio.to_thread(_invalidate, repository, tenant_id, source['id'], getattr(exc, 'code', type(exc).__name__))
            else:
                raise
    if not settings.learning_enabled or not settings.learning_business_events_enabled or settings.learning_model_config is None:
        return
    after = await asyncio.to_thread(_cursor, repository, tenant_id)
    page = await runtime.gateway.business_learning_sources(after, 50)
    for source in page['items']:
        if source['learning_state'] == 'pending':
            # A confirmed task can precede persisted run finalization. Keep the
            # cursor so the next scan reads its latest policy, rather than
            # treating a temporary state (or a snapshot race) as an opt-out.
            return
        try:
            await runtime.gateway.business_learning_validate(source)
        except Exception as exc:
            if getattr(exc, 'status', getattr(exc, 'status_code', None)) in {403, 404, 409}:
                await asyncio.to_thread(_advance, repository, tenant_id, source['id'])
                continue
            raise
        if source['allow_learning']:
            for scope, user in source_targets(source):
                access = MemoryAccess(tenant_id, user, str(source['project_id']), private=scope != 'project',
                    project_read=True, project_write=True, read_scopes=(scope,), write_scopes=(scope,),
                    audience_user_ids=tuple(source['audience_user_ids']),business_source_ids=(str(source['id']),))
                provenance = {'business_source': source}
                event = {'tenant_id':tenant_id, 'source_type':'business_event', 'provenance':provenance,
                    'access_snapshot':asdict(access), 'scope_type':scope}
                await runtime.authorize(event)
                saved = await asyncio.to_thread(repository.capture, access, scope_type=scope, agent_id='',
                    session_id='business:'+str(source['id']), config_owner=config_owner,
                    event_key=_digest([source['source_key'], source['source_version'], scope, user]),
                    event_type='business_event', evidence=bounded_evidence(source), source_type='business_event',
                    provenance=provenance, delay_seconds=0, daily_limit=settings.learning_daily_job_limit)
                if saved['job'] is None:
                    # Keep the source cursor so budget exhaustion does not lose work.
                    return
        await asyncio.to_thread(_advance, repository, tenant_id, source['id'])
    # The producer also advances over revoked sources omitted from items.
    await asyncio.to_thread(_advance, repository, tenant_id, page['next_after_id'])


async def run_business_learning_worker(repository, *, runtime, settings_loader, tenant_id, config_owner):
    while True:
        try:
            settings = await settings_loader()
            await scan_business_sources(repository, runtime, settings, tenant_id=tenant_id, config_owner=config_owner)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Business learning source scan failed')
            await asyncio.sleep(30)
