# -*- coding: utf-8 -*-
"""Mandatory attachment preprocessing before a message reaches a model."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ...message import Base64Source, DataBlock, Msg, TextBlock, ToolResultState
from ...tool import Toolkit


_PARSER_TOOL_NAME = "mcp__attachment-parser__parse_attachment"
_DATA_MODELING_IMPORT_TOOL_NAME = (
    "mcp__interactive-data-modeling__predict_import_data"
)
_PAGE_LIMIT = 500
_DATA_MODELING_SUFFIXES = frozenset(
    {".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl", ".ndjson", ".parquet", ".pq"},
)


@dataclass(frozen=True)
class _AttachmentSource:
    """One attachment source accepted by the fixed parser tool."""

    name: str
    content_base64: str | None = None
    media_type: str | None = None

    def arguments(self) -> dict[str, Any]:
        return {
            "file_name": self.name,
            "content_base64": self.content_base64,
            "media_type": self.media_type,
        }


class AttachmentPipeline:
    """Parse every user attachment and replace raw model input with text.

    The original user message is kept for persistence and UI rendering.  A
    deep copy is produced for the agent context, with binary blocks removed
    and deterministic parser output appended as text.  Parse status is stored
    in both messages' metadata so refreshes retain auditable pipeline state.
    """

    async def prepare(
        self,
        input_msg: Msg | list[Msg],
        toolkit: Toolkit,
    ) -> Msg | list[Msg]:
        """Prepare one message or message batch before model execution."""
        if isinstance(input_msg, Msg):
            return await self._prepare_message(input_msg, toolkit)
        return [
            await self._prepare_message(message, toolkit)
            for message in input_msg
        ]

    async def _prepare_message(self, message: Msg, toolkit: Toolkit) -> Msg:
        if message.role != "user":
            return message

        sources = self._collect_sources(message)
        if not sources:
            return message

        parser_tool = await toolkit.get_tool(_PARSER_TOOL_NAME)
        data_modeling_import_tool = await toolkit.get_tool(
            _DATA_MODELING_IMPORT_TOOL_NAME,
        )
        parsed_sections: list[str] = []
        statuses: list[dict[str, Any]] = []
        for source in sources:
            data_modeling = await self._stage_for_data_modeling(
                data_modeling_import_tool,
                source,
            )
            if data_modeling and data_modeling.get("status") == "ready":
                parsed_sections.append(
                    self._data_modeling_section(source.name, data_modeling),
                )
            if parser_tool is None:
                error = "平台附件解析工具尚未就绪"
                parsed_sections.append(self._error_section(source.name, error))
                statuses.append(
                    {
                        "name": source.name,
                        "status": "failed",
                        "error": error,
                        "data_modeling": data_modeling,
                    },
                )
                continue
            try:
                sections, status = await self._parse_source(parser_tool, source)
            except Exception as exc:  # pylint: disable=broad-except
                error = str(exc).strip() or exc.__class__.__name__
                sections = [self._error_section(source.name, error)]
                status = {
                    "name": source.name,
                    "status": "failed",
                    "error": error,
                }
            parsed_sections.extend(sections)
            statuses.append(status)
            status["data_modeling"] = data_modeling

        failed = sum(item["status"] == "failed" for item in statuses)
        pipeline_status = (
            "failed"
            if failed == len(statuses)
            else "partial"
            if failed
            else "ready"
        )
        pipeline_metadata = {
            "version": 1,
            "status": pipeline_status,
            "total": len(statuses),
            "ready": len(statuses) - failed,
            "failed": failed,
            "items": statuses,
        }
        message.metadata = {
            **message.metadata,
            "attachment_preprocessing": pipeline_metadata,
        }

        prepared = message.model_copy(deep=True)
        prepared.content = [
            block
            for block in prepared.content
            if not isinstance(block, DataBlock)
        ]
        prepared.content.append(
            TextBlock(
                text=(
                    "\n<parsed-attachments>\n"
                    + "\n\n".join(parsed_sections)
                    + "\n</parsed-attachments>"
                ),
            ),
        )
        prepared.metadata["attachment_preprocessing"] = pipeline_metadata
        return prepared

    async def _stage_for_data_modeling(
        self,
        import_tool: Any | None,
        source: _AttachmentSource,
    ) -> dict[str, Any] | None:
        suffix = "." + source.name.rsplit(".", 1)[-1].lower() if "." in source.name else ""
        if suffix not in _DATA_MODELING_SUFFIXES:
            return None
        if source.content_base64 is None:
            return {
                "status": "failed",
                "error": "数据附件来源不受支持，请重新选择本地文件上传",
            }
        if import_tool is None:
            return {"status": "unavailable"}
        try:
            result = await import_tool.call(
                file_name=source.name,
                content_base64=source.content_base64,
                media_type=source.media_type,
            )
            if result.state == ToolResultState.ERROR:
                detail = "\n".join(
                    block.text
                    for block in result.content
                    if isinstance(block, TextBlock)
                ).strip()
                raise RuntimeError(detail or "数据分析 MCP 导入失败")
            raw = "\n".join(
                block.text
                for block in result.content
                if isinstance(block, TextBlock)
            )
            payload = json.loads(raw)
            data = payload.get("data") if isinstance(payload, dict) else None
            data_ref = data.get("data_ref") if isinstance(data, dict) else None
            if payload.get("status") != "ok" or not isinstance(data_ref, str):
                raise RuntimeError("数据分析 MCP 未返回有效 data_ref")
            return {
                "status": "ready",
                "data_ref": data_ref,
                "file_name": str(data.get("file_name") or source.name),
                "size": data.get("size"),
                "sha256": data.get("sha256"),
            }
        except Exception as exc:  # pylint: disable=broad-except
            return {
                "status": "failed",
                "error": str(exc).strip() or exc.__class__.__name__,
            }

    @staticmethod
    def _collect_sources(message: Msg) -> list[_AttachmentSource]:
        sources: list[_AttachmentSource] = []
        for block in message.get_content_blocks("data"):
            name = block.name or "attachment"
            if isinstance(block.source, Base64Source):
                sources.append(
                    _AttachmentSource(
                        name=name,
                        content_base64=block.source.data,
                        media_type=block.source.media_type,
                    ),
                )
            else:
                # URL/file sources are intentionally not fetched by the
                # server. Accepting arbitrary URLs here would turn attachment
                # preprocessing into a server-side request/file-read primitive.
                sources.append(_AttachmentSource(name=name))
        return sources

    async def _parse_source(
        self,
        parser_tool: Any,
        source: _AttachmentSource,
    ) -> tuple[list[str], dict[str, Any]]:
        if source.content_base64 is None:
            raise ValueError("附件来源不受支持，请重新选择本地文件上传")

        sections: list[str] = []
        parsers: set[str] = set()
        fallback_reasons: list[str] = []
        segment_count = 0
        character_count = 0
        sheet_queue: list[str | None] = [None]
        seen_sheets: set[str | None] = set()

        while sheet_queue:
            sheet_name = sheet_queue.pop(0)
            if sheet_name in seen_sheets:
                continue
            seen_sheets.add(sheet_name)
            start = 1
            seen_starts: set[int] = set()
            while True:
                if start in seen_starts:
                    raise RuntimeError("附件解析分页位置重复，已停止异常循环")
                seen_starts.add(start)
                arguments = {
                    **source.arguments(),
                    "start": start,
                    "limit": _PAGE_LIMIT,
                    "ocr_mode": "auto",
                }
                if sheet_name is not None:
                    arguments["sheet_name"] = sheet_name

                chunk = await parser_tool.call(**arguments)
                if chunk.state == ToolResultState.ERROR:
                    detail = "\n".join(
                        block.text
                        for block in chunk.content
                        if isinstance(block, TextBlock)
                    ).strip()
                    raise RuntimeError(detail or "附件解析失败")
                raw = "\n".join(
                    block.text
                    for block in chunk.content
                    if isinstance(block, TextBlock)
                )
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise RuntimeError("附件解析工具返回了无效结果")

                parser_name = str(payload.get("parser") or "unknown")
                parsers.add(parser_name)
                fallback = payload.get("mineru_error") or payload.get(
                    "fallback_reason",
                )
                if fallback:
                    fallback_reasons.append(str(fallback))
                rendered = self._render_payload(payload)
                segment_count += 1
                character_count += len(rendered)
                sections.append(
                    self._ready_section(
                        source.name,
                        payload,
                        rendered,
                        segment_count,
                    ),
                )

                if sheet_name is None:
                    current_sheet = payload.get("sheet_name")
                    sheet_names = payload.get("sheet_names")
                    if isinstance(sheet_names, list):
                        for candidate in sheet_names:
                            if not isinstance(candidate, str):
                                continue
                            if candidate != current_sheet:
                                sheet_queue.append(candidate)

                raw_next = payload.get("next_start")
                if raw_next is None:
                    break
                try:
                    next_start = int(raw_next)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("附件解析返回了无效分页位置") from exc
                if next_start <= start:
                    raise RuntimeError("附件解析分页位置没有向后推进")
                start = next_start

        return sections, {
            "name": source.name,
            "status": "ready",
            "parser": "+".join(sorted(parsers)),
            "segments": segment_count,
            "characters": character_count,
            "fallback_reasons": list(dict.fromkeys(fallback_reasons)),
        }

    @staticmethod
    def _render_payload(payload: dict[str, Any]) -> str:
        markdown = payload.get("markdown")
        if isinstance(markdown, str):
            return markdown
        lines = payload.get("lines")
        if isinstance(lines, list) and all(isinstance(item, str) for item in lines):
            return "\n".join(lines)
        content = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "file_id",
                "file_name",
                "parser",
                "primary_service",
                "mineru_error",
                "fallback_reason",
                "next_start",
                "result_files",
                "image_files",
            }
        }
        return json.dumps(content, ensure_ascii=False, default=str)

    @staticmethod
    def _ready_section(
        name: str,
        payload: dict[str, Any],
        rendered: str,
        segment: int,
    ) -> str:
        header = {
            "name": name,
            "status": "ready",
            "parser": payload.get("parser"),
            "format": payload.get("format"),
            "sheet_name": payload.get("sheet_name"),
            "segment": segment,
        }
        return (
            "<attachment>\n"
            f"{json.dumps(header, ensure_ascii=False)}\n"
            "<content>\n"
            f"{rendered}\n"
            "</content>\n"
            "</attachment>"
        )

    @staticmethod
    def _error_section(name: str, error: str) -> str:
        return (
            "<attachment>\n"
            + json.dumps(
                {"name": name, "status": "failed", "error": error},
                ensure_ascii=False,
            )
            + "\n附件未解析成功，原始二进制内容未发送给 AI。\n"
            "</attachment>"
        )

    @staticmethod
    def _data_modeling_section(name: str, staged: dict[str, Any]) -> str:
        return (
            "<data-analysis-source>\n"
            + json.dumps(
                {
                    "name": name,
                    "status": "ready",
                    "data_ref": staged["data_ref"],
                    "next_tool": "predict_create_session",
                },
                ensure_ascii=False,
            )
            + "\n该引用仅用于当前会话的数据分析 MCP，不是服务器文件路径。\n"
            "</data-analysis-source>"
        )
