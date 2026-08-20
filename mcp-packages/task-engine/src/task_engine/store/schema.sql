-- 任务引擎的持久化结构。
--
-- 设计取舍：节点与流转记录用独立表而非 JSON 列，因为「谁在哪一步卡住了」「这条记录
-- 是谁改的」是核心查询，需要索引支撑。任务流定义里的 steps 则用 JSON——它是模板，
-- 整体读写，不单独查询。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 任务流定义（模板）
CREATE TABLE IF NOT EXISTS flows (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'general',
    priority        TEXT NOT NULL DEFAULT 'normal',
    origin          TEXT NOT NULL DEFAULT 'manual',
    origin_note     TEXT NOT NULL DEFAULT '',
    steps_json      TEXT NOT NULL,           -- StepSpec 数组
    watchers_json   TEXT NOT NULL DEFAULT '[]',
    tags_json       TEXT NOT NULL DEFAULT '[]',
    scope_json      TEXT NOT NULL DEFAULT '{}',
    -- 工点与确认人：工程责任制要求任务能回答「在哪」「谁验收」
    site_ref        TEXT NOT NULL DEFAULT '',
    site_name       TEXT NOT NULL DEFAULT '',
    site_code       TEXT NOT NULL DEFAULT '',
    confirmer_ref   TEXT NOT NULL DEFAULT '',
    confirmer_name  TEXT NOT NULL DEFAULT '',
    -- 触发规则内联存储：查询计划时总是连带读取，拆表反而增加 join
    run_mode        TEXT NOT NULL DEFAULT 'once',
    first_at        TEXT,
    interval_value  INTEGER NOT NULL DEFAULT 1,
    interval_unit   TEXT NOT NULL DEFAULT 'week',
    timezone        TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    until_at        TEXT,
    max_fires       INTEGER,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flows_category ON flows (category);

-- 触发计划：把任务流与时间绑定。引擎相对宿主系统的核心增量。
CREATE TABLE IF NOT EXISTS schedules (
    id              TEXT PRIMARY KEY,
    flow_id         TEXT NOT NULL REFERENCES flows (id) ON DELETE CASCADE,
    next_fire_at    TEXT,                    -- NULL 表示已走完
    last_fire_at    TEXT,
    fire_count      INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1,
    paused          INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- tick 的核心查询：找出所有到期的计划
CREATE INDEX IF NOT EXISTS idx_schedules_due
    ON schedules (next_fire_at) WHERE active = 1 AND paused = 0;

-- 任务实例
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    flow_id         TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'pending',
    priority        TEXT NOT NULL DEFAULT 'normal',
    category        TEXT NOT NULL DEFAULT 'general',
    trigger_note    TEXT NOT NULL DEFAULT '',
    watchers_json   TEXT NOT NULL DEFAULT '[]',
    tags_json       TEXT NOT NULL DEFAULT '[]',
    scope_json      TEXT NOT NULL DEFAULT '{}',
    -- 工点与确认人
    site_ref        TEXT NOT NULL DEFAULT '',
    site_name       TEXT NOT NULL DEFAULT '',
    site_code       TEXT NOT NULL DEFAULT '',
    confirmer_ref   TEXT NOT NULL DEFAULT '',
    confirmer_name  TEXT NOT NULL DEFAULT '',
    due_at          TEXT,                    -- 冗余存储，用于逾期扫描的索引
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    closed_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks (state);
-- 按工点检索任务：工程管理的常见查询
CREATE INDEX IF NOT EXISTS idx_tasks_site ON tasks (site_ref);
-- 按确认人检索待验收任务
CREATE INDEX IF NOT EXISTS idx_tasks_confirmer ON tasks (confirmer_ref, state);
-- 逾期扫描：只关心未闭环的任务
CREATE INDEX IF NOT EXISTS idx_tasks_due
    ON tasks (due_at) WHERE state NOT IN ('done', 'cancelled');

-- 节点（任务实例的运行时步骤）
CREATE TABLE IF NOT EXISTS steps (
    task_id             TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    seq                 INTEGER NOT NULL,
    name                TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'waiting',
    assignee_ref        TEXT NOT NULL DEFAULT '',
    assignee_name       TEXT NOT NULL DEFAULT '',
    due_at              TEXT,
    deliverable         TEXT NOT NULL DEFAULT '',
    instruction         TEXT NOT NULL DEFAULT '',
    requires_attachment INTEGER NOT NULL DEFAULT 0,
    optional            INTEGER NOT NULL DEFAULT 0,
    started_at          TEXT,
    finished_at         TEXT,
    finished_by         TEXT NOT NULL DEFAULT '',
    comment             TEXT NOT NULL DEFAULT '',
    attachments_json    TEXT NOT NULL DEFAULT '[]',
    -- 被退回重做的标记：要求留证的节点必须重新提交材料
    reopened            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (task_id, seq)
);

-- 「我的任务」查询：某人当前负责哪些活跃节点
CREATE INDEX IF NOT EXISTS idx_steps_assignee
    ON steps (assignee_ref, state);

-- 流转记录：任务的完整审计轨迹
CREATE TABLE IF NOT EXISTS activities (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT '',
    step_seq    INTEGER,
    summary     TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_activities_task ON activities (task_id, at);

-- 触发日志：保证同一计划同一时刻只创建一次任务。
-- 主键即幂等锁——重复 tick 会撞主键冲突而非重复建任务。
CREATE TABLE IF NOT EXISTS fire_log (
    schedule_id TEXT NOT NULL,
    fire_at     TEXT NOT NULL,
    task_id     TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (schedule_id, fire_at)
);
