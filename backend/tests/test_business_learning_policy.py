"""System confirmations must retain opt-out from a real, owned generation run."""
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
import pytest

from test_business_learning_sources import state,task_for
from backend.app import business_learning_policy as policy, business_learning_sources as sources
from backend.app.models import AgentConversation,BusinessLearningSource,ProjectInitializationDraft,ChatTaskDraft,ChatChannel


def source_conversation(db,project,people,kind='task_editor'):
    row=AgentConversation(project_id=project.id,user_id=people[0].id,agent_id='task-agent',agent_name='任务助手',
        conversation_type=kind,title='实际生成',agentscope_session_id='source-session',generation_id='source-generation',status='completed')
    db.add(row)
    db.commit()
    return row


def run(*,run_id='run',no_learning=False,no_memory=False,state='completed'):
    return {'tenant_id':'projectcopilot','run_id':run_id,'root_session_id':'source-session','root_agent_id':'task-agent',
        'state':state,'no_learning':no_learning,'no_memory':no_memory}


def test_signed_generation_rejects_forgery_identity_and_replaced_session(state):
    db,project,people,_=state
    row=source_conversation(db,project,people)
    token=policy.generation_origin_token(row)
    assert policy.resolve_generation_origin(db,token,user_id=people[0].id,project_id=project.id).id==row.id
    for value,user,project_id in [(token+'a',people[0].id,project.id),(token,people[1].id,project.id),(token,people[0].id,project.id+1)]:
        with pytest.raises(HTTPException):
            policy.resolve_generation_origin(db,value,user_id=user,project_id=project_id)
    row.agentscope_session_id='another-run'
    db.commit()
    with pytest.raises(HTTPException):
        policy.resolve_generation_origin(db,token,user_id=people[0].id,project_id=project.id)


@pytest.mark.parametrize('runs',[[],[run(no_learning=True)],[run(no_memory=True)],
    [run(run_id='old',no_learning=True),run(run_id='new')]])
def test_unknown_unfinished_or_any_explicit_exclusion_blocks_confirmation_learning(state,monkeypatch,runs):
    db,project,people,_=state
    row=source_conversation(db,project,people)
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:runs)
    actual=policy.task_generation_policy(db,token=policy.generation_origin_token(row),user_id=people[0].id,project_id=project.id)
    assert not actual['allow_learning']
    assert [ref['run_id'] for ref in actual['source_run_refs']]==[item['run_id'] for item in runs]


def test_publish_and_acceptance_retain_source_optout_and_transaction_rollback(state,monkeypatch):
    db,project,people,engine=state
    row=source_conversation(db,project,people)
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:[run(no_learning=True)])
    restricted=policy.task_generation_policy(db,token=policy.generation_origin_token(row),user_id=people[0].id,project_id=project.id)
    task=task_for(project,people,engine,{'learning_policy':restricted})
    published=sources.record_task_event(db,task,people[0].id,'task_published')
    db.commit()
    assert not sources.read_source(db,published.id)['allow_learning']
    assert sources.authorized_source_ids(db,project.id,[str(people[0].id)])==[]
    engine.complete_step(task.id,0,actor=str(people[0].id))
    accepted=engine.accept(task.id,actor=str(people[1].id))
    event=sources.record_task_event(db,accepted,people[1].id,'task_accepted')
    db.flush()
    assert not event.allow_learning and event.source_run_refs==restricted['source_run_refs']
    db.rollback()
    assert len(list(db.scalars(select(BusinessLearningSource))))==1


def test_source_policy_is_rechecked_without_mutating_original_snapshot(state,monkeypatch):
    db,project,people,engine=state
    row=source_conversation(db,project,people)
    runs=[run()]
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:runs)
    allowed=policy.conversation_learning_policy(row)
    task=task_for(project,people,engine,{'learning_policy':allowed})
    event=sources.record_task_event(db,task,people[0].id,'task_published')
    db.commit()
    original=sources.read_source(db,event.id)
    assert original['allow_learning']
    runs[0]['no_learning']=True
    assert not sources.read_source(db,event.id)['allow_learning']
    with pytest.raises(HTTPException) as caught:
        sources.validate_source(db,original)
    assert caught.value.status_code==409


def test_initialization_confirmation_does_not_ignore_earlier_excluded_material(state,monkeypatch):
    db,project,people,_=state
    row=source_conversation(db,project,people,'initialization')
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:[run(run_id='old',no_learning=True),run(run_id='new')])
    draft=ProjectInitializationDraft(project_id=project.id,conversation_id=row.id,created_by_user_id=people[0].id,
        status='applied',revision=2,payload={})
    db.add(draft)
    db.flush()
    event=sources.record_initialization_applied(db,draft,people[0].id,{'counts':{'wbs':1}})
    db.commit()
    assert not sources.read_source(db,event.id)['allow_learning']
    assert len(event.source_run_refs)==2


