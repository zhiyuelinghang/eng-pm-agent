"""建立知识库 pgvector 目录

Revision ID: c8d3f21a7b4e
Revises: a29f14c8d761
Create Date: 2026-08-13 16:30:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "c8d3f21a7b4e"
down_revision: str | Sequence[str] | None = "a29f14c8d761"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the catalog for per-knowledge-base pgvector tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.execute(
        """
        CREATE TABLE knowledge.vector_collections (
            name VARCHAR(255) PRIMARY KEY,
            table_name VARCHAR(63) NOT NULL UNIQUE,
            dimensions INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_vector_collection_dimensions
                CHECK (dimensions BETWEEN 1 AND 16000),
            CONSTRAINT ck_vector_collection_table_name
                CHECK (table_name ~ '^kbv_[0-9a-f]{32}$')
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_vector_collections_created_at
        ON knowledge.vector_collections (created_at DESC)
        """,
    )


def downgrade() -> None:
    """Drop dynamic knowledge-base tables and their catalog."""

    op.execute(
        """
        DO $$
        DECLARE
            item RECORD;
        BEGIN
            IF to_regclass('knowledge.vector_collections') IS NOT NULL THEN
                FOR item IN
                    SELECT table_name FROM knowledge.vector_collections
                LOOP
                    EXECUTE format(
                        'DROP TABLE IF EXISTS knowledge.%I CASCADE',
                        item.table_name
                    );
                END LOOP;
            END IF;
        END
        $$
        """,
    )
    op.execute(
        "DROP TABLE IF EXISTS knowledge.vector_collections CASCADE",
    )
