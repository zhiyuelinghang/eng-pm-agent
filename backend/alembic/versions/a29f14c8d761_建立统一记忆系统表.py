"""建立统一记忆系统表

Revision ID: a29f14c8d761
Revises: 6e8049fdaea3
Create Date: 2026-08-13 15:15:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "a29f14c8d761"
down_revision: str | Sequence[str] | None = "6e8049fdaea3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the context-control memory store inside the memory schema."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")
    op.execute("CREATE SCHEMA IF NOT EXISTS memory")
    op.execute(
        """
        CREATE TABLE memory.dobby_memories (
            id UUID PRIMARY KEY,
            vector public.vector(1024),
            payload JSONB NOT NULL
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_memory_vectors_hnsw
        ON memory.dobby_memories
        USING hnsw (vector public.vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_memory_text_search
        ON memory.dobby_memories
        USING gin (to_tsvector('simple', payload->>'text_lemmatized'))
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_memory_scope
        ON memory.dobby_memories (
            (payload->>'user_id'),
            (payload->>'agent_id')
        )
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.memory_audit_log (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128),
            platform_user_id VARCHAR(128),
            agent_id VARCHAR(255),
            session_id VARCHAR(255),
            action VARCHAR(32) NOT NULL,
            memory_id UUID,
            query_text TEXT,
            content_hash CHAR(64),
            result_count INTEGER,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_memory_audit_scope_time
        ON memory.memory_audit_log
        (tenant_id, project_id, created_at DESC)
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.experience_extracts (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            platform_user_id VARCHAR(128),
            agent_id VARCHAR(255),
            session_id VARCHAR(255),
            task_id VARCHAR(255) NOT NULL,
            task_outcome VARCHAR(32),
            bucket VARCHAR(32),
            description TEXT NOT NULL,
            reusable_knowledge TEXT,
            pitfalls TEXT,
            keywords TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
            importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            embedding public.vector(1024),
            consolidated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_experience_extract_importance
                CHECK (importance >= 0 AND importance <= 1)
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_experience_extract_scope
        ON memory.experience_extracts
        (tenant_id, project_id, bucket, created_at DESC)
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_experience_extract_pending
        ON memory.experience_extracts
        (tenant_id, project_id, bucket)
        WHERE consolidated_at IS NULL
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_experience_extract_embedding
        ON memory.experience_extracts
        USING hnsw (embedding public.vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.experiences (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            slug VARCHAR(160) NOT NULL,
            body_md TEXT NOT NULL,
            source_extract_ids UUID[] NOT NULL DEFAULT ARRAY[]::uuid[],
            bucket VARCHAR(32),
            importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            embedding public.vector(1024),
            version INTEGER NOT NULL DEFAULT 1,
            consolidated_by VARCHAR(64),
            recall_count INTEGER NOT NULL DEFAULT 0,
            strength DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            verified_at TIMESTAMPTZ,
            classified_at TIMESTAMPTZ,
            archived_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, project_id, slug, version),
            CONSTRAINT ck_experience_importance
                CHECK (importance >= 0 AND importance <= 1),
            CONSTRAINT ck_experience_strength
                CHECK (strength >= 0 AND strength <= 1)
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_experience_scope_status
        ON memory.experiences
        (tenant_id, project_id, status, bucket, updated_at DESC)
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_experience_embedding
        ON memory.experiences
        USING hnsw (embedding public.vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.consolidation_log (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            extracts_processed INTEGER NOT NULL DEFAULT 0,
            experiences_created INTEGER NOT NULL DEFAULT 0,
            experiences_updated INTEGER NOT NULL DEFAULT 0,
            wiki_synced INTEGER NOT NULL DEFAULT 0,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_consolidation_scope_time
        ON memory.consolidation_log
        (tenant_id, project_id, created_at DESC)
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.graphiti_events (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            event_type VARCHAR(32) NOT NULL,
            body TEXT NOT NULL,
            reference_time TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_graphiti_event_pending
        ON memory.graphiti_events
        (tenant_id, project_id, processed_at, reference_time DESC)
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.dreamer_run_log (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            task_name VARCHAR(64) NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            result_json JSONB,
            error_message TEXT,
            run_mode VARCHAR(32) NOT NULL DEFAULT 'scheduled'
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_dreamer_scope_task_time
        ON memory.dreamer_run_log
        (tenant_id, project_id, task_name, started_at DESC)
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.user_activity (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            active_on DATE NOT NULL DEFAULT CURRENT_DATE,
            UNIQUE (tenant_id, project_id, active_on)
        )
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.skill_events (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            role_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            tool_name VARCHAR(255),
            error_message TEXT,
            user_message TEXT,
            previous_response TEXT,
            tool_sequence TEXT[],
            tool_count INTEGER,
            is_compiled BOOLEAN NOT NULL DEFAULT false,
            compiled_to_skill VARCHAR(160),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_skill_event_uncompiled
        ON memory.skill_events
        (tenant_id, project_id, event_type, created_at)
        WHERE is_compiled = false
        """,
    )
    op.execute(
        """
        CREATE TABLE memory.skill_registry (
            id UUID PRIMARY KEY DEFAULT public.gen_random_uuid(),
            tenant_id VARCHAR(128) NOT NULL,
            project_id VARCHAR(128) NOT NULL,
            slug VARCHAR(160) NOT NULL,
            role_id VARCHAR(255) NOT NULL,
            bucket VARCHAR(32),
            title TEXT NOT NULL,
            body_md TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'shadow',
            tier VARCHAR(32) NOT NULL DEFAULT 'hot',
            importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            repeat_count INTEGER NOT NULL DEFAULT 1,
            source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::uuid[],
            version INTEGER NOT NULL DEFAULT 1,
            last_referenced_at TIMESTAMPTZ,
            reference_count INTEGER NOT NULL DEFAULT 0,
            reviewed_by VARCHAR(255),
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, project_id, slug, role_id),
            CONSTRAINT ck_skill_status
                CHECK (status IN ('shadow', 'review_pending', 'active', 'archived'))
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX ix_skill_registry_injectable
        ON memory.skill_registry
        (tenant_id, project_id, role_id, importance DESC)
        WHERE status IN ('shadow', 'active')
        """,
    )


def downgrade() -> None:
    """Drop context-control tables while keeping the shared schema."""

    for table in (
        "skill_registry",
        "skill_events",
        "user_activity",
        "dreamer_run_log",
        "graphiti_events",
        "consolidation_log",
        "experiences",
        "experience_extracts",
        "memory_audit_log",
        "dobby_memories",
    ):
        op.execute(f'DROP TABLE IF EXISTS memory."{table}" CASCADE')
