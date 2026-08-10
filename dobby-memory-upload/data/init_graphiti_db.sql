-- Dobby Step 7: graphiti_events queue table DDL
-- Run once to initialize the Graphiti event store in dobby_demo.
--
-- Usage:
--   psql -U dobby -d dobby_demo -f init_graphiti_db.sql

-- ============================================================
-- graphiti_events — event queue for Graphiti Neo4j ingestion
-- ============================================================
CREATE TABLE IF NOT EXISTS graphiti_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    -- risk_created | risk_resolved | task_completed | state_changed
    body TEXT NOT NULL,
    -- episode_body, free-text event description
    reference_time TIMESTAMPTZ DEFAULT NOW(),
    -- event time → Graphiti valid_at
    processed_at TIMESTAMPTZ,
    -- NULL = pending, NOT NULL = written to Neo4j
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Index: project-level pending event lookup
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_ge_project
    ON graphiti_events(project_id, processed_at);
