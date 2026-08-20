"""企业微信项目群机器人通知与 PostgreSQL 可靠投递。"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .connector_secrets import decrypt_connector_secret
from .db import SessionLocal
from .models import (
    OutboundNotification,
    Project,
    ProjectConnectorConfig,
    User,
    UserConnectorConfig,
)


logger = logging.getLogger(__name__)

WECOM_WEBHOOK_HOST = "qyapi.weixin.qq.com"
WECOM_WEBHOOK_PATH = "/cgi-bin/webhook/send"
MOBILE_PATTERN = re.compile(r"^1\d{10}$")
MAX_DELIVERY_ATTEMPTS = 5
RETRY_DELAYS_SECONDS = (15, 60, 300, 900, 1800)
SENDING_LEASE = timedelta(minutes=10)

EVENT_LABELS = {
    "task_created": "新任务已下发",
    "schedule_fired": "计划任务已触发",
    "step_activated": "新的流程节点待处理",
    "step_blocked": "流程节点已受阻",
    "task_reassigned": "任务已转办",
    "task_rejected": "任务已退回",
    "task_review": "任务等待验收",
    "task_completed": "任务已闭环",
    "task_cancelled": "任务已取消",
    "task_overdue": "任务已逾期",
}


class WeComDeliveryError(RuntimeError):
    """企业微信明确拒绝或无法完成一次投递。"""


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    claimed: int = 0
    sent: int = 0
    retrying: int = 0
    failed: int = 0

    def describe(self) -> str:
        return (
            f"领取 {self.claimed} 条，成功 {self.sent} 条，"
            f"待重试 {self.retrying} 条，失败 {self.failed} 条"
        )


def validate_wecom_webhook_url(value: str) -> str:
    """只接受企业微信官方群机器人 Webhook，避免把密钥发往第三方。"""

    normalized = value.strip()
    parsed = urlparse(normalized)
    keys = parse_qs(parsed.query, keep_blank_values=True).get("key", [])
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("企业微信机器人 Webhook 端口无效") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != WECOM_WEBHOOK_HOST
        or parsed.path != WECOM_WEBHOOK_PATH
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or len(keys) != 1
        or not keys[0].strip()
    ):
        raise ValueError(
            "请填写企业微信官方项目群机器人 Webhook，地址应以 "
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key= 开头",
        )
    return normalized


def is_wecom_webhook_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        validate_wecom_webhook_url(value)
    except ValueError:
        return False
    return True


def project_wecom_configured(row: ProjectConnectorConfig | None) -> bool:
    """判断配置是否具备可用凭据，同时兼容早期明文 Webhook 数据。"""

    return bool(
        row
        and row.configured
        and (row.secret_encrypted or is_wecom_webhook_url(row.connection_id))
    )


def project_wecom_webhook(
    db: Session,
    project_id: int,
) -> str:
    row = db.scalar(
        select(ProjectConnectorConfig).where(
            ProjectConnectorConfig.project_id == project_id,
            ProjectConnectorConfig.connector_type == "wecom",
        ),
    )
    if not project_wecom_configured(row):
        raise ValueError("当前项目尚未配置企业微信群机器人")

    assert row is not None
    if row.secret_encrypted:
        webhook = decrypt_connector_secret(row.secret_encrypted)
    else:
        webhook = row.connection_id
    if not webhook:
        raise ValueError("企业微信群机器人凭据为空，请重新保存配置")
    return validate_wecom_webhook_url(webhook)


def _coerce_user_id(value: object) -> int | None:
    try:
        user_id = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


def _recipient_for_event(
    task: Any,
    event_type: str,
    recipient_user_id: int | None,
) -> tuple[int | None, str]:
    if recipient_user_id:
        return recipient_user_id, ""

    assignee = task.confirmer if event_type == "task_review" else task.current_assignee
    if assignee is None:
        return None, ""
    return _coerce_user_id(assignee.ref), str(assignee.display_name or "").strip()


def _resolve_mentions(
    db: Session,
    user_id: int | None,
    fallback_name: str,
) -> tuple[str | None, str, str | None, str | None]:
    if user_id is None:
        return None, fallback_name, None, None

    user = db.get(User, user_id)
    if user is None:
        return None, fallback_name, None, None

    connector = db.scalar(
        select(UserConnectorConfig).where(
            UserConnectorConfig.user_id == user_id,
            UserConnectorConfig.connector_type == "wecom",
            UserConnectorConfig.configured.is_(True),
        ),
    )
    account = (connector.account_identifier or "").strip() if connector else ""
    phone = (user.phone or "").strip()
    mobile = phone if MOBILE_PATTERN.fullmatch(phone) else None
    if mobile is None and MOBILE_PATTERN.fullmatch(account):
        mobile = account
    mentioned_user_id = (
        account
        if mobile is None and account and not MOBILE_PATTERN.fullmatch(account)
        else None
    )
    return user_id, user.real_name or fallback_name, mentioned_user_id, mobile


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "未设置"
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value.tzinfo else value.strftime("%Y-%m-%d %H:%M")


def _event_marker(task: Any, explicit: str) -> str:
    if explicit:
        return explicit.strip()[:120]
    activities = getattr(task, "activities", None) or []
    if activities:
        return str(activities[-1].id)
    current = getattr(task, "current_step", None)
    return f"{getattr(task, 'state', '')}:{getattr(current, 'seq', 'none')}"


def _build_task_message(
    *,
    project_name: str,
    task: Any,
    event_type: str,
    recipient_name: str,
) -> tuple[str, str]:
    event_label = EVENT_LABELS.get(event_type, "任务状态已更新")
    current = task.current_step
    due_at = current.due_at if current is not None else task.due_at
    site = str(task.site) if task.site is not None else "未关联"
    reason = str(task.trigger_note or task.summary or "").strip()
    if len(reason) > 360:
        reason = f"{reason[:357]}..."
    base_url = get_settings().frontend_public_url.rstrip("/")
    task_link = f"{base_url}/#/tasks?task_id={quote(str(task.id))}"
    lines = [
        f"【Dobby · 任务通知】{event_label}",
        f"项目：{project_name}",
        f"任务：{task.title}",
        f"工点：{site}",
        f"当前节点：{current.name if current is not None else '流程已结束'}",
        f"责任人：{recipient_name or '无指定提醒人'}",
        f"截止：{_format_datetime(due_at)}",
    ]
    if reason:
        lines.append(f"说明：{reason}")
    lines.append(f"进入任务中心：{task_link}")
    return f"{event_label} · {task.title}"[:300], "\n".join(lines)[:2000]


def enqueue_task_notification(
    db: Session,
    task: Any,
    event_type: str,
    *,
    recipient_user_id: int | None = None,
    dedupe_suffix: str = "",
) -> OutboundNotification | None:
    """把引擎事件写入平台 outbox；不在任务请求内访问企业微信。"""

    project_id = _coerce_user_id((getattr(task, "scope", {}) or {}).get("project_id"))
    if project_id is None:
        return None
    connector = db.scalar(
        select(ProjectConnectorConfig).where(
            ProjectConnectorConfig.project_id == project_id,
            ProjectConnectorConfig.connector_type == "wecom",
        ),
    )
    if not project_wecom_configured(connector):
        return None

    project = db.get(Project, project_id)
    if project is None:
        return None
    raw_user_id, fallback_name = _recipient_for_event(
        task,
        event_type,
        recipient_user_id,
    )
    user_id, recipient_name, mentioned_user_id, mentioned_mobile = _resolve_mentions(
        db,
        raw_user_id,
        fallback_name,
    )
    marker = _event_marker(task, dedupe_suffix)
    current = task.current_step
    dedupe_key = ":".join(
        (
            "wecom",
            str(task.id),
            event_type,
            str(user_id or "group"),
            str(current.seq if current is not None else "none"),
            marker,
        ),
    )[:500]
    existing = db.scalar(
        select(OutboundNotification).where(
            OutboundNotification.dedupe_key == dedupe_key,
        ),
    )
    if existing is not None:
        return existing

    title, content = _build_task_message(
        project_name=project.name,
        task=task,
        event_type=event_type,
        recipient_name=recipient_name,
    )
    notification = OutboundNotification(
        project_id=project_id,
        connector_type="wecom",
        event_type=event_type,
        task_id=str(task.id),
        recipient_user_id=user_id,
        recipient_name=recipient_name or None,
        title=title,
        content=content,
        mentioned_user_id=mentioned_user_id,
        mentioned_mobile=mentioned_mobile,
        status="pending",
        next_attempt_at=datetime.now(UTC),
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    return notification


def _text_payload(notification: OutboundNotification) -> dict[str, Any]:
    text: dict[str, Any] = {"content": notification.content}
    if notification.mentioned_user_id:
        text["mentioned_list"] = [notification.mentioned_user_id]
    if notification.mentioned_mobile:
        text["mentioned_mobile_list"] = [notification.mentioned_mobile]
    return {"msgtype": "text", "text": text}


def validate_wecom_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the five message shapes exposed by the WeCom MCP package."""

    if not isinstance(payload, dict):
        raise ValueError("企业微信消息必须是 JSON 对象")
    msgtype = str(payload.get("msgtype") or "").strip()
    if msgtype == "text":
        body = payload.get("text")
        if not isinstance(body, dict):
            raise ValueError("企业微信文本消息结构无效")
        content = str(body.get("content") or "").strip()
        if not content or len(content) > 2048:
            raise ValueError("企业微信文本不能为空且不能超过 2048 字符")
        clean: dict[str, Any] = {"content": content}
        for field in ("mentioned_list", "mentioned_mobile_list"):
            raw = body.get(field) or []
            if not isinstance(raw, list) or len(raw) > 100:
                raise ValueError("企业微信提醒人员列表格式无效")
            values = [str(item).strip() for item in raw if str(item).strip()]
            if values:
                clean[field] = values
        return {"msgtype": msgtype, "text": clean}

    if msgtype == "markdown":
        body = payload.get("markdown")
        content = str(body.get("content") or "").strip() if isinstance(body, dict) else ""
        if not content or len(content) > 4096:
            raise ValueError("企业微信 Markdown 不能为空且不能超过 4096 字符")
        return {"msgtype": msgtype, "markdown": {"content": content}}

    if msgtype == "image":
        body = payload.get("image")
        encoded = str(body.get("base64") or "") if isinstance(body, dict) else ""
        md5_value = str(body.get("md5") or "").lower() if isinstance(body, dict) else ""
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("企业微信图片 Base64 无法解析") from exc
        if not raw or len(raw) > 2 * 1024 * 1024:
            raise ValueError("企业微信机器人图片必须小于 2MB")
        if not re.fullmatch(r"[0-9a-f]{32}", md5_value):
            raise ValueError("企业微信图片 MD5 格式无效")
        return {
            "msgtype": msgtype,
            "image": {"base64": encoded, "md5": md5_value},
        }

    if msgtype == "news":
        body = payload.get("news")
        articles = body.get("articles") if isinstance(body, dict) else None
        if not isinstance(articles, list) or not 1 <= len(articles) <= 8:
            raise ValueError("企业微信图文消息必须包含 1 至 8 条内容")
        clean_articles: list[dict[str, str]] = []
        for article in articles:
            if not isinstance(article, dict):
                raise ValueError("企业微信图文消息结构无效")
            title = str(article.get("title") or "").strip()
            url = str(article.get("url") or "").strip()
            if not title or not url:
                raise ValueError("企业微信图文消息必须填写标题和链接")
            clean_articles.append(
                {
                    "title": title[:128],
                    "description": str(article.get("description") or "")[:512],
                    "url": url[:2048],
                    "picurl": str(article.get("picurl") or "")[:2048],
                },
            )
        return {"msgtype": msgtype, "news": {"articles": clean_articles}}

    raise ValueError("不支持的企业微信消息类型")


