"""Local AgentScope development service used by ``start_agentscope.bat``."""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any

from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope.app import AgentScopeAuthConfig, create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.mcp_registry import MCPRegistryManager
from agentscope.app.database_interactions import (
    DatabaseInteractionGatewayError,
    DatabaseInteractionManager,
    create_database_interaction_tools,
)
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
PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


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
MCP_REGISTRY_HOME = Path(
    os.getenv("AGENTSCOPE_MCP_REGISTRY_HOME", RUNTIME_HOME / "mcp_registry"),
).resolve()
SQLITE_PATH = Path(
    os.getenv("AGENTSCOPE_SQLITE_PATH", RUNTIME_HOME / "agentscope.db"),
).resolve()
_fake_redis_client: Any = None

for runtime_path in (
    WORKSPACE_HOME,
    QDRANT_HOME,
    KNOWLEDGE_BLOB_HOME,
    MCP_REGISTRY_HOME,
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


def _database_interaction_api_base() -> str:
    explicit = os.getenv("DOBBY_INTERNAL_API_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    gateway = os.getenv(
        "DOBBY_AGENT_TOOL_BASE_URL",
        "http://127.0.0.1:38430/api/internal/agent-tools",
    ).strip().rstrip("/")
    return gateway.rsplit("/agent-tools", 1)[0]


database_interaction_manager = DatabaseInteractionManager(
    base_url=_database_interaction_api_base(),
    token=(
        os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
        or _required_env("AGENTSCOPE_SERVICE_TOKEN")
    ),
)


async def _create_platform_agent_tools(
    user_id: str,
    agent_id: str,
    session_id: str,
):
    """Bind an internal worker to its leader's Dobby platform context."""
    platform_session_id = session_id
    platform_agent_id = agent_id
    legacy_allowed_names: list[str] | None = None
    agent_record = await storage.get_agent(user_id, agent_id)
    if agent_record is not None:
        legacy_allowed_names = agent_record.data.tool_config.allowed_tool_names
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
    try:
        return await create_database_interaction_tools(
            manager=database_interaction_manager,
            agent_id=agent_id,
            session_id=session_id,
            platform_session_id=platform_session_id,
            platform_agent_id=platform_agent_id,
            legacy_allowed_names=legacy_allowed_names,
        )
    except DatabaseInteractionGatewayError as exc:
        logger.warning("Unable to load database interactions: %s", exc)
        return []

app = create_app(
    storage=storage,
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(basedir=str(WORKSPACE_HOME)),
    mcp_registry_manager=MCPRegistryManager(
        root_dir=MCP_REGISTRY_HOME,
        idle_ttl=float(os.getenv("AGENTSCOPE_MCP_IDLE_TTL_SECONDS", "3600")),
        max_active_instances=int(
            os.getenv("AGENTSCOPE_MCP_MAX_ACTIVE_INSTANCES", "128"),
        ),
        system_tool_package_ids={"attachment-parser"},
    ),
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
app.state.database_interaction_manager = database_interaction_manager
