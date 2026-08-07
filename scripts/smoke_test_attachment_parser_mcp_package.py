"""Verify the fixed attachment package through MinerU and fallback paths."""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import subprocess
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from docx import Document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from agentscope.app.mcp_registry import MCPRegistryManager


DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "attachment-parser-mcp-windows.zip"
)


def _docx_bytes(text: str) -> bytes:
    output = io.BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(output)
    return output.getvalue()


class _FixtureServer(ThreadingHTTPServer):
    primary_docx = _docx_bytes("MinerU 主解析输入")
    fallback_docx = _docx_bytes("本地降级解析成功")
    post_count = 0


class _FixtureHandler(BaseHTTPRequestHandler):
    server: _FixtureServer

    def _send(
        self,
        status: int,
        content: bytes,
        content_type: str,
        **headers: str,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)
        self.server.post_count += 1
        if self.server.post_count > 1:
            self._send(503, b'{"detail":"fixture unavailable"}', "application/json")
            return
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "fixture/office/fixture.md",
                "# MinerU 主解析成功\n\n接口返回 Markdown。",
            )
        self._send(200, output.getvalue(), "application/zip")

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


def _request(
    process: subprocess.Popen[bytes],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert process.stdin is not None and process.stdout is not None
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    process.stdin.write(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else b""
        raise RuntimeError(stderr.decode(errors="replace"))
    response = json.loads(line.decode())
    if "error" in response:
        raise RuntimeError(str(response["error"]))
    return response["result"]


def _call(
    process: subprocess.Popen[bytes],
    request_id: int,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = _request(
        process,
        request_id,
        "tools/call",
        {
            "name": "parse_attachment",
            "arguments": arguments,
        },
    )
    if result.get("isError"):
        raise RuntimeError(result["content"][0]["text"])
    return json.loads(result["content"][0]["text"])


async def _verify_upload(archive: Path, registry_root: Path) -> None:
    async with MCPRegistryManager(registry_root) as manager:
        with archive.open("rb") as source:
            record = await manager.install_archive(source)
        assert record.manifest.name == "attachment-parser"
        assert record.manifest.version == "2.0.0"
        assert record.manifest.platform_capabilities == []
        assert [tool.display_name for tool in record.tools] == ["解析附件"]


def run(archive: Path) -> None:
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"MCP ZIP 不存在：{archive}")
    fixture = _FixtureServer(("127.0.0.1", 0), _FixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    base_url = f"http://127.0.0.1:{fixture.server_port}"
    previous = {
        key: os.environ.get(key)
        for key in (
            "MINERU_FILE_PARSE_URL",
        )
    }
    os.environ.update(
        {
            "MINERU_FILE_PARSE_URL": f"{base_url}/file_parse",
        },
    )
    try:
        with tempfile.TemporaryDirectory(prefix="attachment-mcp-smoke-") as raw:
            temp_root = Path(raw)
            asyncio.run(_verify_upload(archive, temp_root / "registry"))
            with zipfile.ZipFile(archive) as package:
                package.extractall(temp_root / "package")
            manifests = list((temp_root / "package").rglob("mcp.json"))
            if len(manifests) != 1:
                raise RuntimeError("上传包内必须且只能包含一个 mcp.json")
            package_root = manifests[0].parent
            environment = os.environ.copy()
            environment.update(
                {
                    "AGENTSCOPE_SESSION_ID": "fixture-session",
                    "AGENTSCOPE_AGENT_ID": "fixture-agent",
                    "DOBBY_PLATFORM_SESSION_ID": "fixture-session",
                },
            )
            process = subprocess.Popen(
                [
                    str(package_root / "runtime" / "python.exe"),
                    str(package_root / "server.py"),
                ],
                cwd=package_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                initialized = _request(
                    process,
                    1,
                    "initialize",
                    {"protocolVersion": "2025-06-18"},
                )
                tools = _request(process, 2, "tools/list")["tools"]
                primary = _call(
                    process,
                    3,
                    {
                        "file_name": "主解析.docx",
                        "content_base64": base64.b64encode(
                            fixture.primary_docx,
                        ).decode(),
                    },
                )
                text = _call(
                    process,
                    4,
                    {
                        "file_name": "说明.txt",
                        "content_base64": base64.b64encode(
                            "第一行\n第二行".encode(),
                        ).decode(),
                    },
                )
                fallback = _call(
                    process,
                    5,
                    {
                        "file_name": "降级.docx",
                        "content_base64": base64.b64encode(
                            fixture.fallback_docx,
                        ).decode(),
                    },
                )
                chat_upload = _call(
                    process,
                    6,
                    {
                        "file_name": "聊天附件.txt",
                        "media_type": "text/plain",
                        "content_base64": base64.b64encode(
                            "聊天上传成功".encode(),
                        ).decode(),
                    },
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert initialized["serverInfo"]["version"] == "2.0.0"
            assert tools[0]["title"] == "解析附件"
            assert primary["parser"] == "mineru"
            assert "MinerU 主解析成功" in primary["markdown"]
            assert text["parser"] == "local_fallback"
            assert text["lines"][0] == "第一行"
            assert fallback["parser"] == "local_fallback"
            assert fallback["blocks"][0]["text"] == "本地降级解析成功"
            assert chat_upload["lines"] == ["聊天上传成功"]
            print("MCP 上传检测：通过")
            print("聊天 Base64 附件：通过")
            print("MinerU 主解析：通过")
            print("非 MinerU 格式本地解析：通过")
            print("MinerU 失败自动降级：通过")
    finally:
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=5)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    arguments = parser.parse_args()
    run(arguments.archive)


if __name__ == "__main__":
    main()
