# -*- coding: utf-8 -*-
"""Environment-backed settings for the unified memory runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from sqlalchemy.engine import URL, make_url


_SCHEMA_PATTERN = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MemorySettings:
    """One immutable snapshot of context-control configuration."""

    database_url: str
    schema: str = "memory"
    collection_name: str = "dobby_memories"
    tenant_id: str = "projectcopilot"
    embedding_provider: str = "hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1024
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    infer_enabled: bool = False
    top_k: int = 6
    threshold: float = 0.3
    mem0_dir: Path = Path("data/agentscope/mem0")

    def __post_init__(self) -> None:
        url = make_url(self.database_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("统一记忆系统必须连接 PostgreSQL")
        if not _SCHEMA_PATTERN.fullmatch(self.schema):
            raise ValueError("非法记忆系统 PostgreSQL schema")
        if not _SCHEMA_PATTERN.fullmatch(self.collection_name):
            raise ValueError("非法 Mem0 collection 名称")
        if self.embedding_dims <= 0:
            raise ValueError("MEMORY_EMBEDDING_DIMS 必须大于 0")
        if self.embedding_provider not in {"hash", "openai"}:
            raise ValueError(
                "MEMORY_EMBEDDING_PROVIDER 仅支持 hash 或 openai",
            )

    @classmethod
    def from_env(cls) -> "MemorySettings":
        database_url = (
            os.getenv("MEMORY_DATABASE_URL", "").strip()
            or os.getenv("DATABASE_URL", "").strip()
        )
        if not database_url:
            raise RuntimeError(
                "统一记忆系统需要 MEMORY_DATABASE_URL 或 DATABASE_URL",
            )
        runtime_home = Path(
            os.getenv("AGENTSCOPE_RUNTIME_HOME", "data/agentscope"),
        )
        return cls(
            database_url=database_url,
            schema=os.getenv("MEMORY_DATABASE_SCHEMA", "memory").strip(),
            collection_name=os.getenv(
                "MEMORY_COLLECTION_NAME",
                "dobby_memories",
            ).strip(),
            tenant_id=os.getenv(
                "MEMORY_TENANT_ID",
                os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "projectcopilot"),
            ).strip()
            or "projectcopilot",
            embedding_provider=os.getenv(
                "MEMORY_EMBEDDING_PROVIDER",
                "hash",
            ).strip().lower(),
            embedding_model=os.getenv(
                "MEMORY_EMBEDDING_MODEL",
                "text-embedding-3-small",
            ).strip(),
            embedding_dims=int(os.getenv("MEMORY_EMBEDDING_DIMS", "1024")),
            embedding_api_key=(
                os.getenv("MEMORY_EMBEDDING_API_KEY", "").strip()
                or os.getenv("AI_API_KEY", "").strip()
            ),
            embedding_base_url=(
                os.getenv("MEMORY_EMBEDDING_BASE_URL", "").strip()
                or os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip()
            ),
            llm_model=os.getenv(
                "MEMORY_LLM_MODEL",
                os.getenv("AI_MODEL", "gpt-4.1-mini"),
            ).strip(),
            llm_api_key=(
                os.getenv("MEMORY_LLM_API_KEY", "").strip()
                or os.getenv("AI_API_KEY", "").strip()
            ),
            llm_base_url=(
                os.getenv("MEMORY_LLM_BASE_URL", "").strip()
                or os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip()
            ),
            infer_enabled=_env_bool("MEMORY_INFER_ENABLED", False),
            top_k=max(1, min(20, int(os.getenv("MEMORY_RECALL_TOP_K", "6")))),
            threshold=max(
                0.0,
                min(1.0, float(os.getenv("MEMORY_RECALL_THRESHOLD", "0.3"))),
            ),
            mem0_dir=Path(
                os.getenv("MEM0_DIR", runtime_home / "mem0"),
            ),
        )

    def _postgres_url(self) -> URL:
        return make_url(self.database_url).set(drivername="postgresql")

    def mem0_connection_string(self) -> str:
        """Return a psycopg URL whose unqualified objects live in memory."""

        url = self._postgres_url()
        query = dict(url.query)
        query["options"] = f"-csearch_path={self.schema},public"
        return url.set(query=query).render_as_string(hide_password=False)

    def sqlalchemy_url(self) -> str:
        return self._postgres_url().set(
            drivername="postgresql+psycopg",
            query={},
        ).render_as_string(hide_password=False)
