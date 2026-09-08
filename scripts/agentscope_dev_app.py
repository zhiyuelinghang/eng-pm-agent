"""Local AgentScope development service used by ``start_agentscope.bat``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
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
from agentscope.app.skill_registry import SkillRegistryManager
from agentscope.app.memory import (
    agent_can_use_shared_memory,
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
from agentscope.tool import ToolGroup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
PROJECT_DATABASE_TOOL_GROUP = "project_database"


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
SKILL_REGISTRY_HOME = Path(
    os.getenv("AGENTSCOPE_SKILL_REGISTRY_HOME", RUNTIME_HOME / "skill_registry"),
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
            auto_migrate=False,
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
            auto_migrate=False,
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


async def _create_memory_middlewares(
    user_id: str,
    agent_id: str,
    session_id: str,
):
    """Bind shared memory only to management-level agents.

    Worker agents receive bounded task context from their caller and must not
    independently read or write long-term memory.
    """

    agent_record = await storage.get_agent(user_id, agent_id)
    if not agent_can_use_shared_memory(agent_record):
        return []
    session = await storage.get_session(user_id, agent_id, session_id)
    platform_context = await _memory_platform_context(user_id, session)
    platform_settings = await storage.get_platform_settings(user_id)
    settings = (
        platform_settings.data.memory_settings
        if platform_settings is not None
        else MemorySettingsData()
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
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from utils.memory_repository import MemoryAccess, MemoryError

    async def resolve_memory_access():
        # Refresh agent settings as well as project membership on each operation.
        current_agent = await storage.get_agent(user_id, agent_id)
        if not agent_can_use_shared_memory(current_agent) or not current_agent.data.platform_config.enabled:
            raise MemoryError("agent_memory_disabled", "该智能体已停用长期记忆。", status=403)
        policy = current_agent.data.platform_config
        if platform_context is not None:
            root_id = platform_context.root_session_id or session_id
            live = await database_interaction_manager.resolve_memory_scope(root_id)
            if str(live["user_id"]) != str(platform_context.user_id) or str(live["project_id"]) != str(platform_context.project_id):
                raise MemoryError("identity_mismatch", "会话身份与平台权限不一致。", status=403)
            return MemoryAccess(runtime.tenant_id, str(live["user_id"]), str(live["project_id"]),
                actor_id=f"business_user:{live['user_id']}", private=bool(live["private"]),
                project_read=bool(live["project_read"]), project_write=bool(live["project_write"]),
                group_source_channels=tuple(live.get('group_source_channels', [])), group_shared_channels=tuple(live.get('group_shared_channels', [])),
                read_scopes=tuple(policy.memory_read_scopes), write_scopes=tuple(policy.memory_write_scopes),
                learning_capture=policy.learning_capture,learning_process=policy.learning_process,learning_use=policy.learning_use)
        return MemoryAccess(runtime.tenant_id, str(user_id), identity_type="management_user",
            read_scopes=tuple(policy.memory_read_scopes), write_scopes=tuple(policy.memory_write_scopes),
            learning_capture=policy.learning_capture,learning_process=policy.learning_process,learning_use=policy.learning_use)

    return [
        ThreeDrawerMemoryMiddleware(
            runtime,
            scope,
            settings,
            include_knowledge_base=False,
            access_resolver=resolve_memory_access,
            compression_setup=lambda: configure_platform_memory_model(user_id,settings,memory_resource_access),
            config_owner=user_id,
            learning_session_id=(platform_context.root_session_id or session_id) if platform_context else session_id,
        ),
    ]


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
    platform_context = session.config.platform_context if session else None

    async def _load_database_tools():
        try:
            database_tools = await create_database_interaction_tools(
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

        if (
            platform_context is not None
            and platform_context.conversation_type == "general"
        ):
            # Homepage task creation is handled by the platform's private
            # draft workflow. Keeping the legacy SQL write tools here could
            # silently create records outside the formal task engine.
            database_tools = [
                tool
                for tool in database_tools
                if getattr(tool, "name", "")
                not in {"dobby_create_task", "dobby_update_task"}
            ]
        return database_tools

    tools = []
    if (
        platform_context is not None
        and platform_context.conversation_type == "general"
    ):
        # A normal turn sees only the capability-group description. The live
        # catalogue from the management centre is loaded after Dobby decides
        # that this request actually needs project data.
        tools.append(
            ToolGroup(
                name=PROJECT_DATABASE_TOOL_GROUP,
                description=(
                    "当前项目的数据库交互能力。仅当用户请求需要读取或更新实时"
                    "项目业务数据时激活；普通问候、解释以及不依赖项目数据的"
                    "请求保持关闭。组内只包含管理中心已分配给当前智能体、且"
                    "通过当前登录用户权限校验的能力。"
                ),
                instructions=(
                    "根据用户本轮意图，只调用完成请求所必需的数据库交互。"
                    "工具返回中没有的数据不得猜测；涉及写入时必须遵守工具自身"
                    "的确认和权限策略。"
                ),
                tool_loader=_load_database_tools,
            ),
        )
    else:
        tools.extend(await _load_database_tools())
    robot_id = (
        (platform_context.weknora_agent_id or "").strip()
        if platform_context is not None
        else ""
    )
    from agentscope.app._service._platform_settings import get_global_main_agent_id

    main_agent_id = await get_global_main_agent_id(storage, user_id, legacy_record=agent_record)

    async def _resolve_knowledge_scope():
        return await database_interaction_manager.resolve_knowledge_scope(
            session_id=platform_session_id, actor_agent_id=agent_id,
        )

    if (
        agent_record is not None
        and agent_record.id != main_agent_id
        and agent_record.data.platform_config.project_knowledge_enabled
        and platform_context is not None
    ):
        settings = await storage.get_platform_settings(user_id)
        connection = (
            settings.data.weknora_connection if settings is not None else None
        )
        if connection is not None and connection.api_key.get_secret_value():
            tools.append(
                WeKnoraProjectKnowledgeTool(
                    connection=connection,
                    robot_id=robot_id,
                    project_id=platform_context.project_id,
                    platform_user_id=platform_context.user_id,
                    platform_conversation_id=(
                        platform_context.conversation_id
                    ),
                    knowledge_base_ids=(
                        platform_context.weknora_knowledge_base_ids
                    ),
                    knowledge_ids=platform_context.weknora_knowledge_ids,
                    restricted=(
                        platform_context.weknora_access_mode == "restricted"
                    ),
                    scope_resolver=_resolve_knowledge_scope,
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
    skill_registry_manager=SkillRegistryManager(root_dir=SKILL_REGISTRY_HOME),
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


_agentscope_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_with_memory_maintenance(application: Any):
    async with _agentscope_lifespan(application):
        from utils.memory_service import run_memory_index_worker
        maintenance_task = asyncio.create_task(
            run_memory_index_worker(lambda: _memory_settings(os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "default").strip() or "default")),
            name="dobby-memory-index",
        )
        from utils.learning_repository import LearningRepository
        from utils.learning_service import run_learning_worker
        from utils.memory_service import get_memory_repository
        from agentscope.app.memory._learning import PlatformLearningRuntime
        global_id=os.getenv('AGENTSCOPE_GLOBAL_CONFIG_ID','default').strip() or 'default'
        learning_runtime=PlatformLearningRuntime(storage=storage,gateway=database_interaction_manager,resources=memory_resource_access,
            settings_loader=lambda:_memory_settings(global_id),tenant_id=get_memory_runtime().tenant_id)
        learning_task=asyncio.create_task(run_learning_worker(LearningRepository(get_memory_repository()),tenant_id=get_memory_runtime().tenant_id,
            settings_loader=lambda:_memory_settings(global_id),authorize=learning_runtime.authorize,call_model=learning_runtime.call_model),
            name='dobby-learning')
        from utils.group_learning_repository import GroupLearningRepository
        from utils.group_learning_service import run_group_learning_worker
        group_learning_task = asyncio.create_task(run_group_learning_worker(GroupLearningRepository(get_memory_repository()),
            runtime=learning_runtime, settings_loader=lambda:_memory_settings(global_id),
            tenant_id=get_memory_runtime().tenant_id, config_owner=global_id), name='dobby-group-learning')
        try:
            yield
        finally:
            maintenance_task.cancel()
            learning_task.cancel()
            group_learning_task.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance_task
            with suppress(asyncio.CancelledError):
                await learning_task
            with suppress(asyncio.CancelledError):
                await group_learning_task


app.router.lifespan_context = _lifespan_with_memory_maintenance
