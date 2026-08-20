"""只读核对任务引擎 MCP 的安装状态与智能体分配情况。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
REGISTRY_INDEX = (
    PROJECT_ROOT / "data" / "agentscope" / "mcp_registry" / "index.json"
)


async def audit() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from backend.app.config import get_settings
        from agentscope.app.storage import AsyncSQLAlchemyStorage

        settings = get_settings()
    finally:
        sys.path.remove(str(AGENTSCOPE_ROOT))
        sys.path.remove(str(PROJECT_ROOT))

    if not REGISTRY_INDEX.is_file():
        raise FileNotFoundError(f"MCP 注册索引不存在：{REGISTRY_INDEX}")
    index = json.loads(REGISTRY_INDEX.read_text(encoding="utf-8"))
    installed = any(
        item.get("id") == "task-engine"
        for item in index.get("packages", [])
    )

    configured_url = (
        os.getenv("AGENTSCOPE_DATABASE_URL", "").strip()
        or settings.database_url
    )
    url = make_url(configured_url).set(
        drivername="postgresql+asyncpg",
    ).render_as_string(hide_password=False)
    schema = os.getenv("AGENTSCOPE_DATABASE_SCHEMA", "agentscope").strip()
    global_config_id = os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "default").strip()

    async with AsyncSQLAlchemyStorage(
        url,
        create_tables=False,
        auto_migrate=False,
        schema=schema,
    ) as storage:
        agents = await storage.list_agents(global_config_id)

    print(f"任务引擎 MCP 已安装：{'是' if installed else '否'}")
    for record in agents:
        data = record.data
        assigned = "task-engine" in data.mcp_config.allowed_mcp_ids
        print(
            f"{record.id} | {data.name} | {data.platform_config.role} | "
            f"启用={data.platform_config.enabled} | "
            f"发布={data.platform_config.published} | "
            f"任务引擎={'已分配' if assigned else '未分配'}",
        )


if __name__ == "__main__":
    asyncio.run(audit())
