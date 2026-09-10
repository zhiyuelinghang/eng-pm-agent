"""Committed event sources must retain their original evidence and audience."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app import business_learning_sources as sources, task_engine_gateway
from backend.app.db import Base
from backend.app.models import (AgentConversation, BusinessLearningSource, ChatChannel, ChatChannelMember,
    Project, ProjectInitializationDraft, ProjectMember, User)
from task_engine.domain.models import Assignee, Site, StepSpec, TaskFlow
from task_engine.engine import TaskEngine


@pytest.fixture
def state(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    task_engine = TaskEngine(tmp_path / 'tasks.db')
    monkeypatch.setattr(task_engine_gateway, 'get_engine', lambda: task_engine)
    with Session(engine) as db:
        project = Project(name='学习来源项目')
        people = [User(username=f'event-{i}', real_name=f'成员{i}', role='user', password_hash='x', identity_card_no=f'event-{i}') for i in range(3)]
        db.add_all([project, *people])
        db.flush()
        db.add_all(ProjectMember(project_id=project.id, user_id=user.id) for user in people)
        db.commit()
        yield db, project, people, task_engine
    task_engine.close()
    engine.dispose()


def task_for(project, people, engine, scope=None):
    flow = TaskFlow(title='检查任务', steps=(StepSpec(name='现场检查', assignee=Assignee(str(people[0].id), '执行人')),),
        site=Site('test-site', '测试工点'), confirmer=Assignee(str(people[1].id), '确认人'),
        scope={'project_id': project.id, **(scope or {})})
    return engine.dispatch(flow, actor=str(people[0].id))


def test_generated_or_dispatched_task_is_not_execution_success(state):
    db, project, people, engine = state
    task = task_for(project, people, engine)
    event = sources.record_task_event(db, task, people[0].id, 'task_published')
    db.commit()
    snapshot = sources.read_source(db, event.id)
    assert snapshot['stage'] == 'task_published'
    assert snapshot['evidence'][0]['outcome'] == 'confirmed'
    assert '不能视为任务执行成功' in snapshot['evidence'][0]['text']
    assert sources.validate_source(db, snapshot)['valid']


def test_event_is_idempotent_before_and_after_commit(state):
    db, project, people, engine = state
    task = task_for(project, people, engine)
    first = sources.record_task_event(db, task, people[0].id, 'task_published')
    assert sources.record_task_event(db, task, people[0].id, 'task_published') is first
    db.commit()
    assert sources.record_task_event(db, task, people[0].id, 'task_published').id == first.id
    assert len(list(db.scalars(select(BusinessLearningSource)))) == 1


def test_source_is_discarded_on_business_transaction_rollback(state):
    db, project, people, engine = state
    task = task_for(project, people, engine)
    sources.record_task_event(db, task, people[0].id, 'task_published')
    db.flush()
    db.rollback()
    assert list(db.scalars(select(BusinessLearningSource))) == []


def test_only_actual_acceptance_produces_accepted_evidence(state):
    db, project, people, engine = state
    task = task_for(project, people, engine)
    engine.complete_step(task.id, 0, actor=str(people[0].id), comment='已检查')
    accepted = engine.accept(task.id, actor=str(people[1].id), note='验收通过')
    event = sources.record_task_event(db, accepted, people[1].id, 'task_accepted')
    db.commit()
    snapshot = sources.read_source(db, event.id)
    assert snapshot['evidence'][0]['outcome'] == 'accepted'
    assert snapshot['source_version'] == accepted.activities[-1].id


def test_cancelled_source_cannot_be_learned_as_published_success(state):
    db, project, people, engine = state
    task = task_for(project, people, engine)
    row = sources.record_task_event(db, task, people[0].id, 'task_published')
    db.commit()
    snapshot = sources.read_source(db, row.id)
    engine.cancel_task(task.id, actor=str(people[0].id), reason='撤销')
    with pytest.raises(HTTPException) as caught:
        sources.validate_source(db, snapshot)
    assert caught.value.status_code == 409


def test_source_actor_losing_membership_blocks_validation(state):
    db, project, people, engine = state
    row = sources.record_task_event(db, task_for(project, people, engine), people[0].id, 'task_published')
    db.commit()
    snapshot = sources.read_source(db, row.id)
    db.delete(db.scalar(select(ProjectMember).where(ProjectMember.user_id == people[0].id)))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        sources.validate_source(db, snapshot)
    assert caught.value.status_code == 403


def test_private_source_never_becomes_project_shared_after_expansion(state):
    db, project, people, engine = state
    channel = ChatChannel(project_id=project.id, channel_type='topic', title='小组', auto_sync_members=False)
    db.add(channel)
    db.flush()
    db.add(ChatChannelMember(channel_id=channel.id, user_id=people[0].id))
    db.commit()
    task = task_for(project, people, engine, {'learning_source_channel_ids': [channel.id]})
    row = sources.record_task_event(db, task, people[0].id, 'task_published')
    db.commit()
    first = sources.read_source(db, row.id)
    assert not first['project_shared']
    assert first['audience_user_ids'] == [str(people[0].id)]
    channel.auto_sync_members = True
    db.commit()
    expanded = sources.read_source(db, row.id)
    assert not expanded['project_shared']
    assert expanded['audience_user_ids'] == first['audience_user_ids']


def test_evidence_and_audience_tampering_are_rejected(state):
    db, project, people, engine = state
    row = sources.record_task_event(db, task_for(project, people, engine), people[0].id, 'task_published')
    db.commit()
    original = sources.read_source(db, row.id)
    forged = {**original, 'evidence': [{'text': '伪造已验收', 'outcome': 'accepted'}]}
    with pytest.raises(HTTPException) as caught:
        sources.validate_source(db, forged)
    assert caught.value.status_code == 409


def test_initialization_draft_change_invalidates_confirmed_source(state):
    db, project, people, _ = state
    conversation = AgentConversation(project_id=project.id, user_id=people[0].id, agent_id='initializer',
        agent_name='初始化', conversation_type='initialization', title='初始化')
    db.add(conversation)
    db.flush()
    draft = ProjectInitializationDraft(project_id=project.id, conversation_id=conversation.id,
        created_by_user_id=people[0].id, status='applied', revision=2, payload={'project': {'name': '项目'}})
    db.add(draft)
    db.flush()
    row = sources.record_initialization_applied(db, draft, people[0].id, {})
    db.commit()
    snapshot = sources.read_source(db, row.id)
    draft.payload = {'project': {'name': '修改项目'}}
    db.commit()
    with pytest.raises(HTTPException) as caught:
        sources.validate_source(db, snapshot)
    assert caught.value.status_code == 409


def test_cursor_advances_past_revoked_source(state):
    db, project, people, engine = state
    row = sources.record_task_event(db, task_for(project, people, engine), people[0].id, 'task_published')
    db.commit()
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    page = sources.list_sources(db, 0, 10)
    assert page['items'] == [] and page['next_after_id'] == row.id


def test_immediate_source_authorization_checks_all_recipients_and_current_state(state):
    db, project, people, engine = state
    channel = ChatChannel(project_id=project.id, channel_type='topic', title='私有来源', auto_sync_members=False)
    db.add(channel)
    db.flush()
    db.add(ChatChannelMember(channel_id=channel.id, user_id=people[0].id))
    db.commit()
    task = task_for(project, people, engine, {'learning_source_channel_ids': [channel.id]})
    row = sources.record_task_event(db, task, people[0].id, 'task_published')
    db.commit()
    assert sources.authorized_source_ids(db, project.id, [str(people[0].id)]) == [str(row.id)]
    assert sources.authorized_source_ids(db, project.id, [str(person.id) for person in people]) == []
    engine.cancel_task(task.id, actor=str(people[0].id), reason='撤销')
    assert sources.authorized_source_ids(db, project.id, [str(people[0].id)]) == []
