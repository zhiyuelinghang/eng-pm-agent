"""Durable request evidence and proposals; only this service commits proposals."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
from uuid import uuid4

from psycopg.types.json import Jsonb
from .memory_repository import MemoryError, MemoryWrite, _public


MEMORY_RUN_DDL = """
CREATE TABLE IF NOT EXISTS memory_runs (
    tenant_id text NOT NULL, run_id text NOT NULL, config_owner text NOT NULL,
    root_session_id text NOT NULL, root_agent_id text NOT NULL,
    state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','completed','cancelled')),
    no_memory boolean NOT NULL DEFAULT false, no_learning boolean NOT NULL DEFAULT false,
    learning_state text NOT NULL DEFAULT 'pending' CHECK(learning_state IN ('pending','done','skipped')),
    error_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,run_id)
);
CREATE TABLE IF NOT EXISTS memory_run_nodes (
    tenant_id text NOT NULL, run_id text NOT NULL, session_id text NOT NULL, agent_id text NOT NULL,
    reply_id text, learning_request jsonb, PRIMARY KEY(tenant_id,run_id,session_id),
    FOREIGN KEY(tenant_id,run_id) REFERENCES memory_runs(tenant_id,run_id)
);
CREATE TABLE IF NOT EXISTS memory_run_evidence (
    tenant_id text NOT NULL, run_id text NOT NULL, evidence_id text NOT NULL,
    agent_id text NOT NULL, session_id text NOT NULL, evidence jsonb NOT NULL, source_ref jsonb,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,run_id,evidence_id),
    FOREIGN KEY(tenant_id,run_id) REFERENCES memory_runs(tenant_id,run_id)
);
CREATE TABLE IF NOT EXISTS memory_proposals (
    id uuid PRIMARY KEY, tenant_id text NOT NULL, run_id text NOT NULL, proposal_key text NOT NULL,
    operation text NOT NULL CHECK(operation IN ('write','forget')),
    payload jsonb NOT NULL, evidence_ids jsonb NOT NULL, contributors jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','saved','rejected')),
    result jsonb, error_code text, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,run_id,proposal_key),
    FOREIGN KEY(tenant_id,run_id) REFERENCES memory_runs(tenant_id,run_id)
);
CREATE INDEX IF NOT EXISTS ix_memory_run_pending ON memory_runs(tenant_id,state,learning_state,created_at);
"""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class MemoryRunRepository:
    def __init__(self, memories):
        self.memories = memories

    def begin(self, tenant, run_id, owner, root_session, root_agent, *, no_memory=False, no_learning=False):
        with self.memories._connection() as conn:
            conn.execute('''INSERT INTO memory_runs(tenant_id,run_id,config_owner,root_session_id,root_agent_id,no_memory,no_learning)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,run_id) DO UPDATE SET
                no_memory=memory_runs.no_memory OR excluded.no_memory,
                no_learning=memory_runs.no_learning OR excluded.no_learning''',
                (tenant,run_id,owner,root_session,root_agent,no_memory,no_learning or no_memory))
            row = conn.execute('SELECT * FROM memory_runs WHERE tenant_id=%s AND run_id=%s',(tenant,run_id)).fetchone()
            if (row['config_owner'],row['root_session_id'],row['root_agent_id']) != (owner,root_session,root_agent):
                raise MemoryError('run_identity_mismatch','业务运行归属不一致。',status=403)
            return _public(row)

    def get(self, tenant, run_id):
        with self.memories._connection() as conn:
            row=conn.execute('SELECT * FROM memory_runs WHERE tenant_id=%s AND run_id=%s',(tenant,run_id)).fetchone()
            if not row:
                raise MemoryError('run_missing','该业务运行尚未登记。',status=403)
            return _public(row)

    def node(self, tenant, run_id, session_id, agent_id, reply_id=None):
        with self.memories._connection() as conn:
            conn.execute('''INSERT INTO memory_run_nodes(tenant_id,run_id,session_id,agent_id,reply_id)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,run_id,session_id) DO UPDATE
                SET reply_id=coalesce(excluded.reply_id,memory_run_nodes.reply_id)''',(tenant,run_id,session_id,agent_id,reply_id))

    def evidence(self, tenant, run_id, agent_id, session_id, evidence, source_ref=None):
        with self.memories._connection() as conn:
            state=conn.execute('SELECT state,no_learning,no_memory FROM memory_runs WHERE tenant_id=%s AND run_id=%s FOR SHARE',
                               (tenant,run_id)).fetchone()
            if not state or state['state']!='active' or state['no_memory']:
                return
            conn.execute('''INSERT INTO memory_run_evidence(tenant_id,run_id,evidence_id,agent_id,session_id,evidence,source_ref)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,run_id,evidence_id) DO NOTHING''',
                (tenant,run_id,evidence['id'],agent_id,session_id,Jsonb(evidence),Jsonb(source_ref) if source_ref else None))

    def sources(self, tenant, run_id):
        with self.memories._connection() as conn:
            return [_public(row) for row in conn.execute('SELECT * FROM memory_run_evidence WHERE tenant_id=%s AND run_id=%s ORDER BY recorded_at,evidence_id',
                                                        (tenant,run_id)).fetchall()]

    def nodes(self, tenant, run_id):
        with self.memories._connection() as conn:
            return [_public(row) for row in conn.execute('SELECT * FROM memory_run_nodes WHERE tenant_id=%s AND run_id=%s',
                                                        (tenant,run_id)).fetchall()]

    def request_learning(self, tenant, run_id, session_id, request):
        with self.memories._connection() as conn:
            conn.execute('UPDATE memory_run_nodes SET learning_request=%s WHERE tenant_id=%s AND run_id=%s AND session_id=%s',
                         (Jsonb(request),tenant,run_id,session_id))

    def seal_evidence(self, tenant, run_id, evidence_id, evidence, source_ref):
        with self.memories._connection() as conn:
            conn.execute('UPDATE memory_run_evidence SET evidence=%s,source_ref=%s WHERE tenant_id=%s AND run_id=%s AND evidence_id=%s',
                         (Jsonb(evidence),Jsonb(source_ref),tenant,run_id,evidence_id))

    def propose(self, tenant, run_id, operation, payload, evidence_ids, contributors):
        if operation not in {'write','forget'} or not evidence_ids or not contributors:
            raise MemoryError('proposal_invalid','记忆请求需要原始证据和来源节点。')
        # Source agent is deliberately excluded: relaying one fact does not
        # make it a second request. Payload differences remain reviewable.
        key=fingerprint([operation,payload,sorted(evidence_ids)])
        with self.memories._connection() as conn:
            run=conn.execute('SELECT * FROM memory_runs WHERE tenant_id=%s AND run_id=%s FOR UPDATE',(tenant,run_id)).fetchone()
            if not run or run['state']!='active' or run['no_memory']:
                raise MemoryError('run_closed','本次业务已结束或禁止保存记忆。',status=403)
            known={r['evidence_id'] for r in conn.execute('SELECT evidence_id FROM memory_run_evidence WHERE tenant_id=%s AND run_id=%s',
                                                       (tenant,run_id)).fetchall()}
            if not set(evidence_ids).issubset(known):
                raise MemoryError('source_forbidden','记忆请求引用了本次业务之外的证据。',status=403)
            old=conn.execute('SELECT * FROM memory_proposals WHERE tenant_id=%s AND run_id=%s AND proposal_key=%s FOR UPDATE',
                             (tenant,run_id,key)).fetchone()
            if old:
                if old['state']=='pending':
                    merged={c['session_id']:c for c in [*old['contributors'],*contributors]}
                    old=conn.execute('UPDATE memory_proposals SET contributors=%s WHERE id=%s RETURNING *',
                                     (Jsonb(list(merged.values())),old['id'])).fetchone()
                return _public(old)
            return _public(conn.execute('''INSERT INTO memory_proposals(id,tenant_id,run_id,proposal_key,operation,payload,evidence_ids,contributors)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (uuid4(),tenant,run_id,key,operation,Jsonb(payload),Jsonb(evidence_ids),Jsonb(contributors))).fetchone())

    def pending(self, tenant, run_id):
        with self.memories._connection() as conn:
            return [_public(r) for r in conn.execute("SELECT * FROM memory_proposals WHERE tenant_id=%s AND run_id=%s AND state='pending' ORDER BY created_at",
                                                     (tenant,run_id)).fetchall()]

    def commit(self, proposal, access, source):
        with self.memories._connection() as conn:
            run=conn.execute('SELECT * FROM memory_runs WHERE tenant_id=%s AND run_id=%s FOR UPDATE',
                             (proposal['tenant_id'],proposal['run_id'])).fetchone()
            row=conn.execute('SELECT * FROM memory_proposals WHERE id=%s FOR UPDATE',(proposal['id'],)).fetchone()
            if not run or not row or (row['tenant_id'],row['run_id']) != (proposal['tenant_id'],proposal['run_id']):
                raise MemoryError('proposal_identity_mismatch','候选记忆归属不一致。',status=403)
            if row['state']!='pending':
                return row['result'] or {'status':row['state']}
            if run['state']=='cancelled' or run['no_memory']:
                raise MemoryError('run_closed','业务已取消或禁止记忆。',status=403)
            if row['operation']=='write':
                result=self.memories.write(access,[MemoryWrite.model_validate(v) for v in row['payload']],
                    request_id='run:'+row['run_id']+':'+row['proposal_key'], source=source, connection=conn)
            else:
                result=self.memories.forget(access,row['payload']['memory_id'],row['payload']['expected_version'],connection=conn)
            conn.execute("UPDATE memory_proposals SET state='saved',result=%s WHERE id=%s",(Jsonb(result),row['id']))
            return result

    def reject(self, proposal_id, code):
        with self.memories._connection() as conn:
            conn.execute("UPDATE memory_proposals SET state='rejected',error_code=%s WHERE id=%s AND state='pending'",(code,proposal_id))

    def work(self, tenant):
        with self.memories._connection() as conn:
            return [_public(r) for r in conn.execute("SELECT * FROM memory_runs WHERE tenant_id=%s AND (state='active' OR (state='completed' AND learning_state='pending')) ORDER BY updated_at,created_at LIMIT 50",(tenant,)).fetchall()]

    def checked(self, tenant, run_id):
        # Waiting for a model or a teammate must not starve newer runs.
        with self.memories._connection() as conn:
            conn.execute('UPDATE memory_runs SET updated_at=now() WHERE tenant_id=%s AND run_id=%s',(tenant,run_id))

    def finish(self, tenant, run_id, *, cancelled=False, learning_state=None, error=None):
        with self.memories._connection() as conn:
            conn.execute('''UPDATE memory_runs SET state=%s,learning_state=coalesce(%s,learning_state),error_code=%s,updated_at=now()
                WHERE tenant_id=%s AND run_id=%s''',('cancelled' if cancelled else 'completed',learning_state,error,tenant,run_id))
            if cancelled:
                conn.execute("UPDATE memory_proposals SET state='rejected',error_code=%s WHERE tenant_id=%s AND run_id=%s AND state='pending'",
                             (error or 'run_cancelled',tenant,run_id))
