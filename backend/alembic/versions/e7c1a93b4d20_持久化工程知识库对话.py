"""持久化工程知识库对话

Revision ID: e7c1a93b4d20
Revises: d18b7a43c2e1
Create Date: 2026-08-18 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e7c1a93b4d20"
down_revision: str | Sequence[str] | None = "d18b7a43c2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create account-private WeKnora conversations and messages."""

    op.create_table(
        "engineering_knowledge_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            server_default="project",
            nullable=False,
        ),
        sa.Column("knowledge_id", sa.String(length=128), nullable=True),
        sa.Column("knowledge_name", sa.String(length=500), nullable=True),
        sa.Column("knowledge_base_id", sa.String(length=128), nullable=True),
        sa.Column("weknora_session_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope_type IN ('project', 'document')",
            name="ck_engineering_knowledge_conversations_scope",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_engineering_knowledge_conversations_project_id",
        "engineering_knowledge_conversations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_engineering_knowledge_conversations_user_id",
        "engineering_knowledge_conversations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_engineering_knowledge_conversations_weknora_session_id",
        "engineering_knowledge_conversations",
        ["weknora_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_engineering_knowledge_conversations_owner_updated",
        "engineering_knowledge_conversations",
        ["project_id", "user_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "engineering_knowledge_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column(
            "failed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_engineering_knowledge_messages_role",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["engineering_knowledge_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_engineering_knowledge_messages_conversation_id",
        "engineering_knowledge_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_engineering_knowledge_messages_conversation_created",
        "engineering_knowledge_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove persisted WeKnora conversation history."""

    op.drop_index(
        "ix_engineering_knowledge_messages_conversation_created",
        table_name="engineering_knowledge_messages",
    )
    op.drop_index(
        "ix_engineering_knowledge_messages_conversation_id",
        table_name="engineering_knowledge_messages",
    )
    op.drop_table("engineering_knowledge_messages")
    op.drop_index(
        "ix_engineering_knowledge_conversations_owner_updated",
        table_name="engineering_knowledge_conversations",
    )
    op.drop_index(
        "ix_engineering_knowledge_conversations_weknora_session_id",
        table_name="engineering_knowledge_conversations",
    )
    op.drop_index(
        "ix_engineering_knowledge_conversations_user_id",
        table_name="engineering_knowledge_conversations",
    )
    op.drop_index(
        "ix_engineering_knowledge_conversations_project_id",
        table_name="engineering_knowledge_conversations",
    )
    op.drop_table("engineering_knowledge_conversations")
