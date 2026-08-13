# -*- coding: utf-8 -*-
"""Mem0/pgvector runtime with project scoping and PostgreSQL audit."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ._config import MemorySettings


@dataclass(frozen=True)
class MemoryScope:
    tenant_id: str
    project_id: str | None
    platform_user_id: str | None
    agent_id: str
    session_id: str
    scope_key: str


def _scope_key(
    tenant_id: str,
    project_id: str | None,
    platform_user_id: str | None,
) -> str:
    boundary = (
        f"project={project_id}"
        if project_id
        else f"user={platform_user_id or 'anonymous'}"
    )
    digest = hashlib.sha256(f"{tenant_id}|{boundary}".encode()).hexdigest()[:32]
    return f"scope_{digest}"


def _result_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("results", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


class _MemoryAuditStore:
    def __init__(self, settings: MemorySettings) -> None:
        self._engine: Engine = create_engine(
            settings.sqlalchemy_url(),
            connect_args={
                "options": f"-csearch_path={settings.schema},public",
            },
            pool_pre_ping=True,
        )

    def record(
        self,
        scope: MemoryScope,
        *,
        action: str,
        memory_id: str | None = None,
        query_text: str | None = None,
        content: str | None = None,
        result_count: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        content_hash = (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content
            else None
        )
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO memory.memory_audit_log (
                        tenant_id, project_id, platform_user_id, agent_id,
                        session_id, action, memory_id, query_text,
                        content_hash, result_count, details
                    ) VALUES (
                        :tenant_id, :project_id, :platform_user_id, :agent_id,
                        :session_id, :action, CAST(:memory_id AS uuid),
                        :query_text, :content_hash, :result_count,
                        CAST(:details AS jsonb)
                    )
                    """,
                ),
                {
                    "tenant_id": scope.tenant_id,
                    "project_id": scope.project_id,
                    "platform_user_id": scope.platform_user_id,
                    "agent_id": scope.agent_id,
                    "session_id": scope.session_id,
                    "action": action,
                    "memory_id": memory_id,
                    "query_text": query_text,
                    "content_hash": content_hash,
                    "result_count": result_count,
                    "details": json.dumps(details or {}, ensure_ascii=False),
                },
            )

    def search_experiences(
        self,
        scope: MemoryScope,
        embedding: list[float],
        *,
        top_k: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Search raw and consolidated experience memory in one scope."""

        if not scope.project_id:
            return []
        vector = "[" + ",".join(f"{value:.9g}" for value in embedding) + "]"
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    WITH candidates AS (
                        SELECT
                            id,
                            body_md AS memory,
                            bucket,
                            importance,
                            strength,
                            embedding,
                            'experience'::text AS source
                        FROM memory.experiences
                        WHERE tenant_id = :tenant_id
                          AND project_id = :project_id
                          AND status = 'active'
                          AND embedding IS NOT NULL
                        UNION ALL
                        SELECT
                            id,
                            COALESCE(NULLIF(reusable_knowledge, ''), description)
                                AS memory,
                            bucket,
                            importance,
                            1.0 AS strength,
                            embedding,
                            'experience_extract'::text AS source
                        FROM memory.experience_extracts
                        WHERE tenant_id = :tenant_id
                          AND project_id = :project_id
                          AND embedding IS NOT NULL
                    )
                    SELECT
                        id::text,
                        memory,
                        bucket,
                        importance,
                        strength,
                        source,
                        1 - (embedding <=> CAST(:embedding AS public.vector))
                            AS score
                    FROM candidates
                    WHERE 1 - (embedding <=> CAST(:embedding AS public.vector))
                        >= :threshold
                    ORDER BY (
                        (1 - (embedding <=> CAST(:embedding AS public.vector)))
                        * 0.8
                        + importance * 0.1
                        + strength * 0.1
                    ) DESC
                    LIMIT :top_k
                    """,
                ),
                {
                    "tenant_id": scope.tenant_id,
                    "project_id": scope.project_id,
                    "embedding": vector,
                    "threshold": threshold,
                    "top_k": top_k,
                },
            ).mappings().all()
        return [
            {
                "id": row["id"],
                "memory": f"[项目经验/{row['bucket'] or 'general'}] {row['memory']}",
                "score": float(row["score"] or 0.0),
                "metadata": {
                    "source": row["source"],
                    "bucket": row["bucket"],
                    "importance": float(row["importance"] or 0.5),
                    "strength": float(row["strength"] or 1.0),
                },
            }
            for row in rows
        ]


