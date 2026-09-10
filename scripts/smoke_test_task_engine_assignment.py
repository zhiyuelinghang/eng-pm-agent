"""从全局总控的实际 MCP 分配执行只读任务查询。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
REGISTRY_ROOT = PROJECT_ROOT / "data" / "agentscope" / "mcp_registry"


async def smoke() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from backend.app.config import get_settings
        from agentscope.app.mcp_registry import MCPRegistryManager
        from agentscope.app.storage import AsyncSQLAlchemyStorage
        from agentscope.message import TextBlock, ToolResultState

        settings = get_settings()
    finally:
        sys.path.remove(str(AGENTSCOPE_ROOT))
        sys.path.remove(str(PROJECT_ROOT))

    os.environ.setdefault("DATABASE_URL", settings.database_url)
    os.environ.setdefault("TASK_ENGINE_SCHEMA", settings.task_engine_schema)
    os.environ.setdefault("TASK_ENGINE_TZ", settings.task_engine_tz)

    configured_url = (
        os.getenv("AGENTSCOPE_DATABASE_URL", "").strip()
        or settings.database_url
    )
    storage_url = make_url(configured_url).set(
        drivername="postgresql+asyncpg",
    ).render_as_string(hide_password=False)
    storage_schema = os.getenv(
        "AGENTSCOPE_DATABASE_SCHEMA",
        "agentscope",
    ).strip()
    global_config_id = os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "default").strip()

    async with AsyncSQLAlchemyStorage(
        storage_url,
        create_tables=False,
        auto_migrate=False,
        schema=storage_schema,
    ) as storage:
        agents = await storage.list_agents(global_config_id)
        main_agents = [
            record
            for record in agents
            if record.data.platform_config.role == "global_main"
            and record.data.platform_config.enabled
        ]
        if len(main_agents) != 1:
            raise RuntimeError("无法确定唯一启用的全局总控")
        main_agent = main_agents[0]
        if "task-engine" not in main_agent.data.mcp_config.allowed_mcp_ids:
            raise RuntimeError("全局总控尚未分配任务引擎 MCP")

    async with MCPRegistryManager(REGISTRY_ROOT) as manager:
        clients = await manager.get_session_clients(
            user_id=global_config_id,
            agent_id=main_agent.id,
            session_id=f"task-engine-smoke-{uuid.uuid4().hex[:12]}",
            package_ids=main_agent.data.mcp_config.allowed_mcp_ids,
        )
        task_client = next(
            (client for client in clients if client.name == "task-engine"),
            None,
        )
        if task_client is None:
            raise RuntimeError("全局总控运行态未加载任务引擎 MCP")
        tool = await task_client.get_tool("list_tasks")
        if tool is None:
            raise RuntimeError("任务引擎 MCP 缺少 list_tasks 工具")
        chunk = await tool.call(open_only=True, limit=1)
        if chunk.state == ToolResultState.ERROR:
            raise RuntimeError(f"list_tasks 调用失败：{chunk.content!r}")
        raw = "\n".join(
            block.text
            for block in chunk.content
            if isinstance(block, TextBlock)
        )
        payload = json.loads(raw)
        if not isinstance(payload.get("tasks"), list):
            raise RuntimeError("list_tasks 返回结构不符合任务引擎契约")

    print("全局总控 MCP 分配加载：通过")
    print("已安装任务引擎 list_tasks 调用：通过")
    print("PostgreSQL 任务列表返回契约：通过")


if __name__ == "__main__":
    asyncio.run(smoke())
