"""Authoritative three-drawer memory schema, independent of Mem0."""

MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS memory_records (
    id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    identity_type text NOT NULL CHECK (identity_type IN ('business_user', 'management_user')),
    scope_type text NOT NULL CHECK (scope_type IN ('user', 'user_project', 'project')),
    platform_user_id text NOT NULL DEFAULT '',
    project_id text NOT NULL DEFAULT '',
    fact_key text,
    content text NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 16000),
    memory_type text NOT NULL DEFAULT 'fact',
    importance double precision NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'candidate', 'deleted')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    source jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    embedding public.vector(1024),
    indexed_version integer,
    index_status text NOT NULL DEFAULT 'pending' CHECK (index_status IN ('pending', 'ready', 'failed', 'deleted')),
    legacy_id uuid UNIQUE,
    CONSTRAINT ck_memory_drawer CHECK (
        (scope_type = 'user' AND platform_user_id <> '' AND project_id = '') OR
        (scope_type = 'user_project' AND platform_user_id <> '' AND project_id <> '') OR
        (scope_type = 'project' AND platform_user_id = '' AND project_id <> '' AND identity_type = 'business_user')
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_fact ON memory_records
    (tenant_id, identity_type, scope_type, platform_user_id, project_id, fact_key)
    WHERE fact_key IS NOT NULL AND status <> 'deleted';
CREATE INDEX IF NOT EXISTS ix_memory_drawer ON memory_records
    (tenant_id, identity_type, scope_type, platform_user_id, project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_memory_record_vector ON memory_records
    USING hnsw (embedding public.vector_cosine_ops) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS memory_versions (
    memory_id uuid NOT NULL REFERENCES memory_records(id),
    version integer NOT NULL,
    snapshot jsonb NOT NULL,
    action text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (memory_id, version)
);
CREATE TABLE IF NOT EXISTS memory_requests (
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    request_id text NOT NULL,
    payload_hash text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, actor_id, request_id)
);
CREATE TABLE IF NOT EXISTS memory_index_jobs (
    memory_id uuid PRIMARY KEY REFERENCES memory_records(id),
    version integer NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'failed', 'done')),
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    lease_id uuid,
    error_code text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_memory_job_available ON memory_index_jobs (state, available_at);
CREATE TABLE IF NOT EXISTS memory_legacy_reviews (
    legacy_id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    content text NOT NULL,
    original_payload jsonb NOT NULL,
    reason text NOT NULL,
    resolved_memory_id uuid REFERENCES memory_records(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
"""
