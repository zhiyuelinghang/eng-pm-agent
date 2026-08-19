"""扩展知识库问答范围

Revision ID: b724fc19a8de
Revises: e7c1a93b4d20
Create Date: 2026-08-18 19:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b724fc19a8de"
down_revision: str | Sequence[str] | None = "e7c1a93b4d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist knowledge-base and folder conversation scopes."""

    op.add_column(
        "engineering_knowledge_conversations",
        sa.Column("folder_path", sa.String(length=4096), nullable=True),
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


def downgrade() -> None:
    """Return unsupported scoped conversations to project-wide scope."""

    op.execute(
        "UPDATE engineering_knowledge_conversations "
        "SET scope_type = 'project', knowledge_id = NULL, "
        "knowledge_name = NULL, knowledge_base_id = NULL "
        "WHERE scope_type IN ('knowledge_base', 'folder')",
    )
    op.drop_constraint(
        "ck_engineering_knowledge_conversations_scope",
        "engineering_knowledge_conversations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_knowledge_conversations_scope",
        "engineering_knowledge_conversations",
        "scope_type IN ('project', 'document')",
    )
    op.drop_column("engineering_knowledge_conversations", "folder_path")
