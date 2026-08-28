"""本地 SQLite 模式的最小 AgentScope 服务。

用于没有 PostgreSQL/Docker 的开发机快速打开管理端页面。不启用知识库向量、
记忆维护和重型解析器，会话与智能体数据落在 SQLite。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import make_url

from agentscope.app import AgentScopeAuthConfig, create_app
from agentscope.app.access import DenyAllResourceAccessPolicy
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.mcp_registry import MCPRegistryManager
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def _load_project_env() -> None:
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _required_env(name: str) -> str:
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
KNOWLEDGE_BLOB_HOME = RUNTIME_HOME / "knowledge_blobs"
MCP_REGISTRY_HOME = RUNTIME_HOME / "mcp_registry"
SQLITE_PATH = Path(
    os.getenv("AGENTSCOPE_SQLITE_PATH", RUNTIME_HOME / "agentscope.db"),
).resolve()

for runtime_path in (
    WORKSPACE_HOME,
    KNOWLEDGE_BLOB_HOME,
    MCP_REGISTRY_HOME,
    SQLITE_PATH.parent,
):
    runtime_path.mkdir(parents=True, exist_ok=True)


_configured_url = (
    os.getenv("AGENTSCOPE_DATABASE_URL", "").strip()
    or os.getenv("DATABASE_URL", "").strip()
)
_storage_mode = os.getenv("AGENTSCOPE_STORAGE", "sqlite").strip().lower()
if _storage_mode in {"postgres", "postgresql"}:
    if not _configured_url:
        raise RuntimeError(
            "AGENTSCOPE_STORAGE=postgresql 时必须配置 DATABASE_URL "
            "或 AGENTSCOPE_DATABASE_URL",
        )
    _url = make_url(_configured_url)
    if _url.get_backend_name() != "postgresql":
        raise RuntimeError("AgentScope PostgreSQL 存储收到的不是 PostgreSQL URL")
    _async_url = _url.set(drivername="postgresql+asyncpg").render_as_string(
        hide_password=False,
    )
    storage = AsyncSQLAlchemyStorage(
        _async_url,
        create_tables=False,
        auto_migrate=True,
        schema=os.getenv("AGENTSCOPE_DATABASE_SCHEMA", "agentscope").strip(),
    )
else:
    storage = AsyncSQLAlchemyStorage(
        f"sqlite+aiosqlite:///{SQLITE_PATH.as_posix()}",
        create_tables=False,
        auto_migrate=True,
    )

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
    knowledge_base_manager=None,
    knowledge_parsers=None,
    knowledge_chunker=None,
    blob_store=LocalBlobStore(root_dir=KNOWLEDGE_BLOB_HOME),
    enable_index_worker=False,
    resource_access_policy=DenyAllResourceAccessPolicy(),
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
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)
