"""允许同一项目用户多次发起资料会话，保留全部旧会话和草稿。"""
from alembic import op
import sqlalchemy as sa

revision = "ff95db38c426"
down_revision = "fe84ca27b315"
branch_labels = None
depends_on = None

OLD_INDEX = "uq_agent_conversations_project_user_initialization"
NEW_INDEX = "ix_agent_conversations_project_user_initialization"


def upgrade():
    op.drop_index(OLD_INDEX, table_name="agent_conversations")
    op.create_index(
        NEW_INDEX, "agent_conversations", ["project_id", "user_id"],
        sqlite_where=sa.text("conversation_type = 'initialization'"),
        postgresql_where=sa.text("conversation_type = 'initialization'"),
    )


def downgrade():
    # Once a user has multiple sessions, this deliberately fails instead of
    # deleting history to force the obsolete uniqueness rule back into place.
    op.create_index(
        OLD_INDEX, "agent_conversations", ["project_id", "user_id"], unique=True,
        sqlite_where=sa.text("conversation_type = 'initialization'"),
        postgresql_where=sa.text("conversation_type = 'initialization'"),
    )
    op.drop_index(NEW_INDEX, table_name="agent_conversations")
