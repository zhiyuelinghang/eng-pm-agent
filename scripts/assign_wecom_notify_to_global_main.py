"""把已安装的企业微信通知 MCP 分配给唯一启用的 Dobby 全局总控。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
REGISTRY_INDEX = (
    PROJECT_ROOT / "data" / "agentscope" / "mcp_registry" / "index.json"
)
PACKAGE_ID = "wecom-notify"


async def assign() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from backend.app.config import get_settings
        from agentscope.app.storage import AsyncSQLAlchemyStorage
        from agentscope.app.storage._model import AgentData, AgentMCPConfig

        settings = get_settings()
    finally:
        sys.path.remove(str(AGENTSCOPE_ROOT))
        sys.path.remove(str(PROJECT_ROOT))

    if not REGISTRY_INDEX.is_file():
        raise FileNotFoundError(f"MCP 注册索引不存在：{REGISTRY_INDEX}")
    index = json.loads(REGISTRY_INDEX.read_text(encoding="utf-8"))
    if not any(
        item.get("id") == PACKAGE_ID
        for item in index.get("packages", [])
    ):
        raise RuntimeError("企业微信通知 MCP 尚未安装，不能分配")

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
        candidates = [
            record
            for record in agents
            if record.data.platform_config.role == "global_main"
            and record.data.platform_config.enabled
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"期望唯一启用的全局总控，实际找到 {len(candidates)} 个",
            )
        target = candidates[0]
        allowed = list(target.data.mcp_config.allowed_mcp_ids)
        if PACKAGE_ID in allowed:
            print(f"{target.data.name} 已分配企业微信通知 MCP，无需重复修改")
            return
        allowed.append(PACKAGE_ID)
        updated_data = AgentData.model_validate(
            {
                **target.data.model_dump(),
                "mcp_config": AgentMCPConfig(
                    allowed_mcp_ids=allowed,
                ).model_dump(),
            },
        )
        updated = target.model_copy(
            update={"data": updated_data, "updated_at": datetime.now()},
        )
        await storage.upsert_agent(global_config_id, updated)
        verified = await storage.get_agent(global_config_id, target.id)
        if (
            verified is None
            or PACKAGE_ID not in verified.data.mcp_config.allowed_mcp_ids
        ):
            raise RuntimeError("企业微信通知 MCP 分配结果未能持久化")
    print(f"已给 {target.data.name} 分配企业微信通知 MCP")


if __name__ == "__main__":
    asyncio.run(assign())
