"""MinerU-first attachment parsing for the managed MCP package."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import threading
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from local_parser import (
    SUPPORTED_ATTACHMENT_SUFFIXES,
    parse_attachment_content,
)


DEFAULT_MINERU_URL = "https://mgwzs689.xiaomy.net/file_parse"
MINERU_SUPPORTED_SUFFIXES = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".jp2",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
    },
)
_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jp2": "image/jp2",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_MAX_ZIP_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
_MAX_CACHE_ENTRIES = 8
_MAX_RAW_ATTACHMENT_BYTES = 100 * 1024 * 1024
_MEDIA_TYPE_SUFFIXES = {
    media_type: suffix
    for suffix, media_type in _MIME_TYPES.items()
}
_MEDIA_TYPE_SUFFIXES.update(
    {
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/vnd.ms-excel": ".xls",
    },
)


class AttachmentParserError(ValueError):
    """An attachment could not be fetched or parsed safely."""


class MinerUParserError(RuntimeError):
    """The configured MinerU service did not return usable Markdown."""


@dataclass(frozen=True)
class MinerUResult:
    markdown: str
    members: tuple[str, ...]
    images: tuple[str, ...]


_MINERU_CACHE: OrderedDict[str, MinerUResult] = OrderedDict()
_MINERU_CACHE_LOCK = threading.Lock()


def _positive_int(value: int, *, maximum: int) -> int:
    return min(max(1, int(value)), maximum)


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload
    else:
        detail = payload
    return json.dumps(detail, ensure_ascii=False, default=str)


def _find_markdown(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload if payload.strip() else None
    if isinstance(payload, dict):
        for key in ("markdown", "md", "content"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        for value in payload.values():
            candidate = _find_markdown(value)
            if candidate:
                return candidate
    if isinstance(payload, list):
        parts = [candidate for item in payload if (candidate := _find_markdown(item))]
        if parts:
            return "\n\n---\n\n".join(parts)
    return None


def _read_mineru_zip(content: bytes) -> MinerUResult:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if sum(item.file_size for item in infos) > _MAX_ZIP_UNCOMPRESSED_BYTES:
                raise MinerUParserError("MinerU 返回的 ZIP 解压后超过 250MB")
            markdown_infos = [
                item for item in infos if Path(item.filename).suffix.lower() == ".md"
            ]
            if not markdown_infos:
                raise MinerUParserError("MinerU 返回的 ZIP 中没有 Markdown 结果")
            markdown_parts = [
                archive.read(item).decode("utf-8-sig", errors="replace")
                for item in markdown_infos
            ]
            members = tuple(item.filename for item in infos)
            images = tuple(
                item.filename
                for item in infos
                if Path(item.filename).suffix.lower()
                in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
            )
    except zipfile.BadZipFile as exc:
        raise MinerUParserError("MinerU 返回内容不是有效 ZIP") from exc
    markdown = "\n\n---\n\n".join(markdown_parts).strip()
    if not markdown:
        raise MinerUParserError("MinerU 返回的 Markdown 为空")
    return MinerUResult(markdown=markdown, members=members, images=images)


def _decode_mineru_response(response: httpx.Response) -> MinerUResult:
    content_type = response.headers.get("content-type", "").lower()
    if "zip" in content_type or zipfile.is_zipfile(io.BytesIO(response.content)):
        return _read_mineru_zip(response.content)
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MinerUParserError("MinerU 返回了无效 JSON") from exc
        markdown = _find_markdown(payload)
        if markdown:
            return MinerUResult(markdown=markdown.strip(), members=(), images=())
    text = response.text.strip()
    if text:
        return MinerUResult(markdown=text, members=(), images=())
    raise MinerUParserError("MinerU 没有返回可读取的解析结果")


def _mineru_settings() -> tuple[str, str, str, float]:
    url = os.getenv("MINERU_FILE_PARSE_URL", DEFAULT_MINERU_URL).strip()
    backend = os.getenv("MINERU_BACKEND", "hybrid-engine").strip() or "hybrid-engine"
    server_url = os.getenv("MINERU_SERVER_URL", "").strip()
    try:
        timeout = float(os.getenv("MINERU_TIMEOUT_SECONDS", "180"))
    except ValueError as exc:
        raise MinerUParserError("MINERU_TIMEOUT_SECONDS 必须是数字") from exc
    if not url:
        raise MinerUParserError("未配置 MINERU_FILE_PARSE_URL")
    return url, backend, server_url, max(10.0, min(timeout, 900.0))


def _parse_with_mineru(
    content: bytes,
    suffix: str,
    source_name: str,
) -> MinerUResult:
    url, backend, server_url, timeout = _mineru_settings()
    cache_key = hashlib.sha256(
        b"\0".join(
            (
                url.encode("utf-8"),
                backend.encode("utf-8"),
                suffix.encode("ascii"),
                content,
            ),
        ),
    ).hexdigest()
    with _MINERU_CACHE_LOCK:
        cached = _MINERU_CACHE.get(cache_key)
        if cached is not None:
            _MINERU_CACHE.move_to_end(cache_key)
            return cached

    filename = Path(source_name).name or f"attachment{suffix}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                files={
                    "files": (
                        filename,
                        content,
                        _MIME_TYPES.get(suffix, "application/octet-stream"),
                    ),
                },
                data={
                    "backend": backend,
                    "server_url": server_url,
                    "return_md": "true",
                    "return_images": "true",
                    "response_format_zip": "true",
                },
            )
    except httpx.HTTPError as exc:
        raise MinerUParserError(f"MinerU 请求失败：{exc}") from exc
    if response.is_error:
        raise MinerUParserError(
            f"MinerU 返回 {response.status_code}：{_response_detail(response)}",
        )
    parsed = _decode_mineru_response(response)
    with _MINERU_CACHE_LOCK:
        _MINERU_CACHE[cache_key] = parsed
        _MINERU_CACHE.move_to_end(cache_key)
        while len(_MINERU_CACHE) > _MAX_CACHE_ENTRIES:
            _MINERU_CACHE.popitem(last=False)
    return parsed


def _paginate_markdown(
    parsed: MinerUResult,
    *,
    suffix: str,
    start: int,
    limit: int,
) -> dict[str, Any]:
    lines = parsed.markdown.splitlines()
    selected = lines[start - 1:start - 1 + limit]
    end = start + len(selected) - 1
    return {
        "format": suffix.removeprefix("."),
        "parser": "mineru",
        "start_line": start,
        "end_line": end,
        "total_lines": len(lines),
        "markdown": "\n".join(selected),
        "lines": selected,
        "result_files": list(parsed.members),
        "image_files": list(parsed.images),
        "next_start": end + 1 if end < len(lines) else None,
    }


def parse_attachment(
    file_name: str | None = None,
    content_base64: str | None = None,
    media_type: str | None = None,
    sheet_name: str | None = None,
    start: int = 1,
    limit: int = 100,
    ocr_mode: str = "auto",
) -> dict[str, Any]:
    """Parse one in-memory attachment supplied by the platform pipeline."""
    normalized_start = _positive_int(start, maximum=2_000_000_000)
    normalized_limit = _positive_int(limit, maximum=500)
    if content_base64 is None:
        raise AttachmentParserError("必须提供 content_base64")
    encoded = content_base64.strip()
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentParserError("附件内容不是有效的 Base64 数据") from exc
    if len(content) > _MAX_RAW_ATTACHMENT_BYTES:
        raise AttachmentParserError("单个附件不能超过 100MB")
    safe_name = Path(file_name or "attachment").name
    suffix = Path(safe_name).suffix.lower()
    if not suffix:
        suffix = _MEDIA_TYPE_SUFFIXES.get((media_type or "").lower(), "")
        safe_name = f"{safe_name}{suffix}"

    if suffix not in SUPPORTED_ATTACHMENT_SUFFIXES:
        raise AttachmentParserError(f"不支持的附件格式：{suffix or '未知'}")

    mineru_error: str | None = None
    if suffix in MINERU_SUPPORTED_SUFFIXES:
        try:
            parsed = _parse_with_mineru(content, suffix, safe_name)
            result = _paginate_markdown(
                parsed,
                suffix=suffix,
                start=normalized_start,
                limit=normalized_limit,
            )
            result["file_name"] = safe_name
            result["primary_service"] = urlsplit(_mineru_settings()[0]).netloc
            return result
        except (MinerUParserError, OSError, ValueError) as exc:
            mineru_error = str(exc)

    try:
        result = parse_attachment_content(
            content,
            suffix,
            sheet_name,
            normalized_start,
            normalized_limit,
            ocr_mode,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        if mineru_error:
            raise AttachmentParserError(
                f"MinerU 解析失败：{mineru_error}；本地降级解析也失败：{exc}",
            ) from exc
        raise AttachmentParserError(f"本地附件解析失败：{exc}") from exc
    result["file_name"] = safe_name
    result["parser"] = "local_fallback"
    if mineru_error:
        result["mineru_error"] = mineru_error
    elif suffix not in MINERU_SUPPORTED_SUFFIXES:
        result["fallback_reason"] = "该格式不属于开源 MinerU 的输入范围"
    return result
