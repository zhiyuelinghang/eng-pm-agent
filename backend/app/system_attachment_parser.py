"""Bridge document-library uploads into the fixed attachment parser package.

The parsing implementation lives in ``mcp-packages/attachment-parser``.  The
engineering platform only coordinates complete pagination and stores the
result so later AI requests never need the old, format-specific extractor.
"""

from __future__ import annotations

import base64
import importlib.util
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sys
from threading import Lock
from types import ModuleType
from typing import Any


_PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mcp-packages"
    / "attachment-parser"
)
_LOAD_LOCK = Lock()
_PAGE_LIMIT = 500


class SystemAttachmentParserError(RuntimeError):
    """The fixed attachment parser could not produce complete text."""


@dataclass(frozen=True)
class ParsedAttachment:
    """Complete, persistence-ready parser output for one uploaded file."""

    content: str
    parsers: tuple[str, ...]
    segments: int
    details: dict[str, Any]


@lru_cache(maxsize=1)
def _load_runtime() -> ModuleType:
    runtime_path = _PACKAGE_ROOT / "parser_runtime.py"
    if not runtime_path.is_file():
        raise SystemAttachmentParserError("平台固定附件解析工具源码不存在")
    with _LOAD_LOCK:
        module_name = "_dobby_system_attachment_parser_runtime"
        existing = sys.modules.get(module_name)
        if isinstance(existing, ModuleType):
            return existing
        spec = importlib.util.spec_from_file_location(module_name, runtime_path)
        if spec is None or spec.loader is None:
            raise SystemAttachmentParserError("无法加载平台固定附件解析工具")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        sys.path.insert(0, str(_PACKAGE_ROOT))
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        finally:
            sys.path.remove(str(_PACKAGE_ROOT))
        return module


@lru_cache(maxsize=1)
def _load_local_parser() -> ModuleType:
    """Load the bundled deterministic parser used for structured imports."""
    parser_path = _PACKAGE_ROOT / "local_parser.py"
    if not parser_path.is_file():
        raise SystemAttachmentParserError("平台固定附件解析工具源码不存在")
    with _LOAD_LOCK:
        module_name = "_dobby_system_attachment_local_parser"
        existing = sys.modules.get(module_name)
        if isinstance(existing, ModuleType):
            return existing
        spec = importlib.util.spec_from_file_location(module_name, parser_path)
        if spec is None or spec.loader is None:
            raise SystemAttachmentParserError("无法加载平台结构化附件解析器")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module


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


def parse_uploaded_attachment(
    content: bytes,
    *,
    file_name: str,
    media_type: str | None,
) -> ParsedAttachment:
    """Parse every page/row/sheet of one document-library upload."""
    runtime = _load_runtime()
    encoded = base64.b64encode(content).decode("ascii")
    rendered_segments: list[str] = []
    raw_segments: list[dict[str, Any]] = []
    parsers: set[str] = set()
    sheet_queue: list[str | None] = [None]
    seen_sheets: set[str | None] = set()

    try:
        while sheet_queue:
            sheet_name = sheet_queue.pop(0)
            if sheet_name in seen_sheets:
                continue
            seen_sheets.add(sheet_name)
            start = 1
            seen_starts: set[int] = set()
            while True:
                if start in seen_starts:
                    raise SystemAttachmentParserError(
                        "附件解析分页位置重复，已停止异常循环",
                    )
                seen_starts.add(start)
                arguments: dict[str, Any] = {
                    "file_name": file_name,
                    "content_base64": encoded,
                    "media_type": media_type,
                    "start": start,
                    "limit": _PAGE_LIMIT,
                    "ocr_mode": "auto",
                }
                if sheet_name is not None:
                    arguments["sheet_name"] = sheet_name
                payload = runtime.parse_attachment(**arguments)
                if not isinstance(payload, dict):
                    raise SystemAttachmentParserError(
                        "平台固定附件解析工具返回了无效结果",
                    )
                raw_segments.append(payload)
                parsers.add(str(payload.get("parser") or "unknown"))
                rendered_segments.append(_render_payload(payload))

                if sheet_name is None:
                    current_sheet = payload.get("sheet_name")
                    sheet_names = payload.get("sheet_names")
                    if isinstance(sheet_names, list):
                        for candidate in sheet_names:
                            if (
                                isinstance(candidate, str)
                                and candidate != current_sheet
                            ):
                                sheet_queue.append(candidate)

                raw_next = payload.get("next_start")
                if raw_next is None:
                    break
                next_start = int(raw_next)
                if next_start <= start:
                    raise SystemAttachmentParserError(
                        "附件解析分页位置没有向后推进",
                    )
                start = next_start
    except SystemAttachmentParserError:
        raise
    except Exception as exc:  # Parser errors are persisted by the caller.
        detail = str(exc).strip() or exc.__class__.__name__
        raise SystemAttachmentParserError(detail) from exc

    fallback_reasons = list(
        dict.fromkeys(
            str(reason)
            for segment in raw_segments
            if (
                reason := segment.get("mineru_error")
                or segment.get("fallback_reason")
            )
        ),
    )
    return ParsedAttachment(
        content="\n\n".join(rendered_segments),
        parsers=tuple(sorted(parsers)),
        segments=len(raw_segments),
        details={
            "version": 1,
            "status": "ready",
            "file_name": file_name,
            "segments": len(raw_segments),
            "parsers": sorted(parsers),
            "fallback_reasons": fallback_reasons,
        },
    )


def parse_structured_attachment_segments(
    content: bytes,
    *,
    file_name: str,
) -> list[dict[str, Any]]:
    """Return complete deterministic segments without any model-side paging.

    MinerU remains the primary document parser.  This second representation
    preserves spreadsheet rows, document blocks and page metadata so the
    platform can import known schemas directly instead of asking an agent to
    copy large tables through repeated tool calls.
    """
    parser = _load_local_parser()
    suffix = Path(file_name).suffix.lower()
    queue: list[str | None] = [None]
    seen_sheets: set[str | None] = set()
    segments: list[dict[str, Any]] = []
    while queue:
        sheet_name = queue.pop(0)
        if sheet_name in seen_sheets:
            continue
        seen_sheets.add(sheet_name)
        start = 1
        seen_starts: set[int] = set()
        while True:
            if start in seen_starts:
                raise SystemAttachmentParserError(
                    "结构化附件分页位置重复，已停止异常循环",
                )
            seen_starts.add(start)
            try:
                payload = parser.parse_attachment_content(
                    content,
                    suffix,
                    sheet_name,
                    start,
                    _PAGE_LIMIT,
                    "auto",
                )
            except Exception as exc:
                detail = str(exc).strip() or exc.__class__.__name__
                raise SystemAttachmentParserError(detail) from exc
            if not isinstance(payload, dict):
                raise SystemAttachmentParserError(
                    "平台结构化附件解析器返回了无效结果",
                )
            segments.append(payload)
            if sheet_name is None:
                current_sheet = payload.get("sheet_name")
                sheet_names = payload.get("sheet_names")
                if isinstance(sheet_names, list):
                    for candidate in sheet_names:
                        if (
                            isinstance(candidate, str)
                            and candidate != current_sheet
                        ):
                            queue.append(candidate)
            raw_next = payload.get("next_start")
            if raw_next is None:
                break
            next_start = int(raw_next)
            if next_start <= start:
                raise SystemAttachmentParserError(
                    "结构化附件分页位置没有向后推进",
                )
            start = next_start
    return segments
