"""Provision the PostgreSQL schemas and extensions used by Dobby."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import create_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.alembic_runner import upgrade_postgres_schema  # noqa: E402
from backend.app.postgres_foundation import (  # noqa: E402
    bootstrap_postgres_foundation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="创建 Dobby 统一 PostgreSQL 的扩展与 schema 基线",
    )
    parser.add_argument(
        "--expected-database",
        required=True,
        help="安全校验：只允许初始化这个数据库名",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="同时将平台、记忆和知识库 Alembic 迁移升级到 head",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        report = bootstrap_postgres_foundation(
            engine,
            expected_database=args.expected_database,
        )
        if args.upgrade:
            upgrade_postgres_schema(engine, settings.database_schema)
    finally:
        engine.dispose()

    print(f"database={report.database}")
    print("schemas=" + ",".join(report.schemas))
    print(
        "extensions="
        + ",".join(
            f"{name}:{version}"
            for name, version in sorted(report.extensions.items())
        ),
    )
    if args.upgrade:
        print(f"migrations={settings.database_schema}:head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
