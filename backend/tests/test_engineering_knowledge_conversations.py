import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api import (
    create_engineering_knowledge_conversation,
    create_engineering_knowledge_message,
    delete_engineering_knowledge_conversation,
    list_engineering_knowledge_conversations,
    list_engineering_knowledge_messages,
    update_engineering_knowledge_conversation,
)
from backend.app.db import Base
from backend.app.models import (
    EngineeringKnowledgeConversation,
    EngineeringKnowledgeMessage,
    Project,
    User,
)
from backend.app.schemas import (
    EngineeringKnowledgeConversationCreateInput,
    EngineeringKnowledgeConversationUpdateInput,
    EngineeringKnowledgeMessageInput,
    EngineeringKnowledgeScopeItemInput,
)


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
    engine.dispose()


def _admin(db: Session, suffix: str) -> User:
    user = User(
        username=f"knowledge-{suffix}",
        password_hash="test",
        role="admin",
        real_name=f"知识库测试用户{suffix}",
        identity_card_no=f"knowledge-conversation-{suffix}",
    )
    db.add(user)
    db.flush()
    return user


def test_engineering_knowledge_conversation_is_persisted_and_deleted(
    db: Session,
) -> None:
    user = _admin(db, "owner")
    project = Project(name="知识库聊天测试项目")
    db.add(project)
    db.commit()

    created = create_engineering_knowledge_conversation(
        project.id,
        EngineeringKnowledgeConversationCreateInput(
            title="塔吊基础问题",
            scope_type="document",
            knowledge_id="knowledge-001",
            knowledge_name="塔吊基础计算书.pdf",
            knowledge_base_id="kb-001",
            first_message="这份资料解决了什么问题？",
        ),
        db,
        user,
    )["data"]
    conversation_id = created["conversation"]["id"]
    assert created["messages"][0]["role"] == "user"
    assert created["messages"][0]["content"] == "这份资料解决了什么问题？"

    listed = list_engineering_knowledge_conversations(
        project.id,
        db,
        user,
    )["data"]
    assert [item["id"] for item in listed] == [conversation_id]
    assert listed[0]["knowledge_id"] == "knowledge-001"

    updated = update_engineering_knowledge_conversation(
        project.id,
        conversation_id,
        EngineeringKnowledgeConversationUpdateInput(
            weknora_session_id="weknora-session-001",
        ),
        db,
        user,
    )["data"]
    assert updated["weknora_session_id"] == "weknora-session-001"

    create_engineering_knowledge_message(
        project.id,
        conversation_id,
        EngineeringKnowledgeMessageInput(
            role="assistant",
            content="它用于完成塔吊基础结构设计和安全验算。",
            references=[{"knowledge_id": "knowledge-001"}],
        ),
        db,
        user,
    )
    messages = list_engineering_knowledge_messages(
        project.id,
        conversation_id,
        db,
        user,
    )["data"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[1]["references"] == [{"knowledge_id": "knowledge-001"}]

    deleted = delete_engineering_knowledge_conversation(
        project.id,
        conversation_id,
        db,
        user,
    )
    assert deleted["data"] == {"id": conversation_id}
    assert db.get(EngineeringKnowledgeConversation, conversation_id) is None
    assert db.scalars(
        select(EngineeringKnowledgeMessage).where(
            EngineeringKnowledgeMessage.conversation_id == conversation_id,
        ),
    ).all() == []


def test_engineering_knowledge_conversation_rejects_empty_and_cross_user_access(
    db: Session,
) -> None:
    owner = _admin(db, "first")
    other = _admin(db, "second")
    project = Project(name="知识库隔离测试项目")
    db.add(project)
    db.commit()

    with pytest.raises(HTTPException) as empty_error:
        create_engineering_knowledge_conversation(
            project.id,
            EngineeringKnowledgeConversationCreateInput(first_message="  "),
            db,
            owner,
        )
    assert empty_error.value.status_code == 422

    created = create_engineering_knowledge_conversation(
        project.id,
        EngineeringKnowledgeConversationCreateInput(
            first_message="请概括本项目安全资料。",
        ),
        db,
        owner,
    )["data"]["conversation"]
    with pytest.raises(HTTPException) as access_error:
        list_engineering_knowledge_messages(
            project.id,
            created["id"],
            db,
            other,
        )
    assert access_error.value.status_code == 404


def test_engineering_knowledge_conversation_persists_folder_scope(
    db: Session,
) -> None:
    user = _admin(db, "folder")
    project = Project(name="知识库目录问答测试项目")
    db.add(project)
    db.commit()

    created = create_engineering_knowledge_conversation(
        project.id,
        EngineeringKnowledgeConversationCreateInput(
            title="安全方案目录问答",
            scope_type="folder",
            knowledge_name="安全生产保证计划",
            knowledge_base_id="kb-001",
            folder_path="01_合同图纸与方案/方案/安全生产保证计划",
            first_message="该目录有哪些资料？",
        ),
        db,
        user,
    )["data"]["conversation"]

    assert created["scope_type"] == "folder"
    assert created["knowledge_id"] is None
    assert created["knowledge_name"] == "安全生产保证计划"
    assert created["knowledge_base_id"] == "kb-001"
    assert created["folder_path"] == "01_合同图纸与方案/方案/安全生产保证计划"


def test_engineering_knowledge_conversation_persists_multi_selection(
    db: Session,
) -> None:
    user = _admin(db, "multi-scope")
    project = Project(name="知识库多选问答测试项目")
    db.add(project)
    db.commit()

    created = create_engineering_knowledge_conversation(
        project.id,
        EngineeringKnowledgeConversationCreateInput(
            title="安全资料联合问答",
            scope_type="selection",
            scope_items=[
                EngineeringKnowledgeScopeItemInput(
                    scope_type="folder",
                    knowledge_name="安全生产保证计划",
                    knowledge_base_id="kb-001",
                    folder_path="01_合同图纸与方案/方案/安全生产保证计划",
                ),
                EngineeringKnowledgeScopeItemInput(
                    scope_type="document",
                    knowledge_id="knowledge-002",
                    knowledge_name="安全网.pdf",
                    knowledge_base_id="kb-002",
                ),
            ],
            first_message="对比两个范围中的安全要求。",
        ),
        db,
        user,
    )["data"]["conversation"]

    assert created["scope_type"] == "selection"
    assert created["knowledge_id"] is None
    assert created["knowledge_base_id"] is None
    assert created["folder_path"] is None
    assert created["scope_items"] == [
        {
            "scope_type": "folder",
            "knowledge_id": None,
            "knowledge_name": "安全生产保证计划",
            "knowledge_base_id": "kb-001",
            "folder_path": "01_合同图纸与方案/方案/安全生产保证计划",
        },
        {
            "scope_type": "document",
            "knowledge_id": "knowledge-002",
            "knowledge_name": "安全网.pdf",
            "knowledge_base_id": "kb-002",
            "folder_path": None,
        },
    ]


def test_engineering_knowledge_conversation_validates_scoped_targets(
    db: Session,
) -> None:
    user = _admin(db, "scope-validation")
    project = Project(name="知识库问答范围校验项目")
    db.add(project)
    db.commit()

    with pytest.raises(HTTPException) as folder_error:
        create_engineering_knowledge_conversation(
            project.id,
            EngineeringKnowledgeConversationCreateInput(
                scope_type="folder",
                knowledge_base_id="kb-001",
                first_message="目录里有什么？",
            ),
            db,
            user,
        )
    assert folder_error.value.status_code == 422

    with pytest.raises(HTTPException) as knowledge_base_error:
        create_engineering_knowledge_conversation(
            project.id,
            EngineeringKnowledgeConversationCreateInput(
                scope_type="knowledge_base",
                first_message="知识库里有什么？",
            ),
            db,
            user,
        )
    assert knowledge_base_error.value.status_code == 422

    with pytest.raises(HTTPException) as selection_error:
        create_engineering_knowledge_conversation(
            project.id,
            EngineeringKnowledgeConversationCreateInput(
                scope_type="selection",
                first_message="多选范围里有什么？",
            ),
            db,
            user,
        )
    assert selection_error.value.status_code == 422
