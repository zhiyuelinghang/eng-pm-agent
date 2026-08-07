"""Build-time smoke test for the project-initialization validator MCP."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from agentscope.app.mcp_registry import MCPRegistryManager
from agentscope.message import TextBlock, ToolResultState


DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "project-initialization-validator-mcp-windows.zip"
)


def _draft(*, valid_dates: bool) -> dict:
    return {
        "project": {
            "name": "核验测试项目",
            "contract_start_date": "2026-08-01" if valid_dates else "2026-08-10",
            "contract_end_date": "2026-08-09",
        },
        "personnel": [],
        "wbs": [],
        "risks": [],
        "quality_requirements": [],
    }


async def _call(tool, draft: dict) -> dict:
    chunk = await tool.call(draft=draft)
    if chunk.state == ToolResultState.ERROR:
        raise RuntimeError(
            f"核验 MCP 调用失败：state={chunk.state!r}, content={chunk.content!r}",
        )
    raw = "\n".join(
        block.text for block in chunk.content if isinstance(block, TextBlock)
    )
    return json.loads(raw)


async def _run(archive: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="initialization-validator-smoke-") as raw:
        async with MCPRegistryManager(Path(raw) / "registry") as manager:
            with archive.open("rb") as source:
                record = await manager.install_archive(source)
            assert record.id == "project-initialization-validator"
            assert record.manifest.platform_capabilities == [
                "project_initialization_validation",
            ]
            assert [tool.display_name for tool in record.tools] == [
                "核验项目初始化草稿",
            ]

            client = await manager.get_platform_client(
                record.id,
                runtime_id="smoke-test",
            )
            tool = await client.get_tool("validate_project_initialization")
            assert tool is not None
            valid = await _call(tool, _draft(valid_dates=True))
            invalid = await _call(tool, _draft(valid_dates=False))

            assert valid["status"] == "ready"
            assert invalid["status"] == "invalid"
            assert any(
                issue["rule_id"] == "project.contract_date_order"
                for issue in invalid["validation_issues"]
            )
            assert valid["ruleset_version"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    arguments = parser.parse_args()
    archive = arguments.archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"MCP ZIP 不存在：{archive}")
    asyncio.run(_run(archive))
    print("MCP 包上传与探测：通过")
    print("平台固定入口调用：通过")
    print("有效/无效草稿规则判定：通过")


if __name__ == "__main__":
    main()
