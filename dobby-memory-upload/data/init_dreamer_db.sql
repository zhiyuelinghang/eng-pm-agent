-- data/init_dreamer_db.sql

-- dreamer_run_log: 每次 Dreamer Task 执行记录
CREATE TABLE IF NOT EXISTS dreamer_run_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL,
    task_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    result_json JSONB,
    error_message TEXT,
    run_mode TEXT NOT NULL DEFAULT 'scheduled'
);
CREATE INDEX IF NOT EXISTS idx_dreamer_run_log_project_task
    ON dreamer_run_log(project_id, task_name, started_at DESC);

-- user_activity: 追踪项目每日活跃状态（decay_curves.py:167-184 已引用此表）
CREATE TABLE IF NOT EXISTS user_activity (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL,
    active_on DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE(project_id, active_on)
);

-- experiences 表新增列（幂等 ALTER）
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS recall_count INT DEFAULT 0;
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ;
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS strength FLOAT DEFAULT 1.0;
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS archived_reason TEXT;

-- 新增索引
CREATE INDEX IF NOT EXISTS idx_experiences_status ON experiences(status);
CREATE INDEX IF NOT EXISTS idx_experiences_verified_at ON experiences(verified_at);
CREATE INDEX IF NOT EXISTS idx_experiences_strength ON experiences(strength);
