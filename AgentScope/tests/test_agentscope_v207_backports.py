# -*- coding: utf-8 -*-
"""Regression coverage for the selected AgentScope v2.0.7 backports."""
from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Literal
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from pydantic import BaseModel, Field, ValidationError

from agentscope.agent import ContextConfig
from agentscope.event import ModelCallEndEvent, ToolResultDataDeltaEvent
from agentscope.exception import ToolGroupInactiveError, ToolNotFoundError
from agentscope.mcp import HttpMCPConfig, MCPClient
from agentscope.message import AssistantMsg, TextBlock
from agentscope.model import ChatResponse
from agentscope.state import ToolContext
from agentscope.tool import FunctionTool, Toolkit, ToolGroup
from agentscope.tool._utils import _extract_input_schema


class _Location(BaseModel):
    """Location used to verify lazy model annotations."""

    city: str = Field(description="城市名称")


def _lazy_tool(
    query: Annotated[str, Field(description="检索关键词")],
    location: _Location,
    limit: int = 5,
) -> str:
    """Run a typed search."""
    return f"{query}:{location.city}:{limit}"


def _grouped_tool(value: int) -> str:
    """Return the supplied value."""
    return str(value)


class _CustomInput(BaseModel):
    """Custom input constraints."""

    mode: Literal["fast", "slow"]


class AgentScopeV207BackportTest(TestCase):
    """Synchronous v2.0.7 regression tests."""

    def test_lazy_annotations_and_custom_schema(self) -> None:
        """PEP 563 annotations and explicit schemas remain usable."""
        schema = _extract_input_schema(_lazy_tool)
        self.assertEqual(
            schema["properties"]["query"]["description"],
            "检索关键词",
        )
        self.assertEqual(
            schema["$defs"]["_Location"]["properties"]["city"][
                "description"
            ],
            "城市名称",
        )

        tool = FunctionTool(_grouped_tool, input_schema=_CustomInput)
        self.assertEqual(
            tool.input_schema["properties"]["mode"]["enum"],
            ["fast", "slow"],
        )
        self.assertNotIn("title", tool.input_schema)

    def test_data_event_requires_exactly_one_source(self) -> None:
        """Binary result events cannot be empty or ambiguous."""
        common = {
            "reply_id": "reply",
            "tool_call_id": "tool",
            "media_type": "image/png",
        }
        self.assertEqual(
            ToolResultDataDeltaEvent(**common, data="aGVsbG8=").data,
            "aGVsbG8=",
        )
        self.assertEqual(
            ToolResultDataDeltaEvent(
                **common,
                url="https://example.com/image.png",
            ).url,
            "https://example.com/image.png",
        )
        for invalid in (
            {},
            {"data": "aGVsbG8=", "url": "https://example.com/image.png"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    ToolResultDataDeltaEvent(**common, **invalid)

    def test_prompt_cache_usage_is_preserved(self) -> None:
        """Prompt cache counters survive event-to-message aggregation."""
        message = AssistantMsg(id="reply", name="assistant", content=[])
        message.append_event(
            ModelCallEndEvent(
                reply_id="reply",
                input_tokens=100,
                output_tokens=20,
                cache_input_tokens=60,
                cache_creation_input_tokens=40,
            ),
        )
        message.append_event(
            ModelCallEndEvent(
                reply_id="reply",
                input_tokens=10,
                output_tokens=2,
                cache_input_tokens=6,
                cache_creation_input_tokens=4,
            ),
        )
        self.assertIsNotNone(message.usage)
        self.assertEqual(message.usage.input_tokens, 110)
        self.assertEqual(message.usage.output_tokens, 22)
        self.assertEqual(message.usage.cache_input_tokens, 66)
        self.assertEqual(message.usage.cache_creation_input_tokens, 44)

    def test_missing_dict_attribute_follows_python_protocol(self) -> None:
        """Missing response attributes support hasattr and deepcopy."""
        response = ChatResponse(
            content=[TextBlock(text="hello")],
            is_last=True,
        )
        copied = deepcopy(response)
        self.assertFalse(hasattr(response, "missing"))
        self.assertEqual(getattr(response, "missing", "fallback"), "fallback")
        self.assertEqual(copied, response)
        self.assertIsNot(copied.content, response.content)

    def test_context_trigger_ratio_accepts_point_nine(self) -> None:
        """The documented maximum compression ratio is accepted."""
        self.assertEqual(ContextConfig(trigger_ratio=0.9).trigger_ratio, 0.9)
        with self.assertRaises(ValidationError):
            ContextConfig(trigger_ratio=0.9001)

    def test_mcp_sse_query_string_does_not_change_transport(self) -> None:
        """SSE endpoints with API-key query strings stay on SSE."""
        url = "https://mcp.example.com/sse?key=secret"
        marker = object()
        with patch(
            "agentscope.mcp._mcp_client.sse_client",
            return_value=marker,
        ) as mock_sse:
            client = MCPClient(
                name="query_sse",
                is_stateful=False,
                mcp_config=HttpMCPConfig(url=url),
            )
            self.assertIs(client._create_http_client(), marker)
        mock_sse.assert_called_once_with(
            url=url,
            headers=None,
            timeout=30.0,
        )


class AgentScopeV207AsyncBackportTest(IsolatedAsyncioTestCase):
    """Asynchronous v2.0.7 regression tests."""

    async def test_inactive_tool_group_is_not_reported_as_missing(self) -> None:
        """Inactive tools return an activation hint."""
        toolkit = Toolkit(
            tool_groups=[
                ToolGroup(
                    name="extra",
                    description="额外工具",
                    tools=[FunctionTool(_grouped_tool)],
                ),
            ],
        )
        with self.assertRaises(ToolGroupInactiveError):
            await toolkit.check_tool_available("_grouped_tool", [])
        self.assertEqual(
            (
                await toolkit.check_tool_available(
                    "_grouped_tool",
                    ["extra"],
                )
            ).name,
            "_grouped_tool",
        )
        with self.assertRaises(ToolNotFoundError):
            await toolkit.check_tool_available("missing", [])

    async def test_file_cache_hit_refreshes_lru_recency(self) -> None:
        """Recently read files are not evicted before older entries."""
        context = ToolContext(max_cache_files=3)
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"file-{idx}.txt" for idx in range(4)]
            for idx, path in enumerate(paths):
                path.write_text(f"content-{idx}", encoding="utf-8")
            for path in paths[:3]:
                await context.cache_file(str(path), [path.read_text("utf-8")])

            self.assertIsNotNone(await context.get_cache(str(paths[0])))
            await context.cache_file(
                str(paths[3]),
                [paths[3].read_text("utf-8")],
            )

            cached = {entry.file_path for entry in context.read_file_cache}
            self.assertIn(str(paths[0]), cached)
            self.assertNotIn(str(paths[1]), cached)
            self.assertIn(str(paths[2]), cached)
            self.assertIn(str(paths[3]), cached)
