from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agentscope_client import AgentScopeReply
from backend.app import chat_api
from backend.app.chat_api import (
    claim_chat_message_mention,
    create_chat_message,
    create_private_chat_channel,
    create_chat_realtime_token,
    get_chat_message,
    invoke_mentioned_chat_agents,
    list_chat_channel_members,
    list_chat_messages,
    list_project_chat_channels,
    list_project_chat_participants,
    list_unseen_chat_mention_notices,
)
from backend.app.db import Base
from backend.app.models import (
    ChatAgentThread,
    ChatMessage,
    ChatMessageMention,
    ChatMessageMentionReceipt,
    ChatRealtimeOutbox,
    Project,
    ProjectMember,
    User,
)
from backend.app.schemas import ChatMessageInput, ChatPrivateChannelInput


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


def _user(db: Session, suffix: str, *, role: str = "user") -> User:
    row = User(
        username=f"chat-{suffix}",
        password_hash="test",
        role=role,
        real_name=f"群聊用户{suffix}",
        title="项目成员",
        identity_card_no=f"chat-user-{suffix}",
    )
    db.add(row)
    db.flush()
    return row


def _project_with_members(
    db: Session,
) -> tuple[Project, User, User, User]:
    project = Project(name="真实群聊测试项目")
    member = _user(db, "member")
    colleague = _user(db, "colleague")
    outsider = _user(db, "outsider")
    db.add(project)
    db.flush()
    db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=member.id),
            ProjectMember(project_id=project.id, user_id=colleague.id),
        ],
    )
    db.commit()
    return project, member, colleague, outsider


def test_project_channel_is_shared_and_normal_message_does_not_invoke_agent(
    db: Session,
) -> None:
    project, member, colleague, _ = _project_with_members(db)

    member_channels = list_project_chat_channels(project.id, db, member)["data"]
    colleague_channels = list_project_chat_channels(project.id, db, colleague)["data"]

    assert len(member_channels) == 1
    assert colleague_channels[0]["id"] == member_channels[0]["id"]
    assert member_channels[0]["channel_type"] == "project"
    assert member_channels[0]["member_count"] == 2

    channel_id = member_channels[0]["id"]
    created = create_chat_message(
        channel_id,
        ChatMessageInput(
            content="大家好，这是一条真实的项目群消息。",
            client_message_id="chat-message-0001",
        ),
        db,
        member,
    )["data"]

    assert created["sender_type"] == "user"
    assert created["sender_user_id"] == member.id
    assert created["sender"]["name"] == member.real_name
    assert db.scalar(select(func.count(ChatMessage.id))) == 1

    received = list_chat_messages(channel_id, None, 100, db, colleague)["data"]
    assert [message["id"] for message in received] == [created["id"]]
    assert received[0]["content"] == "大家好，这是一条真实的项目群消息。"

    outbox = db.scalar(select(ChatRealtimeOutbox))
    assert outbox is not None
    assert outbox.method == "publish"
    assert outbox.payload["channel"] == (
        f"chat:project_{project.id}:channel_{channel_id}"
    )
    assert outbox.payload["data"]["message"]["id"] == created["id"]


def test_user_mention_is_persisted_and_published_to_personal_channel(
    db: Session,
) -> None:
    project, member, colleague, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]

    created = create_chat_message(
        channel_id,
        ChatMessageInput(
            content=f"@{colleague.real_name} 请确认今天的处理记录。",
            client_message_id="chat-user-mention-0001",
            mentioned_user_ids=[colleague.id],
        ),
        db,
        member,
    )["data"]

    assert created["mentions"] == [
        {
            "target_type": "user",
            "target_user_id": colleague.id,
            "target_agent_id": None,
            "display_name": colleague.real_name,
        },
    ]
    mention = db.scalar(select(ChatMessageMention))
    assert mention is not None
    assert mention.target_user_id == colleague.id
    receipt = db.scalar(select(ChatMessageMentionReceipt))
    assert receipt is not None
    assert receipt.user_id == colleague.id
    assert receipt.seen_at is None
    assert claim_chat_message_mention(created["id"], db, colleague)["data"] == {
        "first_seen": True,
    }
    assert claim_chat_message_mention(created["id"], db, colleague)["data"] == {
        "first_seen": False,
    }
    outbox_rows = db.scalars(
        select(ChatRealtimeOutbox).order_by(ChatRealtimeOutbox.id),
    ).all()
    assert len(outbox_rows) == 2
    assert outbox_rows[1].payload["channel"] == (
        f"chat:project_{project.id}:user_{colleague.id}"
    )
    assert outbox_rows[1].payload["data"]["type"] == "chat.mention.created"


