"""Local AgentScope development service used by ``start_agentscope.bat``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope.app import AgentScopeAuthConfig, create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import (
    AsyncSQLAlchemyStorage,
    RedisStorage,
    StorageBase,
)
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.rag import (
    ExcelParser,
    PDFParser,
    PPTParser,
    QdrantStore,
    TextParser,
    WordParser,
)
from scripts.dobby_agent_tools import create_dobby_agent_tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_project_env() -> None:
    """Load the root ``.env`` without adding another runtime dependency."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
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


def _required_env(name: str) -> str:
    """Return one required auth setting with an actionable startup error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"缺少 AgentScope 鉴权配置 {name}，请在项目根目录 .env 中设置。",
        )
    return value


_load_project_env()
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
SQLITE_PATH = Path(
    os.getenv("AGENTSCOPE_SQLITE_PATH", RUNTIME_HOME / "agentscope.db"),
).resolve()
_fake_redis_client: Any = None

for runtime_path in (
    WORKSPACE_HOME,
    QDRANT_HOME,
    KNOWLEDGE_BLOB_HOME,
    SQLITE_PATH.parent,
):
    runtime_path.mkdir(parents=True, exist_ok=True)


def _create_storage() -> StorageBase:
    """Create the configured durable or compatibility storage backend."""
    global _fake_redis_client

    mode = os.getenv("AGENTSCOPE_STORAGE", "sqlite").strip().lower()
    if mode == "sqlite":
        sqlite_url = f"sqlite+aiosqlite:///{SQLITE_PATH.as_posix()}"
        return AsyncSQLAlchemyStorage(
            sqlite_url,
            create_tables=False,
            auto_migrate=True,
        )

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
        "AGENTSCOPE_STORAGE 仅支持 'sqlite'、'memory' 或 'redis'",
    )


storage = _create_storage()
knowledge_base_manager = CollectionPerKbManager(
    storage=storage,
    vector_store=QdrantStore(path=str(QDRANT_HOME)),
)


async def _create_platform_agent_tools(
    user_id: str,
    agent_id: str,
    session_id: str,
):
    """Bind an internal worker to its leader's Dobby platform context."""
    platform_session_id = session_id
    platform_agent_id = agent_id
    read_only = False
    initialization_role: str | None = None
    agent_record = await storage.get_agent(user_id, agent_id)
    if agent_record is not None:
        initialization_role = (
            agent_record.data.platform_config.initialization_role
        )
    session = await storage.get_session(user_id, agent_id, session_id)
    if session is not None and session.team_id is not None:
        team = await storage.get_team(user_id, session.team_id)
        if team is not None and team.session_id != session_id:
            leader_session = await storage.get_session(
                user_id,
                "",
                team.session_id,
            )
            if leader_session is not None:
                platform_session_id = leader_session.id
                platform_agent_id = leader_session.agent_id
                read_only = True
    return await create_dobby_agent_tools(
        user_id,
        agent_id,
        session_id,
        platform_session_id=platform_session_id,
        platform_agent_id=platform_agent_id,
        read_only=read_only,
        initialization_role=initialization_role,
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
    auth_config=AgentScopeAuthConfig(
        admin_username=_required_env("AGENTSCOPE_ADMIN_USERNAME"),
        admin_password=_required_env("AGENTSCOPE_ADMIN_PASSWORD"),
        signing_secret=_required_env("AGENTSCOPE_AUTH_SECRET"),
        service_token=_required_env("AGENTSCOPE_SERVICE_TOKEN"),
        global_config_id=os.getenv(
            "AGENTSCOPE_GLOBAL_CONFIG_ID",
            "default",
        ).strip()
        or "default",
        management_token_ttl_seconds=int(
            os.getenv("AGENTSCOPE_MANAGEMENT_TOKEN_TTL_SECONDS", "28800"),
        ),
    ),
    extra_agent_tools=_create_platform_agent_tools,
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)
