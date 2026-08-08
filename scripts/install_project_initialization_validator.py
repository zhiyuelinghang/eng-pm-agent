"""Install or update the platform-owned initialization validator package."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "project-initialization-validator-mcp-windows.zip"
)
DEFAULT_REGISTRY = PROJECT_ROOT / "data" / "agentscope" / "mcp_registry"


async def install() -> None:
    sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from agentscope.app.mcp_registry import MCPRegistryManager
    finally:
        sys.path.remove(str(AGENTSCOPE_ROOT))

    if not DEFAULT_ARCHIVE.is_file():
        raise FileNotFoundError(
            "项目初始化核验 MCP 不存在，请先运行构建脚本："
            f"{DEFAULT_ARCHIVE}",
        )
    async with MCPRegistryManager(DEFAULT_REGISTRY) as manager:
        with DEFAULT_ARCHIVE.open("rb") as source:
            record = await manager.install_archive(source)
    print(
        f"已安装平台核验 MCP：{record.manifest.display_name} "
        f"v{record.manifest.version}",
    )


if __name__ == "__main__":
    asyncio.run(install())