def test_mention_all_has_no_quota_and_notifies_every_other_member(
    db: Session,
) -> None:
    project, member, colleague, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]

    for index in range(12):
        created = create_chat_message(
            channel_id,
            ChatMessageInput(
                content=f"@全体成员 第 {index + 1} 次项目提醒。",
                client_message_id=f"chat-all-mention-{index:04d}",
                mention_all=True,
            ),
            db,
            member,
        )["data"]
        assert created["mentions"] == [
            {
                "target_type": "all",
                "target_user_id": None,
                "target_agent_id": None,
                "display_name": "全体成员",
            },
        ]
        assert created["metadata"]["mention_all"] is True

    assert db.scalar(select(func.count(ChatMessage.id))) == 12
    assert db.scalar(select(func.count(ChatMessageMention.id))) == 0
    personal_events = [
        row
        for row in db.scalars(select(ChatRealtimeOutbox)).all()
        if row.payload["data"]["type"] == "chat.mention.created"
    ]
    assert len(personal_events) == 12
    assert all(
        row.payload["channel"] == f"chat:project_{project.id}:user_{colleague.id}"
        for row in personal_events
    )
    with pytest.raises(HTTPException) as spoofed_all:
        create_chat_message(
            channel_id,
            ChatMessageInput(content="正文没有全体成员提及。", mention_all=True),
            db,
            member,
        )
    assert spoofed_all.value.status_code == 422


def test_mention_attention_is_claimed_independently_for_each_recipient(
    db: Session,
) -> None:
    project, sender, colleague, another_recipient = _project_with_members(db)
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=another_recipient.id,
        ),
    )
    db.commit()
    channel_id = list_project_chat_channels(project.id, db, sender)["data"][0]["id"]
    created = create_chat_message(
        channel_id,
        ChatMessageInput(
            content="@全体成员 请分别确认收到。",
            client_message_id="chat-all-personal-receipt-0001",
            mention_all=True,
        ),
        db,
        sender,
    )["data"]

    receipts = db.scalars(
        select(ChatMessageMentionReceipt).order_by(ChatMessageMentionReceipt.user_id),
    ).all()
    assert {receipt.user_id for receipt in receipts} == {
        colleague.id,
        another_recipient.id,
    }
    colleague_notices = list_unseen_chat_mention_notices(
        project.id,
        50,
        db,
        colleague,
    )["data"]
    another_notices = list_unseen_chat_mention_notices(
        project.id,
        50,
        db,
        another_recipient,
    )["data"]
    assert [item["id"] for item in colleague_notices] == [created["id"]]
    assert [item["id"] for item in another_notices] == [created["id"]]
    assert get_chat_message(created["id"], db, colleague)["data"]["id"] == created["id"]
    assert claim_chat_message_mention(created["id"], db, colleague)["data"] == {
        "first_seen": True,
    }
    assert claim_chat_message_mention(created["id"], db, colleague)["data"] == {
        "first_seen": False,
    }
    assert claim_chat_message_mention(
        created["id"],
        db,
        another_recipient,
    )["data"] == {"first_seen": True}
    assert claim_chat_message_mention(created["id"], db, sender)["data"] == {
        "first_seen": False,
    }
    assert list_unseen_chat_mention_notices(project.id, 50, db, colleague)["data"] == []
    assert [
        item["id"]
        for item in list_unseen_chat_mention_notices(
            project.id,
            50,
            db,
            another_recipient,
        )["data"]
    ] == []


