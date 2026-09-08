"""建立三抽屉记忆正文与索引任务。

Revision ID: c9d81a4e7302
Revises: b7a903d1e642
"""
from alembic import op
from utils.memory_schema import MEMORY_DDL

revision = "c9d81a4e7302"
down_revision = "b7a903d1e642"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS memory")
    # Fully qualify statements without changing the platform connection's search path.
    for statement in MEMORY_DDL.split(";"):
        if not statement.strip():
            continue
        for table in ("memory_records", "memory_versions", "memory_requests", "memory_index_jobs", "memory_legacy_reviews"):
            import re
            statement = re.sub(rf"\b{table}\b", f"memory.{table}", statement)
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("记忆正文和历史版本不可自动删除；回退服务版本时保留这些表。")
