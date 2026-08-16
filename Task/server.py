"""任务引擎的 MCP stdio 入口。

手写 JSON-RPC 而非依赖 mcp SDK——与宿主仓库现有的 MCP 包保持一致，且零第三方依赖，
部署时不必担心 SDK 版本漂移。

协议：每行一个 JSON-RPC 消息，从 stdin 读，往 stdout 写。日志一律走 stderr，
绝不能污染 stdout，否则会破坏协议帧。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# 允许以 `python server.py` 直接运行，无需先安装包
sys.path.insert(0, str(Path(__file__).parent / "src"))

from task_engine.engine import TaskEngine  # noqa: E402
from task_engine.generator.llm import FlowGenerator, LLMConfig  # noqa: E402
from task_engine.tools import ToolError, ToolRegistry  # noqa: E402

SERVER_NAME = "task-engine"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

# JSON-RPC 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def log(message: str) -> None:
    """诊断信息只能走 stderr——stdout 是协议通道。"""
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


def load_tools() -> list[dict[str, Any]]:
    payload = json.loads(Path(__file__).with_name("tools.json").read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("tools.json 必须是工具定义数组")
    return payload


TOOLS = load_tools()


def public_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "title": tool.get("title"),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {"type": "object"}),
        "annotations": tool.get("annotations", {}),
    }


def result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    """把结果包成 MCP 的 content 格式。

    同时给出 structuredContent——支持它的客户端可以直接拿到结构化数据，
    不用从文本里再解析一遍。
    """
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
        "structuredContent": payload,
        "isError": is_error,
    }


class Server:
    def __init__(self) -> None:
        db_path = os.getenv("TASK_ENGINE_DB", "task_engine.db")
        timezone = os.getenv("TASK_ENGINE_TZ", "Asia/Shanghai")
        self.engine = TaskEngine(db_path, timezone=timezone)

        config = LLMConfig.from_env()
        self.registry = ToolRegistry(self.engine, FlowGenerator(config))

        log(f"数据库 {db_path}，时区 {timezone}")
        log(f"任务流生成：{'模型 ' + config.model if config.enabled else '规则模板（未配置模型）'}")

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """处理一条消息。返回 None 表示这是通知，无需响应。"""
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        # 通知没有 id，不能响应
        if request_id is None and method and method.startswith("notifications/"):
            return None

        match method:
            case "initialize":
                return result(request_id, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                })

            case "tools/list":
                return result(request_id, {"tools": [public_tool(t) for t in TOOLS]})

            case "tools/call":
                return self._call_tool(request_id, params)

            case "ping":
                return result(request_id, {})

            case _:
                if request_id is None:
                    return None
                return error(request_id, METHOD_NOT_FOUND, f"不支持的方法：{method}")

    def _call_tool(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if not isinstance(name, str):
            return error(request_id, INVALID_PARAMS, "缺少工具名称")
        if not isinstance(arguments, dict):
            return error(request_id, INVALID_PARAMS, "arguments 必须是对象")

        try:
            payload = self.registry.call(name, arguments)
            return result(request_id, tool_result(payload))

        except ToolError as exc:
            # 业务错误作为工具结果返回，让模型能看到并自行纠正，
            # 而不是变成协议层错误中断对话
            return result(request_id, tool_result(
                {"error": str(exc), "tool": name}, is_error=True,
            ))

        except Exception as exc:
            log(f"工具 {name} 执行异常：{exc!r}")
            return result(request_id, tool_result(
                {"error": f"内部错误：{exc}", "tool": name}, is_error=True,
            ))

    def serve(self) -> None:
        log(f"就绪，暴露 {len(TOOLS)} 个工具")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                _write(error(None, PARSE_ERROR, f"JSON 解析失败：{exc}"))
                continue

            if not isinstance(message, dict):
                _write(error(None, INVALID_REQUEST, "消息必须是 JSON 对象"))
                continue

            try:
                response = self.handle(message)
            except Exception as exc:  # 单条消息异常不应终止服务
                log(f"处理消息失败：{exc!r}")
                response = error(message.get("id"), INTERNAL_ERROR, str(exc))

            if response is not None:
                _write(response)

    def close(self) -> None:
        self.engine.close()


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main() -> int:
    server = Server()
    try:
        server.serve()
    except KeyboardInterrupt:
        log("收到中断信号，退出")
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
