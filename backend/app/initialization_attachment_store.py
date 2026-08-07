"""Persist fixed-parser output as bounded, session-scoped temporary data."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    ProjectInitializationAttachmentChunk,
    ProjectInitializationFile,
)
from .system_attachment_parser import ParsedAttachment


PARSED_ATTACHMENT_CHUNK_CHAR_LIMIT = 20_000


class InitializationAttachmentParseError(RuntimeError):
    """One or more selected attachments have no complete parsed content."""


def split_parsed_attachment_content(
    content: str,
    *,
    limit: int = PARSED_ATTACHMENT_CHUNK_CHAR_LIMIT,
) -> list[str]:
    """Split without losing characters, preferring a nearby line boundary."""
    if limit < 1:
        raise ValueError("解析资料分块上限必须大于 0")
    if not content:
        return [""]
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + limit, len(content))
        if end < len(content):
            # ``str.rfind`` uses an exclusive upper bound.  Excluding ``end``
            # guarantees that including the chosen newline can never produce
            # a chunk longer than ``limit``.
            newline = content.rfind("\n", start + (limit // 2), end)
            if newline >= 0:
                end = newline + 1
        chunks.append(content[start:end])
        start = end
    return chunks


def store_parsed_initialization_attachment(
    db: Session,
    file: ProjectInitializationFile,
    parsed: ParsedAttachment,
) -> list[ProjectInitializationAttachmentChunk]:
    """Replace the temporary parsed chunks for one raw initialization file."""
    db.execute(
        delete(ProjectInitializationAttachmentChunk).where(
            ProjectInitializationAttachmentChunk.file_id == file.id,
        ),
    )
    texts = split_parsed_attachment_content(parsed.content)
    rows = [
        ProjectInitializationAttachmentChunk(
            project_id=file.project_id,
            conversation_id=file.conversation_id,
            file_id=file.id,
            file_name=file.file_name,
            chunk_index=index,
            chunk_count=len(texts),
            status="ready",
            parser="+".join(parsed.parsers),
            content=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            parse_details=parsed.details,
        )
        for index, text in enumerate(texts)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def store_failed_initialization_attachment(
    db: Session,
    file: ProjectInitializationFile,
    error: str,
) -> ProjectInitializationAttachmentChunk:
    """Persist a visible failure marker instead of silently dropping a file."""
    db.execute(
        delete(ProjectInitializationAttachmentChunk).where(
            ProjectInitializationAttachmentChunk.file_id == file.id,
        ),
    )
    details = {
        "version": 1,
        "status": "failed",
        "file_name": file.file_name,
        "error": error,
    }
    row = ProjectInitializationAttachmentChunk(
        project_id=file.project_id,
        conversation_id=file.conversation_id,
        file_id=file.id,
        file_name=file.file_name,
        chunk_index=0,
        chunk_count=1,
        status="failed",
        content="",
        content_hash=hashlib.sha256(b"").hexdigest(),
        parse_error=error,
        parse_details=details,
    )
    db.add(row)
    db.flush()
    return row


def _rows_for_files(
    db: Session,
    files: Iterable[ProjectInitializationFile],
) -> dict[int, list[ProjectInitializationAttachmentChunk]]:
    file_ids = [item.id for item in files]
    if not file_ids:
        return {}
    rows = db.scalars(
        select(ProjectInitializationAttachmentChunk)
        .where(ProjectInitializationAttachmentChunk.file_id.in_(file_ids))
        .order_by(
            ProjectInitializationAttachmentChunk.file_id,
            ProjectInitializationAttachmentChunk.chunk_index,
        ),
    ).all()
    grouped: dict[int, list[ProjectInitializationAttachmentChunk]] = {
        file_id: [] for file_id in file_ids
    }
    for row in rows:
        grouped.setdefault(row.file_id, []).append(row)
    return grouped


def initialization_attachment_summary(
    db: Session,
    file: ProjectInitializationFile,
) -> dict[str, Any]:
    """Return compact preprocessing status for upload/list responses."""
    rows = _rows_for_files(db, [file]).get(file.id, [])
    if not rows:
        return {"version": 1, "status": "pending", "chunks": 0}
    failed = next((row for row in rows if row.status == "failed"), None)
    if failed is not None:
        return dict(failed.parse_details or {})
    return {
        **dict(rows[0].parse_details or {}),
        "status": "ready",
        "chunks": len(rows),
        "characters": sum(len(row.content) for row in rows),
    }


def initialization_attachment_manifest(
    db: Session,
    files: list[ProjectInitializationFile],
) -> dict[str, Any]:
    """Build a reference-only manifest; parsed text never enters invites."""
    grouped = _rows_for_files(db, files)
    manifest_files: list[dict[str, Any]] = []
    for file in files:
        rows = grouped.get(file.id, [])
        if not rows:
            raise InitializationAttachmentParseError(
                f"初始化附件「{file.file_name}」尚未完成解析",
            )
        failed = next((row for row in rows if row.status == "failed"), None)
        if failed is not None:
            raise InitializationAttachmentParseError(
                f"初始化附件「{file.file_name}」解析失败："
                f"{failed.parse_error or '未知错误'}",
            )
        expected_count = rows[0].chunk_count
        if (
            len(rows) != expected_count
            or [row.chunk_index for row in rows] != list(range(expected_count))
        ):
            raise InitializationAttachmentParseError(
                f"初始化附件「{file.file_name}」解析分块不完整",
            )
        manifest_files.append(
            {
                "file_id": file.id,
                "file_name": file.file_name,
                "content_type": file.content_type,
                "file_size": file.file_size,
                "chunks": [
                    {
                        "chunk_id": row.id,
                        "chunk_index": row.chunk_index,
                        "chunk_count": row.chunk_count,
                        "characters": len(row.content),
                        "content_hash": row.content_hash,
                    }
                    for row in rows
                ],
            },
        )
    return {
        "version": 1,
        "storage": "project_initialization_attachment_chunks",
        "files": manifest_files,
    }
