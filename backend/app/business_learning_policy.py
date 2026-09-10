"""Bind confirmed business evidence to actual server-created generation runs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine.url import make_url

from .config import get_settings
from .models import AgentConversation, ChatTaskDraft


def _signature(payload):
    key = hashlib.sha256(('business-generation-origin:' + get_settings().jwt_secret).encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def generation_origin_token(conversation):
    if not conversation.generation_id or not conversation.agentscope_session_id or conversation.status != 'completed':
        raise ValueError('任务生成来源尚未完成')
    data = {'conversation_id':conversation.id,'generation_id':conversation.generation_id,
        'session_id':conversation.agentscope_session_id,'user_id':conversation.user_id,'project_id':conversation.project_id}
    payload = base64.urlsafe_b64encode(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).decode().rstrip('=')
    return payload + '.' + _signature(payload)


def resolve_generation_origin(db, token, *, user_id, project_id):
    try:
        payload, signature = token.rsplit('.',1)
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError('signature')
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        row = db.get(AgentConversation, int(data['conversation_id']))
        if (row is None or row.conversation_type != 'task_editor' or row.status != 'completed' or
            row.user_id != user_id or row.project_id != project_id or generation_origin_token(row) != token):
            raise ValueError('binding')
        return row
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(403, '任务生成来源无效或不属于当前账号和项目，请重新生成。') from exc


def _source_memory_configuration():
    settings = get_settings()
    schema = settings.memory_database_schema.strip()
    if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}',schema):
        raise ValueError('记忆数据库 schema 配置无效')
    url = make_url(settings.memory_database_url.strip() or settings.database_url)
    if url.get_backend_name() != 'postgresql':
        raise ValueError('记忆来源查询需要 PostgreSQL')
    url = url.set(drivername='postgresql',query={**url.query,'options':f'-csearch_path={schema},public'})
    tenant = settings.memory_tenant_id.strip() or settings.agentscope_global_config_id.strip() or 'projectcopilot'
    return url.render_as_string(hide_password=False),tenant


@lru_cache(maxsize=1)
def _source_memory_repository(url):
    from utils.memory_repository import MemoryRepository
    return MemoryRepository(url)


def _memory_runs(session_id=None, refs=None):
    database_url,tenant = _source_memory_configuration()
    columns = '''SELECT r.tenant_id,r.run_id,r.root_session_id,r.root_agent_id,r.state,r.no_memory,r.no_learning,
        EXISTS(SELECT 1 FROM memory_run_evidence e WHERE e.tenant_id=r.tenant_id AND e.run_id=r.run_id
            AND (e.evidence->>'tool_name'='weknora_query_project_knowledge' OR e.source_ref->>'knowledge_source'='true')) AS has_knowledge
        FROM memory_runs r '''
    with _source_memory_repository(database_url)._connection() as conn:
        if refs is not None:
            return conn.execute(columns + 'WHERE r.tenant_id=%s AND r.run_id=ANY(%s)',
                (tenant,[item['run_id'] for item in refs])).fetchall()
        return conn.execute(columns + 'WHERE r.tenant_id=%s AND r.root_session_id=%s ORDER BY r.created_at,r.run_id',
            (tenant,session_id)).fetchall()


def conversation_learning_policy(conversation):
    """All runs contributing to this source session count; never guess the latest run."""
    if conversation is None or not conversation.agentscope_session_id:
        return {'allow_learning':False,'source_run_refs':[]}
    try:
        runs = _memory_runs(session_id=conversation.agentscope_session_id)
    except Exception:
        return {'allow_learning':False,'source_run_refs':[]}
    refs = [{key:str(run[key]) for key in ('tenant_id','run_id','root_session_id','root_agent_id')} for run in runs]
    allowed = bool(runs) and all(run['root_agent_id'] == conversation.agent_id and run['state'] in {'active','completed'}
        and not run['no_memory'] and not run['no_learning'] for run in runs)
    return {'allow_learning':allowed,'source_run_refs':refs}


def merge_learning_policies(*policies):
    refs = {}
    for policy in policies:
        for ref in policy['source_run_refs']:
            refs[(ref['tenant_id'],ref['run_id'])] = ref
    return {'allow_learning':all(policy['allow_learning'] for policy in policies),
        'source_run_refs':list(refs.values())}


def current_policy_state(allow_learning, refs):
    if not allow_learning:
        return 'excluded'
    if not refs:  # A manually confirmed business event has no model generation source.
        return 'allowed'
    try:
        runs = _memory_runs(refs=refs)
    except Exception:
        return 'pending'
    expected = {tuple(ref[key] for key in ('tenant_id','run_id','root_session_id','root_agent_id')) for ref in refs}
    actual = {tuple(str(run[key]) for key in ('tenant_id','run_id','root_session_id','root_agent_id')) for run in runs}
    if expected != actual or any(run['state']=='cancelled' or run['no_memory'] or run['no_learning'] for run in runs):
        return 'excluded'
    # This business pipeline publishes shared operational lessons. Knowledge-derived
    # task text retains external document authority and is not copied into that pipeline.
    if any(run.get('has_knowledge') for run in runs):
        return 'excluded'
    return 'allowed' if all(run['state']=='completed' for run in runs) else 'pending'


def current_policy_allows(allow_learning, refs):
    return current_policy_state(allow_learning,refs) == 'allowed'


def task_generation_policy(db, *, token=None, generation_id=None, user_id, project_id):
    if token:
        conversation = resolve_generation_origin(db,token,user_id=user_id,project_id=project_id)
    elif generation_id:
        conversation = db.scalar(select(AgentConversation).where(AgentConversation.generation_id==generation_id,
            AgentConversation.user_id==user_id,AgentConversation.project_id==project_id,
            AgentConversation.conversation_type=='task_editor'))
        if conversation is None or conversation.status != 'completed':
            return {'allow_learning':False,'source_run_refs':[]}
    else:
        return {'allow_learning':True,'source_run_refs':[]}
    return conversation_learning_policy(conversation)


def derived_input_constraints(db, conversation):
    """Only an authenticated homepage-to-draft binding marks copied input as derived."""
    clear = {'input_is_derived':False,'inherited_no_memory':False,'inherited_no_learning':False}
    if conversation.conversation_type != 'task_editor' or not conversation.generation_id:
        return clear
    draft = db.scalar(select(ChatTaskDraft).where(ChatTaskDraft.generation_id==conversation.generation_id,
        ChatTaskDraft.requested_by_user_id==conversation.user_id,ChatTaskDraft.project_id==conversation.project_id))
    reference = next((item for item in draft.context_json or [] if item.get('source')=='home_agent_reference'
        and item.get('conversation_id')),None) if draft is not None else None
    if reference is None:
        return clear
    denied = {'input_is_derived':True,'inherited_no_memory':True,'inherited_no_learning':True}
    origin = db.get(AgentConversation,int(reference['conversation_id']))
    policy = reference.get('learning_policy') or {}
    refs = policy.get('source_run_refs') or []
    if (origin is None or origin.user_id != conversation.user_id or origin.project_id != conversation.project_id
        or origin.conversation_type != 'general' or not refs
        or any(ref['root_session_id'] != origin.agentscope_session_id or ref['root_agent_id'] != origin.agent_id for ref in refs)):
        return denied
    try:
        runs = _memory_runs(refs=refs)
    except Exception:
        return denied
    keys = ('tenant_id','run_id','root_session_id','root_agent_id')
    if {tuple(ref[key] for key in keys) for ref in refs} != {tuple(str(run[key]) for key in keys) for run in runs}:
        return denied
    no_memory = any(run['no_memory'] for run in runs)
    return {'input_is_derived':True,'inherited_no_memory':no_memory,
        'inherited_no_learning':no_memory or not policy.get('allow_learning') or any(run['no_learning'] for run in runs)}
