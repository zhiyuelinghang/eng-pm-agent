"""Versioned business evidence, independent of any agent's model or permissions."""
from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from .group_learning_source import channel_policy
from .models import AgentConversation, BusinessLearningSource, ChatChannel, Project, ProjectInitializationDraft, ProjectMember, User
from .business_learning_policy import conversation_learning_policy, current_policy_state


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@contextmanager
def task_learning_origin(db, channel_id, generation_id=None, source_policy=None):
    """Carry the trusted draft source into the official task without client overrides."""
    prior = db.info.get('task_learning_source_channel_ids')
    prior_generation = db.info.get('task_learning_generation_id')
    prior_policy = db.info.get('task_learning_origin_policy')
    db.info['task_learning_source_channel_ids'] = [int(channel_id)]
    db.info['task_learning_generation_id'] = generation_id
    db.info['task_learning_origin_policy'] = source_policy
    try:
        yield
    finally:
        if prior is None:
            db.info.pop('task_learning_source_channel_ids', None)
        else:
            db.info['task_learning_source_channel_ids'] = prior
        if prior_generation is None:
            db.info.pop('task_learning_generation_id', None)
        else:
            db.info['task_learning_generation_id'] = prior_generation
        if prior_policy is None:
            db.info.pop('task_learning_origin_policy',None)
        else:
            db.info['task_learning_origin_policy'] = prior_policy


def _project_audience(db, project_id):
    return {str(uid) for uid in db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id))}


def _audience(db, project_id, channel_ids):
    audience, shared = _project_audience(db, project_id), True
    for cid in channel_ids:
        channel = db.get(ChatChannel, cid)
        if channel is None or channel.project_id != project_id or channel.archived_at is not None:
            raise HTTPException(403, '业务学习来源群聊已失效')
        full, users = channel_policy(db, channel)
        shared = shared and full
        audience.intersection_update(str(uid) for uid in users)
    return sorted(audience), shared


def _source_channels(scope):
    channels = set(scope.get('learning_source_channel_ids') or [])
    actions = [scope.get('action'), *(scope.get('step_actions') or {}).values()]
    channels.update(int(action['channel_id']) for action in actions if isinstance(action, dict) and action.get('channel_id'))
    return sorted(int(cid) for cid in channels)


def _record(db, *, source_type, source_id, source_version, stage, project_id, actor_user_id,
            evidence, source_fingerprint, channel_ids=(), learning_policy=None):
    key = f'{source_type}:{source_id}:{source_version}:{stage}'
    existing = db.scalar(select(BusinessLearningSource).where(BusinessLearningSource.source_key == key))
    if existing is not None:
        return existing
    # Include pending ORM rows too: callers may emit twice before committing.
    pending = next((row for row in db.new if isinstance(row, BusinessLearningSource) and row.source_key == key), None)
    if pending is not None:
        return pending
    audience, shared = _audience(db, project_id, channel_ids)
    policy = learning_policy if learning_policy is not None else {'allow_learning':True,'source_run_refs':[]}
    row = BusinessLearningSource(
        source_key=key, source_type=source_type, source_id=str(source_id), source_version=str(source_version),
        stage=stage, project_id=project_id, actor_user_id=int(actor_user_id),
        audience_user_ids=audience, project_shared=shared, source_channel_ids=list(channel_ids),
        evidence=evidence, evidence_hash=digest(evidence), source_fingerprint=source_fingerprint,
        allow_learning=bool(policy['allow_learning']),source_run_refs=policy['source_run_refs'],
    )
    db.add(row)
    return row


def record_initialization_applied(db, draft, actor_user_id, result):
    # Confirmed business structure only; never copy uploaded documents, account secrets or the raw draft.
    evidence = [{
        'id': f'initialization:{draft.id}:{draft.revision}', 'kind': 'business_event', 'outcome': 'confirmed',
        'text': json.dumps({'stage': 'initialization_applied', 'revision': draft.revision,
            'confirmed_counts': {key: int(value) for key, value in (result.get('counts') or {}).items()
                if key in {'personnel', 'positions', 'position_assignments', 'wbs', 'risks', 'quality_requirements'}},
            'meaning': '初始化数据已由用户确认并写入项目，不表示工程施工任务已完成'}, ensure_ascii=False),
    }]
    return _record(db, source_type='initialization', source_id=draft.id, source_version=draft.revision,
        stage='initialization_applied', project_id=draft.project_id, actor_user_id=actor_user_id,
        evidence=evidence, source_fingerprint=digest([draft.revision, draft.payload]),
        learning_policy=conversation_learning_policy(db.get(AgentConversation,draft.conversation_id)))


def _task_fingerprint(task):
    # Business edits revoke an old summary; state progress alone does not erase publication evidence.
    return digest({'title': task.title, 'summary': task.summary, 'scope': task.scope,
        'confirmer': asdict(task.confirmer) if task.confirmer else None,
        'steps': [{'name': s.name, 'assignee': asdict(s.assignee) if s.assignee else None,
                   'deliverable': s.deliverable, 'instruction': s.instruction} for s in task.steps]})


