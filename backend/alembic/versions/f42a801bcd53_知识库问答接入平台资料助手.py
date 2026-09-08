"""知识库问答接入平台资料助手，保留旧会话与消息。"""
from alembic import op
import sqlalchemy as sa

revision = 'f42a801bcd53'
down_revision = 'e31f790abc42'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('engineering_knowledge_conversations') as batch:
        batch.add_column(sa.Column('agent_conversation_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_knowledge_agent_conversation', 'agent_conversations', ['agent_conversation_id'], ['id'], ondelete='SET NULL')
        batch.create_unique_constraint('uq_knowledge_agent_conversation', ['agent_conversation_id'])


def downgrade():
    with op.batch_alter_table('engineering_knowledge_conversations') as batch:
        batch.drop_constraint('uq_knowledge_agent_conversation', type_='unique')
        batch.drop_constraint('fk_knowledge_agent_conversation', type_='foreignkey')
        batch.drop_column('agent_conversation_id')
