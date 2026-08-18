"""Local AgentScope development service used by ``start_agentscope.bat``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import os
import logging
from pathlib import Path
from typing import Any

from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import make_url

from agentscope.app import AgentScopeAuthConfig, create_app
from agentscope.app.access import DenyAllResourceAccessPolicy
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.mcp_registry import MCPRegistryManager
from agentscope.app.memory import (
    DobbyMemoryMiddleware,
    apply_global_memory_settings,
    configure_platform_memory_model,
    get_memory_runtime,
)
from agentscope.app.database_interactions import (
    DatabaseInteractionGatewayError,
    DatabaseInteractionManager,
    create_database_interaction_tools,
)
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import (
    AsyncSQLAlchemyStorage,
    MemorySettingsData,
    RedisStorage,
    StorageBase,
    WeKnoraConnectionConfig,
)
from agentscope.app._service import ResourceAccessService
from agentscope.app._tool import WeKnoraProjectKnowledgeTool
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.rag import (
    ExcelParser,
    PDFParser,
    PPTParser,
    PGVectorStore,
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
    KNOWLEDGE_BLOB_HOME,
    MCP_REGISTRY_HOME,
    SQLITE_PATH.parent,
):
    runtime_path.mkdir(parents=True, exist_ok=True)


def _create_storage() -> StorageBase:
    """Create the configured durable or compatibility storage backend."""
    global _fake_redis_client

    configured_url = (
        os.getenv("AGENTSCOPE_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    mode = os.getenv("AGENTSCOPE_STORAGE", "postgresql").strip().lower()

    if mode in {"postgres", "postgresql"}:
        if not configured_url:
            raise RuntimeError(
                "AGENTSCOPE_STORAGE=postgresql 时必须配置 DATABASE_URL "
                "或 AGENTSCOPE_DATABASE_URL",
            )
        url = make_url(configured_url)
        if url.get_backend_name() != "postgresql":
            raise RuntimeError("AgentScope PostgreSQL 存储收到的不是 PostgreSQL URL")
        async_url = url.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False,
        )
        return AsyncSQLAlchemyStorage(
            async_url,
            create_tables=False,
            auto_migrate=True,
            schema=os.getenv(
                "AGENTSCOPE_DATABASE_SCHEMA",
                "agentscope",
            ).strip(),
        )

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
        "AGENTSCOPE_STORAGE 仅支持 'postgresql'、'sqlite'、'memory' 或 'redis'",
    )


def _create_vector_store() -> PGVectorStore:
    """Create the shared PostgreSQL knowledge-base vector store."""

    configured_url = (
        os.getenv("AGENTSCOPE_KNOWLEDGE_DATABASE_URL", "").strip()
        or os.getenv("AGENTSCOPE_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not configured_url:
        raise RuntimeError(
            "知识库必须配置 DATABASE_URL、AGENTSCOPE_DATABASE_URL "
            "或 AGENTSCOPE_KNOWLEDGE_DATABASE_URL",
        )
    url = make_url(configured_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("知识库向量存储仅支持 PostgreSQL/pgvector")
    return PGVectorStore(
        url.render_as_string(hide_password=False),
        schema=(
            os.getenv("AGENTSCOPE_KNOWLEDGE_DATABASE_SCHEMA", "knowledge")
            .strip()
            or "knowledge"
        ),
    )


storage = _create_storage()
memory_resource_access = ResourceAccessService(
    storage=storage,
    policy=DenyAllResourceAccessPolicy(),
)
knowledge_base_manager = CollectionPerKbManager(
    storage=storage,
    vector_store=_create_vector_store(),
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


async def _memory_platform_context(user_id: str, session: Any) -> Any:
    """Resolve a worker session to the leader's platform project context."""

    platform_context = session.config.platform_context if session else None
    if session is not None and platform_context is None and session.team_id:
        team = await storage.get_team(user_id, session.team_id)
        if team is not None:
            leader = await storage.get_session(user_id, "", team.session_id)
            if leader is not None:
                platform_context = leader.config.platform_context
    return platform_context


async def _memory_settings(user_id: str) -> MemorySettingsData:
    """Load the persisted platform policy, including defaults for old rows."""

    record = await storage.get_platform_settings(user_id)
    if record is None:
        return MemorySettingsData()
    return record.data.memory_settings


def _configure_weknora_runtime(
    connection: WeKnoraConnectionConfig | None,
) -> None:
    """Make persisted platform WeKnora settings authoritative for chat tools."""

    if connection is None:
        return
    from utils import config as runtime_config
    from utils.langgraph_utils import invalidate_weknora_kb_cache

    next_base_url = (
        f"{connection.base_url}{connection.api_prefix}"
    )
    next_api_key = connection.api_key.get_secret_value()
    connection_changed = (
        runtime_config.WEKNORA_BASE_URL != next_base_url
        or runtime_config.WEKNORA_API_KEY != next_api_key
    )
    runtime_config.WEKNORA_BASE_URL = next_base_url
    runtime_config.WEKNORA_API_KEY = next_api_key
    runtime_config.WEKNORA_AGENT_ID = connection.agent_id
    runtime_config.WEKNORA_ENABLED = bool(runtime_config.WEKNORA_API_KEY)
    # No single knowledge base is pinned globally. The AgentScope tool lists
    # the tenant's available bases and searches them unless a turn selects one.
    runtime_config.WEKNORA_KB_NAME = ""
    if connection_changed:
        invalidate_weknora_kb_cache()


