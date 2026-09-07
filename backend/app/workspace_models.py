"""工程平台定义、个人账号、公告与群资料归档的持久化记录。"""
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import TimestampMixin


class ProjectPlatform(TimestampMixin, Base):
    __tablename__ = "project_platforms"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_platform_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    platform_type: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2000))
    description: Mapped[str] = mapped_column(Text, default="")


class UserPlatformAccount(TimestampMixin, Base):
    __tablename__ = "user_platform_accounts"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", name="uq_user_platform_account"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("project_platforms.id", ondelete="CASCADE"), index=True)
    account_identifier: Mapped[str] = mapped_column(String(500))
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectAnnouncement(TimestampMixin, Base):
    __tablename__ = "project_announcements"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class ChatKnowledgeFolder(TimestampMixin, Base):
    """独立绑定保证目录同步后仍按群成员权限过滤。"""
    __tablename__ = "chat_knowledge_folders"
    __table_args__ = (UniqueConstraint("project_id", "knowledge_base_id", "folder_path", name="uq_chat_knowledge_folder"),)
    channel_id: Mapped[int] = mapped_column(ForeignKey("chat_channels.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(128))
    folder_path: Mapped[str] = mapped_column(String(1000))
