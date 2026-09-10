"""业务确认继承真实运行的学习排除，不回填未经证明的旧来源权限。"""
from alembic import op
import sqlalchemy as sa

revision = 'fd73b916a204'
down_revision = 'fc62e708b193'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('agent_conversations') as batch:
        batch.add_column(sa.Column('generation_id',sa.String(64),nullable=True))
        batch.create_unique_constraint('uq_agent_conversations_generation_id',['generation_id'])
    with op.batch_alter_table('business_learning_sources') as batch:
        batch.add_column(sa.Column('allow_learning',sa.Boolean(),nullable=False,server_default=sa.false()))
        batch.add_column(sa.Column('source_run_refs',sa.JSON(),nullable=False,server_default='[]'))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE memory.memory_run_evidence ADD COLUMN IF NOT EXISTS recorded_at '
                   'timestamptz NOT NULL DEFAULT clock_timestamp()')


def downgrade():
    raise RuntimeError('不能删除业务来源的运行绑定和用户学习排除记录。')