async def _create_memory_middlewares(
    user_id: str,
    agent_id: str,
    session_id: str,
):
    """Bind every AgentScope turn to its immutable project memory scope."""

    session = await storage.get_session(user_id, agent_id, session_id)
    platform_context = await _memory_platform_context(user_id, session)
    platform_settings = await storage.get_platform_settings(user_id)
    settings = (
        platform_settings.data.memory_settings
        if platform_settings is not None
        else MemorySettingsData()
    )
    _configure_weknora_runtime(
        platform_settings.data.weknora_connection
        if platform_settings is not None
        else None,
    )
    await configure_platform_memory_model(
        user_id,
        settings,
        memory_resource_access,
    )

    runtime = get_memory_runtime()
    scope = runtime.scope(
        project_id=(
            platform_context.project_id if platform_context is not None else None
        ),
        platform_user_id=(
            platform_context.user_id if platform_context is not None else user_id
        ),
        agent_id=agent_id,
        session_id=session_id,
        project_name=(
            platform_context.project_name
            if platform_context is not None
            else None
        ),
    )
    return [DobbyMemoryMiddleware(runtime, scope, settings)]


async def _end_memory_session(
    user_id: str,
    agent_id: str,
    session: Any,
) -> None:
    """Flush decay/reflection/experience lifecycle before session deletion."""

    platform_context = await _memory_platform_context(user_id, session)
    settings = await _memory_settings(user_id)
    await configure_platform_memory_model(
        user_id,
        settings,
        memory_resource_access,
    )
    runtime = get_memory_runtime()
    scope = runtime.scope(
        project_id=(
            platform_context.project_id if platform_context is not None else None
        ),
        platform_user_id=(
            platform_context.user_id if platform_context is not None else user_id
        ),
        agent_id=agent_id,
        session_id=session.id,
        project_name=(
            platform_context.project_name
            if platform_context is not None
            else None
        ),
    )
    await DobbyMemoryMiddleware(runtime, scope, settings).end_persisted_session(
        session.state,
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
    tools = []
    try:
        tools.extend(await create_database_interaction_tools(
            manager=database_interaction_manager,
            agent_id=agent_id,
            session_id=session_id,
            platform_session_id=platform_session_id,
            platform_agent_id=platform_agent_id,
            legacy_allowed_names=legacy_allowed_names,
        ))
    except DatabaseInteractionGatewayError as exc:
        logger.warning("Unable to load database interactions: %s", exc)
    platform_context = session.config.platform_context if session else None
    robot_id = (
        (platform_context.weknora_agent_id or "").strip()
        if platform_context is not None
        else ""
    )
    if robot_id:
        settings = await storage.get_platform_settings(user_id)
        connection = (
            settings.data.weknora_connection if settings is not None else None
        )
        if connection is not None and connection.api_key.get_secret_value():
            tools.append(
                WeKnoraProjectKnowledgeTool(
                    connection=connection,
                    robot_id=robot_id,
                ),
            )
    return tools

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
    extra_agent_middlewares=_create_memory_middlewares,
    session_end_handler=_end_memory_session,
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


def _active_memory_projects() -> list[str]:
    """Load active Dobby scopes for the upstream Dreamer cron scheduler."""

    import psycopg
    from utils import config as memory_config

    conn = psycopg.Connection.connect(
        memory_config.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
    )
    try:
        rows = conn.execute(
            """SELECT DISTINCT project_id
               FROM user_activity
               WHERE active_on >= CURRENT_DATE - INTERVAL '90 days'
               ORDER BY project_id""",
        ).fetchall()
        return [str(row[0]) for row in rows if row and row[0]]
    finally:
        conn.close()


async def _memory_maintenance_loop() -> None:
    """Run the copied Dreamer scheduler for every active memory scope."""

    from utils.memory_manager import MemoryManager

    last_slot = ""
    while True:
        slot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        if slot != last_slot:
            last_slot = slot
            try:
                global_config_id = (
                    os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "default").strip()
                    or "default"
                )
                settings = await _memory_settings(global_config_id)
                apply_global_memory_settings(settings)
                await configure_platform_memory_model(
                    global_config_id,
                    settings,
                    memory_resource_access,
                )
                if settings.dreamer_enabled:
                    projects = await asyncio.to_thread(_active_memory_projects)
                    for project_id in projects:
                        await MemoryManager(
                            project_id=project_id,
                            role_id="dobby_core",
                            runtime_settings=settings,
                        ).run_dreamer(project_id=project_id)
            except Exception:
                logger.exception("Dobby Dreamer maintenance iteration failed")
        await asyncio.sleep(30)


_agentscope_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_with_memory_maintenance(application: Any):
    async with _agentscope_lifespan(application):
        maintenance_task = asyncio.create_task(
            _memory_maintenance_loop(),
            name="dobby-memory-dreamer",
        )
        try:
            yield
        finally:
            maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance_task


app.router.lifespan_context = _lifespan_with_memory_maintenance
