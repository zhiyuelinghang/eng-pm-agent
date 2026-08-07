import io

import pytest
from openpyxl import Workbook

from backend.app.system_attachment_parser import (
    SystemAttachmentParserError,
    _load_runtime,
    parse_uploaded_attachment,
)


def test_text_upload_is_parsed_completely() -> None:
    content = "\n".join(f"第{index}行" for index in range(1, 503)).encode()

    parsed = parse_uploaded_attachment(
        content,
        file_name="说明.txt",
        media_type="text/plain",
    )

    assert parsed.details["status"] == "ready"
    assert parsed.segments == 2
    assert "第1行" in parsed.content
    assert "第502行" in parsed.content
    assert parsed.parsers == ("local_fallback",)


def test_every_excel_sheet_is_included(monkeypatch) -> None:
    runtime = _load_runtime()

    def fail_mineru(*_args):
        raise runtime.MinerUParserError("测试中跳过远程解析")

    monkeypatch.setattr(runtime, "_parse_with_mineru", fail_mineru)
    workbook = Workbook()
    first = workbook.active
    first.title = "工程信息"
    first.append(["名称", "示例工程"])
    second = workbook.create_sheet("风险")
    second.append(["风险", "基坑"])
    stream = io.BytesIO()
    workbook.save(stream)

    parsed = parse_uploaded_attachment(
        stream.getvalue(),
        file_name="项目.xlsx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )

    assert parsed.segments == 2
    assert "示例工程" in parsed.content
    assert "基坑" in parsed.content


def test_unsupported_upload_reports_a_pipeline_error() -> None:
    with pytest.raises(SystemAttachmentParserError, match="不支持的附件格式"):
        parse_uploaded_attachment(
            b"binary",
            file_name="模型.dwg",
            media_type="application/octet-stream",
        )
