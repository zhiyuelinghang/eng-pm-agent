"""支持知识库多选问答范围

Revision ID: c36e91ab7f42
Revises: b724fc19a8de
Create Date: 2026-08-19 13:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c36e91ab7f42"
down_revision: str | Sequence[str] | None = "b724fc19a8de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist several knowledge bases, folders, or files as one scope."""

    op.add_column(
        "engineering_knowledge_conversations",
        sa.Column("scope_items", sa.JSON(), nullable=True),
    )
    op.drop_constraint(
        "ck_engineering_knowledge_conversations_scope",
        "engineering_knowledge_conversations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_knowledge_conversations_scope",
        "engineering_knowledge_conversations",
        "scope_type IN ('project', 'knowledge_base', 'folder', 'document', 'selection')",
    )


def downgrade() -> None:
    """Return multi-selection conversations to project-wide scope."""

    op.execute(
        "UPDATE engineering_knowledge_conversations "
        "SET scope_type = 'project', knowledge_id = NULL, "
        "knowledge_name = NULL, knowledge_base_id = NULL, folder_path = NULL "
        "WHERE scope_type = 'selection'",
    )
    op.drop_constraint(
        "ck_engineering_knowledge_conversations_scope",
        "engineering_knowledge_conversations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_knowledge_conversations_scope",
        "engineering_knowledge_conversations",
        "scope_type IN ('project', 'knowledge_base', 'folder', 'document')",
    )
    op.drop_column("engineering_knowledge_conversations", "scope_items")
