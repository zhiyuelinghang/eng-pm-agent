"""建立项目群聊与实时投递

Revision ID: f7a2c9d4e510
Revises: b38f61c0a7d2
Create Date: 2026-08-25 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f7a2c9d4e510"
down_revision: str | Sequence[str] | None = "b38f61c0a7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create platform-owned chat tables and a Centrifugo outbox."""

    op.create_table(
        "chat_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "channel_type",
            sa.String(length=24),
            server_default="topic",
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "channel_type IN ('project', 'topic', 'private')",
            name="ck_chat_channels_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_channels_project_id",
        "chat_channels",
        ["project_id"],
    )
    op.create_index(
        "ix_chat_channels_project_updated",
        "chat_channels",
        ["project_id", "updated_at"],
    )
    op.create_index(
        "uq_chat_channels_project_default",
        "chat_channels",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text(
            "channel_type = 'project' AND archived_at IS NULL",
        ),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("sender_user_id", sa.Integer(), nullable=True),
        sa.Column("sender_agent_id", sa.String(length=128), nullable=True),
        sa.Column(
            "message_type",
            sa.String(length=24),
            server_default="text",
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
        sa.Column("reply_to_id", sa.Integer(), nullable=True),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            "message_type IN ('text', 'agent', 'system', 'task_draft', 'task_event')",
            name="ck_chat_messages_message_type",
        ),
        sa.CheckConstraint(
            "(sender_type = 'user' AND sender_user_id IS NOT NULL AND sender_agent_id IS NULL) "
            "OR (sender_type = 'agent' AND sender_user_id IS NULL AND sender_agent_id IS NOT NULL) "
            "OR (sender_type = 'system' AND sender_user_id IS NULL)",
            name="ck_chat_messages_sender_identity",
        ),
        sa.CheckConstraint(
            "sender_type IN ('user', 'agent', 'system')",
            name="ck_chat_messages_sender_type",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["chat_channels.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_id"],
            ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "client_message_id",
            name="uq_chat_messages_client_message",
        ),
    )
    op.create_index(
        "ix_chat_messages_channel_id",
        "chat_messages",
        ["channel_id"],
    )
    op.create_index(
        "ix_chat_messages_channel_created",
        "chat_messages",
        ["channel_id", "created_at"],
    )
    op.create_index(
        "ix_chat_messages_sender_agent_id",
        "chat_messages",
        ["sender_agent_id"],
    )
    op.create_index(
        "ix_chat_messages_sender_user_id",
        "chat_messages",
        ["sender_user_id"],
    )

    op.create_table(
        "chat_channel_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "member_role",
            sa.String(length=16),
            server_default="member",
            nullable=False,
        ),
        sa.Column("last_read_message_id", sa.Integer(), nullable=True),
        sa.Column(
            "muted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
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
            "member_role IN ('owner', 'member')",
            name="ck_chat_channel_members_role",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["chat_channels.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_read_message_id"],
            ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "user_id",
            name="uq_chat_channel_member_user",
        ),
    )
    op.create_index(
        "ix_chat_channel_members_channel_id",
        "chat_channel_members",
        ["channel_id"],
    )
    op.create_index(
        "ix_chat_channel_members_user_id",
        "chat_channel_members",
        ["user_id"],
    )
    op.create_index(
        "ix_chat_channel_members_user_active",
        "chat_channel_members",
        ["user_id", "left_at"],
    )

    op.create_table(
        "chat_message_mentions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_agent_id", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.CheckConstraint(
            "(target_type = 'user' AND target_user_id IS NOT NULL AND target_agent_id IS NULL) "
            "OR (target_type = 'agent' AND target_user_id IS NULL AND target_agent_id IS NOT NULL)",
            name="ck_chat_message_mentions_target",
        ),
        sa.CheckConstraint(
            "target_type IN ('user', 'agent')",
            name="ck_chat_message_mentions_type",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_message_mentions_agent",
        "chat_message_mentions",
        ["target_agent_id"],
    )
    op.create_index(
        "ix_chat_message_mentions_message",
        "chat_message_mentions",
        ["message_id"],
    )
    op.create_index(
        "ix_chat_message_mentions_user",
        "chat_message_mentions",
        ["target_user_id"],
    )

    op.create_table(
        "chat_realtime_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "method",
            sa.Text(),
            server_default="publish",
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "partition",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_realtime_outbox_partition_id",
        "chat_realtime_outbox",
        ["partition", "id"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION chat_realtime_notify_outbox()
        RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify(
                'chat_realtime_outbox_changed',
                NEW.partition::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
    )
    op.execute(
        """
        CREATE TRIGGER chat_realtime_outbox_notify_trigger
        AFTER INSERT ON chat_realtime_outbox
        FOR EACH ROW
        EXECUTE FUNCTION chat_realtime_notify_outbox()
        """,
    )


def downgrade() -> None:
    """Remove the isolated chat proof-of-concept tables."""

    op.execute(
        "DROP TRIGGER IF EXISTS chat_realtime_outbox_notify_trigger "
        "ON chat_realtime_outbox",
    )
    op.execute("DROP FUNCTION IF EXISTS chat_realtime_notify_outbox()")
    op.drop_index(
        "ix_chat_realtime_outbox_partition_id",
        table_name="chat_realtime_outbox",
    )
    op.drop_table("chat_realtime_outbox")
    op.drop_index(
        "ix_chat_message_mentions_user",
        table_name="chat_message_mentions",
    )
    op.drop_index(
        "ix_chat_message_mentions_message",
        table_name="chat_message_mentions",
    )
    op.drop_index(
        "ix_chat_message_mentions_agent",
        table_name="chat_message_mentions",
    )
    op.drop_table("chat_message_mentions")
    op.drop_index(
        "ix_chat_channel_members_user_active",
        table_name="chat_channel_members",
    )
    op.drop_index(
        "ix_chat_channel_members_user_id",
        table_name="chat_channel_members",
    )
    op.drop_index(
        "ix_chat_channel_members_channel_id",
        table_name="chat_channel_members",
    )
    op.drop_table("chat_channel_members")
    op.drop_index(
        "ix_chat_messages_sender_user_id",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_sender_agent_id",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_channel_created",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_channel_id",
        table_name="chat_messages",
    )
    op.drop_table("chat_messages")
    op.drop_index(
        "uq_chat_channels_project_default",
        table_name="chat_channels",
    )
    op.drop_index(
        "ix_chat_channels_project_updated",
        table_name="chat_channels",
    )
    op.drop_index(
        "ix_chat_channels_project_id",
        table_name="chat_channels",
    )
    op.drop_table("chat_channels")
