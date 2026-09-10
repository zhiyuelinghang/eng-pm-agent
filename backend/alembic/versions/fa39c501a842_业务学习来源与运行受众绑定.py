"""业务学习来源与运行受众绑定。"""
from alembic import op
import sqlalchemy as sa

revision = 'fa39c501a842'
down_revision = 'f42a801bcd53'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('agent_conversations') as batch:
        batch.add_column(sa.Column('source_channel_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_agent_conversations_source_channel', 'chat_channels',
                                 ['source_channel_id'], ['id'], ondelete='SET NULL')
    op.create_table('business_learning_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_key', sa.String(300), nullable=False, unique=True),
        sa.Column('source_type', sa.String(40), nullable=False),
        sa.Column('source_id', sa.String(128), nullable=False),
        sa.Column('source_version', sa.String(128), nullable=False),
        sa.Column('stage', sa.String(40), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('audience_user_ids', sa.JSON(), nullable=False),
        sa.Column('project_shared', sa.Boolean(), nullable=False),
        sa.Column('source_channel_ids', sa.JSON(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('source_fingerprint', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_business_learning_sources_project_id', 'business_learning_sources', ['project_id'])


def downgrade():
    op.drop_table('business_learning_sources')
    with op.batch_alter_table('agent_conversations') as batch:
        batch.drop_constraint('fk_agent_conversations_source_channel', type_='foreignkey')
        batch.drop_column('source_channel_id')
