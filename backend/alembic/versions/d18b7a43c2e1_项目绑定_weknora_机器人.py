"""项目绑定 WeKnora 机器人

Revision ID: d18b7a43c2e1
Revises: f41c9d7e2b10
Create Date: 2026-08-17 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d18b7a43c2e1"
down_revision: str | Sequence[str] | None = "f41c9d7e2b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store one WeKnora robot ID on every project settings record."""

    op.add_column(
        "project_settings",
        sa.Column("weknora_agent_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_project_settings_weknora_agent_id",
        "project_settings",
        ["weknora_agent_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the project-to-robot binding."""

    op.drop_index(
        "ix_project_settings_weknora_agent_id",
        table_name="project_settings",
    )
    op.drop_column("project_settings", "weknora_agent_id")
