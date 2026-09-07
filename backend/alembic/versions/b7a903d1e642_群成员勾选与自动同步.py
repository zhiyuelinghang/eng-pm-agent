"""独立保存群成员同步模式和实时访问版本。"""
from alembic import op

revision = "b7a903d1e642"
down_revision = "ab906c21d530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from backend.app.chat_membership_policy import upgrade_chat_membership
    upgrade_chat_membership(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("成员访问设置不能通过删除字段还原，请使用备份恢复。")
