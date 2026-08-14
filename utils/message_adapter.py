"""
Multi-Source Message Adapter — G1 message normalization (§1.1).

Normalizes raw messages from Feishu, DingTalk, WeChat, and direct input
into a unified `UnifiedMessage` format consumed by the Dobby agent system.

Design:
    MessageAdapter.normalize(raw_msg, source) → UnifiedMessage
      ├── FeishuAdapter — Feishu webhook body
      ├── DingtalkAdapter — DingTalk webhook body
      ├── WechatAdapter — WeChat webhook body
      └── DirectAdapter — AgentScope UserMsg (existing Demo flow)

The DirectAdapter preserves backward compatibility: all existing Demo
files continue to work without changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class UnifiedMessage:
    """Canonical message representation for all sources.

    All adapters MUST output this format. Downstream consumers
    (LangGraph nodes, compression, audit log) operate on this type.
    """

    source: str  # "feishu" | "dingtalk" | "wechat" | "direct"
    sender_id: str  # unique sender identifier
    sender_name: str  # display name
    content: str  # plain text content
    timestamp: str  # ISO 8601
    msg_type: str = "text"  # "text" | "image" | "file" | "mixed"
    mentions: list[str] = field(default_factory=list)  # @mentioned users
    reply_to: Optional[str] = None  # quoted reply message ID
    attachments: list[dict] = field(default_factory=list)  # [{type, url, name}]


# ============================================================
# Base adapter protocol
# ============================================================


class BaseAdapter:
    """Protocol for message source adapters."""

    @staticmethod
    def normalize(raw: Any) -> UnifiedMessage:
        raise NotImplementedError


# ============================================================
# DirectAdapter — wraps existing AgentScope Msg flow
# ============================================================


class DirectAdapter(BaseAdapter):
    """Normalize AgentScope-style messages (existing Demo flow).

    Accepts:
        - AgentScope Msg objects (UserMsg, SystemMsg)
        - Plain dicts: {"role": "user", "content": "hello"}
        - Plain strings: "hello"

    This adapter preserves backward compatibility: all existing
    Demo files calling Msg("user", text) continue to work.
    """

    @staticmethod
    def normalize(raw: Any) -> UnifiedMessage:
        now = datetime.now(timezone.utc).isoformat()

        # AgentScope Msg object
        if hasattr(raw, "role") and hasattr(raw, "content"):
            content = _extract_text(raw.content)
            sender_name = raw.role if raw.role != "user" else "user"
            return UnifiedMessage(
                source="direct",
                sender_id=sender_name,
                sender_name=sender_name,
                content=content,
                timestamp=now,
            )

        # Plain dict
        if isinstance(raw, dict):
            content = _extract_text(raw.get("content", ""))
            role = raw.get("role", "user")
            sender = raw.get("sender_id", raw.get("user_id", role))
            name = raw.get("sender_name", raw.get("user_name", sender))
            return UnifiedMessage(
                source="direct",
                sender_id=str(sender),
                sender_name=str(name),
                content=content,
                timestamp=raw.get("timestamp", now),
                msg_type=raw.get("msg_type", "text"),
                mentions=raw.get("mentions", []),
                reply_to=raw.get("reply_to"),
                attachments=raw.get("attachments", []),
            )

        # Plain string → treat as direct user message
        if isinstance(raw, str):
            return UnifiedMessage(
                source="direct",
                sender_id="user",
                sender_name="user",
                content=raw,
                timestamp=now,
            )

        # Fallback
        return UnifiedMessage(
            source="direct",
            sender_id="unknown",
            sender_name="unknown",
            content=str(raw),
            timestamp=now,
        )


# ============================================================
# FeishuAdapter — Feishu (Lark) webhook
# ============================================================


class FeishuAdapter(BaseAdapter):
    """Normalize Feishu webhook bodies.

    Expected webhook format (simplified):
        {
            "header": {"event_type": "im.message.receive_v1", ...},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_xxx"}},
                "message": {
                    "message_id": "om_xxx",
                    "chat_id": "oc_xxx",
                    "msg_type": "text",
                    "content": "{\"text\":\"hello\"}",
                    "create_time": "1610000000000",
                }
            }
        }
    """

    @staticmethod
    def normalize(raw: Any) -> UnifiedMessage:
        if not isinstance(raw, dict):
            return DirectAdapter.normalize(raw)

        event = raw.get("event", raw)
        sender = event.get("sender", event.get("sender_id", {}))
        if isinstance(sender, dict):
            # Feishu v2: sender.sender_id.open_id
            # Feishu v1: sender.open_id
            sender_id = sender.get("open_id", "")
            if not sender_id and "sender_id" in sender:
                inner = sender["sender_id"]
                if isinstance(inner, dict):
                    sender_id = inner.get("open_id", inner.get("user_id", ""))
                else:
                    sender_id = str(inner)
            if not sender_id:
                sender_id = sender.get("user_id", "")
        else:
            sender_id = str(sender)

        message = event.get("message", event)
        msg_type = message.get("msg_type", "text")
        content_raw = message.get("content", "")
        content = _parse_feishu_content(content_raw, msg_type)
        create_time = message.get("create_time", "")
        timestamp = _ms_to_iso(create_time)

        # Mentions
        mentions = _extract_feishu_mentions(content_raw)

        return UnifiedMessage(
            source="feishu",
            sender_id=str(sender_id),
            sender_name="",  # Feishu doesn't provide display name in webhook
            content=content,
            timestamp=timestamp,
            msg_type=msg_type,
            mentions=mentions,
            reply_to=message.get("root_id"),
            attachments=_extract_feishu_attachments(message),
        )


# ============================================================
# DingtalkAdapter — DingTalk webhook
# ============================================================


class DingtalkAdapter(BaseAdapter):
    """Normalize DingTalk webhook bodies.

    Expected format (simplified):
        {
            "senderId": "user123",
            "senderNick": "张三",
            "msgtype": "text",
            "text": {"content": "hello"},
            "sessionWebhook": "https://...",
        }
    """

    @staticmethod
    def normalize(raw: Any) -> UnifiedMessage:
        if not isinstance(raw, dict):
            return DirectAdapter.normalize(raw)

        now = datetime.now(timezone.utc).isoformat()

        return UnifiedMessage(
            source="dingtalk",
            sender_id=str(raw.get("senderId", raw.get("sender_id", ""))),
            sender_name=str(raw.get("senderNick", raw.get("sender_nick", ""))),
            content=_extract_dingtalk_content(raw),
            timestamp=raw.get("createAt", now),
            msg_type=raw.get("msgtype", "text"),
            mentions=_extract_dingtalk_mentions(raw),
            reply_to=raw.get("reply_to"),
            attachments=[],
        )


# ============================================================
# WechatAdapter — WeChat / WeCom webhook
# ============================================================


class WechatAdapter(BaseAdapter):
    """Normalize WeChat Work (WeCom) webhook bodies.

    Expected format (simplified):
        {
            "ToUserName": "wxab...",
            "FromUserName": "user123",
            "CreateTime": 1610000000,
            "MsgType": "text",
            "Content": "hello",
        }
    """

    @staticmethod
    def normalize(raw: Any) -> UnifiedMessage:
        if not isinstance(raw, dict):
            return DirectAdapter.normalize(raw)

        create_time = raw.get("CreateTime", raw.get("create_time", 0))
        if isinstance(create_time, (int, float)) and create_time > 0:
            timestamp = datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat()
        else:
            timestamp = datetime.now(timezone.utc).isoformat()

        return UnifiedMessage(
            source="wechat",
            sender_id=str(raw.get("FromUserName", raw.get("from_user", ""))),
            sender_name="",  # WeChat doesn't provide display name
            content=str(raw.get("Content", raw.get("content", ""))),
            timestamp=timestamp,
            msg_type=raw.get("MsgType", raw.get("msg_type", "text")),
            mentions=[],
            reply_to=None,
            attachments=[],
        )


# ============================================================
# MessageAdapter — unified entry point
# ============================================================


class MessageAdapter:
    """Unified entry point for message normalization.

    Usage:
        unified = MessageAdapter.normalize(raw_msg, source="feishu")
        unified = MessageAdapter.normalize(raw_msg, source="direct")  # default
    """

    _adapters = {
        "direct": DirectAdapter,
        "feishu": FeishuAdapter,
        "dingtalk": DingtalkAdapter,
        "wechat": WechatAdapter,
    }

    @classmethod
    def register(cls, source: str, adapter_class):
        """Register a custom adapter for a new message source."""
        cls._adapters[source] = adapter_class

    @staticmethod
    def normalize(raw: Any, source: str = "direct") -> UnifiedMessage:
        """Normalize a raw message into UnifiedMessage.

        Args:
            raw: raw message from the platform
            source: "direct" | "feishu" | "dingtalk" | "wechat"

        Returns:
            UnifiedMessage — canonical representation
        """
        adapter = MessageAdapter._adapters.get(source, DirectAdapter)
        return adapter.normalize(raw)

    @classmethod
    def available_sources(cls) -> list[str]:
        """Return list of registered source names."""
        return list(cls._adapters.keys())


# ============================================================
# Internal helpers
# ============================================================


def _extract_text(content: Any) -> str:
    """Extract plain text from various content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(str(block))
        return "".join(parts)
    if hasattr(content, "text"):
        return content.text
    return str(content) if content else ""


