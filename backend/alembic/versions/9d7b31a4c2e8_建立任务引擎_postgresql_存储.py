"""建立任务引擎 PostgreSQL 存储

Revision ID: 9d7b31a4c2e8
Revises: f52a7c1d9e30
Create Date: 2026-08-20 14:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9d7b31a4c2e8"
down_revision: str | Sequence[str] | None = "f41c9d7e2b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "task_engine"


def upgrade() -> None:
    """Create the guide-defined task-engine structure in PostgreSQL."""

    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))

    op.create_table(
        "flows",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.Text(), server_default="general", nullable=False),
        sa.Column("priority", sa.Text(), server_default="normal", nullable=False),
        sa.Column("origin", sa.Text(), server_default="manual", nullable=False),
        sa.Column("origin_note", sa.Text(), server_default="", nullable=False),
        sa.Column("steps_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "watchers_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "scope_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("site_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("site_name", sa.Text(), server_default="", nullable=False),
        sa.Column("site_code", sa.Text(), server_default="", nullable=False),
        sa.Column("confirmer_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("confirmer_name", sa.Text(), server_default="", nullable=False),
        sa.Column("run_mode", sa.Text(), server_default="once", nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_value", sa.Integer(), server_default="1", nullable=False),
        sa.Column("interval_unit", sa.Text(), server_default="week", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Asia/Shanghai", nullable=False),
        sa.Column("until_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_fires", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_flows_category",
        "flows",
        ["category"],
        schema=SCHEMA,
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("flow_id", sa.Text(), nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fire_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            [f"{SCHEMA}.flows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_schedules_due",
        "schedules",
        ["next_fire_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("active IS TRUE AND paused IS FALSE"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("flow_id", sa.Text(), server_default="", nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("state", sa.Text(), server_default="pending", nullable=False),
        sa.Column("priority", sa.Text(), server_default="normal", nullable=False),
        sa.Column("category", sa.Text(), server_default="general", nullable=False),
        sa.Column("trigger_note", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "watchers_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "scope_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("site_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("site_name", sa.Text(), server_default="", nullable=False),
        sa.Column("site_code", sa.Text(), server_default="", nullable=False),
        sa.Column("confirmer_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("confirmer_name", sa.Text(), server_default="", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index("idx_tasks_state", "tasks", ["state"], schema=SCHEMA)
    op.create_index("idx_tasks_site", "tasks", ["site_ref"], schema=SCHEMA)
    op.create_index(
        "idx_tasks_confirmer",
        "tasks",
        ["confirmer_ref", "state"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_tasks_due",
        "tasks",
        ["due_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("state NOT IN ('done', 'cancelled')"),
    )

    op.create_table(
        "steps",
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="waiting", nullable=False),
        sa.Column("assignee_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("assignee_name", sa.Text(), server_default="", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deliverable", sa.Text(), server_default="", nullable=False),
        sa.Column("instruction", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "requires_attachment",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("optional", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_by", sa.Text(), server_default="", nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "attachments_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("reopened", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            [f"{SCHEMA}.tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", "seq"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_steps_assignee",
        "steps",
        ["assignee_ref", "state"],
        schema=SCHEMA,
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text(), server_default="", nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            [f"{SCHEMA}.tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_activities_task",
        "activities",
        ["task_id", "at"],
        schema=SCHEMA,
    )

    op.create_table(
        "fire_log",
        sa.Column("schedule_id", sa.Text(), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", sa.Text(), server_default="", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("schedule_id", "fire_at"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove the PostgreSQL task-engine structure."""

    op.drop_table("fire_log", schema=SCHEMA)
    op.drop_index("idx_activities_task", table_name="activities", schema=SCHEMA)
    op.drop_table("activities", schema=SCHEMA)
    op.drop_index("idx_steps_assignee", table_name="steps", schema=SCHEMA)
    op.drop_table("steps", schema=SCHEMA)
    op.drop_index("idx_tasks_due", table_name="tasks", schema=SCHEMA)
    op.drop_index("idx_tasks_confirmer", table_name="tasks", schema=SCHEMA)
    op.drop_index("idx_tasks_site", table_name="tasks", schema=SCHEMA)
    op.drop_index("idx_tasks_state", table_name="tasks", schema=SCHEMA)
    op.drop_table("tasks", schema=SCHEMA)
    op.drop_index("idx_schedules_due", table_name="schedules", schema=SCHEMA)
    op.drop_table("schedules", schema=SCHEMA)
    op.drop_index("idx_flows_category", table_name="flows", schema=SCHEMA)
    op.drop_table("flows", schema=SCHEMA)
    op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{SCHEMA}"'))
