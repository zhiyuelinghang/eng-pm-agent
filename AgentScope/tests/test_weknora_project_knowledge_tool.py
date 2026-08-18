"""Tests for the project-scoped WeKnora query tool."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentscope.app._tool import WeKnoraProjectKnowledgeTool
from agentscope.app.storage import WeKnoraConnectionConfig
from agentscope.message import ToolResultState


@pytest.mark.asyncio
async def test_project_knowledge_tool_returns_answer_and_references() -> None:
    tool = WeKnoraProjectKnowledgeTool(
        connection=WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_prefix="/api/v1",
            auth_header="X-API-Key",
            api_key="secret",
        ),
        robot_id="project-robot",
    )
    client = MagicMock()
    client.delete = AsyncMock()
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "agentscope.app._tool._weknora_project_knowledge.httpx.AsyncClient",
            return_value=client_context,
        ),
        patch.object(
            tool,
            "_create_session",
            new=AsyncMock(return_value="remote-session"),
        ),
        patch.object(
            tool,
            "_ask",
            new=AsyncMock(
                return_value=(
                    "根据施工方案，应先复核监测数据。",
                    [{"knowledge_id": "document-1", "score": 0.91}],
                ),
            ),
        ),
    ):
        result = await tool.call("深基坑施工前要检查什么？")

    assert result.state == ToolResultState.SUCCESS
    payload = json.loads(result.content[0].text)
    assert payload["answer"] == "根据施工方案，应先复核监测数据。"
    assert payload["references"][0]["knowledge_id"] == "document-1"
    assert result.metadata["weknora_robot_id"] == "project-robot"
    client.delete.assert_awaited_once_with(
        "https://weknora.example.com/api/v1/sessions/remote-session",
    )


@pytest.mark.asyncio
async def test_project_knowledge_tool_rejects_empty_query() -> None:
    tool = WeKnoraProjectKnowledgeTool(
        connection=WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="secret",
        ),
        robot_id="project-robot",
    )

    result = await tool.call("   ")

    assert result.state == ToolResultState.ERROR
    assert "不能为空" in result.content[0].text
