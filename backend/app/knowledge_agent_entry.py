"""Create private knowledge sessions using the platform-assigned assistant."""
from fastapi import HTTPException
from sqlalchemy import select
from .api_common import audit, ok, project_for_user_or_403, serialize
from .agent_api_support import _engineering_knowledge_conversation_or_404, _platform_session_context, _raise_agentscope_http_error
from .agentscope_client import AgentScopeGatewayError
from .models import AgentConversation, EngineeringKnowledgeConversation


def connect_knowledge_agent_entry(project_id, conversation_id, payload, db, user, client):
    from .knowledge_agent_support import require_knowledge_agent
    conversation = _engineering_knowledge_conversation_or_404(db, project_id, conversation_id, user)
    # Lock the private mapping so simultaneous tabs cannot create two sessions.
    conversation = db.scalar(select(EngineeringKnowledgeConversation).where(
        EngineeringKnowledgeConversation.id == conversation.id).with_for_update())
    if conversation.agent_conversation_id:
        linked = db.get(AgentConversation, conversation.agent_conversation_id)
        if linked is None or linked.user_id != user.id or linked.project_id != project_id:
            raise HTTPException(status_code=409, detail='知识库助手会话关联异常，请新建对话。')
        return ok(serialize(linked))
    try:
        selected = require_knowledge_agent(client.get_catalog(force_refresh=True), payload.agent_id)
        project = project_for_user_or_403(db, project_id, user)
        linked = AgentConversation(project_id=project_id, user_id=user.id,
            agent_id=selected['id'], agent_name=selected['name'], conversation_type='business',
            title=conversation.title, status='creating')
        db.add(linked)
        db.flush()
        conversation.agent_conversation_id = linked.id
        db.flush()
        linked.agentscope_session_id = client.create_session(
            agent=selected, workspace_id=f'platform-u{user.id}-p{project_id}-conversation-{linked.id}',
            name=linked.title,
            platform_context=_platform_session_context(user, project, linked, db, knowledge_query_enabled=False),
        )
        linked.status = 'active'
        audit(db, user, '接入知识库助手', f'知识库对话接入「{linked.agent_name}」',
              project_id, 'engineering_knowledge_conversation', conversation.id)
        db.commit()
        db.refresh(linked)
        return ok(serialize(linked))
    except AgentScopeGatewayError as exc:
        db.rollback()
        _raise_agentscope_http_error(exc)
