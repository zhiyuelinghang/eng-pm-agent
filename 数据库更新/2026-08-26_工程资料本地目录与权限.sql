-- Dobby 工程管理平台数据库更新
-- 版本：c53d891e4fa2 -> d84f2a1c7b90
-- 用途：建立工程资料本地目录、同步状态和用户/项目岗位权限表
--
-- 人工执行前置条件：
--   1. 已完成 PostgreSQL 备份；
--   2. 已停止 Dobby 全部服务；
--   3. 当前连接数据库必须是 projectcopilot；
--   4. platform.alembic_version 当前必须为 c53d891e4fa2，或已经是本版本。
--
-- 本脚本只修改数据库结构，不会连接 WeKnora，也不会同步任何目录或文件。

BEGIN;

DO $guard$
BEGIN
    IF current_database() <> 'projectcopilot' THEN
        RAISE EXCEPTION
            '拒绝更新数据库：当前为 %，要求连接 projectcopilot',
            current_database();
    END IF;
    IF to_regclass('platform.alembic_version') IS NULL THEN
        RAISE EXCEPTION
            'platform.alembic_version 不存在，请先完成平台 PostgreSQL 基线部署';
    END IF;
END
$guard$;

LOCK TABLE platform.alembic_version IN EXCLUSIVE MODE;

DO $revision$
DECLARE
    current_revision text;
BEGIN
    SELECT version_num
      INTO current_revision
      FROM platform.alembic_version
      LIMIT 1;

    IF current_revision = 'd84f2a1c7b90' THEN
        RAISE NOTICE '数据库已经是 d84f2a1c7b90，本次执行为安全复核';
    ELSIF current_revision <> 'c53d891e4fa2' THEN
        RAISE EXCEPTION
            '拒绝跨版本更新：当前版本为 %，要求版本为 c53d891e4fa2',
            COALESCE(current_revision, '<空>');
    END IF;
END
$revision$;

CREATE TABLE IF NOT EXISTS platform.engineering_document_sync_states (
    project_id integer NOT NULL,
    weknora_agent_id varchar(128),
    status varchar(20) DEFAULT 'pending' NOT NULL,
    access_mode varchar(20) DEFAULT 'project' NOT NULL,
    revision integer DEFAULT 0 NOT NULL,
    last_started_at timestamp with time zone,
    last_completed_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_engineering_document_sync_states PRIMARY KEY (project_id),
    CONSTRAINT ck_engineering_document_sync_status
        CHECK (status IN ('pending', 'syncing', 'ready', 'error')),
    CONSTRAINT ck_engineering_document_access_mode
        CHECK (access_mode IN ('project', 'restricted')),
    CONSTRAINT fk_engineering_document_sync_project
        FOREIGN KEY (project_id)
        REFERENCES platform.projects(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform.engineering_document_nodes (
    id serial NOT NULL,
    project_id integer NOT NULL,
    parent_id integer,
    node_type varchar(24) NOT NULL,
    node_key varchar(64) NOT NULL,
    knowledge_base_id varchar(128) NOT NULL,
    external_id varchar(256),
    name varchar(512) NOT NULL,
    folder_path text DEFAULT '' NOT NULL,
    description text,
    file_type varchar(100),
    file_size bigint DEFAULT 0 NOT NULL,
    source varchar(100),
    channel varchar(100),
    parse_status varchar(64),
    enable_status varchar(64),
    document_count integer DEFAULT 0 NOT NULL,
    total_count integer DEFAULT 0 NOT NULL,
    external_created_at varchar(64),
    external_updated_at varchar(64),
    processed_at varchar(64),
    extra_metadata json NOT NULL,
    sync_revision integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_engineering_document_nodes PRIMARY KEY (id),
    CONSTRAINT ck_engineering_document_node_type
        CHECK (node_type IN ('knowledge_base', 'folder', 'file')),
    CONSTRAINT uq_engineering_document_project_node_key
        UNIQUE (project_id, node_key),
    CONSTRAINT fk_engineering_document_node_project
        FOREIGN KEY (project_id)
        REFERENCES platform.projects(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_engineering_document_node_parent
        FOREIGN KEY (parent_id)
        REFERENCES platform.engineering_document_nodes(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_engineering_document_nodes_parent_id
    ON platform.engineering_document_nodes (parent_id);
CREATE INDEX IF NOT EXISTS ix_engineering_document_nodes_project_id
    ON platform.engineering_document_nodes (project_id);
CREATE INDEX IF NOT EXISTS ix_engineering_document_nodes_sync_revision
    ON platform.engineering_document_nodes (sync_revision);
CREATE INDEX IF NOT EXISTS ix_engineering_document_project_base_type
    ON platform.engineering_document_nodes (
        project_id,
        knowledge_base_id,
        node_type
    );
CREATE INDEX IF NOT EXISTS ix_engineering_document_project_external
    ON platform.engineering_document_nodes (project_id, external_id);

CREATE TABLE IF NOT EXISTS platform.engineering_document_permissions (
    id serial NOT NULL,
    project_id integer NOT NULL,
    node_id integer NOT NULL,
    subject_type varchar(20) NOT NULL,
    subject_id integer NOT NULL,
    can_read boolean DEFAULT true NOT NULL,
    can_create boolean DEFAULT false NOT NULL,
    can_update boolean DEFAULT false NOT NULL,
    can_delete boolean DEFAULT false NOT NULL,
    can_manage boolean DEFAULT false NOT NULL,
    inherit_to_children boolean DEFAULT true NOT NULL,
    granted_by_user_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_engineering_document_permissions PRIMARY KEY (id),
    CONSTRAINT ck_engineering_document_permission_subject
        CHECK (subject_type IN ('user', 'position')),
    CONSTRAINT uq_engineering_document_permission_subject_node
        UNIQUE (project_id, node_id, subject_type, subject_id),
    CONSTRAINT fk_engineering_document_permission_project
        FOREIGN KEY (project_id)
        REFERENCES platform.projects(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_engineering_document_permission_node
        FOREIGN KEY (node_id)
        REFERENCES platform.engineering_document_nodes(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_engineering_document_permission_grantor
        FOREIGN KEY (granted_by_user_id)
        REFERENCES platform.users(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_engineering_document_permissions_node_id
    ON platform.engineering_document_permissions (node_id);
CREATE INDEX IF NOT EXISTS ix_engineering_document_permissions_project_id
    ON platform.engineering_document_permissions (project_id);
CREATE INDEX IF NOT EXISTS ix_engineering_document_permission_subject
    ON platform.engineering_document_permissions (
        project_id,
        subject_type,
        subject_id
    );

UPDATE platform.alembic_version
   SET version_num = 'd84f2a1c7b90'
 WHERE version_num = 'c53d891e4fa2';

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM platform.alembic_version
         WHERE version_num = 'd84f2a1c7b90'
    ) THEN
        RAISE EXCEPTION '数据库版本写入失败，事务将回滚';
    END IF;
END
$verify$;

COMMIT;

-- 成功标志：platform.alembic_version = d84f2a1c7b90
