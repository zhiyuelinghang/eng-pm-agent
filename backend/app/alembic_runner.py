from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema

from .postgres_foundation import validate_identifier


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def upgrade_postgres_schema(engine: Engine, schema: str) -> None:
    """Apply committed Alembic migrations to one PostgreSQL application schema."""

    if engine.dialect.name != "postgresql":
        raise ValueError("Alembic PostgreSQL 升级只能用于 PostgreSQL 引擎")
    safe_schema = validate_identifier(schema)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["database_schema"] = safe_schema

    with engine.begin() as connection:
        connection.execute(CreateSchema(safe_schema, if_not_exists=True))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
