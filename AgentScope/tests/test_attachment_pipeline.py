"""Tests for mandatory attachment preprocessing before model execution."""

from __future__ import annotations

import base64
import json
from unittest import IsolatedAsyncioTestCase

from agentscope.app._service._attachment_pipeline import AttachmentPipeline
from agentscope.message import (
    Base64Source,
    DataBlock,
    TextBlock,
    ToolResultState,
    UserMsg,
)
from agentscope.tool import ToolChunk


class _ParserTool:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    async def call(self, **kwargs) -> ToolChunk:
        self.calls.append(kwargs)
        if self.fail:
            return ToolChunk(
                content=[TextBlock(text="解析服务不可用")],
                state=ToolResultState.ERROR,
            )
        start = int(kwargs["start"])
        payload = {
            "file_name": kwargs.get("file_name"),
            "format": "txt",
            "parser": "local_fallback",
            "start_line": start,
            "end_line": start,
            "total_lines": 2,
            "lines": [f"第{start}行"],
            "next_start": start + 1 if start == 1 else None,
        }
        return ToolChunk(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            state=ToolResultState.SUCCESS,
        )


class _Toolkit:
    def __init__(self, tool: _ParserTool | None) -> None:
        self.tool = tool
        self.requested_names: list[str] = []

    async def get_tool(self, name: str) -> _ParserTool | None:
        self.requested_names.append(name)
        return self.tool


class AttachmentPipelineTest(IsolatedAsyncioTestCase):
    async def test_base64_file_is_replaced_with_complete_parsed_text(self) -> None:
        tool = _ParserTool()
        message = UserMsg(
            name="user",
            content=[
                TextBlock(text="请分析附件"),
                DataBlock(
                    name="说明.txt",
                    source=Base64Source(
                        data=base64.b64encode("第一行\n第二行".encode()).decode(),
                        media_type="text/plain",
                    ),
                ),
            ],
        )

        prepared = await AttachmentPipeline().prepare(message, _Toolkit(tool))

        self.assertEqual(len(message.get_content_blocks("data")), 1)
        self.assertEqual(len(prepared.get_content_blocks("data")), 0)
        parsed_text = prepared.get_text_content() or ""
        self.assertIn("<parsed-attachments>", parsed_text)
        self.assertIn("第1行", parsed_text)
        self.assertIn("第2行", parsed_text)
        self.assertEqual(message.metadata["attachment_preprocessing"]["status"], "ready")
        self.assertEqual(tool.calls[0]["file_name"], "说明.txt")
        self.assertIn("content_base64", tool.calls[0])
        self.assertEqual([call["start"] for call in tool.calls], [1, 2])

    async def test_metadata_is_not_an_attachment_transport(self) -> None:
        tool = _ParserTool()
        message = UserMsg(
            name="user",
            content=[TextBlock(text="初始化项目")],
            metadata={
                "external_file_references": [
                    {"id": 42, "name": "项目资料.txt"},
                ],
            },
        )

        prepared = await AttachmentPipeline().prepare(message, _Toolkit(tool))

        self.assertIs(prepared, message)
        self.assertEqual(tool.calls, [])

    async def test_parse_failure_never_forwards_raw_binary(self) -> None:
        message = UserMsg(
            name="user",
            content=[
                DataBlock(
                    name="损坏.pdf",
                    source=Base64Source(
                        data=base64.b64encode(b"broken").decode(),
                        media_type="application/pdf",
                    ),
                ),
            ],
        )

        prepared = await AttachmentPipeline().prepare(
            message,
            _Toolkit(_ParserTool(fail=True)),
        )

        self.assertEqual(len(prepared.get_content_blocks("data")), 0)
        self.assertIn("原始二进制内容未发送给 AI", prepared.get_text_content() or "")
        self.assertEqual(message.metadata["attachment_preprocessing"]["status"], "failed")

    async def test_missing_fixed_parser_fails_closed(self) -> None:
        message = UserMsg(
            name="user",
            content=[
                DataBlock(
                    name="资料.csv",
                    source=Base64Source(
                        data=base64.b64encode(b"a,b").decode(),
                        media_type="text/csv",
                    ),
                ),
            ],
        )

        prepared = await AttachmentPipeline().prepare(message, _Toolkit(None))

        self.assertEqual(len(prepared.get_content_blocks("data")), 0)
        self.assertIn("附件解析工具尚未就绪", prepared.get_text_content() or "")
        self.assertEqual(message.metadata["attachment_preprocessing"]["failed"], 1)