def test_private_draft_unknown_binding_is_excluded_and_manual_confirmation_is_independent(state):
    db,project,people,_=state
    unknown=policy.task_generation_policy(db,generation_id='missing',user_id=people[0].id,project_id=project.id)
    assert not unknown['allow_learning']
    manual=policy.task_generation_policy(db,user_id=people[0].id,project_id=project.id)
    assert manual=={'allow_learning':True,'source_run_refs':[]}


def test_reply_finalizer_window_is_pending_then_allowed_without_recreating_event(state,monkeypatch):
    db,project,people,engine=state
    row=source_conversation(db,project,people)
    runs=[run(state='active')]
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:runs)
    initial=policy.conversation_learning_policy(row)
    assert initial['allow_learning']
    task=task_for(project,people,engine,{'learning_policy':initial})
    event=sources.record_task_event(db,task,people[0].id,'task_published')
    db.commit()
    pending=sources.read_source(db,event.id)
    assert pending['learning_state']=='pending' and not pending['allow_learning']
    runs[0]['state']='completed'
    current=sources.read_source(db,event.id)
    assert current['learning_state']=='allowed' and current['allow_learning']
    assert current['id']==pending['id']


def test_homepage_knowledge_dependency_does_not_become_unrestricted_task_learning(state,monkeypatch):
    db,project,people,engine=state
    row=source_conversation(db,project,people)
    runs=[{**run(run_id='home'),'has_knowledge':True},run(run_id='generation')]
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:runs)
    origin=policy.conversation_learning_policy(row)
    task=task_for(project,people,engine,{'learning_policy':origin})
    event=sources.record_task_event(db,task,people[0].id,'task_published')
    db.commit()
    assert sources.read_source(db,event.id)['learning_state']=='excluded'
    assert not sources.read_source(db,event.id)['allow_learning']


def test_settings_file_configures_memory_source_without_exporting_environment(monkeypatch,tmp_path):
    from backend.app.config import Settings
    from contextlib import contextmanager
    for name in ('MEMORY_DATABASE_URL','MEMORY_DATABASE_SCHEMA','MEMORY_TENANT_ID','AGENTSCOPE_GLOBAL_CONFIG_ID','DATABASE_URL'):
        monkeypatch.delenv(name,raising=False)
    envfile=tmp_path/'source.env'
    envfile.write_text('DATABASE_URL=postgresql://config-only:unused@127.0.0.1:5432/config-only\nMEMORY_DATABASE_SCHEMA=memory_test\nMEMORY_TENANT_ID=file-tenant\n',encoding='utf-8')
    settings=Settings(_env_file=envfile)
    monkeypatch.setattr(policy,'get_settings',lambda:settings)
    captured={}
    class Repo:
        @contextmanager
        def _connection(self):
            yield self
        def execute(self,query,params):
            captured['params']=params
            return SimpleNamespace(fetchall=lambda:[])
    def repository(url):
        captured['url']=url
        return Repo()
    monkeypatch.setattr(policy,'_source_memory_repository',repository)
    assert policy._memory_runs(session_id='actual')==[]
    assert 'config-only' in captured['url'] and 'memory_test' in captured['url']
    assert 'dobby_demo' not in captured['url']
    assert captured['params']==('file-tenant','actual')


def test_derived_input_permissions_require_the_real_homepage_draft_binding(state,monkeypatch):
    db,project,people,_=state
    origin=source_conversation(db,project,people,'general')
    runs=[run(no_memory=True)]
    monkeypatch.setattr(policy,'_memory_runs',lambda **_:runs)
    original_policy=policy.conversation_learning_policy(origin)
    channel=ChatChannel(project_id=project.id,title='项目群',channel_type='project',auto_sync_members=True)
    db.add(channel)
    db.flush()
    generated=AgentConversation(project_id=project.id,user_id=people[0].id,agent_id='task-assistant',agent_name='任务助手',
        conversation_type='task_editor',title='派生草稿',generation_id='derived-generation',agentscope_session_id='derived-session')
    draft=ChatTaskDraft(project_id=project.id,channel_id=channel.id,requested_by_user_id=people[0].id,
        client_request_id='derived-request',generation_id='derived-generation',request_text='请生成任务',status='ready',
        context_json=[{'source':'home_agent_reference','conversation_id':origin.id,'learning_policy':original_policy}])
    db.add_all([generated,draft])
    db.commit()
    assert policy.derived_input_constraints(db,generated)=={
        'input_is_derived':True,'inherited_no_memory':True,'inherited_no_learning':True}
    # A plain task-editor session cannot set this field through a request label.
    generated.generation_id='unrelated-generation'
    db.commit()
    assert not policy.derived_input_constraints(db,generated)['input_is_derived']
