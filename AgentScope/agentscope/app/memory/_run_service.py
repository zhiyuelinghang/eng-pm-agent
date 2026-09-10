"""Finalize one business run after persisted replies and delegated work settle."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import logging

from utils.learning_repository import LearningRepository
from utils.memory_repository import MemoryError
from utils.memory_run_repository import MemoryRunRepository
from .._team_lifecycle import team_work_is_pending
from ._run_context import (digest, resolve_agent_memory_access, validate_source_refs, validate_learning_event,
                          knowledge_source_rows, constrain_knowledge_writes)
from ._source_validation import KNOWLEDGE_TOOL_NAME, knowledge_learning_evidence

logger=logging.getLogger(__name__)


class MemoryRunService:
    def __init__(self, *, storage, gateway, repository, tenant_id):
        self.storage,self.gateway,self.tenant=storage,gateway,tenant_id
        self.journal=MemoryRunRepository(repository)
        self.learning=LearningRepository(repository)

    async def _seal(self, run, rows):
        sealed=[]
        for row in rows:
            ref=row['source_ref']
            if not ref:
                continue
            if ref['kind']=='tool' and 'hash' not in ref:
                message=await self.storage.get_message(run['config_owner'],ref['session_id'],ref['message_id'])
                if message is None or not message.finished_at:
                    raise MemoryError('evidence_pending','工具结果还未可靠保存。',status=409)
                blocks=[b for b in message.get_content_blocks('tool_result') if b.id==ref['tool_call_id']]
                if not blocks:
                    raise MemoryError('source_missing','工具证据已不存在。',status=403)
                block=blocks[-1]
                knowledge_text=knowledge_learning_evidence(block)
                text=knowledge_text if knowledge_text is not None else (
                    block.output if isinstance(block.output,str) else '\n'.join(getattr(b,'text','') for b in block.output))
                evidence={**row['evidence'],'text':(block.name+': '+text)[:4000]}
                if knowledge_text is not None:
                    evidence.update(tool_name=KNOWLEDGE_TOOL_NAME,
                        outcome='assistant_claim' if evidence.get('outcome')=='success' else evidence.get('outcome',''))
                    ref={**ref,'knowledge_source':True}
                ref={**ref,'hash':digest(block.model_dump(mode='json'))}
                await asyncio.to_thread(self.journal.seal_evidence,self.tenant,run['run_id'],row['evidence_id'],evidence,ref)
                row={**row,'evidence':evidence,'source_ref':ref}
            sealed.append(row)
        await validate_source_refs(self.storage,run['config_owner'],[r['source_ref'] for r in sealed],gateway=self.gateway)
        return sealed

    async def _proposal_access(self,run,proposal):
        current=None
        nodes=await asyncio.to_thread(self.journal.nodes,self.tenant,run['run_id'])
        for node in proposal['contributors']:
            record=next((n for n in nodes if n['session_id']==node['session_id']),None)
            reply=await self.storage.get_message(run['config_owner'],node['session_id'],record['reply_id']) if record and record['reply_id'] else None
            if reply is None or not reply.finished_at or reply.finished_reason!='completed':
                raise MemoryError('source_run_failed','来源协作尚未成功完成。',status=403)
            access,_=await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,run['config_owner'],
                                                       node['agent_id'],node['session_id'],write=True)
            current=access if current is None else replace(current,write_scopes=tuple(sorted(set(current.write_scopes)&set(access.write_scopes))))
        return current

    async def process(self, run, settings):
        from ._settings import runtime_memory_settings
        settings = runtime_memory_settings(settings)
        owner,run_id=run['config_owner'],run['run_id']
        root=await self.storage.get_session(owner,'',run['root_session_id'])
        if root is None or (run['state']=='active' and root.config.memory_run_id!=run_id):
            await asyncio.to_thread(self.journal.finish,self.tenant,run_id,cancelled=True,error='run_superseded')
            return
        nodes=await asyncio.to_thread(self.journal.nodes,self.tenant,run_id)
        root_node=next((n for n in nodes if n['session_id']==root.id),None)
        if not root_node or not root_node['reply_id']:
            return
        reply=await self.storage.get_message(owner,root.id,root_node['reply_id'])
        if reply is None or not reply.finished_at:
            return
        if reply.finished_reason!='completed':
            await asyncio.to_thread(self.journal.finish,self.tenant,run_id,cancelled=True,error='run_'+str(reply.finished_reason))
            return
        if root.team_id:
            team=await self.storage.get_team(owner,root.team_id)
            if team is None:
                await asyncio.to_thread(self.journal.finish,self.tenant,run_id,cancelled=True,error='run_team_missing')
                return
            if team_work_is_pending(team):
                return
        rows=await self._seal(run,await asyncio.to_thread(self.journal.sources,self.tenant,run_id))
        knowledge_rows=knowledge_source_rows(rows)
        knowledge_contributors=list({row['session_id']:{'agent_id':row['agent_id'],'session_id':row['session_id']}
                                     for row in knowledge_rows}.values())
        for proposal in await asyncio.to_thread(self.journal.pending,self.tenant,run_id):
            try:
                if proposal['operation']=='write' and knowledge_contributors:
                    # Only still-pending proposals depend on this final source
                    # set. Earlier explicit user facts already saved stay intact.
                    proposal={**proposal,'contributors':list({node['session_id']:node for node in
                        [*proposal['contributors'],*knowledge_contributors]}.values())}
                access=await self._proposal_access(run,proposal)
                dependency_ids={r['evidence_id'] for r in knowledge_rows} if proposal['operation']=='write' else set()
                if dependency_ids:
                    access=constrain_knowledge_writes(access)
                refs=[r['source_ref'] for r in rows if r['evidence_id'] in set(proposal['evidence_ids'])|dependency_ids]
                await validate_source_refs(self.storage,owner,refs,gateway=self.gateway)
                await asyncio.to_thread(self.journal.commit,proposal,access,{'kind':'run_memory','run_id':run_id,
                    'session_id':root.id,'agent_id':root.agent_id,'source_refs':refs,
                    'messages':{r['evidence_id']:r['evidence']['text'] for r in rows if r['evidence_id'] in proposal['evidence_ids']}})
            except MemoryError as exc:
                await asyncio.to_thread(self.journal.reject,proposal['id'],exc.code)
        await asyncio.to_thread(self.journal.finish,self.tenant,run_id)
        requests=[n for n in nodes if n['learning_request']]
        if run['no_learning'] or root.config.platform_context is None or not requests:
            await asyncio.to_thread(self.journal.finish,self.tenant,run_id,learning_state='skipped')
            return
        if not settings.learning_enabled or not settings.learning_interactions_enabled or settings.learning_model_config is None:
            return
        access,_=await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,owner,root.agent_id,root.id)
        if not access.learning_enabled:
            await asyncio.to_thread(self.journal.finish,self.tenant,run_id,learning_state='skipped')
            return
        # Every included node retains its own permission ceiling. No copied
        # transcript from a disabled specialist is relabelled as root evidence.
        # Persist all participants, including nodes with no selected evidence.
        # Their actual duties and source authority must still be checked after
        # a reply is relayed or a team member's live reporting parent changes.
        contributors=[{'agent_id':node['agent_id'],'session_id':node['session_id']} for node in nodes]
        eligible_nodes=set()
        allowed_rows=[]
        scopes=set(access.write_scopes)
        # Source authority is independent of whether the querying agent supplies
        # learning material. Excluded contributions must not erase KB limits.
        if knowledge_rows:
            scopes.intersection_update({'user_project'})
            for node in knowledge_contributors:
                node_access,_=await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,owner,
                    node['agent_id'],node['session_id'])
                scopes.intersection_update(node_access.write_scopes)
        for node in nodes:
            node_access,_=await resolve_agent_memory_access(self.storage,self.gateway,self.tenant,owner,node['agent_id'],node['session_id'])
            if not node_access.learning_enabled:
                continue
            node_rows=[r for r in rows if r['session_id']==node['session_id']]
            if node_rows or node['learning_request']:
                scopes.intersection_update(node_access.write_scopes)
                contributors.append({'agent_id':node['agent_id'],'session_id':node['session_id']})
                eligible_nodes.add(node['session_id'])
                allowed_rows.extend(node_rows)
        requests=[node for node in requests if node['session_id'] in eligible_nodes]
        if not requests:
            await asyncio.to_thread(self.journal.finish,self.tenant,run_id,learning_state='skipped')
            return
        access=replace(access,write_scopes=tuple(sorted(scopes)))
        requested_scopes={n['learning_request']['scope_type'] for n in requests if n['learning_request'].get('scope_type')}
        choices=list(requested_scopes) if requested_scopes else (['user_project','user'] if access.private else ['project'])
        scope=None
        for choice in choices:
            try:
                access.target(choice,write=True)
                scope=choice
                break
            except MemoryError:
                continue
        if scope is None or not allowed_rows:
            await asyncio.to_thread(self.journal.finish,self.tenant,run_id,learning_state='skipped')
            return
        # A bounded canonical packet is assembled from persisted sources. Any
        # unselected evidence is neither sent to the model nor claimed as cited.
        priorities={'explicit':0,'correction':1,'recovery':2,'tool_failure':3,'repeated_pattern':4}
        request=min((n['learning_request'] for n in requests),key=lambda r:priorities.get(r['event_type'],99))
        event_type=request['event_type']
        related=[]
        related_source_refs=[]
        if event_type=='recovery' and not any(r['evidence'].get('outcome')=='error' for r in allowed_rows):
            successes=[r['evidence']['tool_name'] for r in allowed_rows if r['evidence'].get('outcome')=='success']
            failures=await asyncio.to_thread(self.learning.recent_failure_events,access,scope_type=scope,
                agent_id=root.agent_id,session_id=root.id,tool_names=successes)
            for previous in failures[:3]:
                try:
                    prior_access=await validate_learning_event(self.storage,self.gateway,self.tenant,previous)
                except MemoryError:
                    continue
                access=replace(access,write_scopes=tuple(sorted(set(access.write_scopes)&set(prior_access.write_scopes))))
                access.target(scope,write=True)
                provenance=previous['provenance']
                ref_by_id={ref.get('tool_call_id',ref['message_id']):ref for ref in provenance['source_refs']}
                for evidence in previous['evidence']:
                    if evidence['id'] in ref_by_id and evidence['id'] not in {r['evidence_id'] for r in allowed_rows}:
                        allowed_rows.append({'evidence_id':evidence['id'],'evidence':evidence,'source_ref':ref_by_id[evidence['id']]})
                contributors.extend(provenance['contributors'])
                # Permission-only references may intentionally have no learning
                # text, for example a querying node with learning disabled.
                related_source_refs.extend(provenance['source_refs'])
                related.append(str(previous['id']))
            if not related:
                if len(successes)>=3 and settings.learning_capture_patterns:
                    event_type='repeated_pattern'
                else:
                    await asyncio.to_thread(self.journal.finish,self.tenant,run_id,learning_state='skipped')
                    return
        selected=allowed_rows[:20]
        contributors=list({(node['agent_id'],node['session_id']):node for node in contributors}.values())
        source_refs=list({(ref['kind'],ref['session_id'],ref['message_id'],ref.get('tool_call_id')):ref
            for ref in [*[row['source_ref'] for row in [*selected,*knowledge_rows]],*related_source_refs]}.values())
        result=await asyncio.to_thread(self.learning.capture,access,scope_type=scope,agent_id=root.agent_id,
            session_id=root.id,config_owner=owner,event_key=digest([run_id,scope]),event_type=event_type,
            evidence=[r['evidence'] for r in selected],enqueue=request['enqueue'],
            fingerprint=digest([event_type,[r['evidence'].get('tool_name') for r in selected if r['evidence']['kind']=='tool']]),
            delay_seconds=settings.learning_cooldown_seconds,daily_limit=settings.learning_daily_job_limit,
            pattern_threshold=settings.learning_pattern_threshold,source_type='interaction',
            provenance={'run_id':run_id,'root_session_id':root.id,'root_agent_id':root.agent_id,
                'contributors':contributors,'source_refs':source_refs,'no_learning':False})
        await asyncio.to_thread(self.journal.finish,self.tenant,run_id,learning_state='done')

    async def scan(self, settings):
        for run in await asyncio.to_thread(self.journal.work,self.tenant):
            try:
                await self.process(run,settings)
            except MemoryError as exc:
                if exc.status==403:
                    await asyncio.to_thread(self.journal.finish,self.tenant,run['run_id'],cancelled=True,error=exc.code)
                else:
                    logger.warning('Memory run deferred: %s',exc.code)
            except Exception:
                logger.exception('Memory run finalization failed: %s',run['run_id'])
            finally:
                await asyncio.to_thread(self.journal.checked,self.tenant,run['run_id'])


async def run_memory_run_worker(service, settings_loader):
    while True:
        try:
            await service.scan(await settings_loader())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Memory run scan failed')
        await asyncio.sleep(2)
