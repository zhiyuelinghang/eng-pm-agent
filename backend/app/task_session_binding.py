"""Durable identity binding for task editor and private draft runs."""
from __future__ import annotations

from sqlalchemy import select

from .db import SessionLocal
from .models import AgentConversation, Project, ProjectMember, User


def create_bound_task_session(client, *, agent, user_id, project_id, generation_id,
                              source_channel_id=None, session_factory=None):
    """Commit a real user/project binding before the first model invocation."""
    with (session_factory or SessionLocal)() as db:
        user, project = db.get(User, int(user_id)), db.get(Project, int(project_id))
        if user is None or project is None:
            raise ValueError("任务生成账号或项目不存在")
        membership = db.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
        if user.role != "admin" and membership is None:
            raise ValueError("当前账号无权访问任务所属项目")
        if source_channel_id is not None:
            from .chat_api import chat_channel_for_user_or_403
            channel = chat_channel_for_user_or_403(db, source_channel_id, user)
            if channel.project_id != project.id:
                raise ValueError("任务来源群聊不属于当前项目")
        conversation = AgentConversation(
            user_id=user.id, project_id=project.id, agent_id=str(agent['id']),
            agent_name="任务助手", conversation_type="task_editor", title="生成任务草稿",
            status="creating", source_channel_id=source_channel_id,
            generation_id=generation_id,
        )
        db.add(conversation)
        db.commit()
        context = {
            'user_id': str(user.id), 'username': user.username, 'display_name': user.real_name,
            'project_id': str(project.id), 'project_name': project.name,
            'conversation_id': str(conversation.id), 'conversation_title': conversation.title,
            'conversation_type': 'task_editor', 'agent_name': '任务助手',
            'trigger': 'task_generation', 'session_role': 'primary',
            'generation_id': generation_id,
            'auto_allowed_tool_names': ['generate_task_flow', 'mcp__task-engine__generate_task_flow'],
        }
        if source_channel_id is not None:
            context['chat_channel_id'] = str(source_channel_id)
        try:
            session_id = client.create_session(
                agent=agent, workspace_id=f'platform-task-editor-p{project.id}-u{user.id}-r{conversation.id}',
                name='任务助手 · 生成任务草稿', platform_context=context,
            )
            conversation.agentscope_session_id = session_id
            conversation.status = 'running'
            db.commit()
            return session_id
        except Exception:
            db.rollback()
            conversation.status = 'failed'
            # Do not persist gateway errors which may contain connection credentials.
            conversation.last_error = '任务助手会话创建失败'
            db.commit()
            raise


def finish_bound_task_session(session_id: str, status: str) -> str | None:
    if status not in {'completed', 'failed', 'cancelled'}:
        raise ValueError('非法任务生成状态')
    with SessionLocal() as db:
        row = db.scalar(select(AgentConversation).where(
            AgentConversation.agentscope_session_id == session_id,
            AgentConversation.conversation_type == 'task_editor'))
        if row is not None:
            row.status = status
            db.commit()
            if status == 'completed':
                from .business_learning_policy import generation_origin_token
                return generation_origin_token(row)
    return None
