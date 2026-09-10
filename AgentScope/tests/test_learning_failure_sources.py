"""A recovery can reuse evidence only with its complete original provenance."""
from uuid import uuid4

from test_memory_repository import repository, access
from utils.learning_repository import LearningRepository


def capture(learning, *, actor=None, session='s', agent='agent', outcome='error', kind='tool_failure', run='run-1', refs=True):
    provenance = {'run_id':run,'root_session_id':session,'root_agent_id':agent,
        'contributors':[{'agent_id':agent,'session_id':session}],
        'source_refs':[{'kind':'tool','session_id':session,'message_id':'m','tool_call_id':'call','hash':'original-hash'}] if refs else []}
    return learning.capture(actor or access(), scope_type='user_project', agent_id=agent, session_id=session,
        config_owner='owner',event_key=str(uuid4()),event_type=kind,enqueue=False,
        evidence=[{'id':str(uuid4()),'kind':'tool','tool_name':'verify','text':'真实工具结果','outcome':outcome}],
        source_type='interaction',provenance=provenance)


def failures(learning,actor=None,**kwargs):
    return learning.recent_failure_events(actor or access(),scope_type='user_project',agent_id=kwargs.get('agent','agent'),
        session_id=kwargs.get('session','s'),tool_names=['verify'])


def test_recent_failure_keeps_original_event_and_all_source_references(repository):
    learning = LearningRepository(repository)
    saved = capture(learning)
    rows = failures(learning)
    assert len(rows) == 1 and rows[0]['id'] == saved['event_id']
    assert rows[0]['provenance']['source_refs'][0]['hash'] == 'original-hash'
    assert rows[0]['provenance']['contributors'] == [{'agent_id':'agent','session_id':'s'}]
    assert rows[0]['source_type'] == 'interaction' and rows[0]['evidence'][0]['outcome'] == 'error'


def test_failure_lookup_is_scoped_and_does_not_accept_text_only_sources(repository):
    learning = LearningRepository(repository)
    capture(learning,actor=access(user='b'))
    capture(learning,actor=access(project='other'))
    capture(learning,session='other')
    capture(learning,agent='other')
    capture(learning,refs=False)
    capture(learning,run='')
    assert failures(learning) == []
    capture(learning)
    assert len(failures(learning)) == 1
    assert failures(learning,access(learning_enabled=False)) == []


def test_successful_recovery_stops_reusing_old_failure_until_new_failure(repository):
    learning = LearningRepository(repository)
    capture(learning)
    capture(learning,outcome='success',kind='recovery',run='run-2')
    assert failures(learning) == []
    latest = capture(learning,run='run-3')
    assert [row['id'] for row in failures(learning)] == [latest['event_id']]
