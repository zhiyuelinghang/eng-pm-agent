"""建立外部通知可靠投递队列

Revision ID: b38f61c0a7d2
Revises: 9d7b31a4c2e8
Create Date: 2026-08-20 17:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b38f61c0a7d2"
down_revision: str | Sequence[str] | None = "9d7b31a4c2e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the platform-owned external notification outbox."""

    op.create_table(
        "outbound_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column(
            "connector_type",
            sa.String(length=32),
            server_default="wecom",
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("recipient_name", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mentioned_user_id", sa.String(length=100), nullable=True),
        sa.Column("mentioned_mobile", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("response_code", sa.String(length=100), nullable=True),
        sa.Column("dedupe_key", sa.String(length=500), nullable=False),
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
            "connector_type IN ('wecom')",
            name="ck_outbound_notification_connector_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'retrying', 'sent', 'failed', 'skipped')",
            name="ck_outbound_notification_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dedupe_key",
            name="uq_outbound_notification_dedupe",
        ),
    )
    op.create_index(
        "ix_outbound_notifications_due",
        "outbound_notifications",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_outbound_notifications_project",
        "outbound_notifications",
        ["project_id"],
    )
    op.create_index(
        "ix_outbound_notifications_task",
        "outbound_notifications",
        ["task_id"],
    )


def downgrade() -> None:
    """Remove the external notification outbox."""

    op.drop_index(
        "ix_outbound_notifications_task",
        table_name="outbound_notifications",
    )
    op.drop_index(
        "ix_outbound_notifications_project",
        table_name="outbound_notifications",
    )
    op.drop_index(
        "ix_outbound_notifications_due",
        table_name="outbound_notifications",
    )
    op.drop_table("outbound_notifications")
