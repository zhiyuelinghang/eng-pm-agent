"""Install or update the platform-compatible data-analysis MCP package."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "interactive-data-modeling-mcp-windows.zip"
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
            "数据分析 MCP 包不存在，请先运行构建脚本："
            f"{DEFAULT_ARCHIVE}",
        )
    with zipfile.ZipFile(DEFAULT_ARCHIVE) as archive:
        manifests = [name for name in archive.namelist() if name.endswith("/mcp.json")]
        if len(manifests) != 1:
            raise RuntimeError("MCP ZIP 内必须且只能包含一个 mcp.json")
        archive_manifest = json.loads(archive.read(manifests[0]).decode("utf-8"))
    async with MCPRegistryManager(DEFAULT_REGISTRY) as manager:
        current = await manager.get_record(str(archive_manifest["name"]))
        if (
            current is not None
            and current.manifest.version == str(archive_manifest["version"])
        ):
            print(
                f"平台 MCP 已是当前版本：{current.manifest.display_name} "
                f"v{current.manifest.version}，工具 {len(current.tools)} 个",
            )
            return
        with DEFAULT_ARCHIVE.open("rb") as source:
            record = await manager.install_archive(source)
    print(
        f"已安装平台 MCP：{record.manifest.display_name} "
        f"v{record.manifest.version}，工具 {len(record.tools)} 个",
    )


if __name__ == "__main__":
    asyncio.run(install())
