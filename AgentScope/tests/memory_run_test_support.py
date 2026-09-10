"""Persisted session/message fixtures around the real run controller and PG store."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from agentscope.app.memory._run_context import bind_memory_run
from agentscope.app.memory._run_controller import RunMemoryController
from agentscope.app.memory._run_service import MemoryRunService
from agentscope.app.storage import (
    PlatformAgentConfig, PlatformSessionContext, SessionConfig, SessionRecord,
    TeamData, TeamMember, TeamRecord, MemorySettingsData, ChatModelConfig,
    PlatformSettingsData, PlatformSettingsRecord,
)
from agentscope.message import UserMsg, AssistantMsg, ToolResultBlock, ToolResultState
from utils.memory_repository import MemoryAccess
from agentscope.app.memory._settings import RuntimeMemorySettings


class MemoryRunHarness:
    def __init__(self, repository, *, actor=None, depth=1, debug=False):
        self.repository = repository
        # The gateway actor supplies live identity and project authorization;
        # agent capabilities come from system duties and the trusted scenario.
        self.actor = actor or MemoryAccess('t', 'a', 'p', project_read=True, project_write=True)
        self.messages = {}
        self.sessions = {}
        self.agents = {}
        self.controllers = {}
        self.team = None
        self.entry_kind = 'business'
        self.knowledge_agent_id = None
        self.global_main_agent_id = None
        self.project_initializer_agent_id = None
        self.task_assistant_agent_id = None
        self.knowledge_ids = ['restricted-doc']
        for index in range(depth):
            sid = 's' if index == 0 else f'child-{index}'
            aid = 'agent' if index == 0 else f'agent-{index}'
            context = None if debug else PlatformSessionContext(
                user_id=self.actor.user_id, username='test', display_name='test',
                project_id=self.actor.project_id, project_name='test project',
                conversation_id='conversation', conversation_title='test', conversation_type='chat',
                agent_name=aid, session_role='primary' if index == 0 else 'worker',
                root_session_id=None if index == 0 else 's',
            )
            self.sessions[sid] = SessionRecord(id=sid, user_id='owner', agent_id=aid,
                team_id='team' if depth > 1 else None,
                config=SessionConfig(workspace_id=aid, platform_context=context))
            self.agents[aid] = SimpleNamespace(id=aid, data=SimpleNamespace(platform_config=PlatformAgentConfig()))
        if depth > 1:
            self.team = TeamRecord(id='team', user_id='owner', session_id='s', data=TeamData(name='test',
                members=[TeamMember(owner_id='owner', agent_id=f'agent-{i}', session_id=f'child-{i}',
                    role='invited', inviter_session_id='s' if i == 1 else f'child-{i-1}',
                    work_status='completed') for i in range(1, depth)]))
        self.storage = SimpleNamespace(get_session=self.get_session, get_agent=self.get_agent,
            get_team=self.get_team, get_message=self.get_message, upsert_session=self.upsert_session,
            get_platform_settings=self.get_platform_settings)
        self.gateway = SimpleNamespace(resolve_memory_scope=self.resolve_memory_scope,
            resolve_knowledge_scope=self.resolve_knowledge_scope)
        self.service = MemoryRunService(storage=self.storage, gateway=self.gateway, repository=repository, tenant_id=self.actor.tenant_id)
        self.settings = RuntimeMemorySettings(learning_enabled=True, learning_model_config=ChatModelConfig(
            type='custom_openai_credential', credential_id='test', model='test', parameters={}), learning_cooldown_seconds=0)

    async def get_session(self, owner, aid, sid):
        value = self.sessions.get(sid)
        return value if owner == 'owner' and value and (not aid or value.agent_id == aid) else None

    async def get_agent(self, owner, aid):
        return self.agents.get(aid) if owner == 'owner' else None

    async def get_team(self, owner, tid):
        return self.team if owner == 'owner' and self.team and tid == self.team.id else None

    async def get_message(self, owner, sid, mid):
        return self.messages.get((sid, mid)) if owner == 'owner' else None

    async def upsert_session(self, owner, aid, config, *, state, session_id, **_):
        self.sessions[session_id] = self.sessions[session_id].model_copy(update={'config': config, 'state': state})

    async def resolve_memory_scope(self, _):
        a = self.actor
        return {'entry_kind': self.entry_kind, **{key: getattr(a, key) for key in ('user_id', 'project_id', 'private', 'project_read', 'project_write', 'group_source_channels', 'group_shared_channels', 'audience_user_ids', 'business_source_ids')}}

    async def get_platform_settings(self, _):
        return PlatformSettingsRecord(user_id='owner', data=PlatformSettingsData(
            global_main_agent_id=self.global_main_agent_id,
            project_initializer_agent_id=self.project_initializer_agent_id,
            task_assistant_agent_id=self.task_assistant_agent_id,
            knowledge_assistant_agent_id=self.knowledge_agent_id))

    async def resolve_knowledge_scope(self, *, session_id, actor_agent_id):
        return {'user_id': self.actor.user_id, 'project_id': self.actor.project_id,
            'conversation_id': 'conversation', 'weknora_agent_id': 'robot',
            'weknora_query_enabled': True, 'weknora_catalogue_ready': True,
            'weknora_knowledge_ids': self.knowledge_ids}

    async def persist_inputs(self, inputs):
        users = inputs if isinstance(inputs, list) else [inputs]
        for msg in users:
            if getattr(msg, 'role', None) == 'user':
                self.messages[('s', msg.id)] = msg
        await bind_memory_run(self.storage, 'owner', self.sessions['s'], inputs)
        for sid in self.sessions:
            if sid != 's':
                self.sessions[sid].config.memory_run_id = self.sessions['s'].config.memory_run_id

    def controller(self, sid='s', *, prepare_inputs=True):
        if sid in self.controllers:
            return self.controllers[sid]
        controller = RunMemoryController(storage=self.storage, gateway=self.gateway, repository=self.repository,
            tenant_id=self.actor.tenant_id, owner='owner', agent_id=self.sessions[sid].agent_id, session_id=sid)
        if prepare_inputs and sid == 's':
            begin = controller.begin
            async def before_begin(inputs):
                await self.persist_inputs(inputs)
                if controller.run_id != self.sessions['s'].config.memory_run_id:
                    controller.reply_id = None
                await begin(inputs)
            controller.begin = before_begin
        record = controller.record_tool
        async def persist_tool(evidence):
            if not controller.reply_id:
                await controller.reply_started('reply-' + uuid4().hex)
            key = (sid, controller.reply_id)
            message = self.messages.get(key) or AssistantMsg(self.sessions[sid].agent_id, [], id=controller.reply_id)
            message.content.append(ToolResultBlock(id=evidence['id'], name=evidence['tool_name'],
                output=evidence['text'], metadata=evidence.get('metadata', {}),
                state=ToolResultState.ERROR if evidence['outcome']=='error' else ToolResultState.SUCCESS))
            self.messages[key] = message
            await record({key: evidence[key] for key in ('id', 'kind', 'text', 'outcome', 'tool_name')})
        controller.record_tool = persist_tool
        self.controllers[sid] = controller
        return controller

    def knowledge_evidence(self, *, evidence_id='knowledge-call'):
        return {'id': evidence_id, 'kind': 'tool', 'tool_name': 'weknora_query_project_knowledge',
            'outcome': 'success', 'text': json.dumps({'answer': '受限合同中的私有条款', 'references': [{'knowledge_id': 'restricted-doc'}]}, ensure_ascii=False),
            'metadata': {'operation': 'weknora_query_project_knowledge', 'weknora_robot_id': 'robot',
                'platform_user_id': self.actor.user_id, 'platform_project_id': self.actor.project_id,
                'platform_conversation_id': 'conversation', 'knowledge_ids': ['restricted-doc'],
                'knowledge_base_ids': ['kb'], 'knowledge_access_mode': 'restricted', 'reference_count': 1}}

    async def start(self, text='记住项目周报采用问题、责任人和期限格式', *, mid=None):
        msg = UserMsg('user', text, id=mid or uuid4().hex)
        await self.controller().begin([msg])
        for sid in self.sessions:
            if sid != 's':
                await self.controller(sid).begin([])
        return msg

    async def finish(self, *, reason='completed', node_reasons=None):
        for sid, controller in self.controllers.items():
            if not controller.reply_id:
                await controller.reply_started('reply-' + uuid4().hex)
            key = (sid, controller.reply_id)
            message = self.messages.get(key) or AssistantMsg(self.sessions[sid].agent_id, '完成', id=controller.reply_id)
            message.finished_at = '2026-09-10T10:00:00+08:00'
            message.finished_reason = (node_reasons or {}).get(sid, reason if sid == 's' else 'completed')
            self.messages[key] = message
        run = self.service.journal.get(self.actor.tenant_id, self.controller().run_id)
        await self.service.process(run, self.settings)
        return self.service.journal.get(self.actor.tenant_id, self.controller().run_id)
