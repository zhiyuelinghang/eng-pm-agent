"""统一记忆运行与系统学习来源，保留旧来源和版本审计。"""
import re

from alembic import op

from utils.learning_schema import LEARNING_DDL, BUSINESS_LEARNING_DDL
from utils.group_learning_schema import GROUP_LEARNING_DDL
from utils.memory_run_repository import MEMORY_RUN_DDL

revision = 'fc62e708b193'
down_revision = 'fa39c501a842'
branch_labels = None
depends_on = None


TABLES = ('memory_records', 'memory_versions', 'memory_index_jobs', 'learning_events', 'learning_jobs',
    'learning_feedback', 'learning_maintenance', 'business_learning_cursors', 'group_learning_cursors',
    'group_learning_batches', 'group_learning_sources', 'memory_runs', 'memory_run_nodes',
    'memory_run_evidence', 'memory_proposals')


def _memory_sql(statement):
    for table in TABLES:
        statement = re.sub(rf'\b{table}\b', f'memory.{table}', statement)
    return statement


def upgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    for ddl in (LEARNING_DDL, GROUP_LEARNING_DDL, BUSINESS_LEARNING_DDL, MEMORY_RUN_DDL):
        for statement in ddl.split(';'):
            if statement.strip():
                op.execute(_memory_sql(statement))

    # The stored group batch is an actual source, so preserve its history and
    # replace its former policy-agent attribution with an explicit system source.
    op.execute('''UPDATE memory.learning_events e SET source_type='group',agent_id='',
        provenance=jsonb_build_object('batch_id',b.id::text,'channel_id',b.channel_id::text)
        FROM memory.group_learning_batches b
        WHERE e.tenant_id=b.tenant_id AND e.session_id='group:' || b.id::text''')
    op.execute('''UPDATE memory.learning_events SET access_snapshot=
        (access_snapshot-'learning_capture'-'learning_process') || jsonb_build_object('learning_enabled',
            CASE WHEN source_type='group' THEN true ELSE coalesce((access_snapshot->>'learning_enabled')::boolean,
                coalesce((access_snapshot->>'learning_capture')::boolean,true) AND
                coalesce((access_snapshot->>'learning_process')::boolean,true)) END)''')

    # A historical reply cannot be retrospectively declared a complete business
    # run. Keep its evidence, but do not invent run IDs or tool-version references.
    op.execute('''UPDATE memory.learning_jobs j SET state='cancelled',lease_id=NULL,lease_until=NULL,
        error_code='source_provenance_missing',finished_at=now(),updated_at=now()
        FROM memory.learning_events e WHERE j.event_id=e.id AND e.source_type='interaction'
            AND coalesce(e.provenance->>'run_id','')='' AND j.state IN ('pending','running','failed')''')
    op.execute('''INSERT INTO memory.memory_versions(memory_id,version,snapshot,action,actor_id)
        SELECT r.id,r.version,to_jsonb(r)-'embedding','learning_source_migration','system:migration'
        FROM memory.memory_records r JOIN memory.learning_events e ON e.id::text=r.learning->>'event_id'
        WHERE r.tenant_id=e.tenant_id AND e.source_type='interaction' AND coalesce(e.provenance->>'run_id','')=''
            AND r.status IN ('active','candidate') ON CONFLICT(memory_id,version) DO NOTHING''')
    op.execute('''WITH changed AS (
        UPDATE memory.memory_records r SET status='inactive',version=r.version+1,updated_at=now(),
            embedding=NULL,indexed_version=NULL,index_status='pending',learning=r.learning ||
            jsonb_build_object('validation_state','source_provenance_missing',
                'review_note','运行与来源机制调整前的经验缺少完整证据关联；保留原文和历史，等待真实业务重新验证。')
        FROM memory.learning_events e WHERE e.id::text=r.learning->>'event_id' AND r.tenant_id=e.tenant_id
            AND e.source_type='interaction' AND coalesce(e.provenance->>'run_id','')=''
            AND r.status IN ('active','candidate') RETURNING r.*
        ), versions AS (
        INSERT INTO memory.memory_versions(memory_id,version,snapshot,action,actor_id)
            SELECT id,version,to_jsonb(changed)-'embedding','learning_source_unverified','system:migration' FROM changed
        ) INSERT INTO memory.memory_index_jobs(memory_id,version)
            SELECT id,version FROM changed ON CONFLICT(memory_id) DO UPDATE SET version=excluded.version,
                state='pending',attempts=0,available_at=now(),lease_until=NULL,lease_id=NULL,error_code=NULL,updated_at=now()''')


def downgrade():
    raise RuntimeError('运行证据和学习来源不可自动删除或恢复为未经验证状态；回退应用时保留审计数据。')
