"""项目资料分批确认与差异预览，不改动现有正式业务数据。"""
from alembic import op
import sqlalchemy as sa

revision = "fe84ca27b315"
down_revision = "fd73b916a204"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_initialization_applied_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_key", sa.String(200), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("draft_id", "change_key", name="uq_initialization_applied_key"),
    )
    op.create_index("ix_project_initialization_applied_changes_draft_id", "project_initialization_applied_changes", ["draft_id"])
    op.create_table(
        "project_initialization_change_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("project_initialization_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("baseline_hash", sa.String(64), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("review", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.JSON()),
    )
    for field in ("project_id", "draft_id"):
        op.create_index(f"ix_project_initialization_change_previews_{field}", "project_initialization_change_previews", [field])


def downgrade():
    op.drop_table("project_initialization_change_previews")
    op.drop_table("project_initialization_applied_changes")
