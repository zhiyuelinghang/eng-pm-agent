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


@pytest.mark.asyncio
async def test_project_knowledge_tool_prefers_public_resource_urls() -> None:
    tool = WeKnoraProjectKnowledgeTool(
        connection=WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="secret",
        ),
        robot_id="project-robot",
    )
    request: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"response_type":"answer","content":"包含直链图片"}'
            yield 'data: {"response_type":"complete"}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *args):
            del args
            return False

    class FakeClient:
        def stream(self, method, url, **kwargs):
            request.update({"method": method, "url": url, **kwargs})
            return FakeStream()

    answer, references = await tool._ask(
        FakeClient(),
        "session-1",
        "问题",
    )

    assert answer == "包含直链图片"
    assert references == []
    assert request["params"] == {"resource_urls": "public"}
