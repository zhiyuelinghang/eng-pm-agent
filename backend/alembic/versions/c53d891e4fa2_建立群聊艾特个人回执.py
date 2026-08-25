"""建立群聊艾特个人回执

Revision ID: c53d891e4fa2
Revises: b412d8e9a6f3
Create Date: 2026-08-25 21:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c53d891e4fa2"
down_revision: str | Sequence[str] | None = "b412d8e9a6f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one independently claimable first-view receipt per recipient."""

    op.create_table(
        "chat_message_mention_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_chat_message_mention_receipts_message_user",
        ),
    )
    op.create_index(
        "ix_chat_message_mention_receipts_message_id",
        "chat_message_mention_receipts",
        ["message_id"],
    )
    op.create_index(
        "ix_chat_message_mention_receipts_user_id",
        "chat_message_mention_receipts",
        ["user_id"],
    )
    op.create_index(
        "ix_chat_message_mention_receipts_user_seen",
        "chat_message_mention_receipts",
        ["user_id", "seen_at"],
    )


def downgrade() -> None:
    """Remove per-recipient mention receipts."""

    op.drop_index(
        "ix_chat_message_mention_receipts_user_seen",
        table_name="chat_message_mention_receipts",
    )
    op.drop_index(
        "ix_chat_message_mention_receipts_user_id",
        table_name="chat_message_mention_receipts",
    )
    op.drop_index(
        "ix_chat_message_mention_receipts_message_id",
        table_name="chat_message_mention_receipts",
    )
    op.drop_table("chat_message_mention_receipts")
