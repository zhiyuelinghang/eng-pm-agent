import asyncio
import json
import sys
import os

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import ServerCapabilities
import mcp.server.stdio
import mcp.types as types

# 确保能导入 src 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.send_text import send_text as tool_send_text
from src.tools.send_markdown import send_markdown as tool_send_markdown
from src.tools.send_image import send_image as tool_send_image
from src.tools.send_news import send_news as tool_send_news
from src.tools.get_status import get_status as tool_get_status
from src.session.store import store

server = Server("wecom-notify-mcp")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="wecom_send_text",
            description="[阶段工具] 向企业微信群发送纯文本通知。"
                        "前置条件：无。"
                        "交互约束：该工具无需用户决策，直接发送。",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID，默认用 'default'"},
                    "content": {"type": "string", "description": "消息文本，最长2048"},
                    "mentioned_list": {"type": "array", "items": {"type": "string"}, "description": "要@的成员UserID列表（可选）"},
                    "mentioned_mobile_list": {"type": "array", "items": {"type": "string"}, "description": "要@的成员手机号列表（可选）"}
                },
                "required": ["content"]
            }
        ),
        types.Tool(
            name="wecom_send_markdown",
            description="[阶段工具] 向企业微信群发送 Markdown 格式通知，支持排版。"
                        "前置条件：无。"
                        "交互约束：该工具无需用户决策，直接发送。",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID，默认用 'default'"},
                    "content": {"type": "string", "description": "Markdown 内容，最长4096"}
                },
                "required": ["content"]
            }
        ),
        types.Tool(
            name="wecom_send_image",
            description="[阶段工具] 向企业微信群发送图片（工地现场照片、违规截图等）。"
                        "前置条件：无。"
                        "交互约束：该工具无需用户决策，直接发送。",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID，默认用 'default'"},
                    "image_source": {"type": "string", "description": "图片路径或 base64 字符串"}
                },
                "required": ["image_source"]
            }
        ),
        types.Tool(
            name="wecom_send_news",
            description="[阶段工具] 向企业微信群发送图文消息（1~8 条），每条含标题、描述、链接、可选缩略图。"
                        "前置条件：无。"
                        "交互约束：该工具无需用户决策，直接发送。"
                        "当需要一次性推送多条任务概要时优先使用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID，默认用 'default'"},
                    "articles": {
                        "type": "array",
                        "description": "图文列表，每个元素包含 title、url、可选的 description、picurl",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "标题，必填，最长128字符"},
                                "description": {"type": "string", "description": "描述，选填，最长512字符"},
                                "url": {"type": "string", "description": "点击跳转链接，必填"},
                                "picurl": {"type": "string", "description": "缩略图链接，选填"}
                            },
                            "required": ["title", "url"]
                        }
                    }
                },
                "required": ["articles"]
            }
        ),
        types.Tool(
            name="wecom_get_status",
            description="[只读探查工具] 查看群机器人会话状态与发送统计。可随时调用，无副作用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID，默认用 'default'"}
                }
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    session_id = arguments.get("session_id", "default")
    if name == "wecom_send_text":
        result = tool_send_text(
            session_id=session_id,
            content=arguments["content"],
            mentioned_list=arguments.get("mentioned_list"),
            mentioned_mobile_list=arguments.get("mentioned_mobile_list")
        )
    elif name == "wecom_send_markdown":
        result = tool_send_markdown(
            session_id=session_id,
            content=arguments["content"]
        )
    elif name == "wecom_send_image":
        result = tool_send_image(
            session_id=session_id,
            image_source=arguments["image_source"]
        )
    elif name == "wecom_send_news":
        result = tool_send_news(
            session_id=session_id,
            articles=arguments["articles"]
        )
    elif name == "wecom_get_status":
        result = tool_get_status(session_id)
    else:
        return [types.TextContent(type="text", text=f"未知工具: {name}")]

    return [types.TextContent(type="text", text=json.dumps(result.to_dict(), ensure_ascii=False))]

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="wecom-notify-mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(
                    tools={"list": True}  # 关键：声明支持工具列表
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
