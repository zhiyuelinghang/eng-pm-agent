"""建立群聊智能体会话

Revision ID: b412d8e9a6f3
Revises: f7a2c9d4e510
Create Date: 2026-08-25 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b412d8e9a6f3"
down_revision: str | Sequence[str] | None = "f7a2c9d4e510"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one durable AgentScope session per channel and mentioned agent."""

    op.create_table(
        "chat_agent_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("agent_name", sa.String(length=200), nullable=False),
        sa.Column("agentscope_session_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="creating",
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_source_message_id", sa.Integer(), nullable=True),
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
            ["channel_id"],
            ["chat_channels.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_source_message_id"],
            ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agentscope_session_id",
            name="uq_chat_agent_threads_agentscope_session_id",
        ),
        sa.UniqueConstraint(
            "channel_id",
            "agent_id",
            name="uq_chat_agent_threads_channel_agent",
        ),
    )
    op.create_index(
        "ix_chat_agent_threads_agent",
        "chat_agent_threads",
        ["agent_id"],
    )
    op.create_index(
        "ix_chat_agent_threads_channel",
        "chat_agent_threads",
        ["channel_id"],
    )


def downgrade() -> None:
    """Remove shared chat-agent sessions."""

    op.drop_index(
        "ix_chat_agent_threads_channel",
        table_name="chat_agent_threads",
    )
    op.drop_index(
        "ix_chat_agent_threads_agent",
        table_name="chat_agent_threads",
    )
    op.drop_table("chat_agent_threads")
