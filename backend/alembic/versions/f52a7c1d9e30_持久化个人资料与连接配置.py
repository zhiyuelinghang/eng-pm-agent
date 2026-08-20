"""持久化个人资料与连接配置

Revision ID: f52a7c1d9e30
Revises: c36e91ab7f42
Create Date: 2026-08-20 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f52a7c1d9e30"
down_revision: str | Sequence[str] | None = "c36e91ab7f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add real profile fields and encrypted connector configuration tables."""

    op.add_column("users", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=200), nullable=True))
    op.add_column("users", sa.Column("title", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("org_name", sa.String(length=200), nullable=True))

    op.add_column(
        "project_risks",
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_risks",
        sa.Column("confirmer_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_risks",
        sa.Column(
            "material_requirements",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_risks",
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_project_risks_responsible_user",
        "project_risks",
        "users",
        ["responsible_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_project_risks_confirmer_user",
        "project_risks",
        "users",
        ["confirmer_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "project_wbs_items",
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_wbs_items",
        sa.Column(
            "raw_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_project_wbs_items_responsible_user",
        "project_wbs_items",
        "users",
        ["responsible_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "project_wbs_quality_requirements",
        sa.Column(
            "required_materials",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_wbs_quality_requirements",
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_wbs_quality_requirements",
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_project_quality_owner_user",
        "project_wbs_quality_requirements",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "user_connector_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("connector_type", sa.String(length=32), nullable=False),
        sa.Column("account_identifier", sa.String(length=500), nullable=False),
        sa.Column("platform_type", sa.String(length=100), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "configured",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
            "connector_type IN ('platform', 'mail', 'wecom', 'feishu', 'dingtalk')",
            name="ck_user_connector_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "connector_type",
            name="uq_user_connector_type",
        ),
    )
    op.create_index(
        "ix_user_connector_configs_user",
        "user_connector_configs",
        ["user_id"],
    )
    op.create_index(
        "ix_user_connector_configs_type",
        "user_connector_configs",
        ["connector_type"],
    )

    op.create_table(
        "project_connector_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("connector_type", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=1000), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "configured",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
            "connector_type IN ('wecom', 'feishu', 'dingtalk')",
            name="ck_project_connector_type",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "connector_type",
            name="uq_project_connector_type",
        ),
    )
    op.create_index(
        "ix_project_connector_configs_project",
        "project_connector_configs",
        ["project_id"],
    )
    op.create_index(
        "ix_project_connector_configs_type",
        "project_connector_configs",
        ["connector_type"],
    )


def downgrade() -> None:
    """Remove connector persistence and optional profile fields."""

    op.drop_index(
        "ix_project_connector_configs_type",
        table_name="project_connector_configs",
    )
    op.drop_index(
        "ix_project_connector_configs_project",
        table_name="project_connector_configs",
    )
    op.drop_table("project_connector_configs")
    op.drop_index(
        "ix_user_connector_configs_type",
        table_name="user_connector_configs",
    )
    op.drop_index(
        "ix_user_connector_configs_user",
        table_name="user_connector_configs",
    )
    op.drop_table("user_connector_configs")
    op.drop_constraint(
        "fk_project_quality_owner_user",
        "project_wbs_quality_requirements",
        type_="foreignkey",
    )
    op.drop_column("project_wbs_quality_requirements", "status")
    op.drop_column("project_wbs_quality_requirements", "owner_user_id")
    op.drop_column("project_wbs_quality_requirements", "required_materials")
    op.drop_constraint(
        "fk_project_wbs_items_responsible_user",
        "project_wbs_items",
        type_="foreignkey",
    )
    op.drop_column("project_wbs_items", "raw_data")
    op.drop_column("project_wbs_items", "responsible_user_id")
    op.drop_constraint(
        "fk_project_risks_confirmer_user",
        "project_risks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_project_risks_responsible_user",
        "project_risks",
        type_="foreignkey",
    )
    op.drop_column("project_risks", "status")
    op.drop_column("project_risks", "material_requirements")
    op.drop_column("project_risks", "confirmer_user_id")
    op.drop_column("project_risks", "responsible_user_id")
    op.drop_column("users", "org_name")
    op.drop_column("users", "title")
    op.drop_column("users", "email")
    op.drop_column("users", "phone")
