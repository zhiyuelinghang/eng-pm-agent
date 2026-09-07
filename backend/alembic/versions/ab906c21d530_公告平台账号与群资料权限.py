"""公告、工程平台、个人账号、群资料权限与群名唯一约束。"""
from alembic import op

revision = "ab906c21d530"
down_revision = "f28c6b91d4a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from backend.app.workspace_migrations import upgrade_workspace
    upgrade_workspace(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("此次升级包含公告和个人账号数据，请通过备份恢复，避免丢失数据。")
