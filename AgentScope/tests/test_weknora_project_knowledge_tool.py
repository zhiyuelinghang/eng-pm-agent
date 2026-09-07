"""Tests for the project-scoped WeKnora query tool."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentscope.app._tool import WeKnoraProjectKnowledgeTool
from agentscope.app.storage import WeKnoraConnectionConfig
from agentscope.message import ToolResultState


@pytest.mark.asyncio
async def test_revoked_membership_prevents_any_remote_knowledge_query():
    resolver = AsyncMock(side_effect=RuntimeError("当前账号已无权访问该项目"))
    tool = WeKnoraProjectKnowledgeTool(
        connection=WeKnoraConnectionConfig(base_url="https://weknora.example.com", api_key="secret"),
        robot_id="old-robot", project_id="1", platform_user_id="2", scope_resolver=resolver,
    )
    with patch("agentscope.app._tool._weknora_project_knowledge.httpx.AsyncClient") as client:
        result = await tool.call("查询项目资料")
    assert result.state == ToolResultState.ERROR
    client.assert_not_called()


@pytest.mark.asyncio
async def test_answer_is_discarded_if_document_access_is_revoked_during_query():
    scope = {"user_id": "2", "project_id": "1", "conversation_id": "3",
             "weknora_agent_id": "robot", "weknora_query_enabled": True,
             "weknora_catalogue_ready": True, "weknora_knowledge_base_ids": ["kb"],
             "weknora_knowledge_ids": ["allowed-document"]}
    resolver = AsyncMock(side_effect=[scope, {**scope, "weknora_knowledge_ids": []}])
    tool = WeKnoraProjectKnowledgeTool(
        connection=WeKnoraConnectionConfig(base_url="https://weknora.example.com", api_key="secret"),
        robot_id="robot", project_id="1", platform_user_id="2", scope_resolver=resolver,
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=SimpleAsyncDeleteClient())
    client.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("agentscope.app._tool._weknora_project_knowledge.httpx.AsyncClient", return_value=client),
        patch.object(WeKnoraProjectKnowledgeTool, "_create_session", new=AsyncMock(return_value="remote")),
        patch.object(WeKnoraProjectKnowledgeTool, "_ask", new=AsyncMock(return_value=("不可再返回的内容", []))),
    ):
        result = await tool.call("查询资料")
    assert result.state == ToolResultState.ERROR
    assert "本次结果已丢弃" in result.content[0].text
    assert "不可再返回的内容" not in result.content[0].text


class SimpleAsyncDeleteClient:
    async def delete(self, _url):
        return None


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
        project_id="project-1",
        platform_user_id="user-7",
        platform_conversation_id="conversation-9",
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
    assert result.metadata["platform_user_id"] == "user-7"
    assert result.metadata["platform_project_id"] == "project-1"
    assert result.metadata["platform_conversation_id"] == "conversation-9"
    assert result.metadata["knowledge_access_mode"] == "project"
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


@pytest.mark.asyncio
async def test_project_knowledge_tool_applies_document_allowlist() -> None:
    tool = WeKnoraProjectKnowledgeTool(
        connection=WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="secret",
        ),
        robot_id="project-robot",
        project_id="project-1",
        knowledge_base_ids=["kb-allowed"],
        knowledge_ids=["document-allowed"],
        restricted=True,
    )
    request: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"response_type":"answer","content":"授权回答"}'
            yield 'data: {"response_type":"references","knowledge_references":[{"knowledge_id":"document-allowed","preview_url":"https://weknora.example.com/public-preview","download_url":"https://weknora.example.com/public-download"},{"knowledge_id":"document-denied"}]}'
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

    answer, references = await tool._ask(FakeClient(), "session-1", "问题")

    assert answer == "授权回答"
    assert references == [
        {
            "knowledge_id": "document-allowed",
            "preview_url": (
                "/api/projects/project-1/engineering-documents/knowledge/"
                "document-allowed/preview"
            ),
            "download_url": (
                "/api/projects/project-1/engineering-documents/knowledge/"
                "document-allowed/download"
            ),
        },
    ]
    assert str(request["url"]).endswith("/knowledge-chat/session-1")
    assert request["json"] == {
        "query": "问题",
        "agent_enabled": False,
        "agent_id": "project-robot",
        "knowledge_base_ids": ["kb-allowed"],
        "knowledge_ids": ["document-allowed"],
        "channel": "api",
    }
