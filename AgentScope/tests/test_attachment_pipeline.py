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


class _ImportTool:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    async def call(self, **kwargs) -> ToolChunk:
        self.calls.append(kwargs)
        if self.fail:
            return ToolChunk(
                content=[TextBlock(text="数据导入失败")],
                state=ToolResultState.ERROR,
            )
        payload = {
            "status": "ok",
            "data": {
                "data_ref": "predict-data://" + "a" * 32,
                "file_name": kwargs["file_name"],
                "size": 12,
                "sha256": "a" * 64,
            },
        }
        return ToolChunk(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            state=ToolResultState.SUCCESS,
        )


class _Toolkit:
    def __init__(
        self,
        tool: _ParserTool | None,
        import_tool: _ImportTool | None = None,
    ) -> None:
        self.tool = tool
        self.import_tool = import_tool
        self.requested_names: list[str] = []

    async def get_tool(self, name: str) -> _ParserTool | _ImportTool | None:
        self.requested_names.append(name)
        if name.endswith("__predict_import_data"):
            return self.import_tool
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

    async def test_tabular_attachment_is_staged_for_assigned_data_mcp(self) -> None:
        parser = _ParserTool()
        importer = _ImportTool()
        message = UserMsg(
            name="user",
            content=[
                TextBlock(text="请建立预测模型"),
                DataBlock(
                    name="样本.csv",
                    source=Base64Source(
                        data=base64.b64encode(b"x,target\n1,0").decode(),
                        media_type="text/csv",
                    ),
                ),
            ],
        )

        prepared = await AttachmentPipeline().prepare(
            message,
            _Toolkit(parser, importer),
        )

        rendered = prepared.get_text_content() or ""
        self.assertIn("<data-analysis-source>", rendered)
        self.assertIn("predict-data://" + "a" * 32, rendered)
        self.assertNotIn(importer.calls[0]["content_base64"], rendered)
        self.assertEqual(importer.calls[0]["file_name"], "样本.csv")
        staged = message.metadata["attachment_preprocessing"]["items"][0][
            "data_modeling"
        ]
        self.assertEqual(staged["status"], "ready")

    async def test_data_import_failure_does_not_block_text_parser(self) -> None:
        message = UserMsg(
            name="user",
            content=[
                DataBlock(
                    name="样本.csv",
                    source=Base64Source(
                        data=base64.b64encode(b"x,target\n1,0").decode(),
                        media_type="text/csv",
                    ),
                ),
            ],
        )

        prepared = await AttachmentPipeline().prepare(
            message,
            _Toolkit(_ParserTool(), _ImportTool(fail=True)),
        )

        self.assertIn("第1行", prepared.get_text_content() or "")
        staged = message.metadata["attachment_preprocessing"]["items"][0][
            "data_modeling"
        ]
        self.assertEqual(staged["status"], "failed")
        self.assertEqual(message.metadata["attachment_preprocessing"]["status"], "ready")

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
