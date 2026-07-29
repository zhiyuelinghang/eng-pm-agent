# -*- coding: utf-8 -*-
"""Add the platform-wide settings table.

Revision ID: 0003_platform_settings
Revises: 0002_permission_reviewer
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_platform_settings"
down_revision: Union[str, None] = "0002_permission_reviewer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the single-record platform settings table."""
    op.create_table(
        "platform_settings",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("platform_settings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_platform_settings_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_platform_settings_updated_at"),
            ["updated_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_platform_settings_user_id"),
            ["user_id"],
            unique=False,
        )
        batch_op.create_index(
            "ux_platform_settings_user",
            ["user_id"],
            unique=True,
        )


def downgrade() -> None:
    """Drop the platform settings table."""
    with op.batch_alter_table("platform_settings", schema=None) as batch_op:
        batch_op.drop_index("ux_platform_settings_user")
        batch_op.drop_index(batch_op.f("ix_platform_settings_user_id"))
        batch_op.drop_index(batch_op.f("ix_platform_settings_updated_at"))
        batch_op.drop_index(batch_op.f("ix_platform_settings_created_at"))
    op.drop_table("platform_settings")