class ScopedMemoryClient:
    """Async Mem0 facade that enforces one immutable project boundary."""

    def __init__(
        self,
        inner: Any,
        settings: MemorySettings,
        scope: MemoryScope,
        audit: _MemoryAuditStore,
    ) -> None:
        self._inner = inner
        self._settings = settings
        self._scope = scope
        self._audit = audit

    def _filters(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        scoped = dict(filters or {})
        scoped.update(
            {
                "user_id": self._scope.scope_key,
                "agent_id": self._scope.scope_key,
                "tenant_id": self._scope.tenant_id,
            },
        )
        if self._scope.project_id:
            scoped["project_id"] = self._scope.project_id
        return scoped

    def _metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        scoped = dict(metadata or {})
        scoped.update(
            {
                "tenant_id": self._scope.tenant_id,
                "project_id": self._scope.project_id or "",
                "platform_user_id": self._scope.platform_user_id or "",
                "source_agent_id": self._scope.agent_id,
                "source_session_id": self._scope.session_id,
            },
        )
        return scoped

    async def search(self, query: str, **kwargs: Any) -> Any:
        kwargs["filters"] = self._filters(kwargs.get("filters"))
        top_k = int(kwargs.get("top_k", self._settings.top_k))
        threshold = float(kwargs.get("threshold", self._settings.threshold))
        raw, embedding = await asyncio.gather(
            self._inner.search(query, **kwargs),
            asyncio.to_thread(
                self._inner.embedding_model.embed,
                query,
                "search",
            ),
        )
        items = _result_items(raw)
        try:
            experiences = await asyncio.to_thread(
                self._audit.search_experiences,
                self._scope,
                embedding,
                top_k=top_k,
                threshold=threshold,
            )
        except Exception:
            experiences = []

        for item in items:
            metadata = dict(item.get("metadata") or {})
            metadata.setdefault("source", "mem0")
            item["metadata"] = metadata
        combined = [*items, *experiences]
        combined.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float((item.get("metadata") or {}).get("importance") or 0.0),
            ),
            reverse=True,
        )
        combined = combined[:top_k]
        await asyncio.to_thread(
            self._audit.record,
            self._scope,
            action="recall",
            query_text=query,
            result_count=len(combined),
            details={
                "mem0_count": len(items),
                "experience_count": len(experiences),
            },
        )
        if isinstance(raw, dict):
            return {**raw, "results": combined}
        return {"results": combined}

    async def add(self, messages: Any, **kwargs: Any) -> Any:
        kwargs["user_id"] = self._scope.scope_key
        kwargs["agent_id"] = self._scope.scope_key
        kwargs["metadata"] = self._metadata(kwargs.get("metadata"))
        if not self._settings.infer_enabled:
            kwargs["infer"] = False
        raw = await self._inner.add(messages, **kwargs)
        items = _result_items(raw)
        if isinstance(messages, str):
            content = messages
        elif isinstance(messages, list):
            content = "\n".join(
                str(item.get("content", ""))
                for item in messages
                if isinstance(item, dict)
            )
        else:
            content = str(messages)
        if items:
            for item in items:
                await asyncio.to_thread(
                    self._audit.record,
                    self._scope,
                    action="remember",
                    memory_id=str(item.get("id")) if item.get("id") else None,
                    content=content,
                    result_count=1,
                    details={"infer": bool(kwargs.get("infer", True))},
                )
        else:
            await asyncio.to_thread(
                self._audit.record,
                self._scope,
                action="remember_empty",
                content=content,
                result_count=0,
            )
        return raw

    async def get(self, memory_id: str) -> Any:
        item = await self._inner.get(memory_id)
        if not isinstance(item, dict):
            return None
        metadata = item.get("metadata") or {}
        if (
            item.get("user_id") != self._scope.scope_key
            or item.get("agent_id") != self._scope.scope_key
            or metadata.get("tenant_id") != self._scope.tenant_id
        ):
            return None
        return item

    async def delete(self, memory_id: str) -> bool:
        item = await self.get(memory_id)
        if item is None:
            return False
        await self._inner.delete(memory_id)
        await asyncio.to_thread(
            self._audit.record,
            self._scope,
            action="forget",
            memory_id=memory_id,
            result_count=1,
        )
        return True


