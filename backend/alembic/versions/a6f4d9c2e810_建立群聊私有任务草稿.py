"""建立群聊私有任务草稿

Revision ID: a6f4d9c2e810
Revises: d84f2a1c7b90
Create Date: 2026-09-02 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a6f4d9c2e810"
down_revision: str | Sequence[str] | None = "d84f2a1c7b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store generated chat task drafts outside the shared message stream."""

    op.create_table(
        "chat_task_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="generating",
            nullable=False,
        ),
        sa.Column("draft_payload", sa.JSON(), nullable=False),
        sa.Column("publish_result", sa.JSON(), nullable=False),
        sa.Column("published_task_ids", sa.JSON(), nullable=False),
        sa.Column("published_message_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'publishing', 'published', "
            "'dismissed', 'cancelled', 'failed')",
            name="ck_chat_task_drafts_status",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["chat_channels.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_message_id"],
            ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "requested_by_user_id",
            "client_request_id",
            name="uq_chat_task_drafts_requester_client",
        ),
        sa.UniqueConstraint("generation_id"),
    )
    op.create_index(
        "ix_chat_task_drafts_channel_id",
        "chat_task_drafts",
        ["channel_id"],
    )
    op.create_index(
        "ix_chat_task_drafts_project_id",
        "chat_task_drafts",
        ["project_id"],
    )
    op.create_index(
        "ix_chat_task_drafts_requested_by_user_id",
        "chat_task_drafts",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_chat_task_drafts_project_requester_updated",
        "chat_task_drafts",
        ["project_id", "requested_by_user_id", "updated_at"],
    )


def downgrade() -> None:
    """Remove private chat task drafts."""

    op.drop_index(
        "ix_chat_task_drafts_project_requester_updated",
        table_name="chat_task_drafts",
    )
    op.drop_index(
        "ix_chat_task_drafts_requested_by_user_id",
        table_name="chat_task_drafts",
    )
    op.drop_index(
        "ix_chat_task_drafts_project_id",
        table_name="chat_task_drafts",
    )
    op.drop_index(
        "ix_chat_task_drafts_channel_id",
        table_name="chat_task_drafts",
    )
    op.drop_table("chat_task_drafts")
