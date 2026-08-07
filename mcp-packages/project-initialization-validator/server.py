"""STDIO MCP entrypoint for deterministic project-initialization validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from initialization_validator import validate_project_initialization


SERVER_NAME = "project-initialization-validator"
SERVER_VERSION = "1.0.0"


def _load_tools() -> list[dict[str, Any]]:
    payload = json.loads(
        Path(__file__).with_name("tools.json").read_text(encoding="utf-8"),
    )
    if not isinstance(payload, list):
        raise RuntimeError("tools.json 必须是工具定义数组")
    return payload


TOOLS = _load_tools()
TOOLS_BY_NAME = {str(tool["name"]): tool for tool in TOOLS}


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _public_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "title": tool.get("title"),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {"type": "object"}),
        "annotations": tool.get("annotations", {}),
    }


def _tool_result(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = validate_project_initialization(arguments.get("draft"))
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False),
                },
            ],
            "isError": False,
        }
    except (TypeError, ValueError) as exc:
        return {
            "content": [{"type": "text", "text": str(exc)}],
            "isError": True,
        }
    except Exception as exc:  # Keep unexpected failures inside the MCP result.
        return {
            "content": [{"type": "text", "text": f"初始化核验异常：{exc}"}],
            "isError": True,
        }


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    if request_id is None:
        return None
    method = message.get("method")
    if method == "initialize":
        parameters = message.get("params") or {}
        return _result(
            request_id,
            {
                "protocolVersion": parameters.get(
                    "protocolVersion",
                    "2025-06-18",
                ),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(
            request_id,
            {"tools": [_public_tool(tool) for tool in TOOLS]},
        )
    if method == "tools/call":
        parameters = message.get("params") or {}
        tool = TOOLS_BY_NAME.get(str(parameters.get("name") or ""))
        if tool is None:
            return _error(request_id, -32602, "未知的项目初始化核验工具")
        arguments = parameters.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "工具参数必须是对象")
        return _result(request_id, _tool_result(arguments))
    return _error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    for raw_line in sys.stdin.buffer:
        try:
            message = json.loads(raw_line.decode("utf-8-sig"))
            response = _handle(message)
        except Exception as exc:
            response = _error(None, -32603, str(exc))
        if response is None:
            continue
        encoded = json.dumps(
            response,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
