"""The upgrade adds review bookkeeping without rewriting existing projects."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from backend.app.db import Base
from backend.app import models  # noqa: F401


def test_change_review_migration_matches_models_and_preserves_formal_data():
    names = {"project_initialization_change_previews", "project_initialization_applied_changes"}
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name not in names])
    migration_path = Path(__file__).resolve().parents[1] / "alembic/versions/fe84ca27b315_项目资料分批确认与差异预览.py"
    spec = importlib.util.spec_from_file_location("initialization_change_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (name) VALUES ('保留原项目')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        inspector = inspect(conn)
        for name in names:
            assert {column["name"] for column in inspector.get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
        assert conn.scalar(text("SELECT name FROM projects")) == "保留原项目"
    engine.dispose()
