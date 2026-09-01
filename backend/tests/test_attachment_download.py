from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.engineering_documents_api import download_attachment
from backend.app.db import Base
from backend.app.models import Attachment, Project, ProjectMember, User


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def attachment_context(
    db: Session,
    tmp_path: Path,
) -> tuple[Attachment, User, User, Path]:
    project = Project(name="附件下载权限测试项目")
    member = User(
        username="attachment-member",
        password_hash="hash",
        role="user",
        real_name="项目成员",
        identity_card_no="ATTACHMENT_MEMBER",
    )
    outsider = User(
        username="attachment-outsider",
        password_hash="hash",
        role="user",
        real_name="外部用户",
        identity_card_no="ATTACHMENT_OUTSIDER",
    )
    db.add_all([project, member, outsider])
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=member.id))
    source = tmp_path / "evidence.txt"
    source.write_text("任务闭环材料", encoding="utf-8")
    attachment = Attachment(
        project_id=project.id,
        file_name="evidence.txt",
        storage_path=str(source),
        content_type="text/plain",
        file_size=source.stat().st_size,
        category="任务处置",
    )
    db.add(attachment)
    db.commit()
    return attachment, member, outsider, source


def test_project_member_can_download_attachment(
    db: Session,
    attachment_context: tuple[Attachment, User, User, Path],
) -> None:
    attachment, member, _, source = attachment_context

    response = download_attachment(attachment.id, db, member)

    assert Path(response.path) == source
    assert response.media_type == "text/plain"
    assert response.headers["cache-control"] == "private, no-store"


def test_non_member_cannot_download_attachment(
    db: Session,
    attachment_context: tuple[Attachment, User, User, Path],
) -> None:
    attachment, _, outsider, _ = attachment_context

    with pytest.raises(HTTPException) as error:
        download_attachment(attachment.id, db, outsider)

    assert error.value.status_code == 403
    assert error.value.detail == "你不是该项目的有效成员"


def test_missing_attachment_file_returns_404(
    db: Session,
    attachment_context: tuple[Attachment, User, User, Path],
) -> None:
    attachment, member, _, source = attachment_context
    source.unlink()

    with pytest.raises(HTTPException) as error:
        download_attachment(attachment.id, db, member)

    assert error.value.status_code == 404
    assert error.value.detail == "附件文件不存在"
