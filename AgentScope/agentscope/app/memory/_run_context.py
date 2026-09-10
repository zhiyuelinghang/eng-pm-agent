"""Trusted request identities and current permissions for memory operations."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from utils.memory_repository import MemoryAccess, MemoryError
from ...message import Msg
from ._source_validation import KNOWLEDGE_TOOL_NAME
from ._policy import memory_duty, memory_rules


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def knowledge_source_rows(rows):
    return [row for row in rows if row['evidence'].get('tool_name') == KNOWLEDGE_TOOL_NAME
        or (row.get('source_ref') or {}).get('knowledge_source') is True]


def constrain_knowledge_writes(access):
    return replace(access, write_scopes=tuple(scope for scope in access.write_scopes if scope == 'user_project'))


async def session_chain(storage, owner, session):
    """Validate stored membership, instead of trusting a supplied role label."""
    chain = [session]
    if session.team_id:
        from .._team_delegation import report_recipient_session_id
        team = await storage.get_team(owner, session.team_id)
        if team is None:
            raise MemoryError('run_team_missing', '协作关系已失效。', status=403)
        seen = {session.id}
        while chain[-1].id != team.session_id:
            member = next((m for m in team.data.members if m.session_id == chain[-1].id), None)
            if member is None or member.agent_id != chain[-1].agent_id:
                raise MemoryError('run_member_invalid', '当前会话不属于该协作关系。', status=403)
            parent_id = report_recipient_session_id(team, chain[-1].id)
            if parent_id in seen:
                raise MemoryError('run_cycle', '协作关系存在循环。', status=403)
            parent = await storage.get_session(owner, '', parent_id)
            if parent is None:
                raise MemoryError('run_parent_missing', '调用来源已失效。', status=403)
            chain.append(parent)
            seen.add(parent.id)
    root_context = chain[-1].config.platform_context
    for node in chain:
        context=node.config.platform_context
        if (context is None) != (root_context is None):
            raise MemoryError('run_identity_mismatch', '协作会话的用户或项目不一致。', status=403)
        if context is None:
            continue
        if (context.user_id,context.project_id)!=(root_context.user_id,root_context.project_id):
            raise MemoryError('run_identity_mismatch', '协作会话的用户或项目不一致。', status=403)
        if node.id != chain[-1].id and (context.session_role != 'worker' or context.root_session_id != chain[-1].id):
            raise MemoryError('run_parent_mismatch', '协作来源与保存的根会话不一致。', status=403)
        if node.id == chain[-1].id and context.session_role != 'primary':
            raise MemoryError('run_root_invalid', '被委派会话不能作为新的业务入口。', status=403)
    return chain


async def bind_memory_run(storage, owner, session, inputs):
    messages = inputs if isinstance(inputs, list) else [inputs]
    users = [msg for msg in messages if isinstance(msg, Msg) and msg.role == 'user']
    if not users:
        return session
    chain = await session_chain(storage, owner, session)
    if len(chain) > 1:
        return session
    run_id = digest([owner, session.id, [msg.id for msg in users]])
    if run_id != session.config.memory_run_id:
        await storage.upsert_session(
            owner, session.agent_id, session.config.model_copy(update={'memory_run_id': run_id}),
            state=session.state, session_id=session.id, source=session.source,
            source_schedule_id=session.source_schedule_id,
        )
        session = await storage.get_session(owner,session.agent_id,session.id)
    return session


async def resolve_agent_memory_access(storage, gateway, tenant_id, owner, agent_id, session_id, *, write=False):
    session = await storage.get_session(owner, agent_id, session_id)
    if session is None:
        raise MemoryError('session_missing', '业务会话已不存在。', status=403)
    chain = await session_chain(storage, owner, session)
    root = chain[-1]
    if write and (not session.config.memory_run_id or session.config.memory_run_id != root.config.memory_run_id):
        raise MemoryError('run_superseded', '原业务请求已结束或被新的请求替代。', status=403)
    records = [await storage.get_agent(owner, s.agent_id) for s in chain]
    if any(record is None or not record.data.platform_config.enabled for record in records):
        raise MemoryError('agent_memory_disabled', '该业务涉及的智能体已不可用。', status=403)
    settings = await storage.get_platform_settings(owner)
    settings_data = settings.data if settings is not None else None
    context = root.config.platform_context
    live = None if context is None else await gateway.resolve_memory_scope(root.id)
    if live is not None and (str(live['user_id']), str(live['project_id'])) != (context.user_id, context.project_id):
        raise MemoryError('identity_mismatch', '业务身份与当前权限不一致。', status=403)
    rules = memory_rules(
        duties=[memory_duty(settings_data, node.agent_id) for node in chain],
        entry_kind='debug' if live is None else live['entry_kind'],
        delegated=len(chain) > 1,
        private=True if live is None else bool(live['private']),
        input_is_derived=bool(live and live.get('input_is_derived')),
        inherited_no_learning=bool(live and live.get('inherited_no_learning')),
        inherited_no_memory=bool(live and live.get('inherited_no_memory')),
    )
    if context is None:
        # Admin debug has its own per-root memory identity, never a business
        # account. It does not feed the production learning pipeline.
        access = MemoryAccess(tenant_id, f'debug:{owner}:{root.id}', identity_type='management_user',
            learning_enabled=rules.learning_enabled, read_scopes=rules.read_scopes,
            write_scopes=rules.write_scopes, learning_use=rules.learning_use)
    else:
        access = MemoryAccess(tenant_id, str(live['user_id']), str(live['project_id']),
            private=bool(live['private']), project_read=bool(live['project_read']), project_write=bool(live['project_write']),
            group_source_channels=tuple(live.get('group_source_channels', [])),
            group_shared_channels=tuple(live.get('group_shared_channels', [])),
            audience_user_ids=tuple(live.get('audience_user_ids', [])),
            business_source_ids=tuple(live.get('business_source_ids', [])),
            read_scopes=rules.read_scopes, write_scopes=rules.write_scopes,
            learning_enabled=rules.learning_enabled, learning_use=rules.learning_use)
    return access, chain


async def validate_source_refs(storage, owner, refs, *, gateway=None):
    """Every submitted reference must still point to the original record."""
    for ref in refs:
        message = await storage.get_message(owner, ref['session_id'], ref['message_id'])
        if message is None:
            raise MemoryError('learning_source_changed', '原始消息或工具证据已不存在。', status=403)
        if ref['kind'] == 'user':
            if message.role != 'user' or digest(message.get_text_content()) != ref['hash']:
                raise MemoryError('learning_source_changed', '原始用户消息已修改。', status=403)
        elif ref['kind'] == 'tool':
            matches = [block for block in message.get_content_blocks('tool_result') if block.id == ref['tool_call_id']]
            if not matches or digest(matches[-1].model_dump(mode='json')) != ref['hash']:
                raise MemoryError('learning_source_changed', '原始工具结果已修改。', status=403)
            from ._source_validation import validate_tool_knowledge_source
            await validate_tool_knowledge_source(storage, gateway, owner, ref['session_id'], matches[-1])
        else:
            raise MemoryError('source_invalid', '不支持的记忆来源。', status=403)


async def validate_learning_event(storage, gateway, tenant_id, event, *, existing=False):
    """Fresh source and contributor checks for queued and active lessons."""
    provenance = event['provenance']
    root_id = provenance['root_session_id']
    owner = event['config_owner']
    root = await storage.get_session(owner, '', root_id)
    if root is None or root.config.platform_context is None:
        raise MemoryError('session_missing', '学习来源业务会话已不存在。', status=403)
    context = root.config.platform_context
    live = await gateway.resolve_memory_scope(root_id)
    snapshot = event['access_snapshot']
    if (str(live['user_id']), str(live['project_id'])) != (snapshot['user_id'], snapshot['project_id']):
        raise MemoryError('identity_mismatch', '学习来源的业务身份已改变。', status=403)
    access = MemoryAccess(tenant_id, str(live['user_id']), str(live['project_id']),
        private=bool(live['private']), project_read=bool(live['project_read']), project_write=bool(live['project_write']),
        group_source_channels=tuple(live.get('group_source_channels', [])), group_shared_channels=tuple(live.get('group_shared_channels', [])),
        audience_user_ids=tuple(live.get('audience_user_ids', [])), business_source_ids=tuple(live.get('business_source_ids', [])),
        read_scopes=tuple(snapshot['read_scopes']), write_scopes=tuple(snapshot['write_scopes']))
    if context.user_id != access.user_id or context.project_id != access.project_id:
        raise MemoryError('identity_mismatch', '原始会话身份不一致。', status=403)
    if not existing:
        if provenance.get('no_learning'):
            raise MemoryError('learning_excluded', '用户已排除此业务的学习。', status=403)
        scopes = set(access.write_scopes)
        for contributor in provenance['contributors']:
            current, chain = await resolve_agent_memory_access(
                storage, gateway, tenant_id, owner,
                contributor['agent_id'], contributor['session_id'],
            )
            if chain[-1].id != root_id:
                raise MemoryError('run_parent_mismatch', '学习来源不属于原业务调用链。', status=403)
            if not current.learning_enabled:
                raise MemoryError('learning_disabled', '当前业务场景或本次请求不允许交互学习。', status=403)
            scopes.intersection_update(current.write_scopes)
        access = replace(access, write_scopes=tuple(sorted(scopes)))
    await validate_source_refs(storage, owner, provenance['source_refs'], gateway=gateway)
    access.target(event['scope_type'], write=True)
    return access
