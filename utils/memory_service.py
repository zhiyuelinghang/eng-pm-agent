"""Process-wide repository and bounded, restartable index worker."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from .memory_repository import MemoryRepository

logger = logging.getLogger(__name__)
_repository: MemoryRepository | None = None
_lock = threading.Lock()
_embedder: Any = None
_embedding_lock = threading.Lock()


def get_memory_repository() -> MemoryRepository:
    global _repository
    with _lock:
        if _repository is None:
            from . import config
            _repository = MemoryRepository(config.DATABASE_URL)
        return _repository


def embed_memory(text: str, *, initialize: bool = True) -> list[float] | None:
    """Load only in the index worker; never initialize Mem0 or an LLM."""
    global _embedder
    from . import config
    if not _embedding_lock.acquire(blocking=initialize):
        return None
    try:
        if _embedder is None:
            if not initialize:
                return None
            if config.EMBEDDING_PROVIDER == "local":
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer(config.EMBEDDING_MODEL, local_files_only=True, device="cpu")
            else:
                from openai import OpenAI
                _embedder = OpenAI(api_key=config.EMBEDDING_API_KEY, base_url=config.EMBEDDING_BASE_URL,
                                   timeout=15, max_retries=0)
        if config.EMBEDDING_PROVIDER == "local":
            return _embedder.encode(text, convert_to_numpy=True).tolist()
        return _embedder.embeddings.create(model=config.EMBEDDING_MODEL, input=[text], dimensions=1024).data[0].embedding
    finally:
        _embedding_lock.release()


async def search_vector_if_ready(query: str) -> list[float] | None:
    if _embedder is None or not query.strip() or _embedding_lock.locked():
        return None
    try:
        return await asyncio.wait_for(asyncio.to_thread(embed_memory, query, initialize=False), timeout=1.0)
    except Exception:
        return None


async def run_memory_index_worker(settings_loader=None) -> None:
    """Jobs remain durable on cancellation. Expired leases are reclaimable."""
    repository = get_memory_repository()
    while True:
        try:
            if settings_loader is not None:
                settings = await settings_loader()
                if not settings.memory_index_enabled:
                    await asyncio.sleep(5)
                    continue
            job = await asyncio.to_thread(repository.claim_index_job)
            if job is None:
                await asyncio.sleep(3)
                continue
            try:
                vector = await asyncio.to_thread(embed_memory, job["content"])
                await asyncio.to_thread(repository.finish_index_job, job, vector=vector)
            except Exception as exc:
                logger.exception("Memory index failed: memory_id=%s version=%s", job["memory_id"], job["version"])
                await asyncio.to_thread(repository.finish_index_job, job, error_code=type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Memory index worker iteration failed")
            await asyncio.sleep(10)
