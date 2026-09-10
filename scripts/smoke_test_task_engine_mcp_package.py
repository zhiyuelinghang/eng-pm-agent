"""验证任务引擎 MCP 成品包能由平台注册并以 PostgreSQL 模式启动。"""
from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
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


async def _run(archive: Path) -> None:
    os.sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from agentscope.app.mcp_registry import MCPRegistryManager
    finally:
        os.sys.path.remove(str(AGENTSCOPE_ROOT))

    with tempfile.TemporaryDirectory(prefix="task-engine-mcp-smoke-") as raw:
        registry_root = Path(raw) / "registry"
        async with MCPRegistryManager(registry_root) as manager:
            with archive.open("rb") as source:
                record = await manager.install_archive(
                    source,
                    allow_task_engine_store_capability=True,
                )
            assert record.id == "task-engine"
            assert record.manifest.command == "runtime/python.exe"
            assert record.manifest.platform_capabilities == [
                "dobby_task_engine_store",
            ]
            assert len(record.tools) == 21
            assert not list(registry_root.rglob("*.db"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    arguments = parser.parse_args()
    archive = arguments.archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"MCP ZIP 不存在：{archive}")
    _load_host_environment()
    asyncio.run(_run(archive))
    print("MCP 包上传与 21 个工具探测：通过")
    print("平台 PostgreSQL 模式启动：通过")
    print("未生成 SQLite 数据库：通过")


if __name__ == "__main__":
    main()
