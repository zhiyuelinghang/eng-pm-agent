import json
import sqlite3

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.models import (
    Project,
    ProjectMemberPosition,
    QualityMetric,
    RiskSource,
    User,
    WbsItem,
)
from backend.app.schema_migrations import upgrade_database_schema


def _create_legacy_database(database_path: str) -> None:
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            real_name VARCHAR(100) NOT NULL,
            phone VARCHAR(50),
            email VARCHAR(200),
            title VARCHAR(100),
            org_name VARCHAR(200),
            role VARCHAR(32) NOT NULL DEFAULT 'member',
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            project_name VARCHAR(200) NOT NULL,
            owner_unit VARCHAR(200),
            description TEXT,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        CREATE TABLE project_members (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            member_role VARCHAR(32) NOT NULL DEFAULT 'member',
            display_name VARCHAR(100),
            phone VARCHAR(50),
            responsibilities JSON NOT NULL DEFAULT '[]',
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            UNIQUE(project_id, user_id)
        );
        CREATE TABLE wbs_items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            parent_id INTEGER REFERENCES wbs_items(id),
            code VARCHAR(100) NOT NULL,
            name VARCHAR(300) NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            planned_start VARCHAR(32),
            planned_finish VARCHAR(32),
            progress INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'not_started',
            responsible_user_id INTEGER REFERENCES users(id),
            raw_data JSON NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        CREATE TABLE risk_sources (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name VARCHAR(300) NOT NULL,
            level VARCHAR(32) NOT NULL DEFAULT 'medium',
            risk_type VARCHAR(100) NOT NULL DEFAULT '综合风险',
            planned_start VARCHAR(32),
            planned_finish VARCHAR(32),
            responsible_user_id INTEGER REFERENCES users(id),
            confirmer_user_id INTEGER REFERENCES users(id),
            material_requirements JSON NOT NULL DEFAULT '[]',
            control_requirements TEXT,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        CREATE TABLE quality_metrics (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            wbs_item_id INTEGER REFERENCES wbs_items(id),
            name VARCHAR(300) NOT NULL,
            requirement TEXT NOT NULL,
            inspection_frequency VARCHAR(200),
            required_materials JSON NOT NULL DEFAULT '[]',
            owner_user_id INTEGER REFERENCES users(id),
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );

        INSERT INTO users (
            id, username, password_hash, real_name, title, role
        ) VALUES (1, 'admin', 'hash', '系统管理员', '项目经理', 'superadmin');
        INSERT INTO projects (
            id, project_name, owner_unit, description
        ) VALUES (1, '旧版工程', '旧建设单位', '旧版工程说明');
        INSERT INTO project_members (
            id, project_id, user_id, member_role, responsibilities
        ) VALUES (1, 1, 1, 'manager', '["项目统筹"]');
        INSERT INTO wbs_items (
            id, project_id, code, name, level, planned_start,
            planned_finish, progress, status
        ) VALUES (
            1, 1, '1.1', '基础施工', 2, '2026-07-01',
            '2026-07-31', 20, '进行中'
        );
        INSERT INTO risk_sources (
            id, project_id, name, level, risk_type, planned_start,
            planned_finish, control_requirements
        ) VALUES (
            1, 1, '基坑风险', '重大', '基础施工', '2026-07-01',
            '2026-07-31', '按风险清单检查'
        );
        INSERT INTO quality_metrics (
            id, project_id, wbs_item_id, name, requirement,
            inspection_frequency, required_materials
        ) VALUES (
            1, 1, 1, '基础验收', '符合设计要求', '每道工序', '["验收记录"]'
        );
        """,
    )
    connection.commit()
    connection.close()


def test_legacy_sqlite_schema_is_backed_up_and_migrated(tmp_path) -> None:
    database_path = tmp_path / "engpm.db"
    _create_legacy_database(str(database_path))
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    upgrade_database_schema(engine, Base.metadata)
    upgrade_database_schema(engine, Base.metadata)

    table_names = set(inspect(engine).get_table_names())
    assert {
        "database_interaction_table_policies",
        "database_interactions",
        "database_interaction_agent_assignments",
    } <= table_names

    with Session(engine) as db:
        user = db.scalar(select(User).where(User.id == 1))
        project = db.scalar(select(Project).where(Project.id == 1))
        assignment = db.scalar(select(ProjectMemberPosition))
        wbs = db.scalar(select(WbsItem).where(WbsItem.id == 1))
        risk = db.scalar(select(RiskSource).where(RiskSource.id == 1))
        quality = db.scalar(select(QualityMetric).where(QualityMetric.project_id == 1))

        assert user is not None
        assert user.identity_card_no == "SYSTEM_ADMIN"
        assert user.role == "admin"
        assert project is not None
        assert project.name == "旧版工程"
        assert project.engineering_type_description == "旧版工程说明"
        assert project.construction_unit_name == "旧建设单位"
        assert assignment is not None
        assert assignment.responsibility_description == '["项目统筹"]'
        assert wbs is not None
        assert wbs.wbs_code == "1.1"
        assert wbs.status_text == "进行中"
        assert risk is not None
        assert risk.related_process_name == "基础施工"
        assert risk.risk_window_start_date.isoformat() == "2026-07-01"
        assert quality is not None
        assert quality.wbs_code == "1.1"

        db.add(Project(name="迁移后新建项目"))
        db.commit()

    assert database_path.with_suffix(".db.pre-schema-v2.bak").exists()
    engine.dispose()


def test_existing_database_interactions_receive_join_rules_column(tmp_path) -> None:
    database_path = tmp_path / "existing-interactions.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE database_interactions (
            id INTEGER PRIMARY KEY,
            key VARCHAR(128) NOT NULL,
            display_name VARCHAR(100) NOT NULL
        );
        INSERT INTO database_interactions (id, key, display_name)
        VALUES (1, 'existing_query', '已有查询');
        """,
    )
    connection.commit()
    connection.close()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    upgrade_database_schema(engine, Base.metadata)
    upgrade_database_schema(engine, Base.metadata)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("database_interactions")
    }
    assert {
        "join_rules",
        "context_bindings",
        "fixed_values",
        "runtime_policy",
        "allowed_conversation_types",
        "access_mode",
    } <= columns
    with engine.connect() as database:
        values = database.exec_driver_sql(
            "SELECT join_rules, context_bindings, fixed_values, "
            "runtime_policy, allowed_conversation_types, access_mode "
            "FROM database_interactions WHERE id = 1",
        ).one()
    assert values.join_rules == "[]"
    assert values.context_bindings == "[]"
    assert values.fixed_values == "{}"
    assert values.runtime_policy == "{}"
    assert json.loads(values.allowed_conversation_types) == [
        "general",
        "business",
        "initialization",
    ]
    assert values.access_mode == "agent"
    assert database_path.with_suffix(
        ".db.pre-database-joins.bak",
    ).exists()
    engine.dispose()


def test_existing_attachment_texts_receive_pipeline_state(tmp_path) -> None:
    database_path = tmp_path / "existing-attachment-texts.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE attachment_texts (
            attachment_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            extracted_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        INSERT INTO attachment_texts (attachment_id, project_id, content)
        VALUES (1, 1, '旧版提取内容');
        """,
    )
    connection.commit()
    connection.close()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    upgrade_database_schema(engine, Base.metadata)
    upgrade_database_schema(engine, Base.metadata)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("attachment_texts")
    }
    assert {
        "parse_status",
        "parser",
        "parse_error",
        "parse_details",
    } <= columns
    with engine.connect() as database:
        row = database.exec_driver_sql(
            "SELECT parse_status, parser, parse_details "
            "FROM attachment_texts WHERE attachment_id = 1",
        ).one()
    assert row.parse_status == "legacy"
    assert row.parser == "legacy_extractor"
    assert json.loads(row.parse_details)["status"] == "legacy"
    engine.dispose()
