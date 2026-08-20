"""企业微信通知 MCP stdio 入口。"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "src"))

from wecom_notify.tools import ToolRegistry  # noqa: E402


SERVER_NAME = "wecom-notify"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"
TOOLS = json.loads(Path(__file__).with_name("tools.json").read_text("utf-8"))
REGISTRY = ToolRegistry()


def _public_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "title": tool.get("title"),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {"type": "object"}),
        "annotations": tool.get("annotations", {}),
    }


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    is_error = payload.get("status") == "error"
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None and method and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": [_public_tool(tool) for tool in TOOLS]})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        return _result(request_id, _tool_result(REGISTRY.call(name, arguments)))
    if method == "ping":
        return _result(request_id, {})
    if request_id is None:
        return None
    return _error(request_id, -32601, f"不支持的方法：{method}")


def main() -> None:
    for raw in sys.stdin.buffer:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw.decode("utf-8-sig"))
            response = handle(message)
        except Exception as exc:  # pragma: no cover - 最外层协议保护
            response = _error(None, -32603, str(exc))
        if response is not None:
            encoded = json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            sys.stdout.buffer.write(encoded + b"\n")
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
