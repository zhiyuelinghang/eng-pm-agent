-- PostgreSQL init: enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Mem0 memories table (created by Mem0 VectorStoreFactory at runtime)
-- This is just to verify the extension is available.
-- The actual table is auto-created by Mem0.

-- Experience library tables (Phase 1 & 2)
-- These are created by the app migration, included here for reference.

-- CREATE TABLE IF NOT EXISTS experience_extracts (
--   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--   project_id UUID NOT NULL,
--   rollout_id UUID NOT NULL,
--   role_id VARCHAR(64),
--   task TEXT NOT NULL,
--   task_group VARCHAR(128),
--   task_outcome VARCHAR(16),
--   description TEXT,
--   reusable_knowledge TEXT,
--   pitfalls TEXT,
--   keywords TEXT[],
--   keywords_tsv TSVECTOR,
--   citation_path TEXT,
--   embedding VECTOR(1024),
--   importance FLOAT DEFAULT 0.5,
--   created_at TIMESTAMPTZ DEFAULT NOW(),
--   usage_count INT DEFAULT 0,
--   last_used_at TIMESTAMPTZ
-- );

-- SELECT 'PostgreSQL + pgvector ready' AS status;
