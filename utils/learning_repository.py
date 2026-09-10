"""Evidence-backed learning; every publication and revision is transactional."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from .memory_repository import MemoryAccess, MemoryError, MemoryRepository, _public, learning_fingerprint

from .learning_validation import automatic_validation
from .learning_settings_guard import learning_sources, lock_learning_settings

LEARNED_TYPES = ('reflection','experience','skill')


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=255)
    kind: Literal['user','tool','task','memory','feedback','business_event']
    text: str = Field(min_length=1,max_length=4000)
    outcome: str = Field(default='',max_length=120)
    tool_name: str = Field(default='',max_length=255)


class LearningCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    memory_type: Literal['reflection','experience','skill']
    title: str = Field(min_length=1,max_length=160)
    content: str = Field(min_length=1,max_length=10000)
    conditions: str = Field(min_length=1,max_length=2000)
    limitations: str = Field(min_length=1,max_length=2000)
    evidence_ids: list[str] = Field(min_length=1,max_length=20)
    steps: list[str] = Field(default_factory=list,max_length=10)


class LearningOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1,max_length=2000)
    candidates: list[LearningCandidate] = Field(default_factory=list,max_length=3)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


class LearningRepository:
    def __init__(self, memories: MemoryRepository):
        self.memories = memories

    def capture(self, access: MemoryAccess, *, scope_type: str, agent_id: str, session_id: str,
                config_owner: str, event_key: str, event_type: str, evidence: list[dict],
                fingerprint: str = '', delay_seconds: int = 30, enqueue: bool = True,
                daily_limit: int = 30, pattern_threshold: int = 3,
                source_type: str = 'interaction', provenance: dict | None = None) -> dict:
        if not access.learning_enabled:
            raise MemoryError('learning_disabled','当前业务场景或本次请求不允许交互学习。',status=403)
        user,project = access.target(scope_type,write=True)
        validated = [Evidence.model_validate(e).model_dump() for e in evidence[:20]]
        if source_type not in {'interaction','group','business_event'}:
            raise MemoryError('invalid_learning_source','学习来源类型无效。')
        if not validated or not event_key or len(event_key)>255 or not session_id or (source_type == 'interaction' and not agent_id):
            raise MemoryError('invalid_learning_event','学习事件需要有效来源、智能体和会话。')
        fingerprint = fingerprint or _digest([event_type,[(e['kind'],e['text']) for e in validated]])
        with self.memories._connection() as conn:
            lock_learning_settings(conn, learning_sources({'config_owner':config_owner,
                'source_type':source_type,'provenance':provenance or {}}))
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(f'learning-budget:{access.tenant_id}:{source_type}:{agent_id}',))
            old = conn.execute('SELECT id FROM learning_events WHERE tenant_id=%s AND identity_type=%s AND agent_id=%s AND session_id=%s AND event_key=%s',
                (access.tenant_id,access.identity_type,agent_id,session_id,event_key)).fetchone()
            if old:
                job = conn.execute('SELECT id,state FROM learning_jobs WHERE event_id=%s',(old['id'],)).fetchone()
                if job is None and source_type == 'business_event' and enqueue and access.learning_enabled:
                    count = conn.execute('''SELECT count(*) AS n FROM learning_jobs j JOIN learning_events e ON e.id=j.event_id
                        WHERE e.tenant_id=%s AND e.agent_id=%s AND e.source_type=%s AND j.created_at>=date_trunc('day',now())''',
                        (access.tenant_id, agent_id, source_type)).fetchone()['n']
                    if count < daily_limit:
                        job = conn.execute('''INSERT INTO learning_jobs(id,event_id,available_at)
                            VALUES (%s,%s,now()+(%s * interval '1 second')) RETURNING id,state''',
                            (uuid4(), old['id'], max(0, delay_seconds))).fetchone()
                return {'event_id':str(old['id']),'job':_public(job) if job else None,'status':'unchanged'}
            row = conn.execute('''INSERT INTO learning_events
                (id,tenant_id,identity_type,scope_type,platform_user_id,project_id,agent_id,session_id,config_owner,event_key,event_type,evidence,fingerprint,access_snapshot,source_type,provenance)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (uuid4(),access.tenant_id,access.identity_type,scope_type,user,project,agent_id,session_id,config_owner,event_key,event_type,Jsonb(validated),fingerprint,Jsonb(asdict(access)),source_type,Jsonb(provenance or {}))).fetchone()
            n = conn.execute('''SELECT count(*) AS n FROM learning_jobs j JOIN learning_events e ON e.id=j.event_id
                WHERE e.tenant_id=%s AND e.agent_id=%s AND e.source_type=%s AND j.created_at>=date_trunc('day',now())''',(access.tenant_id,agent_id,source_type)).fetchone()['n']
            job = None
            same=(access.tenant_id,access.identity_type,scope_type,user,project,agent_id,fingerprint,source_type)
            matching="e.tenant_id=%s AND e.identity_type=%s AND e.scope_type=%s AND e.platform_user_id=%s AND e.project_id=%s AND e.agent_id=%s AND e.fingerprint=%s AND e.source_type=%s"
            repeats=conn.execute(f"SELECT count(*) AS n FROM learning_events e WHERE {matching} AND e.created_at>now()-interval '30 days'",same).fetchone()['n']
            cooling=conn.execute(f'''SELECT 1 FROM learning_events e JOIN learning_jobs j ON e.id=j.event_id WHERE {matching}
                AND j.created_at>now()-(%s * interval '1 second') LIMIT 1''',(*same,max(delay_seconds,1))).fetchone()
            if event_type=='repeated_pattern' and repeats<pattern_threshold:
                enqueue=False
            if event_type!='explicit' and cooling:
                enqueue=False
            if enqueue and access.learning_enabled and n < daily_limit:
                job = conn.execute('''INSERT INTO learning_jobs(id,event_id,available_at) VALUES (%s,%s,now()+(%s * interval '1 second')) RETURNING id,state''',
                    (uuid4(),row['id'],max(0,delay_seconds))).fetchone()
            return {'event_id':str(row['id']),'job':_public(job) if job else None,
                    'status':'queued' if job else 'recorded','reason':None if job else '未自动排队：提炼开关、每日预算或触发条件未满足。'}

    def related_evidence(self, event: dict) -> list[dict]:
        # The root run already collected its evidence and provenance. Pulling
        # another event's text here would omit that event's current authorization.
        return list({e['id']:e for e in event['evidence']}.values())[-20:]

    def recent_failure_events(self, access: MemoryAccess, *, scope_type: str, agent_id: str,
                              session_id: str, tool_names: list[str]) -> list[dict]:
        """Return original unresolved failure events, including their source references.

        The caller must reauthorize each event before using any returned evidence.
        A later successful recovery settles only its matching tools.
        """
        if not access.learning_enabled:
            return []
        user,project=access.target(scope_type,write=True)
        with self.memories._connection() as conn:
            rows=conn.execute('''SELECT * FROM learning_events WHERE tenant_id=%s AND identity_type=%s
                AND scope_type=%s AND platform_user_id=%s AND project_id=%s AND agent_id=%s AND session_id=%s
                AND source_type='interaction' AND coalesce(provenance->>'run_id','')<>''
                AND jsonb_array_length(coalesce(provenance->'source_refs','[]'::jsonb))>0
                AND event_type IN ('tool_failure','recovery') AND created_at>now()-interval '1 day'
                ORDER BY created_at DESC,id DESC LIMIT 20''',
                (access.tenant_id,access.identity_type,scope_type,user,project,agent_id,session_id)).fetchall()
        remaining = set(tool_names)
        selected = {}
        for row in rows:
            for name in list(remaining):
                evidence = [e for e in row['evidence'] if e['kind']=='tool' and e.get('tool_name')==name]
                if row['event_type']=='recovery' and any(e.get('outcome')=='success' for e in evidence):
                    remaining.remove(name)
                elif any(e.get('outcome')=='error' for e in evidence):
                    selected[str(row['id'])] = _public(row)
                    remaining.remove(name)
            if not remaining:
                break
        return list(selected.values())

    def validate_sources(self, event: dict) -> None:
        """Derived results may not outlive revoked or revised source versions."""
        if event['event_type'] not in {'consolidate','skill_compile'}:
            return
        with self.memories._connection() as conn:
            self._validate_sources(conn,event)

    @staticmethod
    def _validate_sources(conn,event):
        if event['event_type'] not in {'consolidate','skill_compile'}:
            return
        keys=('tenant_id','identity_type','scope_type','platform_user_id','project_id')
        for evidence in sorted(event['evidence'],key=lambda e:e['id']):
            if evidence['kind']!='memory':
                continue
            _,mid,version=evidence['id'].split(':')
            row=conn.execute('SELECT * FROM memory_records WHERE id=%s FOR SHARE',(UUID(mid),)).fetchone()
            if not row or row['status']!='active' or row['learning'].get('validation_state')!='verified' or row['version']!=int(version[1:]) or any(row[k]!=event[k] for k in keys):
                raise MemoryError('learning_source_changed','来源经验已修改、停用或调整归属，请重新选择当前版本复盘。',status=403)

    def claim(self, tenant_id: str, *, enabled_sources=('interaction', 'business_event', 'group')) -> dict | None:
        with self.memories._connection() as conn:
            conn.execute('''UPDATE learning_jobs j SET state='failed',error_code='lease_expired',lease_id=NULL,lease_until=NULL,
                finished_at=now(),updated_at=now() FROM learning_events e WHERE j.event_id=e.id AND e.tenant_id=%s
                AND j.state='running' AND j.lease_until<now() AND j.attempts>=3''',(tenant_id,))
            row = conn.execute('''WITH next_job AS (SELECT j.id FROM learning_jobs j JOIN learning_events e ON e.id=j.event_id
                WHERE e.tenant_id=%s AND e.source_type=ANY(%s) AND ((j.state='pending' AND j.available_at<=now()) OR (j.state='failed' AND j.updated_at<now()-interval '1 day') OR (j.state='running' AND j.lease_until<now()))
                ORDER BY j.available_at FOR UPDATE OF j SKIP LOCKED LIMIT 1)
                UPDATE learning_jobs j SET state='running',attempts=attempts+1,lease_id=%s,lease_until=now()+interval '5 minutes',
                started_at=now(),updated_at=now() FROM next_job n WHERE j.id=n.id RETURNING j.*''',(tenant_id,list(enabled_sources),uuid4())).fetchone()
            if row:
                row['event'] = conn.execute('SELECT * FROM learning_events WHERE id=%s',(row['event_id'],)).fetchone()
            return row

    @staticmethod
    def _lease(conn, job):
        current = conn.execute('SELECT * FROM learning_jobs WHERE id=%s FOR UPDATE',(job['id'],)).fetchone()
        return current if current and current['state']=='running' and current['lease_id']==job['lease_id'] else None

    def fail(self, job: dict, code: str, *, cancelled: bool = False) -> bool:
        with self.memories._connection() as conn:
            row = self._lease(conn,job)
            if not row:
                return False
            state = 'cancelled' if cancelled else 'failed' if row['attempts']>=3 else 'pending'
            conn.execute('''UPDATE learning_jobs SET state=%s,error_code=%s,lease_id=NULL,lease_until=NULL,
                available_at=now()+(%s * interval '1 second'),updated_at=now() WHERE id=%s''',
                (state,code[:300],min(300,20*2**min(row['attempts'],5)),job['id']))
            return True

    def defer(self, job: dict, code: str) -> bool:
        with self.memories._connection() as conn:
            if not self._lease(conn, job):
                return False
            conn.execute('''UPDATE learning_jobs SET state='pending',attempts=greatest(0,attempts-1),
                error_code=%s,lease_id=NULL,lease_until=NULL,available_at=now()+interval '5 seconds',
                updated_at=now() WHERE id=%s''', (code[:300], job['id']))
            return True

    def complete(self, job: dict, access: MemoryAccess, output: LearningOutput) -> dict:
        if not access.learning_enabled:
            raise MemoryError('learning_disabled','提炼权限已停用。',status=403)
        with self.memories._connection() as conn:
            # Source identity and every original contributor come from the
            # persisted job, not its mutable model-execution snapshot.
            event = conn.execute('''SELECT e.* FROM learning_events e JOIN learning_jobs j ON j.event_id=e.id
                WHERE j.id=%s FOR SHARE OF e''', (job['id'],)).fetchone()
            if not event:
                return {'status':'stale'}
            lock_learning_settings(conn, learning_sources(event))
            user,project = access.target(event['scope_type'],write=True)
            if (access.tenant_id,access.identity_type,user,project)!=(event['tenant_id'],event['identity_type'],event['platform_user_id'],event['project_id']):
                raise MemoryError('learning_scope_changed','学习事件的当前权限或归属已经改变。',status=403)
            evidence_ids = {e['id'] for e in event['evidence']}
            for candidate in output.candidates:
                if not candidate.content.strip() or not candidate.title.strip():
                    raise MemoryError('invalid_content','学习内容和标题不能为空。')
                if not set(candidate.evidence_ids)<=evidence_ids:
                    raise MemoryError('invented_evidence','学习结果引用了不存在的证据。')
                if not any(e['id'] in candidate.evidence_ids and e.get('outcome') != 'assistant_claim' for e in event['evidence']):
                    raise MemoryError('insufficient_evidence','助手自己说过的话不能单独证明学习成果。')
                if candidate.memory_type=='skill' and (not candidate.steps or any(len(s)>2000 for s in candidate.steps)):
                    raise MemoryError('invalid_skill','技能需要有界的明确步骤。')
            results = []
            # One owner lock across all jobs makes candidate dedup deterministic.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(_digest([event['tenant_id'],event['identity_type'],event['scope_type'],user,project]),))
            if not self._lease(conn,job):
                return {'status':'stale'}
            self._validate_sources(conn,event)
            for candidate in output.candidates:
                fingerprint = learning_fingerprint(candidate.memory_type,candidate.content,candidate.model_dump())
                existing = conn.execute('''SELECT * FROM memory_records WHERE tenant_id=%s AND identity_type=%s AND scope_type=%s
                    AND platform_user_id=%s AND project_id=%s AND origin='learning' AND learning->>'fingerprint'=%s
                    ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END LIMIT 1''',
                    (event['tenant_id'],event['identity_type'],event['scope_type'],user,project,fingerprint)).fetchone()
                if existing:
                    results.append({'memory_id':str(existing['id']),'status':'suppressed' if existing['status'] in {'inactive','deleted'} else 'duplicate'})
                    continue
                detail = candidate.model_dump(exclude={'content','memory_type'})
                detail.update({'fingerprint':fingerprint,'validation_state':'unverified','event_id':str(event['id']),
                               'job_id':str(job['id']),'reason':output.reason,'evidence':event['evidence']})
                detail = automatic_validation(candidate.memory_type, detail)
                row = conn.execute('''INSERT INTO memory_records
                    (id,tenant_id,identity_type,scope_type,platform_user_id,project_id,content,memory_type,status,source,created_by,origin,learning)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,'learning',%s) RETURNING *''',
                    (uuid4(),event['tenant_id'],event['identity_type'],event['scope_type'],user,project,candidate.content.strip(),candidate.memory_type,
                     Jsonb({'kind':'learning','event_id':str(event['id']),'session_id':event['session_id'],'agent_id':event['agent_id']}),
                     f"learning:{event['agent_id']}" if event['source_type']=='interaction' else f"system:{event['source_type']}",Jsonb(detail))).fetchone()
                business_sources = [source['provenance']['business_source'] for source in
                    [event, *event['provenance'].get('derived_sources', [])] if source['source_type'] == 'business_event']
                if business_sources:
                    original = business_sources[0]
                    source = {'kind':'business_learning','event_id':str(event['id']),
                        'source_id':str(original['id']), 'source_ids':sorted({str(s['id']) for s in business_sources}),
                        'source_key':original['source_key'],'source_version':original['source_version'],
                        'project_shared':all(s['project_shared'] for s in business_sources),
                        'audience':sorted(set.intersection(*(set(s['audience_user_ids']) for s in business_sources)))}
                    row = conn.execute('UPDATE memory_records SET source=%s WHERE id=%s RETURNING *', (Jsonb(source), row['id'])).fetchone()
                if event['source_type'] == 'group':
                    batch = conn.execute('SELECT channel_id FROM group_learning_batches WHERE id=%s AND tenant_id=%s',
                        (UUID(event['provenance']['batch_id']), event['tenant_id'])).fetchone()
                    if not batch:
                        raise MemoryError('source_missing', '群聊来源批次不存在。', status=403)
                    source = {'kind': 'group_learning', 'channel_id': str(batch['channel_id']),
                         'batch_id': event['provenance']['batch_id'], 'project_shared': event['scope_type']=='project', 'event_id': str(event['id'])}
                    source_audiences = []
                    for evidence in event['evidence']:
                        if evidence['kind'] == 'memory':
                            original = conn.execute('SELECT source FROM memory_records WHERE id=%s',
                                (UUID(evidence['id'].split(':')[1]),)).fetchone()
                            if original:
                                source_audiences.append(set(original['source'].get('audience', [])))
                    if not source_audiences:
                        raise MemoryError('source_missing', '群聊派生成果缺少原始受众证据。', status=403)
                    source['audience'] = sorted(set.intersection(*source_audiences))
                    row = conn.execute('UPDATE memory_records SET source=%s WHERE id=%s RETURNING *', (Jsonb(source), row['id'])).fetchone()
                    for evidence in event['evidence']:
                        if evidence['kind']=='memory':
                            source_id = UUID(evidence['id'].split(':')[1])
                            conn.execute('''INSERT INTO group_learning_sources(memory_id,tenant_id,channel_id,message_id,message_hash)
                                SELECT %s,tenant_id,channel_id,message_id,message_hash FROM group_learning_sources WHERE memory_id=%s
                                ON CONFLICT DO NOTHING''', (row['id'], source_id))
                self.memories._version(conn,row,access.actor,'learning_auto_publish')
                self.memories._queue(conn,row)
                results.append({'memory_id':str(row['id']),'status':'active'})
            result = {'reason':output.reason,'candidates':results}
            conn.execute('''UPDATE learning_jobs SET state=%s,result=%s,lease_id=NULL,lease_until=NULL,error_code=NULL,
                finished_at=now(),updated_at=now() WHERE id=%s''',('done' if results else 'skipped',Jsonb(result),job['id']))
            return result

    def review(self, access: MemoryAccess, memory_id: str, *, expected_version: int,
               action: str, note: str, content: str | None = None, conditions: str | None = None,
               limitations: str | None = None, steps: list[str] | None = None, restore_version: int | None = None) -> dict:
        if not access.management:
            raise MemoryError('forbidden','学习成果审核需要管理权限。',status=403)
        if action not in {'approve','reject','suspend','revise','rollback'} or not note.strip():
            raise MemoryError('invalid_review','请选择审核操作并填写验证依据或处理原因。')
        with self.memories._connection() as conn:
            row = conn.execute('SELECT * FROM memory_records WHERE id=%s FOR UPDATE',(UUID(memory_id),)).fetchone()
            if not row:
                raise MemoryError('not_found','学习成果不存在。',status=404)
            self.memories._check_record(access,row,write=True)
            if row['memory_type'] not in LEARNED_TYPES or row['status']=='deleted':
                raise MemoryError('invalid_review','只能审核未删除的学习成果。')
            if row['version']!=expected_version:
                raise MemoryError('version_conflict','版本已改变，请刷新后再审核。',status=409)
            detail = dict(row['learning'])
            new_content = content.strip() if content is not None else row['content']
            for key,value in [('conditions',conditions),('limitations',limitations),('steps',steps)]:
                if value is not None:
                    detail[key]=value
            if action=='rollback':
                old = conn.execute('SELECT snapshot FROM memory_versions WHERE memory_id=%s AND version=%s',(row['id'],restore_version)).fetchone()
                if not old:
                    raise MemoryError('invalid_version','回滚目标版本不存在。')
                snapshot = old['snapshot']
                if any(snapshot[k]!=row[k] for k in ('scope_type','platform_user_id','project_id','identity_type')):
                    raise MemoryError('scope_mismatch','不能通过版本回滚改变归属或发布私人内容。')
                new_content = snapshot['content']
                detail = dict(snapshot.get('learning',{}))
            if not 1<=len(new_content)<=16000:
                raise MemoryError('invalid_content','学习正文长度无效。')
            if any(not isinstance(s,str) or not s.strip() or len(s)>2000 for s in detail.get('steps',[])) or len(detail.get('steps',[]))>10:
                raise MemoryError('invalid_skill','技能最多 10 步，每步须为 1–2000 字的明确内容。')
            if action=='approve' and (not detail.get('conditions') or not detail.get('limitations') or
                (row['memory_type']=='skill' and not detail.get('steps'))):
                raise MemoryError('validation_required','启用前须填写适用条件、限制以及技能操作步骤。')
            state = {'approve':'verified','reject':'rejected','suspend':'suspended','revise':'unverified','rollback':'unverified'}[action]
            detail['fingerprint']=learning_fingerprint(row['memory_type'],new_content,detail)
            detail.update({'validation_state':state,'review_note':note.strip()[:4000],'reviewed_by':access.actor,
                           'reviewed_at':datetime.now(timezone.utc).isoformat()})
            if action=='approve':
                # Maintenance uses the live platform review interval.
                detail.pop('review_due_at',None)
            status = 'active' if action=='approve' else 'inactive' if action in {'reject','suspend'} else 'candidate'
            row = conn.execute('''UPDATE memory_records SET content=%s,learning=%s,status=%s,version=version+1,updated_at=now(),
                embedding=NULL,indexed_version=NULL,index_status='pending' WHERE id=%s RETURNING *''',
                (new_content,Jsonb(detail),status,row['id'])).fetchone()
            self.memories._version(conn,row,access.actor,f'learning_{action}')
            self.memories._queue(conn,row)
            return _public(row)

    def feedback(self, access: MemoryAccess, memory_id: str, *, expected_version: int, outcome: str,
                 evidence: str, request_id: str) -> dict:
        if not access.learning_enabled:
            raise MemoryError('learning_disabled','当前业务场景或本次请求不允许记录学习反馈。',status=403)
        if outcome not in {'success','failure','irrelevant'} or not evidence.strip() or len(evidence)>4000 or not request_id:
            raise MemoryError('invalid_feedback','反馈需要结果类型、证据和请求标识。')
        with self.memories._connection() as conn:
            row = conn.execute('SELECT * FROM memory_records WHERE id=%s FOR UPDATE',(UUID(memory_id),)).fetchone()
            if not row:
                raise MemoryError('not_found','学习成果不存在。',status=404)
            self.memories._check_record(access,row)
            if row['version']!=expected_version or row['status']!='active':
                raise MemoryError('version_conflict','该成果已变化或停用，请刷新。',status=409)
            if row['memory_type'] not in LEARNED_TYPES:
                raise MemoryError('invalid_feedback','普通记忆请通过纠正更新。')
            saved = conn.execute('''INSERT INTO learning_feedback(id,memory_id,memory_version,actor_id,outcome,evidence,request_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(memory_id,actor_id,request_id) DO NOTHING RETURNING id''',
                (uuid4(),row['id'],expected_version,access.actor,outcome,evidence.strip(),request_id)).fetchone()
            return {'status':'recorded' if saved else 'unchanged'}

    def used(self, access: MemoryAccess, records: list[dict]) -> None:
        where,params = self.memories._where(access)
        ids=[UUID(r['id']) for r in records if r['memory_type'] in LEARNED_TYPES]
        if ids:
            with self.memories._connection() as conn:
                conn.execute(f"UPDATE memory_records SET last_used_at=now(),use_count=use_count+1 WHERE {where} AND id=ANY(%s) AND status='active'",[*params,ids])

    def dashboard(self, access: MemoryAccess, *, offset=0, limit=30, state=None) -> dict:
        if not access.management:
            raise MemoryError('forbidden','学习审计需要管理权限。',status=403)
        with self.memories._connection() as conn:
            params=[access.tenant_id]
            where='e.tenant_id=%s'
            if state=='recorded':
                where+=' AND j.id IS NULL'
            elif state:
                where+=' AND j.state=%s';params.append(state)
            rows=conn.execute(f'''SELECT e.*,j.id AS job_id,j.state,j.attempts,j.error_code,j.result,j.updated_at,j.available_at
                FROM learning_events e LEFT JOIN learning_jobs j ON e.id=j.event_id WHERE {where}
                ORDER BY e.created_at DESC LIMIT %s OFFSET %s''',[*params,min(max(limit,1),100),max(offset,0)]).fetchall()
            total=conn.execute(f'SELECT count(*) AS n FROM learning_events e LEFT JOIN learning_jobs j ON e.id=j.event_id WHERE {where}',params).fetchone()['n']
            counts=conn.execute('''SELECT coalesce(j.state,'recorded') AS state,count(*) AS count FROM learning_events e
                LEFT JOIN learning_jobs j ON j.event_id=e.id WHERE e.tenant_id=%s GROUP BY 1''',(access.tenant_id,)).fetchall()
            return {'events':[_public(r) for r in rows],'total':total,'counts':counts}

    def job_action(self, access: MemoryAccess, event_id: str, action: str) -> dict:
        if not access.management or action not in {'retry','cancel'}:
            raise MemoryError('forbidden','需要有效的管理操作。',status=403)
        with self.memories._connection() as conn:
            event=conn.execute('SELECT * FROM learning_events WHERE id=%s AND tenant_id=%s FOR UPDATE',(UUID(event_id),access.tenant_id)).fetchone()
            if not event:
                raise MemoryError('not_found','学习事件不存在。',status=404)
            job=conn.execute('SELECT * FROM learning_jobs WHERE event_id=%s FOR UPDATE',(event['id'],)).fetchone()
            if action=='cancel':
                if job:
                    conn.execute("UPDATE learning_jobs SET state='cancelled',lease_id=NULL,lease_until=NULL,updated_at=now() WHERE id=%s",(job['id'],))
                return {'status':'cancelled'}
            if job and job['state'] in {'running','pending','done','skipped'}:
                raise MemoryError('job_not_retryable','只重试失败、取消或未排队事件；已完成事件请另建复盘。',status=409)
            conn.execute('''INSERT INTO learning_jobs(id,event_id) VALUES (%s,%s) ON CONFLICT(event_id) DO UPDATE SET
                state='pending',attempts=0,available_at=now(),lease_id=NULL,lease_until=NULL,error_code=NULL,updated_at=now()''',(uuid4(),event['id']))
            return {'status':'pending'}

    def feedback_history(self, access: MemoryAccess, memory_id: str) -> list[dict]:
        if not access.management:
            raise MemoryError('forbidden','反馈证据仅供管理审计。',status=403)
        self.memories.get(access,memory_id)
        with self.memories._connection() as conn:
            return [_public(r) for r in conn.execute('SELECT * FROM learning_feedback WHERE memory_id=%s ORDER BY created_at DESC LIMIT 100',(UUID(memory_id),)).fetchall()]

    def derive(self, access: MemoryAccess, memory_ids: list[str], *, action: str, note: str, event_key: str | None=None,
               daily_limit: int=30) -> dict:
        if not access.management or action not in {'consolidate','skill_compile'}:
            raise MemoryError('forbidden','需要管理权限和有效的提炼动作。',status=403)
        if not 1<=len(memory_ids)<=10 or not note.strip():
            raise MemoryError('invalid_request','请选择 1–10 条成果并说明复盘目标。')
        records=[self.memories.get(access,mid) for mid in dict.fromkeys(memory_ids)]
        first=records[0]
        group_sources = [r.get('source', {}) for r in records if r.get('source', {}).get('kind') == 'group_learning']
        if group_sources and (len(group_sources) != len(records) or len({s.get('channel_id') for s in group_sources}) != 1):
            raise MemoryError('group_scope_mismatch', '群聊成果只能在同一来源群内合并，避免跨群传播私人内容。')
        keys=('tenant_id','identity_type','scope_type','platform_user_id','project_id')
        if any(any(row[k]!=first[k] for k in keys) or row['status']!='active' or row['learning'].get('validation_state')!='verified' or row['memory_type'] not in LEARNED_TYPES for row in records):
            raise MemoryError('scope_mismatch','只能合并同一抽屉、同一归属下已启用的学习成果。')
        with self.memories._connection() as conn:
            source_events = [conn.execute('SELECT * FROM learning_events WHERE id=%s AND tenant_id=%s',
                (UUID(record['learning']['event_id']),access.tenant_id)).fetchone() for record in records]
        if any(event is None for event in source_events):
            raise MemoryError('source_missing','原始学习来源不存在。')
        event = source_events[0]
        derived_sources = {}
        source_fields = ('tenant_id','identity_type','scope_type','platform_user_id','project_id','agent_id',
            'session_id','config_owner','source_type','access_snapshot','provenance')
        for source_event in source_events:
            sources = source_event['provenance'].get('derived_sources') or [source_event]
            for source_event in sources:
                item = {key:source_event[key] for key in source_fields}
                item['provenance'] = {k:v for k,v in item['provenance'].items() if k != 'derived_sources'}
                derived_sources[_digest(item)] = item
        if len(derived_sources) > 50:
            raise MemoryError('source_limit', '合并的原始来源过多，请拆分处理。')
        source_access=MemoryAccess(**event['access_snapshot'])
        if source_access.target(first['scope_type'],write=True)!=(first['platform_user_id'],first['project_id']):
            raise MemoryError('learning_scope_changed','归属已改变，原始会话无法代表当前归属发起学习；请从当前归属会话重新复盘。',status=403)
        evidence=[{'id':f"memory:{r['id']}:v{r['version']}",'kind':'memory',
            'text':json.dumps({'content':r['content'],'conditions':r['learning'].get('conditions'),'limitations':r['learning'].get('limitations')},ensure_ascii=False)[:4000],
            'outcome':'reviewed'} for r in records]
        evidence.append({'id':'review:'+str(uuid4()),'kind':'user','text':note.strip()[:4000],'outcome':'management_request'})
        return self.capture(source_access,scope_type=first['scope_type'],agent_id=event['agent_id'],
            session_id=event['session_id'],config_owner=event['config_owner'],event_key=event_key or str(uuid4()),event_type=action,
            evidence=evidence,delay_seconds=0,daily_limit=daily_limit,
            source_type=event['source_type'],provenance={**event['provenance'],'derived_sources':list(derived_sources.values())})

    def export_document(self,access: MemoryAccess,memory_id: str) -> dict:
        if not access.management:
            raise MemoryError('forbidden','导出学习文档需要管理权限。',status=403)
        row=self.memories.get(access,memory_id)
        if row['memory_type'] not in LEARNED_TYPES or row['status']!='active' or row['learning'].get('validation_state')!='verified':
            raise MemoryError('review_required','只能导出已审核启用的学习成果。')
        detail=row['learning']
        title=detail.get('title') or '学习成果'
        sections=[f'# {title}',row['content'],'## 适用条件',detail.get('conditions',''),'## 限制与反例',detail.get('limitations','')]
        if detail.get('steps'):
            sections+=['## 操作步骤','\n'.join(f'{i+1}. {step}' for i,step in enumerate(detail['steps']))]
        sections += ['## 版本',f"记录 {row['id']} · 版本 {row['version']} · 抽屉 {row['scope_type']}",
                     '此文档是人工发布材料，不包含原始私人对话；导出不代表已同步到外部知识库。']
        return {'filename':f"learning-{row['id']}-v{row['version']}.md",'content':'\n\n'.join(sections)}

    def maintain(self, tenant_id: str, *, review_days=90, consolidate=False, daily_limit=30) -> dict:
        """Flag aging learned content and counterexamples; never erase explicit facts."""
        with self.memories._connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'learning-maintenance:{tenant_id}',))
            recent=conn.execute("SELECT 1 FROM learning_maintenance WHERE tenant_id=%s AND last_run_at>now()-interval '1 hour'",(tenant_id,)).fetchone()
            if recent:
                return {'skipped':True}
            rows=conn.execute('''SELECT r.* FROM memory_records r WHERE tenant_id=%s AND memory_type IN ('reflection','experience','skill')
                AND status='active' AND (coalesce((learning->>'reviewed_at')::timestamptz,updated_at)<now()-(%s * interval '1 day') OR EXISTS
                    (SELECT 1 FROM learning_feedback f WHERE f.memory_id=r.id AND f.memory_version=r.version AND f.outcome='failure'))
                AND learning->>'validation_state' IS DISTINCT FROM 'review_due' FOR UPDATE''',(tenant_id,review_days)).fetchall()
            for row in rows:
                failed = conn.execute("SELECT 1 FROM learning_feedback WHERE memory_id=%s AND memory_version=%s AND outcome='failure' LIMIT 1", (row['id'],row['version'])).fetchone()
                detail={**row['learning'],'validation_state':'contradicted' if failed else 'review_due','review_due_at':datetime.now(timezone.utc).isoformat()}
                if failed:
                    detail['review_note']='实际使用出现反例，系统自动停用；后续新证据可重新学习。'
                    changed=conn.execute("UPDATE memory_records SET learning=%s,status='inactive',version=version+1,updated_at=now(),embedding=NULL,indexed_version=NULL,index_status='pending' WHERE id=%s RETURNING *",(Jsonb(detail),row['id'])).fetchone()
                    self.memories._version(conn,changed,'system','learning_auto_suspend')
                    self.memories._queue(conn,changed)
                else:
                    conn.execute('UPDATE memory_records SET learning=%s WHERE id=%s',(Jsonb(detail),row['id']))
                # A review flag is operational metadata, not a new fact or approval.
            groups=conn.execute('''SELECT identity_type,scope_type,platform_user_id,project_id FROM memory_records
                WHERE tenant_id=%s AND status='active' AND memory_type IN ('reflection','experience') AND learning->>'validation_state'='verified'
                GROUP BY identity_type,scope_type,platform_user_id,project_id HAVING count(*)>=3 LIMIT 20''',(tenant_id,)).fetchall() if consolidate else []
            batches=[]
            for group in groups:
                batch=conn.execute('''SELECT id,version FROM memory_records WHERE tenant_id=%s AND identity_type=%s AND scope_type=%s
                    AND platform_user_id=%s AND project_id=%s AND status='active' AND memory_type IN ('reflection','experience') AND learning->>'validation_state'='verified'
                    ORDER BY updated_at DESC LIMIT 10''',(tenant_id,*[group[k] for k in ('identity_type','scope_type','platform_user_id','project_id')])).fetchall()
                batches.append(batch)
            result={'review_due':len(rows),'consolidation_groups':len(batches)}
            conn.execute('''INSERT INTO learning_maintenance(tenant_id,result) VALUES (%s,%s)
                ON CONFLICT(tenant_id) DO UPDATE SET last_run_at=now(),result=excluded.result''',(tenant_id,Jsonb(result)))
        # New jobs are queued outside the maintenance transaction; IDs/versions
        # determine the request key so the same source set is never reprocessed.
        queued=0
        for batch in batches:
            try:
                response=self.derive(MemoryAccess(tenant_id,'maintenance',management=True),[str(r['id']) for r in batch],
                    action='consolidate',note='周期复盘：对照同一归属下的已验证经验，提炼共性、反例和可复用操作方法；没有新价值则跳过。',
                    event_key='auto-consolidate:'+_digest(sorted(batch,key=lambda r:str(r['id']))),daily_limit=daily_limit)
                queued+=response['status']=='queued'
            except MemoryError:
                continue
        return {**result,'queued':queued}

    def automatic_check_queue(self, tenant_id: str) -> list[dict]:
        with self.memories._connection() as conn:
            return conn.execute('''SELECT r.*,to_jsonb(e.*) AS event FROM memory_records r
                LEFT JOIN learning_events e ON e.id::text=r.learning->>'event_id' AND e.tenant_id=r.tenant_id
                WHERE r.tenant_id=%s AND (r.status='candidate' OR
                    (r.status='active' AND r.learning->>'validation_state'='review_due'))
                AND coalesce((r.learning->>'auto_check_after')::double precision,0)<extract(epoch FROM now())
                ORDER BY r.updated_at,r.id LIMIT 30''',(tenant_id,)).fetchall()

    def finish_automatic_check(self, snapshot: dict, access: MemoryAccess | None, *, error: str = '') -> bool:
        with self.memories._connection() as conn:
            if not error and snapshot['status'] == 'candidate':
                event=conn.execute('''SELECT e.* FROM learning_events e JOIN memory_records r
                    ON r.learning->>'event_id'=e.id::text WHERE r.id=%s FOR SHARE OF e''', (snapshot['id'],)).fetchone()
                if not event:
                    raise MemoryError('source_missing','学习候选的原始来源不存在。',status=403)
                lock_learning_settings(conn, learning_sources(event))
            row=conn.execute('SELECT * FROM memory_records WHERE id=%s FOR UPDATE',(snapshot['id'],)).fetchone()
            if not row or row['version']!=snapshot['version'] or row['status'] not in {'active','candidate'}:
                return False
            detail=dict(row['learning'])
            if not error:
                if access is None or (row['status'] == 'candidate' and not access.learning_enabled):
                    raise MemoryError('learning_disabled','后台学习权限已撤销。',status=403)
                self.memories._check_record(access,row,write=True)
                event=snapshot['event']
                self._validate_sources(conn,event)
                if any(row[k]!=event[k] for k in ('tenant_id','identity_type','scope_type','platform_user_id','project_id')):
                    raise MemoryError('learning_scope_changed','候选归属与来源不一致。',status=403)
                detail=automatic_validation(row['memory_type'],detail)
                if conn.execute("SELECT 1 FROM learning_feedback WHERE memory_id=%s AND memory_version=%s AND outcome='failure'",(row['id'],row['version'])).fetchone():
                    error='contradicted'
            if error:
                detail.update(validation_state='source_changed' if error in {'group_source_changed','learning_source_changed'} else 'auto_rejected',
                    review_note='系统自动停用：'+error, validation_method='automatic_v1')
            detail.pop('review_due_at',None)
            detail.pop('auto_check_after',None)
            changed=conn.execute('''UPDATE memory_records SET status=%s,learning=%s,version=version+1,updated_at=now(),
                embedding=NULL,indexed_version=NULL,index_status='pending' WHERE id=%s RETURNING *''',
                ('inactive' if error else 'active',Jsonb(detail),row['id'])).fetchone()
            self.memories._version(conn,changed,'system','learning_auto_reject' if error else 'learning_auto_publish')
            self.memories._queue(conn,changed)
            return True

    def defer_automatic_check(self, row: dict, code: str):
        with self.memories._connection() as conn:
            conn.execute('''UPDATE memory_records SET learning=learning || jsonb_build_object(
                'auto_check_after',extract(epoch FROM now()+interval '5 minutes'),'auto_check_error',%s::text)
                WHERE id=%s AND version=%s AND status IN ('active','candidate')''',(code[:200],row['id'],row['version']))
