"""Bind each group invocation to its requesting platform account."""

from .agent_api_support import _platform_session_context
from .models import AgentConversation


def create_group_agent_session(db, client, *, user, project, channel, thread, agent):
    """A channel's previous agent session must never become another user's history."""
    conversation = AgentConversation(
        project_id=project.id, user_id=user.id, agent_id=thread.agent_id,
        agent_name=thread.agent_name, conversation_type="group_chat",
        title=channel.title, status="creating",
    )
    db.add(conversation)
    db.flush()
    context = _platform_session_context(user, project, conversation, db)
    context.update({
        "chat_channel_id": str(channel.id), "chat_channel_type": channel.channel_type,
        "trigger": "explicit_agent_mention",
    })
    session_id = client.create_session(
        agent=agent,
        workspace_id=f"platform-chat-p{project.id}-c{channel.id}-u{user.id}-r{conversation.id}",
        name=f"{channel.title} · {thread.agent_name}", platform_context=context,
    )
    conversation.agentscope_session_id = session_id
    conversation.status = "running"
    thread.agentscope_session_id = session_id
    db.commit()
    return conversation
