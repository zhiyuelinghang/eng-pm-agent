"""建立工程资料本地目录与权限

Revision ID: d84f2a1c7b90
Revises: c53d891e4fa2
Create Date: 2026-08-26 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d84f2a1c7b90"
down_revision: str | Sequence[str] | None = "c53d891e4fa2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the project-owned WeKnora catalogue and hierarchical grants."""

    op.create_table(
        "engineering_document_sync_states",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("weknora_agent_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "access_mode",
            sa.String(length=20),
            server_default="project",
            nullable=False,
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "status IN ('pending', 'syncing', 'ready', 'error')",
            name="ck_engineering_document_sync_status",
        ),
        sa.CheckConstraint(
            "access_mode IN ('project', 'restricted')",
            name="ck_engineering_document_access_mode",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "engineering_document_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("node_type", sa.String(length=24), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("folder_path", sa.Text(), server_default="", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("parse_status", sa.String(length=64), nullable=True),
        sa.Column("enable_status", sa.String(length=64), nullable=True),
        sa.Column("document_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("external_created_at", sa.String(length=64), nullable=True),
        sa.Column("external_updated_at", sa.String(length=64), nullable=True),
        sa.Column("processed_at", sa.String(length=64), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=False),
        sa.Column("sync_revision", sa.Integer(), server_default="0", nullable=False),
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
            "node_type IN ('knowledge_base', 'folder', 'file')",
            name="ck_engineering_document_node_type",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["engineering_document_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "node_key",
            name="uq_engineering_document_project_node_key",
        ),
    )
    op.create_index(
        "ix_engineering_document_nodes_parent_id",
        "engineering_document_nodes",
        ["parent_id"],
    )
    op.create_index(
        "ix_engineering_document_nodes_project_id",
        "engineering_document_nodes",
        ["project_id"],
    )
    op.create_index(
        "ix_engineering_document_nodes_sync_revision",
        "engineering_document_nodes",
        ["sync_revision"],
    )
    op.create_index(
        "ix_engineering_document_project_base_type",
        "engineering_document_nodes",
        ["project_id", "knowledge_base_id", "node_type"],
    )
    op.create_index(
        "ix_engineering_document_project_external",
        "engineering_document_nodes",
        ["project_id", "external_id"],
    )

    op.create_table(
        "engineering_document_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("can_read", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("can_create", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_update", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_delete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_manage", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("inherit_to_children", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
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
            "subject_type IN ('user', 'position')",
            name="ck_engineering_document_permission_subject",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["engineering_document_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "node_id",
            "subject_type",
            "subject_id",
            name="uq_engineering_document_permission_subject_node",
        ),
    )
    op.create_index(
        "ix_engineering_document_permissions_node_id",
        "engineering_document_permissions",
        ["node_id"],
    )
    op.create_index(
        "ix_engineering_document_permissions_project_id",
        "engineering_document_permissions",
        ["project_id"],
    )
    op.create_index(
        "ix_engineering_document_permission_subject",
        "engineering_document_permissions",
        ["project_id", "subject_type", "subject_id"],
    )


def downgrade() -> None:
    """Remove catalogue permissions, nodes and synchronization state."""

    op.drop_index(
        "ix_engineering_document_permission_subject",
        table_name="engineering_document_permissions",
    )
    op.drop_index(
        "ix_engineering_document_permissions_project_id",
        table_name="engineering_document_permissions",
    )
    op.drop_index(
        "ix_engineering_document_permissions_node_id",
        table_name="engineering_document_permissions",
    )
    op.drop_table("engineering_document_permissions")
    op.drop_index(
        "ix_engineering_document_project_external",
        table_name="engineering_document_nodes",
    )
    op.drop_index(
        "ix_engineering_document_project_base_type",
        table_name="engineering_document_nodes",
    )
    op.drop_index(
        "ix_engineering_document_nodes_sync_revision",
        table_name="engineering_document_nodes",
    )
    op.drop_index(
        "ix_engineering_document_nodes_project_id",
        table_name="engineering_document_nodes",
    )
    op.drop_index(
        "ix_engineering_document_nodes_parent_id",
        table_name="engineering_document_nodes",
    )
    op.drop_table("engineering_document_nodes")
    op.drop_table("engineering_document_sync_states")
