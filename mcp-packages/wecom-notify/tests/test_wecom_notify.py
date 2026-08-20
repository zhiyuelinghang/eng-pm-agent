from __future__ import annotations

import json

import httpx
import pytest

from wecom_notify.client import (
    PlatformWeComClient,
    WeComWebhookClient,
    validate_webhook_url,
)
from wecom_notify.tools import ToolRegistry


WEBHOOK = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?"
    "key=00000000-0000-0000-0000-000000000000"
)


def test_webhook_must_be_official_https_url() -> None:
    assert validate_webhook_url(WEBHOOK) == WEBHOOK
    with pytest.raises(ValueError):
        validate_webhook_url("https://example.com/cgi-bin/webhook/send?key=x")


def test_text_message_keeps_mentions() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    client = WeComWebhookClient(
        WEBHOOK,
        transport=httpx.MockTransport(handler),
    )
    result = client.send_text(
        "任务已下发",
        mentioned_list=["zhangsan"],
        mentioned_mobile_list=["13800138000"],
    )

    assert result.ok
    assert captured["text"]["mentioned_list"] == ["zhangsan"]
    assert captured["text"]["mentioned_mobile_list"] == ["13800138000"]


def test_tool_reports_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DOBBY_AGENT_TOOL_BASE_URL", raising=False)
    monkeypatch.delenv("DOBBY_AGENT_TOOL_TOKEN", raising=False)
    monkeypatch.delenv("DOBBY_PLATFORM_SESSION_ID", raising=False)
    result = ToolRegistry().call(
        "wecom_send_text",
        {"content": "任务已下发"},
    )
    assert result["status"] == "needs_input"
    assert result["error"]["code"] == "WECOM_NOT_CONFIGURED"


def test_platform_client_relays_by_bound_session_without_webhook() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["session"] = request.url.params["agentscope_session_id"]
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "status": "ok",
                    "response_code": "0",
                    "message_type": "markdown",
                },
                "message": "企业微信消息已发送",
            },
        )

    client = PlatformWeComClient(
        "http://gateway.test/api/internal/agent-tools",
        "dedicated-token",
        "platform-session-001",
        transport=httpx.MockTransport(handler),
    )
    result = client.send_markdown("**任务已完成**")

    assert result.ok
    assert captured["path"].endswith("/agent-tools/wecom/messages")
    assert captured["session"] == "platform-session-001"
    assert captured["authorization"] == "Bearer dedicated-token"
    assert captured["body"]["payload"]["msgtype"] == "markdown"


def test_tool_prefers_platform_gateway_over_standalone_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeClient:
        def send_text(self, content: str, **_: object):
            captured["content"] = content
            return type(
                "Result",
                (),
                {"ok": True, "errcode": 0, "errmsg": "ok"},
            )()

    def gateway_factory(url: str, token: str, session_id: str):
        captured.update(url=url, token=token, session_id=session_id)
        return FakeClient()

    monkeypatch.setenv(
        "DOBBY_AGENT_TOOL_BASE_URL",
        "http://gateway.test/api/internal/agent-tools",
    )
    monkeypatch.setenv("DOBBY_AGENT_TOOL_TOKEN", "gateway-token")
    monkeypatch.setenv("DOBBY_PLATFORM_SESSION_ID", "bound-session")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", WEBHOOK)
    registry = ToolRegistry(gateway_client_factory=gateway_factory)

    result = registry.call("wecom_send_text", {"content": "新的任务节点"})

    assert result["status"] == "ok"
    assert captured["token"] == "gateway-token"
    assert captured["session_id"] == "bound-session"
    assert captured["content"] == "新的任务节点"
