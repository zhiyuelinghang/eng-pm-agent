"""Local AgentScope development service used by ``start_agentscope.bat``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import RedisStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.rag import (
    ExcelParser,
    PDFParser,
    PPTParser,
    QdrantStore,
    TextParser,
    WordParser,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_HOME = Path(
    os.getenv("AGENTSCOPE_RUNTIME_HOME", PROJECT_ROOT / "data" / "agentscope"),
).resolve()
WORKSPACE_HOME = RUNTIME_HOME / "workspaces"
QDRANT_HOME = Path(
    os.getenv("AGENTSCOPE_QDRANT_HOME", RUNTIME_HOME / "qdrant"),
).resolve()
KNOWLEDGE_BLOB_HOME = Path(
    os.getenv("AGENTSCOPE_KNOWLEDGE_BLOB_HOME", RUNTIME_HOME / "knowledge_blobs"),
).resolve()
_fake_redis_client: Any = None

for runtime_path in (WORKSPACE_HOME, QDRANT_HOME, KNOWLEDGE_BLOB_HOME):
    runtime_path.mkdir(parents=True, exist_ok=True)


def _create_storage() -> RedisStorage:
    """Create the release package's supported Redis storage backend."""
    global _fake_redis_client

    mode = os.getenv("AGENTSCOPE_STORAGE", "memory").strip().lower()
    if mode == "memory":
        from fakeredis.aioredis import FakeRedis

        _fake_redis_client = FakeRedis(decode_responses=True)
        return RedisStorage(
            connection_pool=_fake_redis_client.connection_pool,
        )

    if mode == "redis":
        return RedisStorage(
            host=os.getenv("AGENTSCOPE_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENTSCOPE_REDIS_PORT", "6379")),
            db=int(os.getenv("AGENTSCOPE_REDIS_DB", "0")),
            password=os.getenv("AGENTSCOPE_REDIS_PASSWORD") or None,
            socket_connect_timeout=3,
        )

    raise ValueError(
        "AGENTSCOPE_STORAGE 仅支持 'memory' 或 'redis'",
    )


storage = _create_storage()
knowledge_base_manager = CollectionPerKbManager(
    storage=storage,
    vector_store=QdrantStore(path=str(QDRANT_HOME)),
)

app = create_app(
    storage=storage,
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(basedir=str(WORKSPACE_HOME)),
    knowledge_base_manager=knowledge_base_manager,
    knowledge_parsers=[
        TextParser(),
        PDFParser(),
        WordParser(),
        PPTParser(),
        ExcelParser(),
    ],
    blob_store=LocalBlobStore(root_dir=KNOWLEDGE_BLOB_HOME),
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)
