"""Authorize learning sources independently of business-agent orchestration."""
import asyncio
from dataclasses import replace
import inspect
from uuid import UUID

from ...message import SystemMsg, UserMsg
from .._service import get_model, build_credential_model_catalog
from ...credential import CredentialFactory
from utils.memory_repository import MemoryAccess, MemoryError
from utils.learning_settings_guard import LearningPaused, learning_sources, require_learning_enabled


class PlatformLearningRuntime:
    def __init__(self, *, storage, gateway, resources, settings_loader, tenant_id,
                 interaction_validator=None, memory_repository=None):
        self.storage = storage
        self.gateway = gateway
        self.resources = resources
        self.settings_loader = settings_loader
        self.tenant_id = tenant_id
        self.interaction_validator = interaction_validator
        self.memory_repository = memory_repository

    async def authorize_group(self, job):
        settings = await self.settings_loader()
        if job['tenant_id'] != self.tenant_id:
            raise MemoryError('tenant_mismatch', '学习租户不匹配。', status=403)
        require_learning_enabled(settings, {'group'})

    async def authorize(self, event):
        return await self._authorize_sources(event, existing=False)

    async def authorize_existing(self, event):
        """Stopping new learning does not invalidate already published shared results."""
        return await self._authorize_sources(event, existing=True)

    async def filter_existing(self, event, access, rows):
        """Resolve comparison context under the event owner and live authority."""
        if event.get('tenant_id') != self.tenant_id or access.tenant_id != self.tenant_id:
            raise MemoryError('tenant_mismatch', '学习租户不匹配。', status=403)
        owner = event.get('config_owner')
        if not isinstance(owner, str) or not owner:
            raise MemoryError('learning_source_invalid', '学习来源缺少配置归属。', status=403)
        if not rows:
            return []
        repository = self.memory_repository
        if repository is None:
            from utils.memory_service import get_memory_repository
            repository = get_memory_repository()

        def current_rows():
            found = []
            for row in rows:
                try:
                    current = repository.get(access, str(row['id']))
                except MemoryError:
                    continue
                if current['status'] == 'active' and current['version'] == row['version']:
                    found.append(current)
            return found

        candidates = await asyncio.to_thread(current_rows)
        from ._source_validation import filter_current_memory_results
        return await filter_current_memory_results(self.storage,self.gateway,self.tenant_id,owner,
            candidates,repository=repository,learning_runtime=self)

    async def _authorize_sources(self, event, *, existing):
        access = await self._authorize(event, existing=existing)
        scopes = set(access.write_scopes)
        source_ids = set(access.business_source_ids)
        audience = set(access.audience_user_ids)
        for source in event['provenance'].get('derived_sources', []):
            current = await self._authorize(source, existing=existing)
            if (current.tenant_id, current.identity_type, current.target(source['scope_type'], write=True)) != (
                access.tenant_id, access.identity_type, access.target(event['scope_type'], write=True)):
                raise MemoryError('learning_scope_changed', '合并来源的当前归属已改变。', status=403)
            scopes.intersection_update(current.write_scopes)
            source_ids.update(current.business_source_ids)
            audience.intersection_update(current.audience_user_ids)
        return replace(access, write_scopes=tuple(sorted(scopes)),business_source_ids=tuple(sorted(source_ids)),
            audience_user_ids=tuple(sorted(audience)))

    async def _authorize(self, event, *, existing):
        if event['tenant_id'] != self.tenant_id:
            raise MemoryError('tenant_mismatch', '学习租户不匹配。', status=403)
        settings = await self.settings_loader()
        source_type = event['source_type']
        snapshot = event['access_snapshot']
        if not existing:
            require_learning_enabled(settings, {source_type})
        if source_type == 'group':
            if not existing:
                await self.authorize_group(event)
            repository = self.memory_repository
            if repository is None:
                from utils.memory_service import get_memory_repository
                repository = get_memory_repository()
            def source_snapshot():
                with repository._connection() as conn:
                    row = conn.execute('SELECT snapshot FROM group_learning_batches WHERE id=%s AND tenant_id=%s',
                        (UUID(event['provenance']['batch_id']), self.tenant_id)).fetchone()
                    if not row:
                        raise MemoryError('group_source_missing', '群聊学习来源已不存在。', status=403)
                    return row['snapshot']
            source = await asyncio.to_thread(source_snapshot)
            await self.gateway.group_learning_validate(source)
            if (event['scope_type'] == 'project' and not source['full_project'] or
                event['scope_type'] != 'project' and snapshot['user_id'] not in source['members']):
                raise MemoryError('group_scope_changed', '群聊学习成果不能扩大来源可见范围。', status=403)
            return replace(MemoryAccess(**snapshot), private=event['scope_type'] != 'project',
                audience_user_ids=tuple(source['members']))
        if source_type == 'business_event':
            source = event['provenance']['business_source']
            await self.gateway.business_learning_validate(source)
            if not source['allow_learning']:
                raise MemoryError('learning_source_revoked', '业务来源不允许用于学习。', status=403)
            user = snapshot['user_id']
            if str(source['project_id']) != str(snapshot['project_id']) or (
                event['scope_type'] == 'project' and not source['project_shared'] or
                event['scope_type'] == 'user_project' and user not in source['audience_user_ids'] or
                event['scope_type'] not in {'project', 'user_project'}):
                raise MemoryError('learning_scope_changed', '业务事件成果不能扩大原始受众。', status=403)
            return replace(MemoryAccess(**snapshot), audience_user_ids=tuple(source['audience_user_ids']),
                business_source_ids=(str(source['id']),))
        if source_type != 'interaction':
            raise MemoryError('learning_source_invalid', '未知的学习来源。', status=403)
        if not event['provenance'].get('run_id'):
            raise MemoryError('learning_source_invalid', '交互学习缺少业务运行来源。', status=403)
        if self.interaction_validator is None:
            raise MemoryError('learning_source_unavailable', '业务运行来源校验未配置。', status=403)
        return await self.interaction_validator(event, existing=existing)

    async def call_model(self,event,system_prompt,user_prompt):
        settings=await self.settings_loader()
        if event.get('source_type'):
            sources={source for _,source in learning_sources(event)}
        elif 'snapshot' in event and 'channel_id' in event:
            sources={'group'}
        else:
            raise MemoryError('learning_source_invalid', '模型请求缺少明确学习来源。', status=403)
        require_learning_enabled(settings, sources)
        selected=settings.learning_model_config
        if selected is None:
            raise LearningPaused('请在记忆配置中指定后台学习模型。', code='learning_model_missing')
        record=await self.resources.resolve_credential(event['config_owner'],selected.credential_id)
        credential=CredentialFactory.from_dict(record.data)
        if selected.type!=credential.type:
            raise MemoryError('learning_model_invalid','学习模型与凭证类型不匹配。')
        if not any(m.name==selected.model and m.enabled for m in build_credential_model_catalog(credential)):
            raise MemoryError('learning_model_disabled','所选学习模型已不存在或停用。')
        model=await get_model(event['config_owner'],selected,self.resources)
        # Credential/model resolution can await I/O. Recheck immediately before
        # issuing the paid request; the commit transaction checks once more.
        settings=await self.settings_loader()
        require_learning_enabled(settings, sources)
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
