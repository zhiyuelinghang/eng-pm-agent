-- Dobby Step 4: experience_extracts table DDL
-- Run once to initialize the experience store in dobby_demo.
--
-- Usage:
--   psql -U dobby -d dobby_demo -f init_experience_db.sql

CREATE TABLE IF NOT EXISTS experience_extracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  task_outcome TEXT,              -- success / partial / fail
  bucket TEXT,                    -- preference / procedure / decision / environment
  description TEXT,
  reusable_knowledge TEXT,
  pitfalls TEXT,
  keywords TEXT[],
  importance FLOAT DEFAULT 0.5,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for idempotency checks (extract_experiences queries by task_id)
CREATE INDEX IF NOT EXISTS idx_extracts_task_id ON experience_extracts (task_id);

-- Index for project-scoped queries
CREATE INDEX IF NOT EXISTS idx_extracts_project_id ON experience_extracts (project_id);

-- Index for filtering by bucket type
CREATE INDEX IF NOT EXISTS idx_extracts_bucket ON experience_extracts (bucket);

-- ============================================================
-- Step 6: Phase 2 migration — embedding column + HNSW index
-- ============================================================

-- Add embedding column for vector similarity search
ALTER TABLE experience_extracts ADD COLUMN IF NOT EXISTS embedding VECTOR(1024);

-- HNSW index for fast top-K nearest-neighbor search (cosine distance)
-- Requires pgvector >= 0.5.0. Falls back to IVFFlat on older versions.
CREATE INDEX IF NOT EXISTS idx_extracts_embedding ON experience_extracts
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- ============================================================
-- Step 6: experiences table (merged/consolidated knowledge)
-- ============================================================

CREATE TABLE IF NOT EXISTS experiences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id TEXT NOT NULL,
  slug VARCHAR(160) NOT NULL,
  body_md TEXT NOT NULL,
  source_extract_ids UUID[] NOT NULL,
  bucket TEXT,
  importance FLOAT DEFAULT 0.5,
  version INT NOT NULL DEFAULT 1,
  consolidated_by VARCHAR(64),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (project_id, slug, version)
);

CREATE INDEX IF NOT EXISTS idx_experiences_project ON experiences (project_id);
CREATE INDEX IF NOT EXISTS idx_experiences_slug ON experiences (project_id, slug);
CREATE INDEX IF NOT EXISTS idx_experiences_bucket ON experiences (bucket);

-- Ensure importance column exists (may be missing from earlier migration)
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS importance FLOAT DEFAULT 0.5;

-- ============================================================
-- Step 6: consolidation_log table (cooldown + audit trail)
-- ============================================================

CREATE TABLE IF NOT EXISTS consolidation_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id TEXT NOT NULL,
  extracts_processed INT DEFAULT 0,
  experiences_created INT DEFAULT 0,
  experiences_updated INT DEFAULT 0,
  wiki_synced INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consolidation_log_project_ts
  ON consolidation_log (project_id, created_at DESC);

-- ============================================================
-- Step 6.1: Event-driven consolidation tracking
-- ============================================================

-- Track which extracts have been consolidated (idempotent ALTER)
ALTER TABLE experience_extracts ADD COLUMN IF NOT EXISTS consolidated_at TIMESTAMPTZ;

-- Partial index for fast pending-count queries per bucket
CREATE INDEX IF NOT EXISTS idx_extracts_pending
  ON experience_extracts (project_id, bucket, consolidated_at)
  WHERE consolidated_at IS NULL;

-- ============================================================
-- Step 10: Skill self-evolution pipeline tables
-- ============================================================

-- Raw event store for runtime experience capture
CREATE TABLE IF NOT EXISTS skill_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  event_type TEXT NOT NULL,           -- tool_error | user_correction | success_pattern
  tool_name TEXT,                     -- 工具名称
  error_message TEXT,                 -- 错误信息
  user_message TEXT,                  -- 用户纠正原文
  previous_response TEXT,             -- Agent 被纠正的回答
  tool_sequence TEXT[],               -- 成功模式工具序列
  tool_count INT,                     -- 工具调用次数
  created_at TIMESTAMPTZ DEFAULT NOW(),
  is_compiled BOOLEAN DEFAULT FALSE,  -- 是否已被编译为技能
  compiled_to_skill TEXT              -- 编译到的技能 slug
);

CREATE INDEX IF NOT EXISTS idx_skill_events_project 
  ON skill_events (project_id);
CREATE INDEX IF NOT EXISTS idx_skill_events_type 
  ON skill_events (event_type);
CREATE INDEX IF NOT EXISTS idx_skill_events_uncompiled 
  ON skill_events (project_id, is_compiled) 
  WHERE is_compiled = FALSE;

-- Compiled skill registry
CREATE TABLE IF NOT EXISTS skill_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id TEXT NOT NULL,
  slug VARCHAR(160) NOT NULL,         -- 确定性去重键
  role_id TEXT NOT NULL,              -- 角色范围: "global" | "safety_director" | ...
  bucket TEXT,                        -- preference|procedure|decision|environment
  title TEXT NOT NULL,                -- 人类可读标题
  body_md TEXT NOT NULL,              -- SKILL.md 正文（含 YAML frontmatter）
  status TEXT DEFAULT 'shadow',       -- shadow|review_pending|active|archived
  tier TEXT DEFAULT 'hot',            -- hot|warm|cold
  importance FLOAT DEFAULT 0.5,
  repeat_count INT DEFAULT 1,         -- 编译来源命中次数
  source_event_ids UUID[],            -- 溯源: skill_events.id[]
  version INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  last_referenced_at TIMESTAMPTZ,     -- 最后引用时间
  reference_count INT DEFAULT 0,      -- 被引用总次数
  reviewed_by TEXT,                   -- 人审确认者
  reviewed_at TIMESTAMPTZ,            -- 人审确认时间
  UNIQUE (project_id, slug, role_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_registry_project 
  ON skill_registry (project_id);
CREATE INDEX IF NOT EXISTS idx_skill_registry_active 
  ON skill_registry (project_id, role_id) 
  WHERE status IN ('active', 'shadow');
