"""Small, idempotent migrations for the platform's embedded SQLite database.

The project historically relied on ``MetaData.create_all``.  That creates new
tables but cannot rename columns or upgrade existing tables, so installations
created before the structured project-initialization schema need one explicit
bridge migration.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine


def _table_exists(cursor: Any, table_name: str) -> bool:
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _columns(cursor: Any, table_name: str) -> set[str]:
    if not _table_exists(cursor, table_name):
        return set()
    return {str(row[1]) for row in cursor.execute(f'PRAGMA table_info("{table_name}")')}


def _backup_sqlite_database(engine: Engine) -> Path | None:
    database_name = engine.url.database
    if not database_name or database_name == ":memory:":
        return None
    database_path = Path(database_name)
    if not database_path.exists():
        return None
    backup_path = database_path.with_suffix(database_path.suffix + ".pre-schema-v2.bak")
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database_path, backup_path)
    return backup_path


def _prepare_legacy_sqlite_schema(engine: Engine) -> bool:
    """Upgrade shared legacy tables before current tables are created."""

    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    legacy_projects = False
    try:
        user_columns = _columns(cursor, "users")
        project_columns = _columns(cursor, "projects")
        legacy_projects = bool(project_columns and "name" not in project_columns)
        needs_upgrade = (
            bool(user_columns and "identity_card_no" not in user_columns)
            or legacy_projects
        )
        if not needs_upgrade:
            return False

        _backup_sqlite_database(engine)
        cursor.execute("PRAGMA foreign_keys=OFF")

        if user_columns and "identity_card_no" not in user_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN identity_card_no VARCHAR(30)",
            )
            cursor.execute(
                "UPDATE users SET identity_card_no = CASE "
                "WHEN username = 'admin' THEN 'SYSTEM_ADMIN' "
                "ELSE 'LEGACY_' || id END "
                "WHERE identity_card_no IS NULL OR TRIM(identity_card_no) = ''",
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_identity_card_no "
                "ON users(identity_card_no)",
            )

        if user_columns and "role" in user_columns:
            cursor.execute(
                "UPDATE users SET role = CASE "
                "WHEN role IN ('admin', 'superadmin') OR username = 'admin' "
                "THEN 'admin' ELSE 'user' END",
            )

        if legacy_projects:
            cursor.execute("DROP TABLE IF EXISTS projects__schema_v2")
            cursor.execute(
                """
                CREATE TABLE projects__schema_v2 (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    engineering_type_description TEXT,
                    contract_start_date DATE,
                    contract_end_date DATE,
                    contract_duration_days INTEGER,
                    contract_amount_wan_yuan NUMERIC(18, 2),
                    construction_unit_name VARCHAR(300),
                    general_contractor_unit_name VARCHAR(300),
                    supervision_unit_name VARCHAR(300),
                    design_unit_name VARCHAR(300),
                    survey_unit_name VARCHAR(300),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    CONSTRAINT ck_projects_contract_duration_positive
                        CHECK (contract_duration_days IS NULL OR contract_duration_days > 0),
                    CONSTRAINT ck_projects_contract_amount_nonnegative
                        CHECK (contract_amount_wan_yuan IS NULL OR contract_amount_wan_yuan >= 0),
                    CONSTRAINT ck_projects_contract_date_order
                        CHECK (contract_end_date IS NULL OR contract_start_date IS NULL
                            OR contract_end_date >= contract_start_date)
                )
                """,
            )
            name_expression = (
                "COALESCE(NULLIF(TRIM(project_name), ''), '未命名项目-' || id)"
                if "project_name" in project_columns
                else "'未命名项目-' || id"
            )
            description_expression = (
                "description" if "description" in project_columns else "NULL"
            )
            owner_expression = (
                "owner_unit" if "owner_unit" in project_columns else "NULL"
            )
            created_expression = (
                "created_at" if "created_at" in project_columns else "CURRENT_TIMESTAMP"
            )
            updated_expression = (
                "updated_at" if "updated_at" in project_columns else "CURRENT_TIMESTAMP"
            )
            cursor.execute(
                f"""
                INSERT INTO projects__schema_v2 (
                    id, name, engineering_type_description,
                    construction_unit_name, created_at, updated_at
                )
                SELECT id, {name_expression}, {description_expression},
                    {owner_expression}, {created_expression}, {updated_expression}
                FROM projects
                """,
            )
            cursor.execute("DROP TABLE projects")
            cursor.execute("ALTER TABLE projects__schema_v2 RENAME TO projects")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS ix_projects_name ON projects(name)",
            )

        raw_connection.commit()
        return legacy_projects
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            raw_connection.close()


def _copy_legacy_business_data(engine: Engine) -> None:
    """Copy pre-v2 business rows into the new canonical tables once."""

    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")

        if _table_exists(cursor, "project_members"):
            member_columns = _columns(cursor, "project_members")
            user_columns = _columns(cursor, "users")
            if "member_role" in member_columns:
                position_source = (
                    "COALESCE(NULLIF(TRIM(u.title), ''), "
                    "NULLIF(TRIM(pm.member_role), ''), '项目成员')"
                    if "title" in user_columns
                    else "COALESCE(NULLIF(TRIM(pm.member_role), ''), '项目成员')"
                )
                cursor.execute(
                    f"""
                    INSERT OR IGNORE INTO project_positions (
                        project_id, position_name, created_at, updated_at
                    )
                    SELECT DISTINCT pm.project_id, {position_source},
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    FROM project_members pm
                    JOIN users u ON u.id = pm.user_id
                    """,
                )
                responsibility_source = (
                    "COALESCE(pm.responsibilities, '')"
                    if "responsibilities" in member_columns
                    else "''"
                )
                cursor.execute(
                    f"""
                    INSERT OR IGNORE INTO project_personnel_assignments (
                        project_id, project_member_id, position_id, serial_no,
                        certificate_no, responsibility_description,
                        created_at, updated_at
                    )
                    SELECT pm.project_id, pm.id, pp.id, pm.id, '',
                        {responsibility_source}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    FROM project_members pm
                    JOIN users u ON u.id = pm.user_id
                    JOIN project_positions pp
                      ON pp.project_id = pm.project_id
                     AND pp.position_name = {position_source}
                    """,
                )

        if _table_exists(cursor, "wbs_items"):
            cursor.execute(
                """
                INSERT OR IGNORE INTO project_wbs_items (
                    id, project_id, parent_id, sort_order, wbs_code, name,
                    planned_start_at, planned_finish_at, progress_percent,
                    status_text, level, created_at, updated_at
                )
                SELECT id, project_id, parent_id, id, code, name,
                    planned_start, planned_finish, progress, status, level,
                    created_at, updated_at
                FROM wbs_items
                """,
            )

        if _table_exists(cursor, "risk_sources"):
            cursor.execute(
                """
                INSERT OR IGNORE INTO project_risks (
                    id, project_id, serial_no, related_process_name,
                    risk_part, risk_level, evaluation_condition,
                    risk_window_start_date, risk_window_end_date, summary,
                    created_at, updated_at
                )
                SELECT id, project_id,
                    ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY id),
                    COALESCE(risk_type, ''), name, COALESCE(level, '未分级'),
                    COALESCE(control_requirements, ''),
                    planned_start, planned_finish, NULL, created_at, updated_at
                FROM risk_sources
                """,
            )

        if _table_exists(cursor, "quality_metrics") and _table_exists(cursor, "wbs_items"):
            cursor.execute(
                """
                INSERT OR IGNORE INTO project_wbs_quality_requirements (
                    project_id, wbs_code, quality_acceptance_item,
                    control_indicator, inspection_frequency,
                    related_documents, created_at, updated_at
                )
                SELECT qm.project_id, w.code, qm.name, qm.requirement,
                    COALESCE(qm.inspection_frequency, ''),
                    COALESCE(qm.required_materials, '[]'),
                    qm.created_at, qm.updated_at
                FROM quality_metrics qm
                JOIN wbs_items w ON w.id = qm.wbs_item_id
                """,
            )

        cursor.execute(
            "CREATE TABLE IF NOT EXISTS platform_schema_versions ("
            "version INTEGER NOT NULL PRIMARY KEY, "
            "applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        )
        cursor.execute(
            "INSERT OR IGNORE INTO platform_schema_versions(version) VALUES (2)",
        )
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            raw_connection.close()


def _ensure_database_interaction_join_rules(engine: Engine) -> None:
    """Add the declarative multi-table relation column to existing installs."""
    inspector = inspect(engine)
    if "database_interactions" not in inspector.get_table_names():
        return
    columns = {
        str(column["name"])
        for column in inspector.get_columns("database_interactions")
    }
    if "join_rules" in columns:
        return

    if engine.dialect.name == "sqlite":
        database_name = engine.url.database
        if database_name and database_name != ":memory:":
            database_path = Path(database_name)
            if database_path.exists():
                backup_path = database_path.with_suffix(
                    database_path.suffix + ".pre-database-joins.bak",
                )
                if not backup_path.exists():
                    shutil.copy2(database_path, backup_path)
        ddl = (
            "ALTER TABLE database_interactions "
            "ADD COLUMN join_rules JSON NOT NULL DEFAULT '[]'"
        )
    else:
        ddl = (
            "ALTER TABLE database_interactions "
            "ADD COLUMN join_rules JSON NOT NULL DEFAULT '[]'"
        )
    with engine.begin() as connection:
        connection.execute(text(ddl))


def _ensure_database_interaction_runtime_rules(engine: Engine) -> None:
    """Add declarative caller, conversation and context-binding rules."""
    table_name = "database_interactions"
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    columns = {
        str(column["name"])
        for column in inspector.get_columns(table_name)
    }
    statements: list[str] = []
    if "context_bindings" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "context_bindings JSON NOT NULL DEFAULT '[]'",
        )
    if "fixed_values" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "fixed_values JSON NOT NULL DEFAULT '{}'",
        )
    if "runtime_policy" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "runtime_policy JSON NOT NULL DEFAULT '{}'",
        )
    if "allowed_conversation_types" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "allowed_conversation_types JSON NOT NULL "
            "DEFAULT '[\"general\",\"business\",\"initialization\"]'",
        )
    if "access_mode" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "access_mode VARCHAR(16) NOT NULL DEFAULT 'agent'",
        )
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_attachment_text_pipeline_fields(engine: Engine) -> None:
    """Add auditable parser state to document text created by old installs."""
    table_name = "attachment_texts"
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    columns = {
        str(column["name"])
        for column in inspector.get_columns(table_name)
    }
    statements: list[str] = []
    if "parse_status" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "parse_status VARCHAR(32) NOT NULL DEFAULT 'legacy'",
        )
    if "parser" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN parser VARCHAR(100)",
        )
    if "parse_error" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN parse_error TEXT",
        )
    if "parse_details" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "parse_details JSON NOT NULL DEFAULT '{}'",
        )
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                f"UPDATE {table_name} SET parser = 'legacy_extractor', "
                "parse_details = :details "
                "WHERE parse_status = 'legacy'",
            ),
            {
                "details": json.dumps(
                    {"version": 0, "status": "legacy"},
                    ensure_ascii=False,
                ),
            },
        )


def _ensure_initialization_draft_record_version_fields(engine: Engine) -> None:
    """Keep addressable draft-row history compatible with older installs."""
    table_name = "project_initialization_draft_records"
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    columns = {
        str(column["name"])
        for column in inspector.get_columns(table_name)
    }
    statements: list[str] = []
    if "section_revision" not in columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            "section_revision INTEGER NOT NULL DEFAULT 1",
        )
    if "active" not in columns:
        boolean_default = "1" if engine.dialect.name == "sqlite" else "TRUE"
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN "
            f"active BOOLEAN NOT NULL DEFAULT {boolean_default}",
        )
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    refreshed = inspect(engine)
    index_names = {
        str(index["name"])
        for index in refreshed.get_indexes(table_name)
        if index.get("name")
    }
    index_name = "ix_project_initialization_draft_records_active"
    if index_name not in index_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE INDEX {index_name} "
                    f"ON {table_name} (active)",
                ),
            )


def _backfill_initialization_draft_records(engine: Engine) -> None:
    """Give existing section payload rows stable database identities."""
    if engine.dialect.name != "sqlite":
        return
    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    try:
        if not (
            _table_exists(cursor, "project_initialization_draft_sections")
            and _table_exists(cursor, "project_initialization_draft_records")
        ):
            return
        rows = cursor.execute(
            "SELECT id, draft_id, project_id, conversation_id, section, "
            "revision, payload "
            "FROM project_initialization_draft_sections ORDER BY id",
        ).fetchall()
        key_fields = {
            "personnel": ("serial_no", "real_name"),
            "wbs": ("wbs_code", "name"),
            "risks": ("serial_no", "risk_part"),
            "quality_requirements": (
                "wbs_code",
                "quality_acceptance_item",
            ),
        }
        for section_row in rows:
            section_id = int(section_row[0])
            exists = cursor.execute(
                "SELECT 1 FROM project_initialization_draft_records "
                "WHERE section_id = ? LIMIT 1",
                (section_id,),
            ).fetchone()
            if exists is not None:
                continue
            raw_payload = section_row[6]
            try:
                payload = (
                    json.loads(raw_payload)
                    if isinstance(raw_payload, str)
                    else raw_payload
                )
            except (TypeError, json.JSONDecodeError):
                continue
            section = str(section_row[4])
            items = payload if isinstance(payload, list) else [payload]
            for ordinal, raw_item in enumerate(items):
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item.pop("record_id", None)
                parts = [
                    str(item.get(name, "")).strip()
                    for name in key_fields.get(section, ())
                ]
                business_key = " · ".join(part for part in parts if part)[:300]
                cursor.execute(
                    """
                    INSERT INTO project_initialization_draft_records (
                        section_id, draft_id, project_id, conversation_id,
                        section, section_revision, active, ordinal,
                        business_key, payload,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP)
                    """,
                    (
                        section_id,
                        int(section_row[1]),
                        int(section_row[2]),
                        int(section_row[3]),
                        section,
                        int(section_row[5] or 1),
                        ordinal,
                        business_key or None,
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        cursor.close()
        raw_connection.close()


def upgrade_database_schema(engine: Engine, metadata: MetaData) -> None:
    """Create the current schema and bridge supported legacy SQLite layouts."""

    if engine.dialect.name != "sqlite":
        metadata.create_all(bind=engine)
        _ensure_database_interaction_join_rules(engine)
        _ensure_database_interaction_runtime_rules(engine)
        _ensure_attachment_text_pipeline_fields(engine)
        _ensure_initialization_draft_record_version_fields(engine)
        return

    legacy_layout = _prepare_legacy_sqlite_schema(engine)
    metadata.create_all(bind=engine)
    _ensure_database_interaction_join_rules(engine)
    _ensure_database_interaction_runtime_rules(engine)
    _ensure_attachment_text_pipeline_fields(engine)
    _ensure_initialization_draft_record_version_fields(engine)
    _backfill_initialization_draft_records(engine)
    if legacy_layout:
        _copy_legacy_business_data(engine)
