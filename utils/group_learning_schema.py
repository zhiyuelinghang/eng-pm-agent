"""Durable incremental group learning, separate from interactive reply jobs."""

GROUP_LEARNING_DDL = """
ALTER TABLE learning_events DROP CONSTRAINT IF EXISTS learning_events_event_type_check;
ALTER TABLE learning_events ADD CONSTRAINT learning_events_event_type_check CHECK (event_type IN
    ('explicit','correction','tool_failure','recovery','verified_task','repeated_pattern','feedback','consolidate','skill_compile','group_chat','business_event'));
CREATE TABLE IF NOT EXISTS group_learning_cursors (
    tenant_id text NOT NULL, channel_id bigint NOT NULL,
    project_id text NOT NULL, title text NOT NULL DEFAULT '',
    cursor bigint NOT NULL DEFAULT 0, observed_revision bigint NOT NULL DEFAULT 0,
    invalidation_cursor bigint NOT NULL DEFAULT 0,
    policy_revision bigint NOT NULL DEFAULT 0, paused boolean NOT NULL DEFAULT false,
    last_scan_at timestamptz, last_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(tenant_id,channel_id)
);
CREATE TABLE IF NOT EXISTS group_learning_batches (
    id uuid PRIMARY KEY, tenant_id text NOT NULL, channel_id bigint NOT NULL,
    from_revision bigint NOT NULL, to_revision bigint NOT NULL,
    snapshot jsonb NOT NULL, config_owner text NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','done','skipped','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0, lease_id uuid, lease_until timestamptz,
    available_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz, error_code text, result jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(tenant_id,channel_id,from_revision,to_revision)
);
ALTER TABLE group_learning_batches DROP COLUMN IF EXISTS agent_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_group_learning_open_channel ON group_learning_batches(tenant_id,channel_id)
    WHERE state IN ('pending','running','failed');
CREATE INDEX IF NOT EXISTS ix_group_learning_queue ON group_learning_batches(tenant_id,state,available_at);
CREATE TABLE IF NOT EXISTS group_learning_sources (
    memory_id uuid NOT NULL REFERENCES memory_records(id), tenant_id text NOT NULL,
    channel_id bigint NOT NULL, message_id bigint NOT NULL, message_hash text NOT NULL,
    PRIMARY KEY(memory_id,channel_id,message_id)
);
CREATE INDEX IF NOT EXISTS ix_group_learning_source_channel ON group_learning_sources(tenant_id,channel_id,message_id);
"""
