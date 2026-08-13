"""Idempotent PostgreSQL foundation for the unified Dobby deployment."""

from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema


POSTGRES_SCHEMAS = ("platform", "agentscope", "memory", "knowledge")
POSTGRES_EXTENSIONS = ("vector", "pgcrypto", "pg_trgm")
_IDENTIFIER_PATTERN = re.compile(r"[a-z_][a-z0-9_]{0,62}")


@dataclass(frozen=True)
class PostgresFoundationReport:
    database: str
    schemas: tuple[str, ...]
    extensions: dict[str, str]


def validate_identifier(value: str) -> str:
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"非法 PostgreSQL 标识符：{value!r}")
    return value


def bootstrap_postgres_foundation(
    engine: Engine,
    *,
    expected_database: str | None = None,
    schemas: tuple[str, ...] = POSTGRES_SCHEMAS,
    extensions: tuple[str, ...] = POSTGRES_EXTENSIONS,
) -> PostgresFoundationReport:
    """Create schemas and required extensions in one transaction."""

    if engine.dialect.name != "postgresql":
        raise RuntimeError("数据库基线只能针对 PostgreSQL 执行")

    safe_schemas = tuple(validate_identifier(item) for item in schemas)
    safe_extensions = tuple(validate_identifier(item) for item in extensions)

    with engine.begin() as connection:
        database = str(connection.scalar(text("SELECT current_database()")))
        if expected_database and database != expected_database:
            raise RuntimeError(
                f"拒绝初始化非目标数据库：期望 {expected_database!r}，实际 {database!r}",
            )

        available = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT name FROM pg_available_extensions "
                    "WHERE name = ANY(:extensions)",
                ),
                {"extensions": list(safe_extensions)},
            )
        }
        missing = sorted(set(safe_extensions) - available)
        if missing:
            raise RuntimeError(
                "PostgreSQL 服务器缺少扩展安装文件：" + ", ".join(missing),
            )

        for extension in safe_extensions:
            connection.execute(
                text(
                    f'CREATE EXTENSION IF NOT EXISTS "{extension}" '
                    "WITH SCHEMA public",
                ),
            )
        for schema in safe_schemas:
            connection.execute(CreateSchema(schema, if_not_exists=True))

        installed = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension "
                    "WHERE extname = ANY(:extensions)",
                ),
                {"extensions": list(safe_extensions)},
            )
        }

    return PostgresFoundationReport(
        database=database,
        schemas=safe_schemas,
        extensions=installed,
    )
