"""安装或更新平台可分配的任务引擎 MCP 包。"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "task-engine-mcp-windows.zip"
)
DEFAULT_REGISTRY = PROJECT_ROOT / "data" / "agentscope" / "mcp_registry"


def _load_host_environment() -> None:
    os.sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from backend.app.config import get_settings

        settings = get_settings()
    finally:
        os.sys.path.remove(str(PROJECT_ROOT))
    os.environ.setdefault("DATABASE_URL", settings.database_url)
    os.environ.setdefault("TASK_ENGINE_SCHEMA", settings.task_engine_schema)
    os.environ.setdefault("TASK_ENGINE_TZ", settings.task_engine_tz)


async def install() -> None:
    os.sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from agentscope.app.mcp_registry import MCPRegistryManager
    finally:
        os.sys.path.remove(str(AGENTSCOPE_ROOT))

    if not DEFAULT_ARCHIVE.is_file():
        raise FileNotFoundError(
            "任务引擎 MCP 不存在，请先运行构建脚本："
            f"{DEFAULT_ARCHIVE}",
        )
    async with MCPRegistryManager(DEFAULT_REGISTRY) as manager:
        with DEFAULT_ARCHIVE.open("rb") as source:
            record = await manager.install_archive(
                source,
                allow_task_engine_store_capability=True,
            )
    print(
        f"已上传任务引擎 MCP：{record.manifest.display_name} "
        f"v{record.manifest.version}。请给需要操作任务的智能体分配该 MCP。",
    )


if __name__ == "__main__":
    _load_host_environment()
    asyncio.run(install())
