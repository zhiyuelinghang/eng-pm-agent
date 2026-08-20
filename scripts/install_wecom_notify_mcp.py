"""安装或更新平台可分配的企业微信通知 MCP 包。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "wecom-notify-mcp-windows.zip"
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
            "企业微信通知 MCP 不存在，请先运行构建脚本："
            f"{DEFAULT_ARCHIVE}",
        )
    async with MCPRegistryManager(DEFAULT_REGISTRY) as manager:
        with DEFAULT_ARCHIVE.open("rb") as source:
            record = await manager.install_archive(
                source,
                allow_wecom_notification_capability=True,
            )
    print(
        f"已上传企业微信通知 MCP：{record.manifest.display_name} "
        f"v{record.manifest.version}。请给 Dobby 全局总控分配该 MCP。",
    )


if __name__ == "__main__":
    asyncio.run(install())
