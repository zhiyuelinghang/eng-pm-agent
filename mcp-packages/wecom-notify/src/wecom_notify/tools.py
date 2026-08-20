"""MCP 工具层：校验输入、调用传输层并返回统一信封。"""
from __future__ import annotations

from collections import defaultdict
import os
from typing import Any, Callable

from .client import PlatformWeComClient, WeComWebhookClient


MAX_TEXT_LENGTH = 2048
MAX_MARKDOWN_LENGTH = 4096


def _envelope(
    *,
    status: str,
    message: str,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "state": "ACTIVE",
        "data": data or {},
        "message": message,
        "error": error,
    }


class ToolRegistry:
    def __init__(
        self,
        *,
        client_factory: Callable[[str], WeComWebhookClient] = WeComWebhookClient,
        gateway_client_factory: Callable[
            [str, str, str],
            PlatformWeComClient,
        ] = PlatformWeComClient,
    ) -> None:
        self.client_factory = client_factory
        self.gateway_client_factory = gateway_client_factory
        self.send_counts: dict[str, int] = defaultdict(int)
        self.last_errors: dict[str, str] = {}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = str(arguments.get("session_id") or "default")
        if name == "wecom_get_status":
            return _envelope(
                status="ok",
                message="企业微信通知状态已读取",
                data={
                    "session_id": session_id,
                    "send_count": self.send_counts[session_id],
                    "last_error": self.last_errors.get(session_id),
                },
            )

        gateway_url = os.getenv("DOBBY_AGENT_TOOL_BASE_URL", "").strip()
        gateway_token = os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
        platform_session_id = os.getenv("DOBBY_PLATFORM_SESSION_ID", "").strip()
        webhook_url = os.getenv("WECOM_WEBHOOK_URL", "").strip()
        if not (
            (gateway_url and gateway_token and platform_session_id)
            or webhook_url
        ):
            return _envelope(
                status="needs_input",
                message="尚未连接平台企业微信网关或独立 Webhook",
                error={
                    "code": "WECOM_NOT_CONFIGURED",
                    "recoverable": True,
                    "suggestion": "请先在当前项目配置企业微信群机器人",
                },
            )
        try:
            if gateway_url and gateway_token and platform_session_id:
                client = self.gateway_client_factory(
                    gateway_url,
                    gateway_token,
                    platform_session_id,
                )
            else:
                client = self.client_factory(webhook_url)
            if name == "wecom_send_text":
                content = str(arguments.get("content") or "").strip()
                if not content or len(content) > MAX_TEXT_LENGTH:
                    raise ValueError("文本内容不能为空且不能超过 2048 字符")
                result = client.send_text(
                    content,
                    mentioned_list=list(arguments.get("mentioned_list") or []),
                    mentioned_mobile_list=list(
                        arguments.get("mentioned_mobile_list") or [],
                    ),
                )
            elif name == "wecom_send_markdown":
                content = str(arguments.get("content") or "").strip()
                if not content or len(content) > MAX_MARKDOWN_LENGTH:
                    raise ValueError("Markdown 不能为空且不能超过 4096 字符")
                result = client.send_markdown(content)
            elif name == "wecom_send_image":
                result = client.send_image(
                    str(arguments.get("image_source") or ""),
                )
            elif name == "wecom_send_news":
                articles = list(arguments.get("articles") or [])
                if not 1 <= len(articles) <= 8:
                    raise ValueError("图文消息必须包含 1 至 8 条内容")
                if any(not item.get("title") or not item.get("url") for item in articles):
                    raise ValueError("每条图文消息必须填写 title 和 url")
                result = client.send_news(articles)
            else:
                raise KeyError(name)
        except (KeyError, TypeError, ValueError) as exc:
            return _envelope(
                status="error",
                message=str(exc),
                error={
                    "code": "INVALID_INPUT",
                    "recoverable": True,
                    "suggestion": "请修正工具参数后重试",
                },
            )

        self.send_counts[session_id] += 1
        if result.ok:
            self.last_errors.pop(session_id, None)
            return _envelope(
                status="ok",
                message="消息已发送至企业微信群",
                data={
                    "session_id": session_id,
                    "errcode": result.errcode,
                    "errmsg": result.errmsg,
                },
            )
        self.last_errors[session_id] = result.errmsg
        return _envelope(
            status="error",
            message=result.errmsg,
            error={
                "code": "SEND_FAILED",
                "recoverable": True,
                "suggestion": "请检查 Webhook、可信 IP 或企业微信频率限制",
            },
        )
