"""兼容原版 Dobby 记忆模块的无租户字段 SQL

Revision ID: f41c9d7e2b10
Revises: e1046bc92ad7
Create Date: 2026-08-14 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "f41c9d7e2b10"
down_revision: str | Sequence[str] | None = "e1046bc92ad7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TENANT_TABLES = (
    "experience_extracts",
    "experiences",
    "consolidation_log",
    "graphiti_events",
    "dreamer_run_log",
    "user_activity",
    "skill_events",
    "skill_registry",
)


def upgrade() -> None:
    """Keep tenant isolation while accepting the upstream SQL unchanged."""

    for table in _TENANT_TABLES:
        op.execute(
            f"""
            ALTER TABLE memory.{table}
            ALTER COLUMN tenant_id SET DEFAULT 'projectcopilot'
            """,
        )

    # The upstream schema permits a missing description and fills the useful
    # fields independently during extraction.
    op.execute(
        """
        ALTER TABLE memory.experience_extracts
        ALTER COLUMN description DROP NOT NULL
        """,
    )


def downgrade() -> None:
    """Restore the stricter platform-only tenant contract."""

    op.execute(
        """
        UPDATE memory.experience_extracts
        SET description = ''
        WHERE description IS NULL
        """,
    )
    op.execute(
        """
        ALTER TABLE memory.experience_extracts
        ALTER COLUMN description SET NOT NULL
        """,
    )
    for table in _TENANT_TABLES:
        op.execute(
            f"""
            ALTER TABLE memory.{table}
            ALTER COLUMN tenant_id DROP DEFAULT
            """,
        )
