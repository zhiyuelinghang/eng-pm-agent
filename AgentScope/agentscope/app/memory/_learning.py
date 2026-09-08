"""Bind background learning to current platform identities and model credentials."""
from dataclasses import replace
import inspect

from ...message import SystemMsg, UserMsg
from .._service import get_model, build_credential_model_catalog
from ...credential import CredentialFactory
from ._policy import agent_can_use_shared_memory
from utils.memory_repository import MemoryAccess, MemoryError


class PlatformLearningRuntime:
    def __init__(self, *, storage, gateway, resources, settings_loader, tenant_id):
        self.storage=storage
        self.gateway=gateway
        self.resources=resources
        self.settings_loader=settings_loader
        self.tenant_id=tenant_id

    async def group_agent_id(self, config_owner):
        from .._service._platform_settings import get_global_main_agent_id
        agent_id = await get_global_main_agent_id(self.storage, config_owner)
        if not agent_id:
            raise MemoryError('group_agent_missing', '请先配置全局主智能体，作为群聊后台学习的策略来源。')
        return agent_id

    async def authorize_group(self, job):
        settings = await self.settings_loader()
        agent = await self.storage.get_agent(job['config_owner'], job['agent_id'])
        if job['tenant_id'] != self.tenant_id or not settings.learning_enabled or not settings.group_learning_enabled:
            raise MemoryError('group_learning_disabled', '群聊学习已停用。', status=403)
        if not agent_can_use_shared_memory(agent) or not agent.data.platform_config.enabled:
            raise MemoryError('group_agent_disabled', '群聊学习来源智能体已停用。', status=403)
        policy = agent.data.platform_config
        if not policy.learning_capture or not policy.learning_process:
            raise MemoryError('group_learning_disabled', '来源智能体已暂停学习记录或提炼。', status=403)
        return policy

    async def authorize(self,event):
        if event['tenant_id']!=self.tenant_id:
            raise MemoryError('tenant_mismatch','学习租户不匹配。',status=403)
        settings=await self.settings_loader()
        agent=await self.storage.get_agent(event['config_owner'],event['agent_id'])
        if not settings.learning_enabled or not agent_can_use_shared_memory(agent) or not agent.data.platform_config.enabled:
            raise MemoryError('learning_disabled','学习功能或来源智能体已停用。',status=403)
        policy=agent.data.platform_config
        snapshot=event['access_snapshot']
        if event['session_id'].startswith('group:'):
            import asyncio
            from uuid import UUID
            from utils.memory_service import get_memory_repository
            def source_snapshot():
                with get_memory_repository()._connection() as conn:
                    row = conn.execute('SELECT snapshot FROM group_learning_batches WHERE id=%s AND tenant_id=%s',
                        (UUID(event['session_id'][6:]), self.tenant_id)).fetchone()
                    if not row:
                        raise MemoryError('group_source_missing', '群聊学习来源已不存在。', status=403)
                    return row['snapshot']
            source = await asyncio.to_thread(source_snapshot)
            await self.authorize_group(event)
            await self.gateway.group_learning_validate(source)
            if event['scope_type']=='project' and not source['full_project'] or event['scope_type']!='project' and snapshot['user_id'] not in source['members']:
                raise MemoryError('group_scope_changed', '群聊学习成果不能扩大来源可见范围。', status=403)
            access = MemoryAccess(**snapshot)
        elif event['identity_type']=='business_user':
            live=await self.gateway.resolve_memory_scope(event['session_id'])
            if str(live['user_id'])!=snapshot['user_id'] or str(live['project_id'])!=snapshot['project_id']:
                raise MemoryError('identity_mismatch','学习来源会话的身份已经改变。',status=403)
            access=MemoryAccess(self.tenant_id,str(live['user_id']),str(live['project_id']),private=live['private'],
                project_read=live['project_read'],project_write=live['project_write'],
                group_source_channels=tuple(live.get('group_source_channels', [])), group_shared_channels=tuple(live.get('group_shared_channels', [])))
        else:
            session=await self.storage.get_session(event['config_owner'],'',event['session_id'])
            if session is None:
                raise MemoryError('session_missing','学习来源会话已删除。',status=404)
            access=MemoryAccess(self.tenant_id,event['config_owner'],identity_type='management_user')
        return replace(access,read_scopes=tuple(policy.memory_read_scopes),write_scopes=tuple(policy.memory_write_scopes),
            learning_capture=policy.learning_capture,learning_process=policy.learning_process,learning_use=policy.learning_use)

    async def call_model(self,event,system_prompt,user_prompt):
        settings=await self.settings_loader()
        selected=settings.learning_model_config
        if selected is None:
            agent=await self.storage.get_agent(event['config_owner'],event['agent_id'])
            if agent and agent.data.model_policy.mode=='fixed':
                selected=agent.data.model_policy.chat_model_config
            else:
                session=await self.storage.get_session(event['config_owner'],'',event['session_id']) if event.get('session_id') else None
                selected=session.config.chat_model_config if session else None
        if selected is None:
            raise MemoryError('learning_model_missing','请配置学习模型，或为来源智能体配置固定模型；群聊后台学习没有对话模型可回退。')
        record=await self.resources.resolve_credential(event['config_owner'],selected.credential_id)
        credential=CredentialFactory.from_dict(record.data)
        if selected.type!=credential.type:
            raise MemoryError('learning_model_invalid','学习模型与凭证类型不匹配。')
        if not any(m.name==selected.model and m.enabled for m in build_credential_model_catalog(credential)):
            raise MemoryError('learning_model_disabled','所选学习模型已不存在或停用。')
        model=await get_model(event['config_owner'],selected,self.resources)
        response=model([SystemMsg('learning',system_prompt),UserMsg('evidence',user_prompt)])
        if inspect.isawaitable(response):
            response=await response
        last=''
        def read(item):
            blocks=item.get('content',[]) if hasattr(item,'get') else getattr(item,'content',[])
            return next((text for b in blocks if (text := str(b.get('text','') if isinstance(b,dict) else getattr(b,'text','')))), '')
        if hasattr(response,'__aiter__'):
            async for chunk in response:
                last=read(chunk) or last
        else:
            last=read(response)
        return last
