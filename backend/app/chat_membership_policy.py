"""群聊自动同步与实时频道规则；群类型保留历史身份。"""
from sqlalchemy import and_, or_, inspect, text
from .models import ChatChannel


def chat_auto_sync(channel: ChatChannel) -> bool:
    value = channel.auto_sync_members
    return value if value is not None else channel.channel_type in {"project", "topic"}


def auto_sync_condition():
    return or_(ChatChannel.auto_sync_members.is_(True), and_(
        ChatChannel.auto_sync_members.is_(None), ChatChannel.channel_type.in_(("project", "topic")),
    ))


def realtime_channel_name(channel: ChatChannel) -> str:
    base = f"chat:project_{channel.project_id}:channel_{channel.id}"
    revision = channel.membership_revision or 0
    return f"{base}:v{revision}" if revision else base


def upgrade_chat_membership(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("chat_channels")}
    if "auto_sync_members" not in columns:
        connection.execute(text("ALTER TABLE chat_channels ADD COLUMN auto_sync_members BOOLEAN"))
    if "membership_revision" not in columns:
        connection.execute(text("ALTER TABLE chat_channels ADD COLUMN membership_revision INTEGER NOT NULL DEFAULT 0"))