def test_published_agent_mention_invokes_agent_and_writes_reply(
    db: Session,
) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    selected_agent = {
        "id": "task-agent-test",
        "name": "任务智能体",
        "description": "测试任务智能体",
        "enabled": True,
        "published": True,
        "model_ready": True,
        "permission_mode": "auto",
        "knowledge_config": None,
    }

    class FakeAgentScopeClient:
        def get_catalog(self):
            return {"business_agents": [selected_agent]}

        def create_session(self, **_):
            return "chat-agent-session-test"

        def sync_session(self, **_):
            return None

        def chat(self, **_):
            return AgentScopeReply(
                status="completed",
                content="已生成任务草案，请确认后再布置。",
                message_id="agent-reply-test",
                raw_message={
                    "content": [
                        {"type": "text", "text": "已生成任务草案，请确认后再布置。"},
                    ],
                },
            )

    fake_client = FakeAgentScopeClient()
    with (
        patch("backend.app.chat_api._agentscope_client", return_value=fake_client),
        patch(
            "backend.app.chat_api._build_agent_project_context",
            return_value="<platform-context>测试项目</platform-context>",
        ),
        patch(
            "backend.app.chat_api.SessionLocal",
            new=sessionmaker(bind=db.get_bind(), expire_on_commit=False),
        ),
    ):
        created = create_chat_message(
            channel_id,
            ChatMessageInput(
                content="@任务智能体 根据上面的讨论生成任务草案。",
                client_message_id="chat-agent-mention-0001",
                mentioned_agent_ids=[selected_agent["id"]],
            ),
            db,
            member,
        )["data"]
        invoke_mentioned_chat_agents(created["id"])

    db.expire_all()
    mention = db.scalar(
        select(ChatMessageMention).where(
            ChatMessageMention.target_type == "agent",
        ),
    )
    assert mention is not None
    assert mention.target_agent_id == selected_agent["id"]
    assert mention.display_name == selected_agent["name"]
    thread = db.scalar(select(ChatAgentThread))
    assert thread is not None
    assert thread.agentscope_session_id == "chat-agent-session-test"
    assert thread.status == "completed"
    reply = db.scalar(
        select(ChatMessage).where(ChatMessage.sender_type == "agent"),
    )
    assert reply is not None
    assert reply.sender_agent_id == selected_agent["id"]
    assert reply.message_type == "task_draft"
    assert reply.reply_to_id == created["id"]
    assert reply.content == "已生成任务草案，请确认后再布置。"
    assert reply.metadata_json["agent_name"] == "任务智能体"
    assert reply.metadata_json["runtime_status"] == "completed"


def test_unpublished_agent_cannot_be_spoofed_in_mention(db: Session) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    with (
        patch(
            "backend.app.chat_api._agentscope_client",
            return_value=SimpleNamespace(
                get_catalog=lambda: {"business_agents": []},
            ),
        ),
        pytest.raises(HTTPException) as mention_error,
    ):
        create_chat_message(
            channel_id,
            ChatMessageInput(
                content="@伪造智能体 执行任务。",
                mentioned_agent_ids=["forged-agent"],
            ),
            db,
            member,
        )

    assert mention_error.value.status_code == 422


def test_private_channel_is_created_with_selected_project_members_only(
    db: Session,
) -> None:
    project, creator, invited, _ = _project_with_members(db)
    unselected = _user(db, "unselected")
    db.add(ProjectMember(project_id=project.id, user_id=unselected.id))
    db.commit()

    participants = list_project_chat_participants(project.id, db, creator)["data"]
    assert {row["user_id"] for row in participants} == {
        creator.id,
        invited.id,
        unselected.id,
    }

    created = create_private_chat_channel(
        project.id,
        ChatPrivateChannelInput(
            title="专项协调",
            participant_user_ids=[invited.id],
        ),
        db,
        creator,
    )["data"]

    assert created["channel_type"] == "private"
    assert created["title"] == "专项协调"
    assert created["created_by_user_id"] == creator.id
    assert created["member_count"] == 2

    creator_channels = list_project_chat_channels(project.id, db, creator)["data"]
    invited_channels = list_project_chat_channels(project.id, db, invited)["data"]
    unselected_channels = list_project_chat_channels(project.id, db, unselected)["data"]
    assert {row["id"] for row in creator_channels} >= {created["id"]}
    assert {row["id"] for row in invited_channels} >= {created["id"]}
    assert created["id"] not in {row["id"] for row in unselected_channels}

    members = list_chat_channel_members(created["id"], db, creator)["data"]
    assert {row["user_id"] for row in members} == {creator.id, invited.id}
    assert next(row for row in members if row["user_id"] == creator.id)["member_role"] == "owner"

    with pytest.raises(HTTPException) as access_error:
        list_chat_messages(created["id"], None, 100, db, unselected)
    assert access_error.value.status_code == 403

    invitation = db.scalar(select(ChatRealtimeOutbox))
    assert invitation is not None
    assert invitation.payload["data"]["type"] == "chat.channel.created"
    assert invitation.payload["channel"] == (
        f"chat:project_{project.id}:user_{invited.id}"
    )


def test_private_channel_rejects_non_project_participant(db: Session) -> None:
    project, creator, _, outsider = _project_with_members(db)

    with pytest.raises(HTTPException) as create_error:
        create_private_chat_channel(
            project.id,
            ChatPrivateChannelInput(participant_user_ids=[outsider.id]),
            db,
            creator,
        )

    assert create_error.value.status_code == 422


