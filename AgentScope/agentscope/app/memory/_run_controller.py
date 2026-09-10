"""Memory proposals and evidence go directly to a durable backend channel."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import re

from utils.memory_repository import MemoryError
from utils.memory_run_repository import MemoryRunRepository
from ._run_context import (digest, resolve_agent_memory_access, validate_source_refs,
                          knowledge_source_rows, constrain_knowledge_writes)
from ._source_validation import KNOWLEDGE_TOOL_NAME


class RunMemoryController:
    def __init__(self, *, storage, gateway, repository, tenant_id, owner, agent_id, session_id):
        self.storage, self.gateway = storage, gateway
        self.journal = MemoryRunRepository(repository)
        self.tenant, self.owner, self.agent_id, self.session_id = tenant_id, owner, agent_id, session_id
        self.run_id = None
        self.root_id = None
        self.reply_id = None

    async def access(self, *, write=False):
        access, chain = await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,self.owner,
                                                         self.agent_id,self.session_id,write=write)
        if self.run_id:
            if write and self.run_id != chain[0].config.memory_run_id:
                raise MemoryError('run_superseded','该执行节点所属业务请求已被新的请求替代。',status=403)
            run=await asyncio.to_thread(self.journal.get,self.tenant,self.run_id)
            if run['no_memory']:
                access=replace(access,read_scopes=(),write_scopes=(),learning_enabled=False,learning_use=False)
            elif run['no_learning']:
                access=replace(access,learning_enabled=False)
            rows=await asyncio.to_thread(self.journal.sources,self.tenant,self.run_id)
            if knowledge_source_rows(rows):
                access=constrain_knowledge_writes(access)
        return access

    async def begin(self, inputs):
        _, chain = await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,self.owner,
                                                     self.agent_id,self.session_id)
        session, root = chain[0], chain[-1]
        self.run_id, self.root_id = session.config.memory_run_id, root.id
        if not self.run_id:
            raise MemoryError('run_missing','当前会话没有已验证的业务请求。',status=403)
        if self.session_id == root.id:
            source_scope = await self.gateway.resolve_memory_scope(root.id) if root.config.platform_context is not None else {}
            derived_input = bool(source_scope.get('input_is_derived'))
            users = inputs if isinstance(inputs,list) else [inputs]
            # Read the persisted original, before attachment enrichment or
            # inbox hints can be mistaken for a new user's assertion.
            originals=[]
            for msg in users:
                if getattr(msg,'role',None)=='user':
                    original=await self.storage.get_message(self.owner,root.id,msg.id)
                    if original is None or original.role!='user':
                        raise MemoryError('source_required','用户请求尚未可靠保存。',status=403)
                    originals.append(original)
            text='\n'.join(m.get_text_content() for m in originals)
            # Negation belongs to its own clause. In particular, “不要学习，
            # 记住我的偏好” must preserve the explicit request to save a fact.
            no_memory=bool(re.search(
                r'(不要|别|无需|不必|不用|不需要)(?:(?!学习|复盘|提炼|但是|但|而|同时)[^，,。.!！?？;；：:\r\n]){0,6}(记住|记忆|保存这段)',text))
            no_learning=bool(re.search(
                r'(不要|别|无需|不必|不用|不需要)(?:(?!记住|记忆|保存这段|但是|但|而|同时)[^，,。.!！?？;；：:\r\n]){0,6}(学习|复盘|提炼)',text))
            await asyncio.to_thread(self.journal.begin,self.tenant,self.run_id,self.owner,root.id,root.agent_id,
                                    no_memory=no_memory,no_learning=no_learning)
            for msg in (() if derived_input else originals):
                raw=msg.get_text_content()
                await asyncio.to_thread(self.journal.evidence,self.tenant,self.run_id,self.agent_id,self.session_id,
                    {'id':msg.id,'kind':'user','text':raw[:4000],'outcome':'observed','tool_name':''},
                    {'kind':'user','session_id':root.id,'message_id':msg.id,'hash':digest(raw)})
        else:
            run=await asyncio.to_thread(self.journal.get,self.tenant,self.run_id)
            if run['root_session_id'] != root.id:
                raise MemoryError('run_parent_mismatch','候选记忆的业务来源不一致。',status=403)
        await asyncio.to_thread(self.journal.node,self.tenant,self.run_id,self.session_id,self.agent_id)

    async def reply_started(self, reply_id):
        self.reply_id=reply_id
        await asyncio.to_thread(self.journal.node,self.tenant,self.run_id,self.session_id,self.agent_id,reply_id)

    async def user_sources(self):
        rows=await asyncio.to_thread(self.journal.sources,self.tenant,self.run_id)
        return {row['evidence_id']:row['evidence']['text'] for row in rows if row['evidence']['kind']=='user'}

    async def record_tool(self, evidence):
        access=await self.access()
        knowledge=evidence.get('tool_name') == KNOWLEDGE_TOOL_NAME
        if not access.learning_enabled and not knowledge:
            return
        if knowledge:
            # This is an authority marker, independent from learning consent.
            # Keep no retrieved text in the journal, including before sealing.
            evidence={**evidence,'text':'发生了项目知识库查询；原文保留在知识库，来源权限待持久工具结果核验。',
                'outcome':'assistant_claim' if evidence.get('outcome')=='success' else evidence.get('outcome','')}
        await asyncio.to_thread(self.journal.evidence,self.tenant,self.run_id,self.agent_id,self.session_id,evidence,
            {'kind':'tool','session_id':self.session_id,'message_id':self.reply_id,'tool_call_id':evidence['id'],
             'knowledge_source':knowledge})

    async def submit(self, operation, payload):
        access, chain=await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,self.owner,
                                                       self.agent_id,self.session_id,write=True)
        access=await self.access(write=True)
        source_rows=await asyncio.to_thread(self.journal.sources,self.tenant,self.run_id)
        knowledge_rows=knowledge_source_rows(source_rows)
        sources=await self.user_sources()
        if not sources:
            raise MemoryError('source_required','保存记忆需要本次业务的真实用户来源。')
        ids=[]
        if operation=='write':
            for item in payload:
                access.target(item.scope_type,write=True)
                item.source_message_id=item.source_message_id or next(reversed(sources))
                if item.source_message_id not in sources:
                    raise MemoryError('source_forbidden','只能引用本次业务的真实用户消息。',status=403)
                ids.append(item.source_message_id)
            data=[item.model_dump(mode='json') for item in payload]
        else:
            ids=[next(reversed(sources))]
            data=payload
        proposal=await asyncio.to_thread(self.journal.propose,self.tenant,self.run_id,operation,data,sorted(set(ids)),
            [{'agent_id':s.agent_id,'session_id':s.id} for s in chain])
        if proposal['state']=='saved':
            # A completed proposal is only an acknowledgement. Never replay
            # a historical record payload without current source/version checks.
            return {'status':'deleted' if operation=='forget' else 'unchanged','proposal_id':proposal['id'],
                'message':'记忆已停止召回。' if operation=='forget' else '该保存请求已处理，不会重复写入。'}
        if proposal['state']=='rejected':
            raise MemoryError(proposal['error_code'],'该记忆请求已被拒绝，请检查来源和权限。')
        if operation=='forget':
            record=await asyncio.to_thread(self.journal.memories.get,access,payload['memory_id'])
            access.target(record['scope_type'],write=True)
        if self.session_id != self.root_id:
            return {'status':'pending','proposal_id':proposal['id'],'message':'候选记忆已提交，后端将在本次业务完成并检查权限后统一处理；尚未保存为长期记忆。'}
        nodes=await asyncio.to_thread(self.journal.nodes,self.tenant,self.run_id)
        if operation=='write' and knowledge_rows:
            return {'status':'pending','proposal_id':proposal['id'],
                'message':'候选记忆依赖知识来源，等待持久工具结果与当前资料权限核验后保存到用户＋项目范围。'}
        if operation=='write':
            # A returned team message does not mean every delegated result is
            # already durable. Pending work may introduce narrower sources.
            for node in nodes:
                if node['session_id']==self.root_id:
                    continue
                reply=await self.storage.get_message(self.owner,node['session_id'],node['reply_id']) if node['reply_id'] else None
                if reply is None or not reply.finished_at:
                    return {'status':'pending','proposal_id':proposal['id'],'message':'协作来源尚未结束，候选记忆等待后端统一检查。'}
                if reply.finished_reason!='completed':
                    raise MemoryError('source_run_failed','协作来源未成功完成，候选记忆不能保存。',status=403)
        for contributor in proposal['contributors']:
            current,_=await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,self.owner,
                contributor['agent_id'],contributor['session_id'],write=True)
            access=replace(access,write_scopes=tuple(sorted(set(access.write_scopes)&set(current.write_scopes))))
            if contributor['session_id'] != self.root_id:
                node=next((n for n in nodes if n['session_id']==contributor['session_id']),None)
                reply=await self.storage.get_message(self.owner,node['session_id'],node['reply_id']) if node and node['reply_id'] else None
                if reply is None or not reply.finished_at:
                    return {'status':'pending','proposal_id':proposal['id'],'message':'来源协作尚未结束，候选记忆等待后端统一检查。'}
                if reply.finished_reason!='completed':
                    raise MemoryError('source_run_failed','来源协作未成功完成，候选记忆不能保存。',status=403)
        source_rows=await asyncio.to_thread(self.journal.sources,self.tenant,self.run_id)
        refs=[r['source_ref'] for r in source_rows if r['evidence_id'] in ids]
        await validate_source_refs(self.storage,self.owner,refs,gateway=self.gateway)
        result=await asyncio.to_thread(self.journal.commit,proposal,access,
            {'kind':'run_memory','run_id':self.run_id,'session_id':self.root_id,'source_refs':refs,
             'agent_id':self.agent_id,'messages':{key:sources[key] for key in ids}})
        if operation=='forget':
            return {'status':'deleted','proposal_id':proposal['id'],'message':'记忆已停止召回。'}
        state='unchanged' if all(item['status']=='unchanged' for item in result) else (
            'candidate' if all(item['memory']['status']=='candidate' for item in result) else 'saved')
        return {'status':state,'proposal_id':proposal['id'],'results':result,
            'message':'内容没有变化，无需重复保存。' if state=='unchanged' else '记忆请求已按当前权限保存。'}

    async def request_learning(self, event_type, *, scope_type=None, enqueue=True):
        access=await self.access(write=True)
        if not access.learning_enabled:
            raise MemoryError('learning_disabled','当前业务场景或本次请求不允许交互学习。',status=403)
        if scope_type:
            access.target(scope_type,write=True)
        await asyncio.to_thread(self.journal.request_learning,self.tenant,self.run_id,self.session_id,
                                {'event_type':event_type,'scope_type':scope_type,'enqueue':enqueue})
        return {'status':'pending','run_id':self.run_id,'message':'素材已归入本次业务；后台在有效阶段结束后统一提炼。'}
