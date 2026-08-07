import json
from types import SimpleNamespace

import pytest

from backend.app.initialization_attachment_store import (
    InitializationAttachmentParseError,
    initialization_attachment_manifest,
    split_parsed_attachment_content,
    store_parsed_initialization_attachment,
)
from backend.app.system_attachment_parser import ParsedAttachment


class _ScalarRows:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self._rows)


class _CaptureWriteSession:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def execute(self, _statement: object) -> None:
        return None

    def add_all(self, rows: list[object]) -> None:
        self.rows.extend(rows)

    def flush(self) -> None:
        return None


def test_split_attachment_content_is_lossless_and_bounded() -> None:
    content = ("甲" * 17) + "\n" + ("乙" * 24) + "\n" + ("丙" * 11)

    chunks = split_parsed_attachment_content(content, limit=20)

    assert "".join(chunks) == content
    assert all(0 < len(chunk) <= 20 for chunk in chunks)


def test_split_long_line_is_lossless_and_bounded() -> None:
    content = "项目资料" * 51

    chunks = split_parsed_attachment_content(content, limit=37)

    assert "".join(chunks) == content
    assert all(0 < len(chunk) <= 37 for chunk in chunks)


def test_newline_exactly_at_limit_does_not_overflow_chunk() -> None:
    content = ("甲" * 20) + "\n后续"

    chunks = split_parsed_attachment_content(content, limit=20)

    assert "".join(chunks) == content
    assert all(0 < len(chunk) <= 20 for chunk in chunks)


def test_store_parsed_attachment_persists_complete_bounded_chunks() -> None:
    content = "第一行\n" + ("较长的项目解析内容" * 3_000)
    parsed = ParsedAttachment(
        content=content,
        parsers=("local-xlsx",),
        segments=2,
        details={"version": 1, "segments": 2},
    )
    file = SimpleNamespace(
        id=12,
        project_id=2,
        conversation_id=3,
        file_name="总进度计划.xlsx",
    )
    db = _CaptureWriteSession()

    rows = store_parsed_initialization_attachment(db, file, parsed)

    assert rows == db.rows
    assert "".join(row.content for row in rows) == content
    assert len(rows) > 1
    assert all(row.chunk_count == len(rows) for row in rows)
    assert [row.chunk_index for row in rows] == list(range(len(rows)))
    assert all(len(row.content) <= 20_000 for row in rows)
    assert all(len(row.content_hash) == 64 for row in rows)


def test_manifest_contains_only_chunk_references() -> None:
    secret_content = "这里是不能进入邀请命令的完整解析正文"
    file = SimpleNamespace(
        id=8,
        file_name="工程资料.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        file_size=1234,
    )
    rows = [
        SimpleNamespace(
            id=81,
            file_id=8,
            chunk_index=0,
            chunk_count=1,
            status="ready",
            content=secret_content,
            content_hash="abc123",
            parse_error=None,
        ),
    ]

    manifest = initialization_attachment_manifest(_FakeSession(rows), [file])
    encoded = json.dumps(manifest, ensure_ascii=False)

    assert manifest["storage"] == "project_initialization_attachment_chunks"
    assert manifest["files"][0]["chunks"][0]["chunk_id"] == 81
    assert secret_content not in encoded


def test_manifest_rejects_incomplete_chunks() -> None:
    file = SimpleNamespace(
        id=9,
        file_name="人员.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_size=42,
    )
    rows = [
        SimpleNamespace(
            id=91,
            file_id=9,
            chunk_index=0,
            chunk_count=2,
            status="ready",
            content="第一块",
            content_hash="hash-1",
            parse_error=None,
        ),
    ]

    with pytest.raises(InitializationAttachmentParseError, match="分块不完整"):
        initialization_attachment_manifest(_FakeSession(rows), [file])