def test_project_and_channel_access_rejects_non_member(db: Session) -> None:
    project, member, _, outsider = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]

    with pytest.raises(HTTPException) as project_error:
        list_project_chat_channels(project.id, db, outsider)
    assert project_error.value.status_code == 403

    with pytest.raises(HTTPException) as channel_error:
        list_chat_messages(channel_id, None, 100, db, outsider)
    assert channel_error.value.status_code == 403

    with pytest.raises(HTTPException) as send_error:
        create_chat_message(
            channel_id,
            ChatMessageInput(content="我不应该能发送这条消息。"),
            db,
            outsider,
        )
    assert send_error.value.status_code == 403


def test_client_message_id_is_idempotent_per_sender(db: Session) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    payload = ChatMessageInput(
        content="网络重试时不能生成两条消息。",
        client_message_id="chat-message-retry-0001",
    )

    first = create_chat_message(channel_id, payload, db, member)["data"]
    second = create_chat_message(channel_id, payload, db, member)["data"]

    assert first["id"] == second["id"]
    assert db.scalar(select(func.count(ChatMessage.id))) == 1
    assert db.scalar(select(func.count(ChatRealtimeOutbox.id))) == 1


def test_client_cannot_spoof_chat_sender(db: Session) -> None:
    project, member, colleague, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    payload = ChatMessageInput.model_validate(
        {
            "content": "发送人只能来自当前登录态。",
            "client_message_id": "chat-sender-security-0001",
            "sender_user_id": colleague.id,
        },
    )

    created = create_chat_message(channel_id, payload, db, member)["data"]

    assert created["sender_user_id"] == member.id
    assert created["sender_user_id"] != colleague.id


def test_removed_project_member_loses_chat_access(db: Session) -> None:
    project, member, colleague, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == colleague.id,
        ),
    )
    assert membership is not None
    db.delete(membership)
    db.commit()

    with pytest.raises(HTTPException) as access_error:
        list_chat_messages(channel_id, None, 100, db, colleague)

    assert access_error.value.status_code == 403


def test_realtime_token_contains_only_authorized_project_and_control_channels(
    db: Session,
) -> None:
    project, member, _, outsider = _project_with_members(db)
    realtime_secret = "chat-test-secret-with-32-bytes-minimum"
    settings = SimpleNamespace(
        centrifugo_enabled=True,
        centrifugo_ws_url="ws://127.0.0.1:38431/connection/websocket",
        effective_centrifugo_token_secret=realtime_secret,
        centrifugo_token_ttl_seconds=120,
    )

    with patch("backend.app.chat_api.get_settings", return_value=settings):
        result = create_chat_realtime_token(project.id, db, member)["data"]

    claims = jwt.decode(
        result["token"],
        realtime_secret,
        algorithms=["HS256"],
        audience="dobby-realtime",
        issuer="dobby-platform",
    )
    assert result["enabled"] is True
    assert claims["sub"] == str(member.id)
    assert claims["channels"] == result["channels"]
    assert len(claims["channels"]) == 2
    assert claims["channels"][0] == f"chat:project_{project.id}:user_{member.id}"
    assert claims["channels"][1].startswith(
        f"chat:project_{project.id}:channel_",
    )

    with patch("backend.app.chat_api.get_settings", return_value=settings):
        with pytest.raises(HTTPException) as access_error:
            create_chat_realtime_token(project.id, db, outsider)
    assert access_error.value.status_code == 403


def test_realtime_token_includes_private_channel_for_selected_member_only(
    db: Session,
) -> None:
    project, creator, invited, _ = _project_with_members(db)
    unselected = _user(db, "token-unselected")
    db.add(ProjectMember(project_id=project.id, user_id=unselected.id))
    db.commit()
    private_channel = create_private_chat_channel(
        project.id,
        ChatPrivateChannelInput(participant_user_ids=[invited.id]),
        db,
        creator,
    )["data"]
    secret = "chat-test-secret-with-32-bytes-minimum"
    settings = SimpleNamespace(
        centrifugo_enabled=True,
        centrifugo_ws_url="ws://127.0.0.1:38431/connection/websocket",
        effective_centrifugo_token_secret=secret,
        centrifugo_token_ttl_seconds=120,
    )

    with patch("backend.app.chat_api.get_settings", return_value=settings):
        invited_result = create_chat_realtime_token(project.id, db, invited)["data"]
        unselected_result = create_chat_realtime_token(project.id, db, unselected)["data"]

    private_realtime_channel = (
        f"chat:project_{project.id}:channel_{private_channel['id']}"
    )
    assert private_realtime_channel in invited_result["channels"]
    assert private_realtime_channel not in unselected_result["channels"]
