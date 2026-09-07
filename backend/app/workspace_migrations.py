"""会议调整的 SQLite / PostgreSQL 共用、可重复执行升级。"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


def upgrade_workspace(connection: Connection) -> None:
    from .chat_membership_policy import upgrade_chat_membership
    upgrade_chat_membership(connection)
    from .workspace_models import ChatKnowledgeFolder, ProjectAnnouncement, ProjectPlatform, UserPlatformAccount

    for table in (ProjectPlatform.__table__, UserPlatformAccount.__table__, ProjectAnnouncement.__table__, ChatKnowledgeFolder.__table__):
        table.create(connection, checkfirst=True)
    columns = {item["name"] for item in inspect(connection).get_columns("user_connector_configs")}
    if "sending_enabled" not in columns:
        connection.execute(text("ALTER TABLE user_connector_configs ADD COLUMN sending_enabled BOOLEAN NOT NULL DEFAULT false"))
        connection.execute(text("UPDATE user_connector_configs SET sending_enabled = true WHERE connector_type = 'mail' AND secret_encrypted IS NOT NULL"))
    # 保留历史群及消息；同工程重名的后建群加稳定编号，再建立数据库唯一约束。
    rows = connection.execute(text("SELECT id, project_id, title FROM chat_channels WHERE archived_at IS NULL ORDER BY id")).mappings().all()
    reserved = {(row["project_id"], row["title"].strip().lower()) for row in rows}
    seen = set()
    for row in rows:
        title = row["title"].strip()
        key = (row["project_id"], title.lower())
        if key in seen:
            base = title[:265]
            title = f"{base}（{row['id']}）"
            while (row["project_id"], title.lower()) in reserved:
                title += "群"
            reserved.add((row["project_id"], title.lower()))
        seen.add((row["project_id"], title.lower()))
        if title != row["title"]:
            connection.execute(text("UPDATE chat_channels SET title = :title WHERE id = :id"), {"title": title, "id": row["id"]})
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_channels_project_title ON chat_channels (project_id, lower(trim(title))) WHERE archived_at IS NULL"))