def _ms_to_iso(ms_str: str) -> str:
    """Convert millisecond timestamp string to ISO 8601."""
    try:
        ts = int(ms_str) / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return datetime.now(timezone.utc).isoformat()


def _parse_feishu_content(content_raw: str, msg_type: str) -> str:
    """Parse Feishu message content."""
    if msg_type == "text":
        try:
            import json
            data = json.loads(content_raw)
            return data.get("text", content_raw)
        except (json.JSONDecodeError, TypeError):
            return content_raw
    return content_raw


def _extract_feishu_mentions(content_raw: str) -> list[str]:
    """Extract @mentions from Feishu message content."""
    try:
        import json
        data = json.loads(content_raw)
        at_list = data.get("at_list", data.get("atUserIds", []))
        if isinstance(at_list, list):
            return at_list
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _extract_feishu_attachments(message: dict) -> list[dict]:
    """Extract attachment metadata from Feishu message."""
    attrs = []
    # Images
    if "image_key" in message:
        attrs.append({"type": "image", "url": "", "name": message["image_key"]})
    # Files
    if "file_key" in message:
        attrs.append({"type": "file", "url": "", "name": message["file_key"]})
    return attrs


def _extract_dingtalk_content(raw: dict) -> str:
    """Extract content from DingTalk message."""
    msgtype = raw.get("msgtype", "text")
    if msgtype == "text":
        text_block = raw.get("text", {})
        if isinstance(text_block, dict):
            return text_block.get("content", "")
        return str(text_block)
    if msgtype == "markdown":
        md_block = raw.get("markdown", {})
        if isinstance(md_block, dict):
            return md_block.get("text", md_block.get("title", ""))
        return str(md_block)
    # Generic fallback
    return str(raw.get("text", raw.get("content", "")))


def _extract_dingtalk_mentions(raw: dict) -> list[str]:
    """Extract @mentions from DingTalk message."""
    at_mobiles = raw.get("atMobiles", raw.get("at_mobiles", []))
    at_user_ids = raw.get("atUserIds", raw.get("at_user_ids", []))
    mentions = []
    if isinstance(at_mobiles, list):
        mentions.extend(at_mobiles)
    if isinstance(at_user_ids, list):
        mentions.extend(at_user_ids)
    return mentions
