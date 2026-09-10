"""Additive learning pipeline schema; no legacy data is reintroduced."""

LEARNING_DDL = """
ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'explicit';
ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS learning jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS last_used_at timestamptz;
ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS use_count integer NOT NULL DEFAULT 0;
ALTER TABLE memory_records DROP CONSTRAINT IF EXISTS memory_records_status_check;
ALTER TABLE memory_records ADD CONSTRAINT memory_records_status_check CHECK (status IN ('active','candidate','inactive','deleted'));
CREATE TABLE IF NOT EXISTS learning_events (
    id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    identity_type text NOT NULL,
    scope_type text NOT NULL,
    platform_user_id text NOT NULL DEFAULT '',
    project_id text NOT NULL DEFAULT '',
    agent_id text NOT NULL,
    session_id text NOT NULL,
    config_owner text NOT NULL,
    event_key text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('explicit','correction','tool_failure','recovery','verified_task','repeated_pattern','feedback','consolidate','skill_compile','business_event','group_chat')),
    evidence jsonb NOT NULL,
    fingerprint text NOT NULL,
    access_snapshot jsonb NOT NULL,
    source_type text NOT NULL DEFAULT 'interaction' CHECK (source_type IN ('interaction','group','business_event')),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,identity_type,agent_id,session_id,event_key),
    CHECK ((scope_type='user' AND platform_user_id<>'' AND project_id='') OR
           (scope_type='user_project' AND platform_user_id<>'' AND project_id<>'') OR
           (scope_type='project' AND platform_user_id='' AND project_id<>'' AND identity_type='business_user'))
);
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'interaction';
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS provenance jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE learning_events DROP CONSTRAINT IF EXISTS learning_events_source_type_check;
ALTER TABLE learning_events ADD CONSTRAINT learning_events_source_type_check CHECK (source_type IN ('interaction','group','business_event'));
CREATE INDEX IF NOT EXISTS ix_learning_event_drawer ON learning_events(tenant_id,identity_type,scope_type,platform_user_id,project_id,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_learning_event_agent ON learning_events(tenant_id,agent_id,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_learning_event_pattern ON learning_events(tenant_id,agent_id,fingerprint,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_learning_memory_fingerprint ON memory_records(tenant_id,(learning->>'fingerprint')) WHERE origin='learning';
CREATE TABLE IF NOT EXISTS learning_jobs (
    id uuid PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE REFERENCES learning_events(id),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','done','skipped','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    lease_id uuid,
    error_code text,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_learning_job_queue ON learning_jobs(state,available_at);
CREATE TABLE IF NOT EXISTS learning_feedback (
    id uuid PRIMARY KEY,
    memory_id uuid NOT NULL REFERENCES memory_records(id),
    memory_version integer NOT NULL,
    actor_id text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('success','failure','irrelevant')),
    evidence text NOT NULL,
    request_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(memory_id,actor_id,request_id)
);
CREATE TABLE IF NOT EXISTS learning_maintenance (
    tenant_id text PRIMARY KEY,
    last_run_at timestamptz NOT NULL DEFAULT now(),
    result jsonb NOT NULL DEFAULT '{}'::jsonb
);
"""

BUSINESS_LEARNING_DDL = """
CREATE TABLE IF NOT EXISTS business_learning_cursors (
    tenant_id text PRIMARY KEY,
    after_id bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""