class MemoryRuntime:
    """Shared Mem0 client plus per-project scoped facades."""

    def __init__(self, settings: MemorySettings) -> None:
        self.settings = settings
        self._client: Any | None = None
        self._client_lock = threading.Lock()
        self._audit = _MemoryAuditStore(settings)

    def scope(
        self,
        *,
        project_id: str | None,
        platform_user_id: str | None,
        agent_id: str,
        session_id: str,
    ) -> MemoryScope:
        return MemoryScope(
            tenant_id=self.settings.tenant_id,
            project_id=project_id,
            platform_user_id=platform_user_id,
            agent_id=agent_id,
            session_id=session_id,
            scope_key=_scope_key(
                self.settings.tenant_id,
                project_id,
                platform_user_id,
            ),
        )

    def _build_client(self) -> Any:
        self.settings.mem0_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MEM0_DIR", str(self.settings.mem0_dir))
        os.environ.setdefault("MEM0_TELEMETRY", "false")

        from mem0 import AsyncMemory
        from mem0.configs.base import MemoryConfig
        from mem0.utils.factory import EmbedderFactory
        from mem0.vector_stores.configs import VectorStoreConfig

        embedder: dict[str, Any]
        if self.settings.embedding_provider == "openai":
            embedder = {
                "provider": "openai",
                "config": {
                    "model": self.settings.embedding_model,
                    "embedding_dims": self.settings.embedding_dims,
                    "api_key": self.settings.embedding_api_key,
                    "openai_base_url": self.settings.embedding_base_url,
                },
            }
        else:
            EmbedderFactory.provider_to_class["dobby_hash"] = (
                "agentscope.app.memory._embedding.HashEmbedding"
            )
            embedder = {
                "provider": "openai",
                "config": {"embedding_dims": self.settings.embedding_dims},
            }

        config = MemoryConfig(
            vector_store=VectorStoreConfig(
                provider="pgvector",
                config={
                    "connection_string": self.settings.mem0_connection_string(),
                    "collection_name": self.settings.collection_name,
                    "embedding_model_dims": self.settings.embedding_dims,
                    "hnsw": True,
                },
            ),
            llm={
                "provider": "openai",
                "config": {
                    "model": self.settings.llm_model,
                    "api_key": self.settings.llm_api_key or "infer-disabled",
                    "openai_base_url": self.settings.llm_base_url,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            },
            embedder=embedder,
            history_db_path=":memory:",
            version="v1.1",
        )
        if self.settings.embedding_provider == "hash":
            config.embedder.provider = "dobby_hash"
        return AsyncMemory(config=config)

    def client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._build_client()
        return self._client

    def scoped_client(self, scope: MemoryScope) -> ScopedMemoryClient:
        return ScopedMemoryClient(
            self.client(),
            self.settings,
            scope,
            self._audit,
        )


_runtime: MemoryRuntime | None = None
_runtime_lock = threading.Lock()


def get_memory_runtime() -> MemoryRuntime:
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = MemoryRuntime(MemorySettings.from_env())
    return _runtime
