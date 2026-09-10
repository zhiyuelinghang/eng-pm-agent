from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.tests.test_engineering_knowledge_conversations import db, _admin
from backend.app.models import AgentConversation, EngineeringKnowledgeConversation, EngineeringDocumentNode, Project
from backend.app.schemas import EngineeringKnowledgeConversationCreateInput, KnowledgeAgentConnectInput
from backend.app.engineering_documents_api import create_engineering_knowledge_conversation, connect_knowledge_agent
from backend.app.agent_conversations_api import _turn_platform_context, list_agent_conversations
from backend.app.knowledge_agent_support import constrain_knowledge_scope, knowledge_entry_prompt


def setup_entry(db, scope='project', **kwargs):
    user = _admin(db, 'entry')
    project = Project(name='独立资料助手测试项目')
    db.add(project)
    db.commit()
    created = create_engineering_knowledge_conversation(project.id,
        EngineeringKnowledgeConversationCreateInput(scope_type=scope, first_message='你好', **kwargs), db, user)['data']
    return user, project, db.get(EngineeringKnowledgeConversation, created['conversation']['id'])


def gateway():
    client = Mock()
    client.get_catalog.return_value = {'knowledge_assistant': {'id': 'docs', 'name': '底层测试模型助手',
        'enabled': True, 'published': False, 'project_knowledge_enabled': True, 'model_ready': True}, 'business_agents': []}
    client.create_session.return_value = 'test-knowledge-session'
    return client


def test_connect_reuses_platform_session_without_contacting_knowledge_service(db):
    user, project, entry = setup_entry(db)
    client = gateway()
    with patch('backend.app.engineering_documents_api._agentscope_client', return_value=client):
        result = connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(), db, user)['data']
        again = connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(agent_id='ignored'), db, user)['data']
    assert result['id'] == again['id'] == entry.agent_conversation_id
    assert result['conversation_type'] == 'business'
    assert result['agent_name'] == '知识库助手'
    assert client.create_session.call_count == 1
    assert client.create_session.call_args.kwargs['platform_context']['weknora_query_enabled'] is False
    conversation = db.get(AgentConversation, result['id'])
    with patch('backend.app.agent_api_support.readable_external_ids', side_effect=AssertionError('问候不能预读资料目录')):
        context, forced = _turn_platform_context(db, user, project, conversation, '你好')
    assert context['project_id'] == str(project.id)
    assert context['user_id'] == str(user.id)
    assert forced is None
    prompt = knowledge_entry_prompt(db, conversation)
    assert '普通问候' in prompt and '管理端已分配的项目工具' in prompt
    # The specialized entry must not replace a normal business-tool conversation.
    assert list_agent_conversations(project.id, 'business', 'docs', db, user)['data'] == []


def test_connect_checks_owner_and_published_capability_before_creating_session(db):
    user, project, entry = setup_entry(db)
    other = _admin(db, 'other')
    db.commit()
    client = gateway()
    with patch('backend.app.engineering_documents_api._agentscope_client', return_value=client):
        with pytest.raises(HTTPException) as denied:
            connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(agent_id='docs'), db, other)
        assert denied.value.status_code in (403, 404)
        with pytest.raises(HTTPException) as missing:
            connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(agent_id='main'), db, user)
        assert missing.value.status_code == 409
    client.create_session.assert_not_called()


def test_scope_is_union_of_selections_intersected_with_fresh_permissions(db):
    user, project, entry = setup_entry(db, scope='selection', scope_items=[
        {'scope_type': 'folder', 'knowledge_base_id': 'kb', 'folder_path': '方案'},
        {'scope_type': 'document', 'knowledge_base_id': 'kb2', 'knowledge_id': 'chosen'},
    ])
    conversation = AgentConversation(project_id=project.id, user_id=user.id, agent_id='docs', agent_name='资料助手', title='测试', conversation_type='business')
    db.add(conversation)
    db.flush()
    entry.agent_conversation_id = conversation.id
    for doc, base, folder in [('inside','kb','方案/安全'), ('sibling','kb','方案旧版'), ('chosen','kb2',''), ('revoked','kb','方案')]:
        db.add(EngineeringDocumentNode(project_id=project.id, node_key=doc, external_id=doc, node_type='file', name=doc, knowledge_base_id=base, folder_path=folder))
    db.flush()
    envelope = {'weknora_knowledge_ids': ['inside','sibling','chosen'], 'weknora_knowledge_base_ids': ['kb','kb2']}
    result = constrain_knowledge_scope(db, conversation, envelope)
    assert result['weknora_knowledge_ids'] == ['chosen','inside']
    assert envelope['weknora_knowledge_ids'] == ['inside','sibling','chosen']
    reduced = constrain_knowledge_scope(db, conversation, {**envelope, 'weknora_knowledge_ids':['sibling']})
    assert reduced['weknora_knowledge_ids'] == [] and reduced['weknora_knowledge_base_ids'] == []
    assert reduced['weknora_access_mode'] == 'restricted'


def test_agent_creation_failure_leaves_legacy_history_intact(db):
    from backend.app.agentscope_client import AgentScopeGatewayError
    user, project, entry = setup_entry(db)
    client = gateway()
    client.create_session.side_effect = AgentScopeGatewayError('测试服务不可用')
    with patch('backend.app.engineering_documents_api._agentscope_client', return_value=client):
        with pytest.raises(HTTPException):
            connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(agent_id='docs'), db, user)
    db.refresh(entry)
    assert entry.agent_conversation_id is None
    assert db.scalars(select(AgentConversation)).all() == []


def test_knowledge_entry_does_not_fall_back_to_published_business_agents(db):
    user, project, entry = setup_entry(db)
    client = gateway()
    client.get_catalog.return_value = {'business_agents': [client.get_catalog.return_value['knowledge_assistant']]}
    with patch('backend.app.engineering_documents_api._agentscope_client', return_value=client):
        with pytest.raises(HTTPException) as error:
            connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(), db, user)
    assert error.value.status_code == 409
    assert '平台主智能体' in error.value.detail
    client.create_session.assert_not_called()
    assert entry.agent_conversation_id is None


def test_linked_turn_uses_assignment_and_rejects_changed_or_disabled_capability(db):
    from backend.app.agent_api_support import _catalog_agent_for_conversation
    user, project, entry = setup_entry(db)
    client = gateway()
    with patch('backend.app.engineering_documents_api._agentscope_client', return_value=client):
        connected = connect_knowledge_agent(project.id, entry.id, KnowledgeAgentConnectInput(), db, user)['data']
    conversation = db.get(AgentConversation, connected['id'])
    catalog = client.get_catalog.return_value
    assert _catalog_agent_for_conversation(catalog, conversation, db=db)['id'] == 'docs'
    for changed in (None, {**catalog['knowledge_assistant'], 'id':'other'},
                    {**catalog['knowledge_assistant'], 'model_ready':False},
                    {**catalog['knowledge_assistant'], 'project_knowledge_enabled':False}):
        with pytest.raises(HTTPException) as error:
            _catalog_agent_for_conversation({**catalog, 'knowledge_assistant':changed}, conversation, db=db)
        assert error.value.status_code == 409
    ordinary = AgentConversation(project_id=project.id, user_id=user.id, agent_id='docs',
        agent_name='资料助手', title='普通入口', conversation_type='business')
    db.add(ordinary)
    db.flush()
    with pytest.raises(HTTPException):
        _catalog_agent_for_conversation(catalog, ordinary, db=db)
