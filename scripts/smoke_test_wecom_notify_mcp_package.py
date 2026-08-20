"""验证企业微信通知 MCP 成品包可注册且不会在测试中外发消息。"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
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


async def _run(archive: Path) -> None:
    sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from agentscope.app.mcp_registry import MCPRegistryManager
    finally:
        sys.path.remove(str(AGENTSCOPE_ROOT))

    with tempfile.TemporaryDirectory(prefix="wecom-notify-mcp-smoke-") as raw:
        registry_root = Path(raw) / "registry"
        async with MCPRegistryManager(registry_root) as manager:
            with archive.open("rb") as source:
                record = await manager.install_archive(
                    source,
                    allow_wecom_notification_capability=True,
                )
            assert record.id == "wecom-notify"
            assert record.manifest.command == "runtime/python.exe"
            assert record.manifest.platform_capabilities == [
                "dobby_wecom_notifications",
            ]
            assert len(record.tools) == 5
            assert "WECOM_WEBHOOK_URL" not in record.manifest.env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"MCP ZIP 不存在：{archive}")
    asyncio.run(_run(archive))
    print("MCP 包上传与 5 个工具探测：通过")
    print("平台会话网关能力声明：通过")
    print("测试过程未向企业微信发送消息：通过")


if __name__ == "__main__":
    main()