def record_task_event(db, task, actor_user_id, stage):
    outcome = {'task_published': 'confirmed', 'task_accepted': 'accepted',
               'task_rejected': 'rejected', 'task_cancelled': 'cancelled'}[stage]
    activity = task.activities[-1] if task.activities else None
    version = activity.id if activity else digest([task.id, str(task.updated_at)])
    detail = {
        'task_id': task.id, 'title': task.title, 'stage': stage, 'state': str(task.state),
        'steps': [{'name': s.name, 'deliverable': s.deliverable, 'state': str(s.state)} for s in task.steps],
        'business_note': activity.summary if activity else '',
        'meaning': '经确认人验收完成' if stage == 'task_accepted' else '仅记录本次业务阶段，不能视为任务执行成功',
    }
    evidence = [{'id': f'task:{task.id}:{version}', 'kind': 'business_event', 'outcome': outcome,
                 'text': json.dumps(detail, ensure_ascii=False)}]
    return _record(db, source_type='task', source_id=task.id, source_version=version, stage=stage,
        project_id=int(task.scope['project_id']), actor_user_id=actor_user_id, evidence=evidence,
        source_fingerprint=_task_fingerprint(task), channel_ids=_source_channels(task.scope),
        learning_policy=task.scope.get('learning_policy'))


def record_task_plan(db, plan, actor_user_id):
    evidence = [{'id': f'task-plan:{plan.id}', 'kind': 'business_event', 'outcome': 'confirmed',
        'text': json.dumps({'title': plan.flow.title, 'trigger': plan.flow.trigger.describe(),
            'steps': [step.name for step in plan.flow.steps],
            'meaning': '用户确认了任务执行计划；尚不能证明任何任务已执行或验收'}, ensure_ascii=False)}]
    fingerprint = digest(asdict(plan.flow))
    return _record(db, source_type='task_schedule', source_id=plan.id, source_version=fingerprint,
        stage='task_plan_confirmed', project_id=int(plan.flow.scope['project_id']), actor_user_id=actor_user_id,
        evidence=evidence, source_fingerprint=fingerprint, channel_ids=_source_channels(plan.flow.scope),
        learning_policy=plan.flow.scope.get('learning_policy'))


def _validate_business_state(db, row):
    if row.revoked_at is not None or db.get(Project, row.project_id) is None:
        raise HTTPException(403, '业务学习来源已撤销')
    user = db.get(User, row.actor_user_id)
    if user is None or (user.role != 'admin' and str(user.id) not in _project_audience(db, row.project_id)):
        raise HTTPException(403, '业务来源账号已无项目权限')
    if row.source_type == 'initialization':
        draft = db.get(ProjectInitializationDraft, int(row.source_id))
        valid = draft is not None and draft.status == 'applied' and draft.project_id == row.project_id
        fingerprint = digest([draft.revision, draft.payload]) if valid else ''
    else:
        from .task_engine_gateway import get_engine
        engine = get_engine()
        if row.source_type == 'task_schedule':
            plan = engine.store.get_schedule(row.source_id)
            valid = plan is not None and plan.active and int(plan.flow.scope.get('project_id') or 0) == row.project_id
            fingerprint = digest(asdict(plan.flow)) if valid else ''
        else:
            task = engine.get_task(row.source_id)
            valid = task is not None and int(task.scope.get('project_id') or 0) == row.project_id
            if valid:
                valid = any(a.id == row.source_version for a in task.activities)
                if row.stage == 'task_accepted':
                    valid = valid and str(task.state) == 'done'
                elif row.stage != 'task_cancelled':
                    valid = valid and str(task.state) != 'cancelled'
            fingerprint = _task_fingerprint(task) if valid else ''
    if not valid or fingerprint != row.source_fingerprint:
        raise HTTPException(409, '业务来源已变化或失效')


def read_source(db, source_id):
    row = db.get(BusinessLearningSource, int(source_id))
    if row is None:
        raise HTTPException(404, '业务学习来源不存在')
    _validate_business_state(db, row)
    current, full = _audience(db, row.project_id, row.source_channel_ids)
    audience = sorted(set(row.audience_user_ids) & set(current))
    if not audience:
        raise HTTPException(403, '业务学习来源已无有效受众')
    learning_state = current_policy_state(row.allow_learning,row.source_run_refs)
    return {
        'id': row.id, 'source_key': row.source_key, 'source_type': row.source_type,
        'source_id': row.source_id, 'source_version': row.source_version, 'stage': row.stage,
        'project_id': str(row.project_id), 'actor_user_id': str(row.actor_user_id),
        'audience_user_ids': audience, 'project_shared': row.project_shared and full,
        'evidence': row.evidence, 'evidence_hash': row.evidence_hash,
        'allow_learning': learning_state == 'allowed', 'learning_state':learning_state,
        'source_run_refs':row.source_run_refs,
        'created_at': row.created_at.isoformat(),
    }


def list_sources(db, after_id=0, limit=50):
    rows = list(db.scalars(select(BusinessLearningSource).where(BusinessLearningSource.id > after_id)
                          .order_by(BusinessLearningSource.id).limit(limit + 1)))
    items = []
    for row in rows[:limit]:
        try:
            items.append(read_source(db, row.id))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
    return {'items': items, 'next_after_id': rows[min(len(rows), limit) - 1].id if rows else after_id,
            'has_more': len(rows) > limit}


def validate_source(db, snapshot):
    current = read_source(db, snapshot['id'])
    if current != snapshot:
        raise HTTPException(409, '业务证据或受众已变化，请重新读取来源')
    return {'valid': True, 'snapshot': current}


def authorized_source_ids(db, project_id, audience_user_ids):
    """Fresh authorization for memory reads, including the entire reply audience."""
    required = set(audience_user_ids)
    if not required:
        return []
    rows = db.scalars(select(BusinessLearningSource).where(
        BusinessLearningSource.project_id == project_id, BusinessLearningSource.revoked_at.is_(None)))
    authorized = []
    for row in rows:
        if not required.issubset(set(row.audience_user_ids)):
            continue
        try:
            current = read_source(db, row.id)
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
            continue
        if current['allow_learning'] and required.issubset(set(current['audience_user_ids'])):
            authorized.append(str(row.id))
    return authorized
