"""Migrate legacy SQLite and local Qdrant data into unified PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable
import uuid

from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.sql.sqltypes import (
    Boolean,
    Date,
    DateTime,
    Integer,
    JSON,
    Numeric,
    Uuid,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXCLUDED_TABLES = {"alembic_version"}


def _load_project_env() -> None:
    """Load project-local defaults without overriding explicit environment."""

    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True, slots=True)
class TableMigrationResult:
    """Verified source and target row counts for one table."""

    schema: str
    table: str
    rows: int


@dataclass(frozen=True, slots=True)
class QdrantMigrationResult:
    """Verified point count for one migrated vector collection."""

    collection: str
    dimensions: int
    points: int


def _quote_identifier(value: str) -> str:
    """Quote one discovered SQL identifier without accepting expressions."""

    if not _SIMPLE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        )
        if str(row[0]) not in _EXCLUDED_TABLES
    }


def _sqlite_table_count(connection: sqlite3.Connection, table: str) -> int:
    quoted = _quote_identifier(table)
    return int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])


def _sqlite_primary_key_columns(
    connection: sqlite3.Connection,
    table: str,
) -> list[str]:
    quoted = _quote_identifier(table)
    rows = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    return [
        str(row[1])
        for row in sorted(rows, key=lambda item: int(item[5] or 0))
        if int(row[5] or 0) > 0
    ]


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON value in legacy SQLite data") from exc


def _parse_datetime(value: str) -> datetime:
    rendered = value.strip()
    if rendered.endswith("Z"):
        rendered = rendered[:-1] + "+00:00"
    return datetime.fromisoformat(rendered)


def _convert_value(value: Any, target_type: Any) -> Any:
    """Convert one untyped sqlite3 value for a reflected target column."""

    if value is None:
        return None
    if isinstance(target_type, JSON):
        return _decode_json(value)
    if isinstance(target_type, Boolean):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            raise ValueError(f"Invalid legacy boolean value: {value!r}")
        return bool(value)
    if isinstance(target_type, DateTime) and isinstance(value, str):
        return _parse_datetime(value)
    if isinstance(target_type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(target_type, Numeric) and not isinstance(value, Decimal):
        return Decimal(str(value))
    if isinstance(target_type, Uuid) and not isinstance(value, uuid.UUID):
        return uuid.UUID(str(value))
    return value


def _chunks(values: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _prepare_table_plan(
    source: sqlite3.Connection,
    engine: Engine,
    schema: str,
) -> tuple[list[str], dict[str, int]]:
    source_tables = _sqlite_tables(source)
    target_tables = {
        table
        for table in inspect(engine).get_table_names(schema=schema)
        if table not in _EXCLUDED_TABLES
    }
    source_only = sorted(source_tables - target_tables)
    nonempty_source_only = {
        table: _sqlite_table_count(source, table)
        for table in source_only
        if _sqlite_table_count(source, table) > 0
    }
    if nonempty_source_only:
        details = ", ".join(
            f"{name}={count}"
            for name, count in nonempty_source_only.items()
        )
        raise RuntimeError(
            f"Legacy {schema} SQLite contains unmapped non-empty tables: "
            f"{details}",
        )

    common = sorted(source_tables & target_tables)
    counts = {
        table: _sqlite_table_count(source, table)
        for table in common
    }
    return common, counts


def inventory_sqlite(
    source_path: Path,
    engine: Engine,
    schema: str,
) -> list[TableMigrationResult]:
    """Validate source/target compatibility and report legacy row counts."""

    if not source_path.is_file():
        raise FileNotFoundError(f"Legacy SQLite file not found: {source_path}")
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    try:
        tables, counts = _prepare_table_plan(source, engine, schema)
        return [
            TableMigrationResult(schema=schema, table=table, rows=counts[table])
            for table in tables
        ]
    finally:
        source.close()


def _validate_target_columns(
    source_columns: set[str],
    target_table: Any,
) -> None:
    target_columns = {column.name for column in target_table.columns}
    unknown = source_columns - target_columns
    if unknown:
        raise RuntimeError(
            f"Legacy table {target_table.name!r} has unmapped columns: "
            f"{sorted(unknown)}",
        )
    missing_required = [
        column.name
        for column in target_table.columns
        if column.name not in source_columns
        and not column.nullable
        and column.default is None
        and column.server_default is None
        and not column.autoincrement
    ]
    if missing_required:
        raise RuntimeError(
            f"Target table {target_table.name!r} requires columns missing "
            f"from SQLite: {missing_required}",
        )


def _load_sqlite_rows(
    source: sqlite3.Connection,
    target_table: Any,
) -> list[dict[str, Any]]:
    quoted = _quote_identifier(target_table.name)
    source_columns = {
        str(row[1])
        for row in source.execute(f"PRAGMA table_info({quoted})")
    }
    _validate_target_columns(source_columns, target_table)
    order_columns = _sqlite_primary_key_columns(source, target_table.name)
    order_clause = ""
    if order_columns:
        order_clause = " ORDER BY " + ", ".join(
            _quote_identifier(column) for column in order_columns
        )
    cursor = source.execute(f"SELECT * FROM {quoted}{order_clause}")
    column_names = [str(item[0]) for item in cursor.description or []]
    target_columns = {
        column.name: column
        for column in target_table.columns
    }
    rows: list[dict[str, Any]] = []
    for raw in cursor:
        rows.append(
            {
                name: _convert_value(value, target_columns[name].type)
                for name, value in zip(column_names, raw, strict=True)
                if name in target_columns
            },
        )
    return rows


def _reset_sequences(
    connection: Connection,
    schema: str,
    tables: Iterable[Any],
) -> None:
    for table in tables:
        qualified = f'{_quote_identifier(schema)}.{_quote_identifier(table.name)}'
        for column in table.primary_key.columns:
            if not isinstance(column.type, Integer):
                continue
            sequence = connection.execute(
                text(
                    "SELECT pg_get_serial_sequence(:qualified, :column_name)",
                ),
                {"qualified": qualified, "column_name": column.name},
            ).scalar_one_or_none()
            if not sequence:
                continue
            maximum = connection.execute(
                text(
                    f"SELECT MAX({_quote_identifier(column.name)}) "
                    f"FROM {qualified}",
                ),
            ).scalar_one_or_none()
            if maximum is None:
                value = 1
                is_called = False
            else:
                value = int(maximum)
                is_called = True
            connection.execute(
                text(
                    "SELECT setval(CAST(:sequence AS regclass), "
                    ":value, :is_called)",
                ),
                {
                    "sequence": sequence,
                    "value": value,
                    "is_called": is_called,
                },
            )


def migrate_sqlite(
    source_path: Path,
    engine: Engine,
    schema: str,
    *,
    replace: bool,
    batch_size: int = 500,
) -> list[TableMigrationResult]:
    """Replace one PostgreSQL application schema from a legacy SQLite DB."""

    if not replace:
        raise ValueError("SQLite migration currently requires replace=True")
    if not source_path.is_file():
        raise FileNotFoundError(f"Legacy SQLite file not found: {source_path}")

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    try:
        table_names, source_counts = _prepare_table_plan(source, engine, schema)
        metadata = MetaData()
        metadata.reflect(bind=engine, schema=schema, only=table_names)
        tables = [
            table
            for table in metadata.sorted_tables
            if table.name in table_names
        ]
        loaded_rows = {
            table.name: _load_sqlite_rows(source, table)
            for table in tables
        }

        with engine.begin() as target:
            if tables:
                qualified_tables = ", ".join(
                    f'{_quote_identifier(schema)}.'
                    f'{_quote_identifier(table.name)}'
                    for table in tables
                )
                target.exec_driver_sql(
                    f"TRUNCATE TABLE {qualified_tables} "
                    "RESTART IDENTITY CASCADE",
                )
            for table in tables:
                rows = loaded_rows[table.name]
                for batch in _chunks(rows, batch_size):
                    target.execute(table.insert(), batch)
            _reset_sequences(target, schema, tables)

            results: list[TableMigrationResult] = []
            for table in tables:
                qualified = (
                    f'{_quote_identifier(schema)}.'
                    f'{_quote_identifier(table.name)}'
                )
                target_count = int(
                    target.execute(
                        text(f"SELECT COUNT(*) FROM {qualified}"),
                    ).scalar_one(),
                )
                source_count = source_counts[table.name]
                if target_count != source_count:
                    raise RuntimeError(
                        f"Row-count verification failed for {schema}."
                        f"{table.name}: source={source_count}, "
                        f"target={target_count}",
                    )
                results.append(
                    TableMigrationResult(
                        schema=schema,
                        table=table.name,
                        rows=target_count,
                    ),
                )
        return results
    finally:
        source.close()


def _qdrant_vector(value: Any) -> list[float]:
    if isinstance(value, dict):
        if len(value) != 1:
            raise RuntimeError("Named multi-vector Qdrant points are unsupported")
        value = next(iter(value.values()))
    if not isinstance(value, list):
        raise RuntimeError("Qdrant point does not contain a dense vector")
    vector = [float(item) for item in value]
    if not vector or not all(math.isfinite(item) for item in vector):
        raise RuntimeError("Qdrant point contains an invalid dense vector")
    return vector


def _qdrant_config_dimensions(client: Any, collection: str) -> int:
    info = client.get_collection(collection)
    vectors = info.config.params.vectors
    if hasattr(vectors, "size"):
        return int(vectors.size)
    if isinstance(vectors, dict) and len(vectors) == 1:
        config = next(iter(vectors.values()))
        return int(config.size)
    raise RuntimeError(
        f"Unable to determine vector dimensions for {collection!r}",
    )


def inventory_qdrant(source_path: Path) -> list[QdrantMigrationResult]:
    """Open local Qdrant read-only in intent and report collection sizes."""

    if not source_path.is_dir():
        raise FileNotFoundError(f"Legacy Qdrant directory not found: {source_path}")
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(source_path))
    try:
        results: list[QdrantMigrationResult] = []
        for item in client.get_collections().collections:
            info = client.get_collection(item.name)
            results.append(
                QdrantMigrationResult(
                    collection=item.name,
                    dimensions=_qdrant_config_dimensions(client, item.name),
                    points=int(info.points_count or 0),
                ),
            )
        return results
    finally:
        client.close()


async def migrate_qdrant(
    source_path: Path,
    database_url: str,
    *,
    schema: str,
    replace: bool,
    batch_size: int = 256,
) -> list[QdrantMigrationResult]:
    """Copy every local Qdrant collection into PGVectorStore."""

    if not replace:
        raise ValueError("Qdrant migration currently requires replace=True")
    if not source_path.is_dir():
        raise FileNotFoundError(f"Legacy Qdrant directory not found: {source_path}")

    from qdrant_client import QdrantClient
    from agentscope.rag import Chunk, PGVectorStore, VectorRecord

    client = QdrantClient(path=str(source_path))
    store = PGVectorStore(
        database_url,
        schema=schema,
        min_pool_size=1,
        max_pool_size=2,
    )
    results: list[QdrantMigrationResult] = []
    try:
        async with store:
            for item in client.get_collections().collections:
                collection = item.name
                dimensions = _qdrant_config_dimensions(client, collection)
                await store.delete_collection(collection)
                await store.create_collection(collection, dimensions)
                inserted = 0
                offset: Any = None
                try:
                    while True:
                        points, next_offset = client.scroll(
                            collection_name=collection,
                            limit=batch_size,
                            offset=offset,
                            with_payload=True,
                            with_vectors=True,
                        )
                        records = []
                        for point in points:
                            payload = dict(point.payload or {})
                            if "document_id" not in payload or "chunk" not in payload:
                                raise RuntimeError(
                                    f"Qdrant collection {collection!r} contains "
                                    "a point without document_id/chunk payload",
                                )
                            records.append(
                                VectorRecord(
                                    vector=_qdrant_vector(point.vector),
                                    document_id=str(payload["document_id"]),
                                    chunk=Chunk.model_validate(payload["chunk"]),
                                ),
                            )
                        await store.insert(collection, records)
                        inserted += len(records)
                        if next_offset is None:
                            break
                        offset = next_offset

                    pool = await store._get_pool()
                    async with pool.acquire() as connection:
                        collection_info = await store._lookup_collection(
                            connection,
                            collection,
                        )
                        assert collection_info is not None
                        target_count = int(
                            await connection.fetchval(
                                "SELECT COUNT(*) FROM "
                                f"{store._qualified_table(collection_info.table_name)}",
                            ),
                        )
                    if target_count != inserted:
                        raise RuntimeError(
                            f"Qdrant verification failed for {collection!r}: "
                            f"source={inserted}, target={target_count}",
                        )
                    results.append(
                        QdrantMigrationResult(
                            collection=collection,
                            dimensions=dimensions,
                            points=inserted,
                        ),
                    )
                except Exception:
                    await store.delete_collection(collection)
                    raise
        return results
    finally:
        client.close()


def _validate_database(database_url: str, expected_database: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("Legacy migration target must be PostgreSQL")
    if url.database != expected_database:
        raise RuntimeError(
            f"Refusing migration: connected database is {url.database!r}, "
            f"expected {expected_database!r}",
        )


def _print_sqlite_results(results: list[TableMigrationResult]) -> None:
    by_schema: dict[str, list[TableMigrationResult]] = {}
    for result in results:
        by_schema.setdefault(result.schema, []).append(result)
    for schema, items in by_schema.items():
        total = sum(item.rows for item in items)
        nonempty = sum(1 for item in items if item.rows)
        print(
            f"sqlite schema={schema} tables={len(items)} "
            f"nonempty={nonempty} rows={total}",
        )


def _print_qdrant_results(results: list[QdrantMigrationResult]) -> None:
    print(
        f"qdrant collections={len(results)} "
        f"points={sum(item.points for item in results)}",
    )
    for item in results:
        print(
            f"qdrant_collection name={item.collection} "
            f"dimensions={item.dimensions} points={item.points}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将旧 SQLite/Qdrant 数据迁移到统一 PostgreSQL",
    )
    parser.add_argument("--expected-database", required=True)
    parser.add_argument(
        "--platform-sqlite",
        type=Path,
        default=PROJECT_ROOT / "data" / "engpm.db",
    )
    parser.add_argument(
        "--agentscope-sqlite",
        type=Path,
        default=PROJECT_ROOT / "data" / "agentscope" / "agentscope.db",
    )
    parser.add_argument(
        "--qdrant-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "agentscope" / "qdrant",
    )
    parser.add_argument("--knowledge-schema", default="knowledge")
    parser.add_argument("--skip-platform", action="store_true")
    parser.add_argument("--skip-agentscope", action="store_true")
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行迁移；省略时仅做兼容性与数量盘点",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="清空对应目标表/集合后精确迁移",
    )
    args = parser.parse_args()

    _load_project_env()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    _validate_database(database_url, args.expected_database)
    if args.apply and not args.replace:
        parser.error("--apply requires --replace for an exact cutover")

    engine = create_engine(database_url, pool_pre_ping=True)
    sqlite_results: list[TableMigrationResult] = []
    try:
        for skipped, path, schema in (
            (args.skip_platform, args.platform_sqlite.resolve(), "platform"),
            (args.skip_agentscope, args.agentscope_sqlite.resolve(), "agentscope"),
        ):
            if skipped:
                continue
            if args.apply:
                sqlite_results.extend(
                    migrate_sqlite(
                        path,
                        engine,
                        schema,
                        replace=args.replace,
                    ),
                )
            else:
                sqlite_results.extend(inventory_sqlite(path, engine, schema))
    finally:
        engine.dispose()
    _print_sqlite_results(sqlite_results)

    if not args.skip_qdrant:
        qdrant_path = args.qdrant_path.resolve()
        if args.apply:
            qdrant_results = asyncio.run(
                migrate_qdrant(
                    qdrant_path,
                    database_url,
                    schema=args.knowledge_schema,
                    replace=args.replace,
                ),
            )
        else:
            qdrant_results = inventory_qdrant(qdrant_path)
        _print_qdrant_results(qdrant_results)

    print("mode=" + ("applied" if args.apply else "inventory"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
