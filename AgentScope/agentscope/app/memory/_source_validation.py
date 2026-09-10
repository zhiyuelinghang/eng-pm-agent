"""Recheck live source authority before memory reaches any business model."""
from __future__ import annotations

import asyncio
import json
from uuid import UUID

from utils.memory_repository import MemoryError


KNOWLEDGE_TOOL_NAME = 'weknora_query_project_knowledge'


def is_knowledge_result(block):
    metadata = block.metadata or {}
    return block.name == KNOWLEDGE_TOOL_NAME or metadata.get('operation') == KNOWLEDGE_TOOL_NAME


def knowledge_learning_evidence(block):
    """Keep operational evidence, never copy the external knowledge answer into memory."""
    if not is_knowledge_result(block):
        return None
    return ('项目知识库查询已完成。资料原文和查询答案继续保留在外部知识库，'
            '本条仅能说明发生了资料查询，不能作为工程事实或任务完成的证据。')


def _document_ids(block):
    metadata = block.metadata or {}
    ids = metadata.get('knowledge_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(item, str) or not item for item in ids):
        raise MemoryError('knowledge_source_unverifiable', '知识查询缺少可验证的资料清单，不能用于长期学习。', status=403)
    # References are structured tool output, never links or names inferred from prose.
    text = block.output if isinstance(block.output, str) else '\n'.join(getattr(item, 'text', '') for item in block.output)
    try:
        result = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise MemoryError('knowledge_source_unverifiable', '知识查询结果缺少结构化来源，不能用于长期学习。', status=403) from exc
    if not isinstance(result, dict) or not isinstance(result.get('references'), list):
        raise MemoryError('knowledge_source_unverifiable', '知识查询结果缺少结构化来源，不能用于长期学习。', status=403)
    for reference in result['references']:
        if not isinstance(reference, dict) or not isinstance(reference.get('knowledge_id'), str) or reference['knowledge_id'] not in ids:
            raise MemoryError('knowledge_source_unverifiable', '知识查询引用超出记录的资料范围，不能用于长期学习。', status=403)
    return set(ids)


async def validate_tool_knowledge_source(storage, gateway, owner, session_id, block):
    if not is_knowledge_result(block):
        return
    if gateway is None:
        raise MemoryError('knowledge_source_unavailable', '无法复查知识库权限，暂不使用该来源。', status=403)
    ids = _document_ids(block)
    from ._run_context import session_chain
    session = await storage.get_session(owner, '', session_id)
    if session is None:
        raise MemoryError('knowledge_source_changed', '知识查询来源会话已不存在。', status=403)
    chain = await session_chain(storage, owner, session)
    root = chain[-1]
    live = await gateway.resolve_knowledge_scope(session_id=root.id, actor_agent_id=session.agent_id)
    metadata = block.metadata
    pairs = (('platform_user_id', 'user_id'), ('platform_project_id', 'project_id'),
             ('platform_conversation_id', 'conversation_id'), ('weknora_robot_id', 'weknora_agent_id'))
    if (not live.get('weknora_query_enabled') or not live.get('weknora_catalogue_ready') or
        any(not metadata.get(original) or str(metadata[original]) != str(live.get(current) or '') for original, current in pairs) or
        not ids.issubset(set(live.get('weknora_knowledge_ids') or []))):
        raise MemoryError('knowledge_source_revoked', '原知识库资料的当前权限或绑定已变化，不能继续使用该学习来源。', status=403)


async def filter_current_memory_results(storage, gateway, tenant_id, owner, rows, *, repository=None, learning_runtime=None):
    """Validate whole original/derived events before returning already scope-filtered rows."""
    if not rows:
        return []
    if repository is None:
        from utils.memory_service import get_memory_repository
        repository = get_memory_repository()
    if learning_runtime is None:
        from ..storage import MemorySettingsData
        from ._learning import PlatformLearningRuntime
        from ._run_context import validate_learning_event
        async def settings():
            record = await storage.get_platform_settings(owner)
            return record.data.memory_settings if record is not None else MemorySettingsData()
        async def interaction(event, *, existing=False):
            return await validate_learning_event(storage, gateway, tenant_id, event, existing=existing)
        learning_runtime = PlatformLearningRuntime(storage=storage, gateway=gateway, resources=None,
            settings_loader=settings, tenant_id=tenant_id, memory_repository=repository, interaction_validator=interaction)

    def load_sources():
        ids = [UUID(str(row['id'])) for row in rows]
        with repository._connection() as conn:
            records = conn.execute('SELECT id,tenant_id,status,version,origin,source,learning FROM memory_records '
                'WHERE tenant_id=%s AND id=ANY(%s)', (tenant_id, ids)).fetchall()
            events, batches = {}, {}
            for record in records:
                source, learning = record['source'] or {}, record['learning'] or {}
                event_id = learning.get('event_id') or source.get('event_id')
                if event_id and event_id not in events:
                    try:
                        parsed = UUID(str(event_id))
                    except (ValueError, TypeError):
                        events[event_id] = None
                    else:
                        events[event_id] = conn.execute('SELECT * FROM learning_events WHERE id=%s AND tenant_id=%s',
                            (parsed, tenant_id)).fetchone()
                if not event_id and source.get('kind') == 'group_learning' and source.get('batch_id'):
                    key = str(source['batch_id'])
                    if key not in batches:
                        batch = conn.execute('SELECT snapshot FROM group_learning_batches WHERE id=%s AND tenant_id=%s',
                            (UUID(key), tenant_id)).fetchone()
                        batches[key] = batch['snapshot'] if batch else None
            return {str(record['id']): record for record in records}, events, batches

    try:
        records, events, batches = await asyncio.to_thread(load_sources)
    except Exception:
        # Broken or temporarily unavailable authority is never permission to reuse text.
        return []
    validation = {}
    result = []
    for row in rows:
        record = records.get(str(row['id']))
        if not record or record['status'] != 'active' or record['version'] != row['version']:
            continue
        source, learning = record['source'] or {}, record['learning'] or {}
        event_id = learning.get('event_id') or source.get('event_id')
        key = ('event', str(event_id)) if event_id else ('record', str(row['id']))
        if key not in validation:
            try:
                if event_id:
                    event = events.get(event_id)
                    if not event:
                        raise MemoryError('learning_source_missing', '学习来源已不存在。', status=403)
                    await learning_runtime.authorize_existing(event)
                elif source.get('kind') == 'group_learning':
                    batch = batches.get(str(source.get('batch_id')))
                    if batch is None:
                        raise MemoryError('learning_source_missing', '群聊学习来源已不存在。', status=403)
                    await gateway.group_learning_validate(batch)
                elif record['origin'] == 'learning':
                    raise MemoryError('learning_source_missing', '学习成果缺少完整来源。', status=403)
                elif source.get('kind') == 'run_memory' and (source.get('knowledge_sources') or
                    any(ref.get('kind') == 'tool' for ref in source.get('source_refs') or [])):
                    from ._run_context import validate_source_refs
                    await validate_source_refs(storage, owner, source.get('source_refs') or [], gateway=gateway)
                validation[key] = True
            except Exception:
                # Source revocation and transient authorization failure both fail closed.
                # The record remains intact; background maintenance owns invalidation.
                validation[key] = False
        if validation[key]:
            result.append(row)
    return result
