"""补齐项目初始化运行状态表

Revision ID: e1046bc92ad7
Revises: c8d3f21a7b4e
Create Date: 2026-08-13 17:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e1046bc92ad7"
down_revision: str | Sequence[str] | None = "c8d3f21a7b4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initialization run, step and parsed-chunk tables."""

    op.create_table(
        "project_initialization_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("current_step_key", sa.String(length=80), nullable=True),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("source_file_ids", sa.JSON(), nullable=False),
        sa.Column("source_files", sa.JSON(), nullable=False),
        sa.Column("detected_sections", sa.JSON(), nullable=False),
        sa.Column("completed_sections", sa.JSON(), nullable=False),
        sa.Column("failed_sections", sa.JSON(), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column("semantic_review_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("final_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ("
            "'queued', 'parsing', 'extracting', 'validating', 'ready', "
            "'needs_attention', 'failed', 'cancelling', 'cancelled', 'applied'"
            ")",
            name="ck_project_initialization_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["project_initialization_drafts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_project_initialization_runs_project_id", ["project_id"]),
        ("ix_project_initialization_runs_conversation_id", ["conversation_id"]),
        ("ix_project_initialization_runs_created_by_user_id", ["created_by_user_id"]),
        ("ix_project_initialization_runs_draft_id", ["draft_id"]),
        ("ix_project_initialization_runs_status", ["status"]),
        (
            "ix_project_initialization_runs_project_status",
            ["project_id", "status", "created_at"],
        ),
    ):
        op.create_index(name, "project_initialization_runs", columns)

    op.create_table(
        "project_initialization_run_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("section", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="ck_project_initialization_run_steps_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["project_initialization_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "step_key",
            name="uq_project_initialization_run_steps_key",
        ),
    )
    for name, columns in (
        ("ix_project_initialization_run_steps_run_id", ["run_id"]),
        ("ix_project_initialization_run_steps_project_id", ["project_id"]),
        (
            "ix_project_initialization_run_steps_conversation_id",
            ["conversation_id"],
        ),
        ("ix_project_initialization_run_steps_status", ["status"]),
        (
            "ix_project_initialization_run_steps_run_order",
            ["run_id", "sort_order"],
        ),
    ):
        op.create_index(name, "project_initialization_run_steps", columns)

    op.create_table(
        "project_initialization_parsed_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=100), nullable=False),
        sa.Column("content_format", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_payload", sa.JSON(), nullable=True),
        sa.Column("section_hints", sa.JSON(), nullable=False),
        sa.Column("source_location", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
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
            "chunk_index >= 0",
            name="ck_project_initialization_parsed_chunks_index",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["project_initialization_files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["project_initialization_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "file_id",
            "chunk_index",
            name="uq_project_initialization_parsed_chunks_position",
        ),
    )
    for name, columns in (
        ("ix_project_initialization_parsed_chunks_run_id", ["run_id"]),
        ("ix_project_initialization_parsed_chunks_file_id", ["file_id"]),
        ("ix_project_initialization_parsed_chunks_content_hash", ["content_hash"]),
        (
            "ix_project_initialization_parsed_chunks_run_file",
            ["run_id", "file_id", "chunk_index"],
        ),
    ):
        op.create_index(name, "project_initialization_parsed_chunks", columns)


def downgrade() -> None:
    """Drop initialization workflow state tables in dependency order."""

    op.drop_table("project_initialization_parsed_chunks")
    op.drop_table("project_initialization_run_steps")
    op.drop_table("project_initialization_runs")
