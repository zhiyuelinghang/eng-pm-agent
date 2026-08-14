"""
GraphRAG Engine — LightRAG embedded wrapper for Dobby.

Architecture:
  - LightRAG as embedded library (not sidecar service)
  - Graph storage: NetworkXStorage (file-based GraphML, zero infrastructure)
  - Vector storage: PGVectorStorage (reuses existing pgvector/pgvector:pg16)
  - KV storage: PGKVStorage (LLM response cache)
  - DocStatus storage: PGDocStatusStorage (document tracking)
  - Embedding: embed_server (:9999) via OpenAI-compatible API
  - LLM: DeepSeek API via OpenAI-compatible wrapper
  - Feature gate: LIGHTRAG_ENABLED env var, default false
"""

from __future__ import annotations

import asyncio
import os
from hashlib import md5
from typing import Any

from . import config as _cfg


# ============================================================
# GraphRAGEngine
# ============================================================


class GraphRAGEngine:
    """LightRAG embedded wrapper, reusing Dobby infrastructure."""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self._rag: Any = None
        self._initialized = False

    # ── Initialize ──────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize the LightRAG instance.

        Storage configuration:
          - Graph: NetworkXStorage (file graph, GraphML persisted to working_dir)
          - Vector: PGVectorStorage (reuses dobby_demo pgvector)
          - KV: PGKVStorage (LLM cache in dobby_demo)
          - DocStatus: PGDocStatusStorage

        Rationale for NetworkXStorage:
          - dobby_demo image is pgvector/pgvector:pg16, no Apache AGE
          - engineering_safety.md ~100KB, est. 200-300 entities, file graph is sufficient
          - Zero infrastructure changes, GraphML files auto-persisted
        """
        if not _cfg.LIGHTRAG_ENABLED:
            return

        if self._initialized:
            return

        # Load entity type guidance lazily (imports graph_rag_prompts)
        _load_guidance()

        try:
            from lightrag import LightRAG, QueryParam
            from lightrag.utils import EmbeddingFunc

            # ── Working directory ──
            working_dir = os.path.join(_cfg.LIGHTRAG_WORKING_DIR, self.project_id)
            os.makedirs(working_dir, exist_ok=True)

            # ── Embedding function → embed_server (:9999) ──
            async def _embed(texts: list[str]) -> Any:
                """Call embed_server (:9999) for embeddings via httpx."""
                import httpx
                import numpy as np
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{_cfg.EMBED_SERVER_URL}/embeddings",
                        json={"input": texts, "model": _cfg.EMBEDDING_MODEL},
                        timeout=60.0,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return np.array([item["embedding"] for item in data["data"]])

            embedding_func = EmbeddingFunc(
                embedding_dim=_cfg.EMBEDDING_DIMS,
                max_token_size=512,
                func=_embed,
            )

            # ── LLM function → active memory-processing model ──
            async def _llm(
                prompt: str,
                system_prompt: str | None = None,
                history_messages: list | None = None,
                **kwargs: Any,
            ) -> str:
                """Use the same model as extraction and reflection."""
                from agentscope.message import AssistantMsg
                from .langgraph_utils import (
                    _call_model,
                    _make_system,
                    _make_user,
                    _msg_content,
                )

                messages: list[Any] = []
                if system_prompt:
                    messages.append(_make_system(system_prompt))
                if history_messages:
                    for item in history_messages:
                        role = (
                            item.get("role", "user")
                            if isinstance(item, dict)
                            else getattr(item, "role", "user")
                        )
                        content = (
                            item.get("content", "")
                            if isinstance(item, dict)
                            else _msg_content(item)
                        )
                        if role == "system":
                            messages.append(_make_system(str(content)))
                        elif role == "assistant":
                            messages.append(AssistantMsg("assistant", str(content)))
                        else:
                            messages.append(_make_user(str(content)))
                messages.append(_make_user(prompt))
                response = await _call_model(messages, intent="extract")
                return _msg_content(response)

            # ── PG connection info (parsed from DATABASE_URL) ──
            db_url = _cfg.DATABASE_URL
            # postgresql://dobby:dobby@localhost:5432/dobby_demo
            pg_host = "localhost"
            pg_port = "5432"
            pg_user = "dobby"
            pg_password = "dobby"
            pg_db = "dobby_demo"
            try:
                from urllib.parse import urlparse
                parsed = urlparse(db_url)
                pg_host = parsed.hostname or pg_host
                pg_port = str(parsed.port or 5432)
                pg_user = parsed.username or pg_user
                pg_password = parsed.password or pg_password
                pg_db = parsed.path.lstrip("/") or pg_db
            except Exception:
                pass

            # Set PG env vars (LightRAG PG backends read from environment)
            os.environ.setdefault("POSTGRES_HOST", pg_host)
            os.environ.setdefault("POSTGRES_PORT", pg_port)
            os.environ.setdefault("POSTGRES_USER", pg_user)
            os.environ.setdefault("POSTGRES_PASSWORD", pg_password)
            os.environ.setdefault("POSTGRES_DATABASE", pg_db)
            os.environ.setdefault("POSTGRES_WORKSPACE", self.project_id)

            # ── Build LightRAG ──
            self._rag = LightRAG(
                working_dir=working_dir,
                # Graph: NetworkX (file graph, zero infrastructure)
                graph_storage="NetworkXStorage",
                # Vector: PG (reuses pgvector)
                vector_storage="PGVectorStorage",
                # KV: PG (LLM cache)
                kv_storage="PGKVStorage",
                # DocStatus: PG
                doc_status_storage="PGDocStatusStorage",
                # Embedding
                embedding_func=embedding_func,
                # LLM
                llm_model_func=_llm,
                # Chunk strategy
                chunk_token_size=_cfg.LIGHTRAG_CHUNK_SIZE,
                chunk_overlap_token_size=_cfg.LIGHTRAG_CHUNK_OVERLAP,
                # Entity extraction
                entity_extract_max_gleaning=_cfg.LIGHTRAG_ENTITY_MAX_GLEANING,
                entity_extraction_use_json=_cfg.LIGHTRAG_ENTITY_EXTRACT_USE_JSON,
                # Query defaults
                top_k=_cfg.LIGHTRAG_QUERY_TOP_K,
                max_entity_tokens=_cfg.LIGHTRAG_ENTITY_MAX_TOKENS,
                max_relation_tokens=_cfg.LIGHTRAG_RELATION_MAX_TOKENS,
                # Domain entity types
                addon_params={
                    "entity_types_guidance": _ENTITY_TYPES_GUIDANCE,
                    "language": "Chinese",
                },
            )

            # Initialize storages (creates PG tables + vector indexes)
            await self._rag.initialize_storages()
            self._initialized = True

        except ImportError:
            import warnings
            warnings.warn(
                "lightrag-hku not installed. GraphRAG disabled. "
                "Install with: pip install lightrag-hku",
                RuntimeWarning,
            )
        except Exception:
            import warnings
            warnings.warn(
                "Failed to initialize GraphRAG. Disabling. "
                "Check PostgreSQL connectivity and embed_server health.",
                RuntimeWarning,
            )

    # ── Index ────────────────────────────────────────────────

    async def index_document(self, doc_id: str, content: str) -> str:
        """Index document raw text via LightRAG.ainsert().

        LightRAG internal flow:
          1. Chunk by 1200-token blocks (independent of WeKnora's 512-token chunks)
          2. extract_entities (LLM extracts entities/relations, using engineering domain types)
          3. merge_nodes_and_edges (incrementally merge into existing graph)
          4. Vector index (upsert into entities_vdb + relationships_vdb)
        """
        if not self._initialized:
            return ""
        await self._rag.ainsert(content, ids=[doc_id])
        return doc_id

    async def index_file(self, file_path: str) -> str:
        """Index a local text file → read + ainsert. Supports .md / .txt / .json."""
        if not self._initialized:
            return ""
        import os as _os
        abs_path = _os.path.abspath(file_path)
        if not _os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        with open(abs_path, "r", encoding="utf-8") as f:
            text = f.read()

        doc_id = md5(text.encode("utf-8")).hexdigest()
        return await self.index_document(f"doc-{doc_id}", text)

    # ── Search ───────────────────────────────────────────────

    async def search(self, query: str, mode: str = "mix") -> dict:
        """Graph retrieval.

        Args:
            query: Search query string
            mode: "local" | "global" | "hybrid" | "mix" | "naive"

        Returns:
            {
                "entities": [{"name": str, "type": str, "description": str}, ...],
                "relations": [{"src": str, "tgt": str, "type": str,
                               "description": str}, ...],
                "chunks": [{"content": str, "source": str}, ...],
                "formatted": "Formatted text, can be injected directly into <system-reminder>"
            }
        """
        if not self._initialized:
            return {"entities": [], "relations": [], "chunks": [], "formatted": ""}

        try:
            from lightrag import QueryParam

            result = await self._rag.aquery(
                query,
                param=QueryParam(mode=mode),
            )

            # LightRAG's QueryResult is a string — the final LLM answer.
            # For RRF fusion, we use the string content.
            # The LLM answer is placed in the "formatted" field.
            return {
                "entities": [],
                "relations": [],
                "chunks": [],
                "formatted": str(result) if result else "",
            }
        except Exception:
            return {"entities": [], "relations": [], "chunks": [], "formatted": ""}

    # ── Delete ───────────────────────────────────────────────

    async def delete_document(self, doc_id: str) -> None:
        """Delete a document and its associated graph nodes."""
        if not self._initialized:
            return
        try:
            await self._rag.adelete_by_doc_id(doc_id)
        except Exception:
            pass

    # ── Finalize ─────────────────────────────────────────────

    async def finalize(self) -> None:
        """Close LightRAG storage connections."""
        if not self._initialized:
            return
        try:
            await self._rag.finalize_storages()
        except Exception:
            pass


# ============================================================
# Module-level lazy singleton (per project_id)
# ============================================================

_engines: dict[str, GraphRAGEngine] = {}
_engines_lock = asyncio.Lock()


async def get_graph_rag(project_id: str = "default") -> GraphRAGEngine:
    """Get or create the GraphRAGEngine singleton for the given project_id.

    Thread-safe: uses asyncio.Lock + double-check to avoid race conditions.
    Engine is only stored after a successful initialize() to prevent callers
    from receiving an uninitialized engine.
    """
    if project_id in _engines:
        return _engines[project_id]

    async with _engines_lock:
        # Double-check after acquiring lock
        if project_id in _engines:
            return _engines[project_id]

        engine = GraphRAGEngine(project_id=project_id)
        await engine.initialize()
        _engines[project_id] = engine
        return engine


async def reset_graph_rag_engines() -> None:
    """Drop model-bound engines after the global memory model changes."""

    async with _engines_lock:
        engines = list(_engines.values())
        _engines.clear()
    for engine in engines:
        await engine.finalize()


# ── Entity type guidance (lazy import to avoid circular dependency) ──
_ENTITY_TYPES_GUIDANCE: str = ""


def _load_guidance() -> str:
    global _ENTITY_TYPES_GUIDANCE
    if not _ENTITY_TYPES_GUIDANCE:
        from .graph_rag_prompts import ENTITY_TYPES_GUIDANCE
        _ENTITY_TYPES_GUIDANCE = ENTITY_TYPES_GUIDANCE
    return _ENTITY_TYPES_GUIDANCE


# Guidance is loaded lazily inside initialize() to avoid
# ImportError from graph_rag_prompts breaking the module when LIGHTRAG_ENABLED=false.
