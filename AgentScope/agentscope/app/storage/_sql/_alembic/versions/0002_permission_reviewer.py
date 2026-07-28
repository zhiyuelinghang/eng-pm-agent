# -*- coding: utf-8 -*-
"""Add built-in permission reviewer configuration and audit tables.

Revision ID: 0002_permission_reviewer
Revises: 0001_initial
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_permission_reviewer"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create permission reviewer configuration and audit tables."""
    op.create_table(
        "permission_reviewer_configs",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table(
        "permission_reviewer_configs",
        schema=None,
    ) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_permission_reviewer_configs_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_reviewer_configs_updated_at"),
            ["updated_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_reviewer_configs_user_id"),
            ["user_id"],
            unique=False,
        )
        batch_op.create_index(
            "ux_permission_reviewer_configs_user",
            ["user_id"],
            unique=True,
        )

    op.create_table(
        "permission_review_audits",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table(
        "permission_review_audits",
        schema=None,
    ) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_permission_review_audits_agent_id"),
            ["agent_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_review_audits_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_review_audits_session_id"),
            ["session_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_review_audits_tool_name"),
            ["tool_name"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_review_audits_updated_at"),
            ["updated_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_permission_review_audits_user_id"),
            ["user_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_permission_review_audits_user_created",
            ["user_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    """Drop permission reviewer configuration and audit tables."""
    with op.batch_alter_table(
        "permission_review_audits",
        schema=None,
    ) as batch_op:
        batch_op.drop_index("ix_permission_review_audits_user_created")
        batch_op.drop_index(batch_op.f("ix_permission_review_audits_user_id"))
        batch_op.drop_index(
            batch_op.f("ix_permission_review_audits_updated_at"),
        )
        batch_op.drop_index(
            batch_op.f("ix_permission_review_audits_tool_name"),
        )
        batch_op.drop_index(
            batch_op.f("ix_permission_review_audits_session_id"),
        )
        batch_op.drop_index(
            batch_op.f("ix_permission_review_audits_created_at"),
        )
        batch_op.drop_index(
            batch_op.f("ix_permission_review_audits_agent_id"),
        )
    op.drop_table("permission_review_audits")

    with op.batch_alter_table(
        "permission_reviewer_configs",
        schema=None,
    ) as batch_op:
        batch_op.drop_index("ux_permission_reviewer_configs_user")
        batch_op.drop_index(
            batch_op.f("ix_permission_reviewer_configs_user_id"),
        )
        batch_op.drop_index(
            batch_op.f("ix_permission_reviewer_configs_updated_at"),
        )
        batch_op.drop_index(
            batch_op.f("ix_permission_reviewer_configs_created_at"),
        )
    op.drop_table("permission_reviewer_configs")
