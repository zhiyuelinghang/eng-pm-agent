"""One atomic commit for group results, source links, batch status and cursor."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from .learning_repository import _digest
from .learning_validation import automatic_validation
from .learning_settings_guard import LearningPaused, lock_learning_settings
from .memory_repository import MemoryAccess, MemoryError, _public, learning_fingerprint


class GroupCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    memory_type: Literal['fact', 'preference', 'decision', 'reference', 'reflection', 'experience', 'skill']
    target: Literal['conversation', 'personal', 'member']
    user_id: str = ''
    topic_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=10000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    conditions: str = Field(default='', max_length=2000)
    limitations: str = Field(default='', max_length=2000)
    steps: list[str] = Field(default_factory=list, max_length=10)
    existing_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)


class GroupOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=2000)
    candidates: list[GroupCandidate] = Field(default_factory=list, max_length=10)


def candidate_targets(candidate, snapshot):
    by_id = {m['id']: m for m in snapshot['messages'] if not m.get('deleted')}
    if not set(candidate.evidence_ids) <= by_id.keys():
        raise MemoryError('invented_evidence', '群聊成果引用了不存在的证据。')
    evidence = [by_id[mid] for mid in candidate.evidence_ids]
    if not any(m.get('kind') != 'agent' for m in evidence) or not any(not m.get('context_only') for m in evidence):
        raise MemoryError('insufficient_evidence', '必须引用本批新证据；助手自述不能独立证明结论。')
    audience = set(snapshot['members'])
    for item in evidence:
        audience &= set(item['audience'])
    project = snapshot['project_id']
    if candidate.target == 'personal':
        if candidate.memory_type != 'preference' or candidate.topic_key not in {'profile.address', 'preference.response_detail'}:
            raise MemoryError('personal_scope_invalid', '自动跨项目记忆仅接受本人明确称呼和回答偏好。')
        if not candidate.user_id or any(m['kind'] != 'user' or m['user_id'] != candidate.user_id for m in evidence):
            raise MemoryError('speaker_mismatch', '个人偏好必须完全来自本人发言。')
        return [('user', candidate.user_id, '')], evidence
    if candidate.target == 'member':
        if candidate.user_id not in audience:
            raise MemoryError('audience_mismatch', '个人项目记忆的归属者必须能看到全部来源证据。')
        return [('user_project', candidate.user_id, project)], evidence
    if snapshot['full_project'] and all(m['project_shared'] for m in evidence):
        return [('project', '', project)], evidence
    return [('user_project', uid, project) for uid in sorted(audience)], evidence


class GroupLearningRepository:
    def __init__(self, memories):
        self.memories = memories

    def observe(self, tenant_id, channel):
        with self.memories._connection() as conn:
            row = conn.execute('''INSERT INTO group_learning_cursors(tenant_id,channel_id,project_id,title,observed_revision,last_scan_at)
                VALUES(%s,%s,%s,%s,%s,now()) ON CONFLICT(tenant_id,channel_id) DO UPDATE SET
                observed_revision=excluded.observed_revision,last_scan_at=now(),title=excluded.title RETURNING *''',
                (tenant_id, channel['channel_id'], str(channel.get('project_id') or ''), channel.get('title') or '已删除群聊', channel['revision'])).fetchone()
            return _public(row)

    def enqueue(self, tenant_id, snapshot, *, config_owner, daily_limit):
        with self.memories._connection() as conn:
            lock_learning_settings(conn, {(config_owner, 'group')})
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'group-budget:{tenant_id}',))
            cursor = conn.execute('SELECT * FROM group_learning_cursors WHERE tenant_id=%s AND channel_id=%s FOR UPDATE',
                (tenant_id, snapshot['channel_id'])).fetchone()
            if not cursor or cursor['paused'] or cursor['cursor'] != snapshot['from_revision'] or snapshot['to_revision'] <= cursor['cursor']:
                return None
            if conn.execute("SELECT 1 FROM group_learning_batches WHERE tenant_id=%s AND channel_id=%s AND state IN ('pending','running','failed')",
                (tenant_id, snapshot['channel_id'])).fetchone():
                return None
            count = conn.execute("SELECT count(*) AS n FROM group_learning_batches WHERE tenant_id=%s AND created_at>=date_trunc('day',now())", (tenant_id,)).fetchone()['n']
            if count >= daily_limit:
                conn.execute("UPDATE group_learning_cursors SET last_result=%s WHERE tenant_id=%s AND channel_id=%s",
                    (Jsonb({'reason': '已达每日群聊任务上限，未处理消息保留至下次。'}), tenant_id, snapshot['channel_id']))
                return None
            row = conn.execute('''INSERT INTO group_learning_batches(id,tenant_id,channel_id,from_revision,to_revision,snapshot,config_owner)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,channel_id,from_revision,to_revision) DO NOTHING RETURNING *''',
                (uuid4(), tenant_id, snapshot['channel_id'], snapshot['from_revision'], snapshot['to_revision'], Jsonb(snapshot), config_owner)).fetchone()
            return _public(row) if row else None

    def claim(self, tenant_id):
        with self.memories._connection() as conn:
            conn.execute("UPDATE group_learning_batches SET state='failed',error_code='lease_expired',lease_id=NULL,lease_until=NULL,available_at=now()+interval '1 day' WHERE tenant_id=%s AND state='running' AND lease_until<now() AND attempts>=3", (tenant_id,))
            return conn.execute('''WITH picked AS (SELECT b.id FROM group_learning_batches b JOIN group_learning_cursors c
                ON c.tenant_id=b.tenant_id AND c.channel_id=b.channel_id WHERE b.tenant_id=%s AND NOT c.paused
                AND ((b.state='pending' AND b.available_at<=now()) OR (b.state='failed' AND b.available_at<now()) OR (b.state='running' AND b.lease_until<now() AND b.attempts<3))
                ORDER BY b.available_at,b.created_at FOR UPDATE OF b SKIP LOCKED LIMIT 1)
                UPDATE group_learning_batches b SET state='running',attempts=attempts+1,lease_id=%s,lease_until=now()+interval '5 minutes'
                FROM picked WHERE b.id=picked.id RETURNING b.*''', (tenant_id, uuid4())).fetchone()

    def invalidation_progress(self, tenant_id, channel_id, revision):
        with self.memories._connection() as conn:
            conn.execute('UPDATE group_learning_cursors SET invalidation_cursor=greatest(invalidation_cursor,%s) WHERE tenant_id=%s AND channel_id=%s',
                (revision, tenant_id, channel_id))

    @staticmethod
    def _lease(conn, job):
        row = conn.execute('SELECT * FROM group_learning_batches WHERE id=%s FOR UPDATE', (job['id'],)).fetchone()
        return row if row and row['state'] == 'running' and str(row['lease_id']) == str(job['lease_id']) else None

    def replace_snapshot(self, job, snapshot):
        with self.memories._connection() as conn:
            if not self._lease(conn, job):
                return False
            conn.execute('UPDATE group_learning_batches SET snapshot=%s WHERE id=%s', (Jsonb(snapshot), job['id']))
            return True

    def fail(self, job, code):
        with self.memories._connection() as conn:
            row = self._lease(conn, job)
            if row:
                conn.execute('''UPDATE group_learning_batches SET state=%s,error_code=%s,lease_id=NULL,lease_until=NULL,
                    available_at=now()+(%s * interval '1 second') WHERE id=%s''',
                    ('failed' if row['attempts'] >= 3 else 'pending', str(code)[:300], 86400 if row['attempts'] >= 3 else 20 * 2 ** row['attempts'], job['id']))

    def defer(self, job, code):
        with self.memories._connection() as conn:
            if not self._lease(conn, job):
                return False
            conn.execute('''UPDATE group_learning_batches SET state='pending',attempts=greatest(0,attempts-1),
                error_code=%s,lease_id=NULL,lease_until=NULL,available_at=now()+interval '5 seconds'
                WHERE id=%s''', (str(code)[:300], job['id']))
            return True

    def existing(self, job):
        with self.memories._connection() as conn:
            rows = conn.execute('''SELECT id,version,scope_type,platform_user_id,project_id,memory_type,content,fact_key,learning,source,status
                FROM memory_records WHERE tenant_id=%s AND identity_type='business_user' AND
                ((source->>'kind'='group_learning' AND source->>'channel_id'=%s
                    AND (scope_type='project' OR ((source->'audience') ?& %s AND EXISTS(
                        SELECT 1 FROM memory_versions v WHERE v.memory_id=memory_records.id AND v.version=memory_records.version
                        AND v.actor_id='group_learning')))) OR
                    (%s AND scope_type='project' AND project_id=%s))
                ORDER BY updated_at DESC LIMIT 100''', (job['tenant_id'], str(job['channel_id']),
                    list(job['snapshot']['members']), job['snapshot']['full_project'], job['snapshot']['project_id'])).fetchall()
        return [_public(r) for r in rows]

    def invalidate(self, tenant_id, channel_id, *, changed_ids=None, policy=False):
        """Suspend stale conclusions before summarization, even when no model runs."""
        with self.memories._connection() as conn:
            rows = conn.execute('''SELECT DISTINCT r.* FROM memory_records r JOIN group_learning_sources s ON s.memory_id=r.id
                WHERE s.tenant_id=%s AND s.channel_id=%s AND r.status IN ('active','candidate')
                AND (%s OR s.message_id=ANY(%s))''', (tenant_id, channel_id, policy, list(changed_ids or []))).fetchall()
            for row in rows:
                current = conn.execute('SELECT * FROM memory_records WHERE id=%s FOR UPDATE', (row['id'],)).fetchone()
                detail = {**current['learning'], 'validation_state': 'source_changed', 'review_note': '来源消息或群可见范围已变化，停止召回。'}
                changed = conn.execute('''UPDATE memory_records SET status='inactive',learning=%s,version=version+1,updated_at=now(),
                    embedding=NULL,indexed_version=NULL WHERE id=%s RETURNING *''', (Jsonb(detail), row['id'])).fetchone()
                self.memories._version(conn, changed, 'group_learning', 'source_invalidated')
                self.memories._queue(conn, changed)

    def complete(self, job, output):
        with self.memories._connection() as conn:
            # Lock the batch once for the lease and its persisted owner/source.
            # Do not first take SHARE then upgrade: competing completions could
            # otherwise deadlock while one waits for the channel lock.
            job = self._lease(conn, job)
            if not job:
                return {'status': 'stale'}
            lock_learning_settings(conn, {(job['config_owner'], 'group')})
            snapshot = job['snapshot']
            plans = []
            for item in output.candidates:
                targets, evidence = candidate_targets(item, snapshot)
                if item.memory_type in {'reflection', 'experience', 'skill'} and (not item.conditions.strip() or not item.limitations.strip()):
                    raise MemoryError('learning_detail_required', '经验需要适用条件和限制。')
                if item.memory_type == 'skill' and (not item.steps or any(not s.strip() or len(s)>2000 for s in item.steps)):
                    raise MemoryError('invalid_skill', '操作技能需要明确、有界的步骤。')
                plans += [(item, target, evidence) for target in targets]
            results = []
            anchors = {}
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f"group-channel:{job['tenant_id']}:{job['channel_id']}",))
            cursor = conn.execute('SELECT * FROM group_learning_cursors WHERE tenant_id=%s AND channel_id=%s FOR UPDATE', (job['tenant_id'], job['channel_id'])).fetchone()
            if cursor['paused']:
                raise LearningPaused('此群聊的学习已暂停，待处理批次将在恢复后继续。')
            if cursor['cursor'] != job['from_revision']:
                raise MemoryError('cursor_changed', '群聊处理进度已经改变。')
            for item, (scope, user, project), evidence in plans:
                learned = item.memory_type in {'reflection', 'experience', 'skill'}
                key = item.topic_key if scope == 'user' else 'group.' + _digest([job['channel_id'], item.topic_key])[:40]
                fingerprint = learning_fingerprint(item.memory_type, item.content, item.model_dump())
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (_digest([job['tenant_id'], scope, user, project, key]),))
                row = conn.execute('''SELECT * FROM memory_records WHERE tenant_id=%s AND identity_type='business_user' AND scope_type=%s
                    AND platform_user_id=%s AND project_id=%s AND (fact_key=%s OR (source->>'kind'='group_learning'
                    AND source->>'channel_id'=%s AND learning->>'fingerprint'=%s)) ORDER BY updated_at DESC LIMIT 1 FOR UPDATE''',
                    (job['tenant_id'], scope, user, project, key, str(job['channel_id']), fingerprint)).fetchone()
                anchor = None
                if item.existing_id:
                    if item.existing_id not in anchors:
                        anchors[item.existing_id] = conn.execute('SELECT * FROM memory_records WHERE id=%s FOR UPDATE', (item.existing_id,)).fetchone()
                    anchor = anchors[item.existing_id]
                    if not anchor or (anchor['tenant_id'],anchor['identity_type'],anchor['scope_type'],anchor['project_id']) != (job['tenant_id'],'business_user',scope,project):
                        raise MemoryError('existing_scope_mismatch', '更新目标必须属于相同租户与抽屉。')
                    if anchor['source'].get('kind') == 'group_learning' and anchor['source'].get('channel_id') != str(job['channel_id']):
                        raise MemoryError('existing_source_mismatch', '不能更新其他群来源的私人记忆。')
                    if anchor['platform_user_id'] == user and not row:
                        row = anchor
                    elif anchor['platform_user_id'] != user and item.target != 'conversation':
                        raise MemoryError('existing_owner_mismatch', '不能用他人的记忆版本更新个人资料。')
                # Explicit direct writes remain authoritative; automatic collection never overwrites them.
                if row and (row['source'].get('kind') != 'group_learning' or row['status'] in {'deleted', 'inactive'} and row['learning'].get('validation_state') != 'source_changed'):
                    results.append({'memory_id': str(row['id']), 'status': 'suppressed'})
                    continue
                if row and (row['content'].strip() == item.content.strip() or row['learning'].get('fingerprint') == fingerprint) and row['learning'].get('validation_state') != 'source_changed':
                    for message in evidence:
                        conn.execute('''INSERT INTO group_learning_sources(memory_id,tenant_id,channel_id,message_id,message_hash)
                            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (row['id'], job['tenant_id'], job['channel_id'], int(message['id']), message['hash']))
                    results.append({'memory_id': str(row['id']), 'status': 'duplicate'})
                    continue
                matching_copy = anchor and row and item.target=='conversation' and anchor['source'].get('kind')=='group_learning' and anchor['fact_key']==row['fact_key'] and anchor['content']==row['content'] and anchor['version']==row['version']
                if row and row['learning'].get('validation_state') != 'source_changed' and ((str(item.existing_id) != str(row['id']) and not matching_copy) or item.expected_version != row['version']):
                    results.append({'memory_id': str(row['id']), 'status': 'conflict', 'reason': '已有结论保留；更新需要匹配当前版本。'})
                    continue
                source = {'kind': 'group_learning', 'channel_id': str(job['channel_id']), 'batch_id': str(job['id']),
                    'project_shared': scope == 'project', 'message_ids': [m['id'] for m in evidence],
                    'audience': sorted(set.intersection(*(set(m['audience']) for m in evidence)))}
                detail = item.model_dump(mode='json', exclude={'content', 'memory_type'})
                detail.update({'fingerprint': fingerprint, 'validation_state': 'verified',
                    'reason': output.reason, 'evidence': [{'id': m['id'], 'kind': m['kind'], 'text': m['text'], 'outcome': m['outcome'], 'user_id': m['user_id']} for m in evidence],
                    'group_batch_id': str(job['id'])})
                if learned:
                    detail = automatic_validation(item.memory_type, detail)
                    access = MemoryAccess(job['tenant_id'], user, project, private=scope != 'project',project_read=True, project_write=True,
                        audience_user_ids=tuple(source['audience']),
                        group_source_channels=(str(job['channel_id']),), group_shared_channels=(str(job['channel_id']),) if scope=='project' else ())
                    event_id = uuid4()
                    event_key = _digest([str(job['id']), scope, user, key])
                    event = conn.execute('''INSERT INTO learning_events(id,tenant_id,identity_type,scope_type,platform_user_id,project_id,
                        agent_id,session_id,config_owner,event_key,event_type,evidence,fingerprint,access_snapshot,source_type,provenance)
                        VALUES(%s,%s,'business_user',%s,%s,%s,'',%s,%s,%s,'group_chat',%s,%s,%s,'group',%s)
                        ON CONFLICT(tenant_id,identity_type,agent_id,session_id,event_key) DO UPDATE SET event_key=excluded.event_key RETURNING id''',
                        (event_id, job['tenant_id'], scope, user, project, 'group:'+str(job['id']), job['config_owner'], event_key,
                         Jsonb([{'id': m['id'], 'kind': 'task' if m['kind']!='user' else 'user', 'text': m['text'][:4000], 'outcome': m['outcome']} for m in evidence]), fingerprint, Jsonb(asdict(access)),
                         Jsonb({'batch_id':str(job['id']), 'channel_id':str(job['channel_id'])}))).fetchone()
                    detail['event_id'] = str(event['id'])
                if row:
                    row = conn.execute('''UPDATE memory_records SET content=%s,memory_type=%s,status=%s,source=%s,learning=%s,
                        version=version+1,updated_at=now(),embedding=NULL,indexed_version=NULL,index_status='pending' WHERE id=%s RETURNING *''',
                        (item.content.strip(), item.memory_type, 'active', Jsonb(source), Jsonb(detail), row['id'])).fetchone()
                    conn.execute('DELETE FROM group_learning_sources WHERE memory_id=%s', (row['id'],))
                else:
                    row = conn.execute('''INSERT INTO memory_records(id,tenant_id,identity_type,scope_type,platform_user_id,project_id,
                        fact_key,content,memory_type,status,source,created_by,origin,learning)
                        VALUES(%s,%s,'business_user',%s,%s,%s,%s,%s,%s,%s,%s,'group_learning','learning',%s) RETURNING *''',
                        (uuid4(), job['tenant_id'], scope, user, project, key, item.content.strip(), item.memory_type,
                         'active', Jsonb(source), Jsonb(detail))).fetchone()
                for message in evidence:
                    conn.execute('''INSERT INTO group_learning_sources(memory_id,tenant_id,channel_id,message_id,message_hash)
                        VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (row['id'], job['tenant_id'], job['channel_id'], int(message['id']), message['hash']))
                self.memories._version(conn, row, 'group_learning', 'group_auto_publish' if learned else 'group_fact')
                self.memories._queue(conn, row)
                if learned:
                    conn.execute('''INSERT INTO learning_jobs(id,event_id,state,result,finished_at) VALUES(%s,%s,'done',%s,now())
                        ON CONFLICT(event_id) DO NOTHING''', (uuid4(), event['id'], Jsonb({'reason': output.reason,
                            'candidates': [{'memory_id': str(row['id']), 'status': 'active'}]})))
                results.append({'memory_id': str(row['id']), 'status': row['status'], 'scope_type': scope, 'platform_user_id': user})
            result = {'reason': output.reason, 'candidates': results}
            conn.execute('''UPDATE group_learning_batches SET state=%s,result=%s,finished_at=now(),error_code=NULL,lease_id=NULL,lease_until=NULL WHERE id=%s''',
                ('done' if results else 'skipped', Jsonb(result), job['id']))
            conn.execute('''UPDATE group_learning_cursors SET cursor=%s,policy_revision=%s,last_result=%s
                WHERE tenant_id=%s AND channel_id=%s''', (job['to_revision'], snapshot['policy_revision'], Jsonb(result), job['tenant_id'], job['channel_id']))
            return result

    def dashboard(self, access, *, offset=0, limit=30):
        if not access.management:
            raise MemoryError('forbidden', '需要管理权限。', status=403)
        with self.memories._connection() as conn:
            cursors = conn.execute('SELECT * FROM group_learning_cursors WHERE tenant_id=%s ORDER BY channel_id LIMIT 500', (access.tenant_id,)).fetchall()
            jobs = conn.execute('SELECT * FROM group_learning_batches WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s', (access.tenant_id, limit, offset)).fetchall()
            total = conn.execute('SELECT count(*) AS n FROM group_learning_batches WHERE tenant_id=%s', (access.tenant_id,)).fetchone()['n']
            return {'channels': [_public(c) for c in cursors], 'batches': [_public(j) for j in jobs], 'total': total}

    def action(self, access, *, channel_id=None, batch_id=None, action):
        if not access.management:
            raise MemoryError('forbidden', '需要管理权限。', status=403)
        with self.memories._connection() as conn:
            if action in {'pause', 'resume'}:
                row = conn.execute('UPDATE group_learning_cursors SET paused=%s WHERE tenant_id=%s AND channel_id=%s RETURNING *',
                    (action == 'pause', access.tenant_id, channel_id)).fetchone()
                if not row:
                    raise MemoryError('not_found', '群聊学习记录不存在。', status=404)
                return _public(row)
            row = conn.execute('SELECT * FROM group_learning_batches WHERE id=%s AND tenant_id=%s FOR UPDATE', (UUID(batch_id), access.tenant_id)).fetchone()
            if not row or action != 'retry' or row['state'] != 'failed':
                raise MemoryError('not_retryable', '仅可重试失败批次；完成或跳过的批次不重复处理。', status=409)
            conn.execute("UPDATE group_learning_batches SET state='pending',attempts=0,error_code=NULL,available_at=now() WHERE id=%s", (row['id'],))
            return {'status': 'pending'}
