import base64
import importlib
import io
import sys
import zipfile
from pathlib import Path

import httpx


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mcp-packages"
    / "attachment-parser"
)
sys.path.insert(0, str(PACKAGE_ROOT))
try:
    parser_runtime = importlib.import_module("parser_runtime")
finally:
    sys.path.remove(str(PACKAGE_ROOT))


def _zip_markdown(markdown: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample/office/sample.md", markdown)
        archive.writestr("sample/office/images/figure.png", b"image")
    return buffer.getvalue()


def test_mineru_zip_is_decoded_as_markdown() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "application/zip"},
        content=_zip_markdown("# 工程说明\n\n测试内容"),
        request=httpx.Request("POST", "https://example.test/file_parse"),
    )

    result = parser_runtime._decode_mineru_response(response)

    assert result.markdown == "# 工程说明\n\n测试内容"
    assert result.images == ("sample/office/images/figure.png",)


def test_mineru_zip_does_not_limit_member_count() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("result/result.md", "# 大批量解析结果")
        for index in range(2050):
            archive.writestr(f"result/assets/{index}.txt", b"")

    result = parser_runtime._read_mineru_zip(buffer.getvalue())

    assert result.markdown == "# 大批量解析结果"
    assert len(result.members) == 2051


def test_open_source_format_uses_mineru_first(monkeypatch) -> None:
    monkeypatch.setattr(
        parser_runtime,
        "_parse_with_mineru",
        lambda content, suffix, file_name: parser_runtime.MinerUResult(
            markdown="# 项目\n第一行\n第二行",
            members=("sample.md",),
            images=(),
        ),
    )

    result = parser_runtime.parse_attachment(
        file_name="项目.docx",
        content_base64=base64.b64encode(b"docx").decode(),
        start=2,
        limit=1,
    )

    assert result["parser"] == "mineru"
    assert result["markdown"] == "第一行"
    assert result["next_start"] == 3


def test_mineru_failure_uses_bundled_local_parser(monkeypatch) -> None:
    def fail_mineru(content: bytes, suffix: str, file_name: str):
        raise parser_runtime.MinerUParserError("服务不可用")

    monkeypatch.setattr(parser_runtime, "_parse_with_mineru", fail_mineru)
    monkeypatch.setattr(
        parser_runtime,
        "parse_attachment_content",
        lambda *args: {"format": "pdf", "pages": [{"text": "降级成功"}]},
    )

    result = parser_runtime.parse_attachment(
        file_name="资料.pdf",
        content_base64=base64.b64encode("降级成功".encode()).decode(),
    )

    assert result["parser"] == "local_fallback"
    assert result["mineru_error"] == "服务不可用"
    assert result["pages"][0]["text"] == "降级成功"


def test_text_files_skip_mineru(monkeypatch) -> None:
    monkeypatch.setattr(
        parser_runtime,
        "_parse_with_mineru",
        lambda *args: (_ for _ in ()).throw(AssertionError("不应调用 MinerU")),
    )

    result = parser_runtime.parse_attachment(
        file_name="资料.txt",
        content_base64=base64.b64encode("第一行\n第二行".encode()).decode(),
        limit=1,
    )

    assert result["parser"] == "local_fallback"
    assert result["fallback_reason"] == "该格式不属于开源 MinerU 的输入范围"
    assert result["lines"] == ["第一行"]


def test_chat_upload_base64_uses_the_same_parser_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(
        parser_runtime,
        "_parse_with_mineru",
        lambda *args: (_ for _ in ()).throw(AssertionError("不应调用 MinerU")),
    )
    content = "第一行\n第二行".encode("utf-8")

    result = parser_runtime.parse_attachment(
        file_name="说明.txt",
        media_type="text/plain",
        content_base64=base64.b64encode(content).decode("ascii"),
        limit=1,
    )

    assert result["file_name"] == "说明.txt"
    assert result["parser"] == "local_fallback"
    assert result["lines"] == ["第一行"]
    assert result["next_start"] == 2