def _post_payload(
    client: httpx.Client,
    webhook: str,
    payload: dict[str, Any],
) -> str:
    response = client.post(webhook, json=payload)
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise WeComDeliveryError("企业微信返回了无法解析的响应") from exc
    errcode = body.get("errcode")
    if errcode != 0:
        errmsg = str(body.get("errmsg") or "未知错误")[:300]
        raise WeComDeliveryError(f"企业微信返回 {errcode}：{errmsg}")
    return str(errcode)


def safe_wecom_error(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(
        r"https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?[^\s]+",
        "[企业微信 Webhook 已隐藏]",
        message,
    )
    message = re.sub(r"([?&]key=)[^&\s]+", r"\1***", message)
    return (message or exc.__class__.__name__)[:1000]


def _claim_due_notifications(
    *,
    session_factory: Callable[[], Session],
    limit: int,
    now: datetime,
) -> list[int]:
    with session_factory() as db:
        due = and_(
            OutboundNotification.status.in_(("pending", "retrying")),
            or_(
                OutboundNotification.next_attempt_at.is_(None),
                OutboundNotification.next_attempt_at <= now,
            ),
        )
        abandoned = and_(
            OutboundNotification.status == "sending",
            OutboundNotification.updated_at <= now - SENDING_LEASE,
        )
        statement = (
            select(OutboundNotification)
            .where(or_(due, abandoned))
            .order_by(
                OutboundNotification.next_attempt_at,
                OutboundNotification.id,
            )
            .limit(max(1, min(limit, 100)))
        )
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        rows = list(db.scalars(statement).all())
        for row in rows:
            row.status = "sending"
            row.attempt_count += 1
            row.next_attempt_at = None
        db.commit()
        return [row.id for row in rows]


def _finish_delivery(
    notification_id: int,
    *,
    session_factory: Callable[[], Session],
    response_code: str | None = None,
    error: Exception | None = None,
) -> str:
    now = datetime.now(UTC)
    with session_factory() as db:
        row = db.get(OutboundNotification, notification_id)
        if row is None:
            return "failed"
        if error is None:
            row.status = "sent"
            row.sent_at = now
            row.last_error = None
            row.response_code = response_code
        else:
            row.last_error = safe_wecom_error(error)
            if row.attempt_count >= MAX_DELIVERY_ATTEMPTS:
                row.status = "failed"
                row.next_attempt_at = None
            else:
                row.status = "retrying"
                delay_index = min(
                    max(row.attempt_count - 1, 0),
                    len(RETRY_DELAYS_SECONDS) - 1,
                )
                row.next_attempt_at = now + timedelta(
                    seconds=RETRY_DELAYS_SECONDS[delay_index],
                )
        status = row.status
        db.commit()
        return status


def _deliver_claimed(
    notification_id: int,
    *,
    session_factory: Callable[[], Session],
    client: httpx.Client,
) -> str:
    try:
        with session_factory() as db:
            row = db.get(OutboundNotification, notification_id)
            if row is None:
                raise WeComDeliveryError("通知记录不存在")
            webhook = project_wecom_webhook(db, row.project_id)
            payload = _text_payload(row)
        response_code = _post_payload(client, webhook, payload)
    except Exception as exc:
        logger.warning(
            "企业微信通知 %s 投递失败：%s",
            notification_id,
            safe_wecom_error(exc),
        )
        return _finish_delivery(
            notification_id,
            session_factory=session_factory,
            error=exc,
        )
    return _finish_delivery(
        notification_id,
        session_factory=session_factory,
        response_code=response_code,
    )


def deliver_due_notifications(
    limit: int = 20,
    *,
    session_factory: Callable[[], Session] | None = None,
    client: httpx.Client | None = None,
) -> DeliveryReport:
    """领取并投递到期通知；可由多个平台进程安全并发调用。"""

    factory = session_factory or SessionLocal
    claimed_ids = _claim_due_notifications(
        session_factory=factory,
        limit=limit,
        now=datetime.now(UTC),
    )
    sent = retrying = failed = 0

    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    try:
        for notification_id in claimed_ids:
            result = _deliver_claimed(
                notification_id,
                session_factory=factory,
                client=http_client,
            )
            if result == "sent":
                sent += 1
            elif result == "retrying":
                retrying += 1
            else:
                failed += 1
    finally:
        if owns_client:
            http_client.close()

    return DeliveryReport(
        claimed=len(claimed_ids),
        sent=sent,
        retrying=retrying,
        failed=failed,
    )


def send_project_wecom_test(
    db: Session,
    project_id: int,
    *,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """显式测试项目群机器人；调用方必须由用户主动触发。"""

    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("项目不存在")
    webhook = project_wecom_webhook(db, project_id)
    payload = {
        "msgtype": "text",
        "text": {
            "content": (
                "【Dobby · 连接测试】\n"
                f"项目：{project.name}\n"
                "企业微信群机器人已成功接入，后续任务节点将通过本群提醒。"
            ),
        },
    }
    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    try:
        response_code = _post_payload(http_client, webhook, payload)
    finally:
        if owns_client:
            http_client.close()
    return {"status": "ok", "response_code": response_code}


def send_project_wecom_payload(
    db: Session,
    project_id: int,
    payload: dict[str, Any],
    *,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """Send one validated MCP-originated message without revealing Webhook."""

    clean_payload = validate_wecom_message_payload(payload)
    webhook = project_wecom_webhook(db, project_id)
    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    try:
        response_code = _post_payload(http_client, webhook, clean_payload)
    finally:
        if owns_client:
            http_client.close()
    return {
        "status": "ok",
        "response_code": response_code,
        "message_type": clean_payload["msgtype"],
    }
