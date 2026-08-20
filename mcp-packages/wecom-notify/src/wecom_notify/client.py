"""企业微信群机器人 HTTP 传输层。"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx


MAX_IMAGE_BYTES = 2 * 1024 * 1024


def validate_webhook_url(value: str) -> str:
    """只接受企业微信官方群机器人 Webhook。"""
    normalized = value.strip()
    parsed = urlsplit(normalized)
    key = parse_qs(parsed.query).get("key", [""])[0].strip()
    if (
        parsed.scheme != "https"
        or parsed.hostname != "qyapi.weixin.qq.com"
        or parsed.path != "/cgi-bin/webhook/send"
        or not key
    ):
        raise ValueError("请输入企业微信官方群机器人 Webhook")
    return normalized


@dataclass(frozen=True, slots=True)
class SendResult:
    ok: bool
    errcode: int | None
    errmsg: str
    response: dict[str, Any]


class WeComWebhookClient:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.webhook_url = validate_webhook_url(webhook_url)
        self.timeout = timeout
        self.transport = transport

    def _post(self, payload: dict[str, Any]) -> SendResult:
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.post(self.webhook_url, json=payload)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError("企业微信返回内容不是 JSON 对象")
            errcode = data.get("errcode")
            return SendResult(
                ok=errcode == 0,
                errcode=int(errcode) if isinstance(errcode, int) else None,
                errmsg=str(data.get("errmsg") or "ok"),
                response=data,
            )
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            return SendResult(
                ok=False,
                errcode=None,
                errmsg=str(exc),
                response={"error": str(exc)},
            )

    def send_text(
        self,
        content: str,
        *,
        mentioned_list: list[str] | None = None,
        mentioned_mobile_list: list[str] | None = None,
    ) -> SendResult:
        body: dict[str, Any] = {
            "msgtype": "text",
            "text": {"content": content},
        }
        if mentioned_list:
            body["text"]["mentioned_list"] = mentioned_list
        if mentioned_mobile_list:
            body["text"]["mentioned_mobile_list"] = mentioned_mobile_list
        return self._post(body)

    def send_markdown(self, content: str) -> SendResult:
        return self._post(
            {"msgtype": "markdown", "markdown": {"content": content}},
        )

    def send_image(self, image_source: str) -> SendResult:
        if image_source.startswith("data:image"):
            try:
                _, encoded = image_source.split(",", 1)
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError("图片 data URI 无法解析") from exc
        else:
            path = Path(image_source).expanduser()
            if not path.is_file():
                raise ValueError(f"图片文件不存在：{image_source}")
            raw = path.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("企业微信机器人图片不能超过 2MB")
        return self._post(
            {
                "msgtype": "image",
                "image": {
                    "base64": base64.b64encode(raw).decode("ascii"),
                    "md5": hashlib.md5(raw).hexdigest(),  # noqa: S324 - 协议要求
                },
            },
        )

    def send_news(self, articles: list[dict[str, str]]) -> SendResult:
        return self._post(
            {"msgtype": "news", "news": {"articles": articles}},
        )


class PlatformWeComClient(WeComWebhookClient):
    """通过会话绑定的平台网关发送，不向 MCP 进程暴露 Webhook。"""

    def __init__(
        self,
        gateway_url: str,
        token: str,
        platform_session_id: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/") + "/wecom/messages"
        self.token = token
        self.platform_session_id = platform_session_id
        self.timeout = timeout
        self.transport = transport

    def _post(self, payload: dict[str, Any]) -> SendResult:
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.gateway_url,
                    params={
                        "agentscope_session_id": self.platform_session_id,
                    },
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"payload": payload},
                )
                response.raise_for_status()
                body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict) or not body.get("success"):
                raise ValueError("平台企业微信网关返回内容无效")
            response_code = data.get("response_code")
            return SendResult(
                ok=data.get("status") == "ok",
                errcode=int(response_code) if str(response_code).isdigit() else None,
                errmsg=str(body.get("message") or "ok"),
                response=data,
            )
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            return SendResult(
                ok=False,
                errcode=None,
                errmsg=str(exc),
                response={"error": str(exc)},
            )
