from types import SimpleNamespace
import asyncio
import json
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
    create_chat_connection_token,
    create_chat_message,
    create_private_chat_channel,
    create_chat_realtime_subscription_token,
    create_chat_realtime_token,
    get_chat_message,
    invoke_mentioned_chat_agents,
    list_chat_channel_members,
    list_chat_messages,
    list_chat_realtime_subscriptions,
    list_project_chat_channels,
    list_project_chat_participants,
    list_unseen_chat_mention_notices,
)
from backend.app.db import Base
from backend.app.dobby_task_draft_bridge import materialize_dobby_task_draft
from backend.app.models import (
    AgentConversation,
    ChatAgentThread,
    ChatMessage,
    ChatMessageMention,
    ChatMessageMentionReceipt,
    ChatRealtimeOutbox,
    ChatTaskDraft,
    Project,
    ProjectMember,
    User,
)
from backend.app.schemas import (
    ChatMessageInput,
    ChatPrivateChannelInput,
    ChatTaskDraftCreateInput,
    HomeTaskDraftCreateInput,
    TaskInput,
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


def test_assigned_task_assistant_uses_fixed_identity_and_writes_task_draft(
    db: Session,
) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    selected_agent = {
        "id": "task-agent-test",
        "name": "可替换的底层解析智能体",
        "description": "管理中心可见的真实名称",
        "enabled": True,
        "published": False,
        "model_ready": True,
        "permission_mode": "auto",
        "knowledge_config": None,
    }

    class FakeAgentScopeClient:
        def get_catalog(self):
            return {
                "task_assistant": selected_agent,
                "business_agents": [],
            }

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
                content="@任务助手 根据上面的讨论生成任务草案。",
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
    assert mention.display_name == "任务助手"
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
    assert reply.metadata_json["agent_name"] == "任务助手"
    assert reply.metadata_json["runtime_status"] == "awaiting_permission"
    assert reply.metadata_json["draft_status"] == "ready"
    assert reply.metadata_json["requires_confirmation"] is True


def test_explicit_business_agent_reuses_one_observable_run_message(
    db: Session,
) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    selected_agent = {
        "id": "managed-knowledge-agent",
        "name": "资料助手",
        "role": "business",
        "enabled": True,
        "published": True,
        "model_ready": True,
    }
    captured: dict[str, object] = {}

    class FakeBusinessAgentClient:
        def get_catalog(self):
            return {"task_assistant": None, "business_agents": [selected_agent]}

        def create_session(self, **kwargs):
            captured["session"] = kwargs
            return "knowledge-agent-session"

        def sync_session(self, **_):
            return None

        def chat(self, **kwargs):
            captured["chat"] = kwargs
            return AgentScopeReply(
                status="completed",
                content="已按当前用户资料权限完成回答。",
                message_id="knowledge-agent-reply",
                raw_message={
                    "id": "knowledge-agent-reply",
                    "name": "资料助手",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "已按当前用户资料权限完成回答。"},
                    ],
                    "created_at": "2026-09-04T08:00:00+00:00",
                },
            )

    created = create_chat_message(
        channel_id,
        ChatMessageInput(
            content="@资料助手 施工方案中的验收依据是什么？",
            client_message_id="observable-agent-run-0001",
            mentioned_agent_ids=[selected_agent["id"]],
        ),
        db,
        member,
        [selected_agent],
    )["data"]
    placeholder_id = created["metadata"]["agent_run_message_ids"][
        selected_agent["id"]
    ]
    placeholder = db.get(ChatMessage, placeholder_id)
    assert placeholder is not None
    assert placeholder.metadata_json["runtime_status"] == "queued"
    assert placeholder.metadata_json["runtime_trace"]["turn_finished_at"] is None

    with (
        patch(
            "backend.app.chat_api._agentscope_client",
            return_value=FakeBusinessAgentClient(),
        ),
        patch(
            "backend.app.chat_api.SessionLocal",
            new=sessionmaker(bind=db.get_bind(), expire_on_commit=False),
        ),
    ):
        invoke_mentioned_chat_agents(created["id"])

    db.expire_all()
    replies = db.scalars(
        select(ChatMessage).where(
            ChatMessage.reply_to_id == created["id"],
            ChatMessage.sender_agent_id == selected_agent["id"],
        ),
    ).all()
    assert [reply.id for reply in replies] == [placeholder_id]
    reply = replies[0]
    assert reply.content == "已按当前用户资料权限完成回答。"
    assert reply.metadata_json["runtime_status"] == "completed"
    assert reply.metadata_json["failed"] is False
    assert reply.metadata_json["runtime_trace"]["turn_finished_at"] is not None
    stages = reply.metadata_json["runtime_trace"]["stages"]
    assert [stage["stage_id"] for stage in stages] == [
        "accepted",
        "authorization",
        "session",
        "execution",
        "persist",
    ]
    assert all(stage["duration_ms"] is not None for stage in stages)
    assert captured["chat"]["metadata"]["trigger"] == "explicit_agent_mention"
    assert captured["chat"]["metadata"]["platform_user_id"] == member.id
    assert captured["chat"]["metadata"]["project_id"] == project.id


def test_task_assistant_uses_ai_flow_generator_and_keeps_draft_unpublished(
    db: Session,
) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    selected_agent = {
        "id": "task-agent-ai-flow-test",
        "name": "底层任务智能体",
        "enabled": True,
        "published": False,
        "model_ready": True,
    }
    captured: dict[str, object] = {}

    generated_flow = {
        "title": "下午五点会议提醒",
        "summary": "提醒项目成员下楼开会",
        "task_type": "automation",
        "risk_level": "low",
        "assignee_user_id": None,
        "confirmer_user_id": None,
        "wbs_item_id": None,
        "risk_source_id": None,
        "run_mode": "once",
        "trigger_date": "2026-09-02",
        "trigger_time": "17:00",
        "trigger_rule": "2026-09-02 17:00 执行一次",
        "trigger_interval_value": 1,
        "trigger_interval_unit": "week",
        "cc": "",
        "steps": [
            {
                "name": "发送会议提醒",
                "node_type": "project_chat_message",
                "owner_user_id": None,
                "due_at": None,
                "material": "",
                "action": {
                    "type": "project_chat_message",
                    "channel_id": channel_id,
                    "mention_mode": "all",
                    "mentioned_user_ids": [],
                    "content": "请大家下午五点下楼开会。",
                },
            },
        ],
        "generated_by": "ai",
        "generation_note": "由测试模型生成",
    }

    class FakeTaskAssistantClient:
        def get_catalog(self):
            return {"task_assistant": selected_agent, "business_agents": []}

        def create_session(self, **kwargs):
            captured["session"] = kwargs
            return "task-assistant-session"

        def sync_session(self, **_):
            return None

        def chat(self, **kwargs):
            captured["chat"] = kwargs
            return AgentScopeReply(
                status="completed",
                content="已生成任务草稿",
                message_id="task-assistant-reply",
                raw_message=None,
                raw_messages=[
                    {
                        "content": [
                            {
                                "type": "tool_call",
                                "name": "generate_task_flow",
                            },
                            {
                                "type": "tool_result",
                                "output": {"data": generated_flow},
                            },
                        ],
                    },
                ],
            )

    with (
        patch(
            "backend.app.chat_api._agentscope_client",
            return_value=FakeTaskAssistantClient(),
        ),
        patch(
            "backend.app.chat_api.SessionLocal",
            new=sessionmaker(bind=db.get_bind(), expire_on_commit=False),
        ),
    ):
        created = create_chat_message(
            channel_id,
            ChatMessageInput(
                content="@任务助手 下午5点提醒大家下楼开会。",
                client_message_id="chat-task-flow-draft-0001",
                mentioned_agent_ids=[selected_agent["id"]],
            ),
            db,
            member,
        )["data"]
        draft = db.scalar(
            select(ChatMessage).where(ChatMessage.message_type == "task_draft"),
        )
        assert draft is not None
        assert draft.metadata_json["draft_status"] == "generating"

        asyncio.run(
            chat_api._generate_task_assistant_draft(
                created["id"],
                selected_agent["id"],
                draft.id,
            ),
        )

    db.expire_all()
    draft = db.get(ChatMessage, draft.id)
    assert draft is not None
    assert captured["session"]["agent"]["id"] == selected_agent["id"]
    assert captured["chat"]["metadata"]["project_id"] == project.id
    assert captured["chat"]["metadata"]["platform_user_id"] == member.id
    assert "本轮明确请求" in str(captured["chat"]["content"])
    assert "generate_task_flow" in str(captured["chat"]["content"])
    assert draft.metadata_json["draft_status"] == "ready"
    assert draft.metadata_json["runtime_status"] == "awaiting_permission"
    assert draft.metadata_json["task_draft"]["action_type"] == (
        "project_chat_message"
    )
    assert draft.metadata_json["task_draft"]["mention_mode"] == "all"
    assert draft.metadata_json.get("publish_result") is None
    assert draft.task_ids == []


def test_task_assistant_mention_uses_management_catalog_identity(
    db: Session,
) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]
    selected_agent = {
        "id": "managed-task-assistant",
        "name": "任务助手",
        "role": "system_internal",
        "enabled": True,
        "published": False,
        "model_ready": True,
    }
    client = SimpleNamespace(
        get_catalog=lambda: {
            "task_assistant": selected_agent,
            "business_agents": [],
        },
    )
    with patch("backend.app.chat_api._agentscope_client", return_value=client):
        created = create_chat_message(
            channel_id,
            ChatMessageInput(
                content="@任务助手 根据当前讨论生成任务草稿。",
                client_message_id="native-task-assistant-0001",
                mentioned_agent_ids=[selected_agent["id"]],
            ),
            db,
            member,
        )["data"]

    assert created["metadata"]["task_assistant_ids"] == [
        selected_agent["id"],
    ]
    draft = db.scalar(
        select(ChatMessage).where(ChatMessage.message_type == "task_draft"),
    )
    assert draft is not None
    assert draft.sender_agent_id == selected_agent["id"]
    assert draft.metadata_json["draft_status"] == "generating"


def test_task_draft_is_visible_to_group_but_only_requester_can_manage(
    db: Session,
) -> None:
    project, requester, colleague, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, requester)["data"][0][
        "id"
    ]
    task_assistant = {
        "id": "managed-task-assistant",
        "name": "任务助手",
        "role": "system_internal",
        "enabled": True,
        "published": False,
        "model_ready": True,
    }
    create_chat_message(
        channel_id,
        ChatMessageInput(
            content="@任务助手 根据当前讨论生成任务草稿。",
            client_message_id="task-draft-permission-0001",
            mentioned_agent_ids=[task_assistant["id"]],
        ),
        db,
        requester,
        [task_assistant],
    )
    draft = db.scalar(
        select(ChatMessage).where(ChatMessage.message_type == "task_draft"),
    )
    assert draft is not None

    colleague_messages = list_chat_messages(
        channel_id,
        None,
        100,
        db,
        colleague,
    )["data"]
    assert draft.id in {message["id"] for message in colleague_messages}
    assert chat_api._task_draft_for_user_or_403(
        db,
        draft.id,
        requester,
    )[0].id == draft.id
    with pytest.raises(HTTPException) as permission_error:
        chat_api._task_draft_for_user_or_403(
            db,
            draft.id,
            colleague,
        )
    assert permission_error.value.status_code == 403
    assert "只有发起" in str(permission_error.value.detail)


def test_private_task_draft_stays_out_of_group_until_publish(
    db: Session,
) -> None:
    project, requester, colleague, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, requester)["data"][0][
        "id"
    ]
    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    selected_agent = {
        "id": "managed-private-task-assistant",
        "name": "任务助手",
        "role": "system_internal",
        "enabled": True,
        "published": False,
        "model_ready": True,
    }
    fake_client = SimpleNamespace(
        get_catalog=lambda: {
            "task_assistant": selected_agent,
            "business_agents": [],
        },
        create_session=lambda **_: "private-task-session",
        chat=lambda **_: AgentScopeReply(
            status="completed",
            content="已生成任务草稿",
            message_id="private-task-reply",
            raw_message=None,
        ),
    )

    with (
        patch("backend.app.chat_api._agentscope_client", return_value=fake_client),
        patch(
            "backend.app.chat_api._start_private_task_draft_generation",
        ) as start_generation,
    ):
        created = asyncio.run(
            chat_api.create_private_chat_task_draft(
                channel_id,
                ChatTaskDraftCreateInput(
                    requirement="@任务助手 明天下午五点提醒大家下楼开会。",
                    client_request_id="private-task-draft-0001",
                ),
                db,
                requester,
            ),
        )["data"]

    start_generation.assert_called_once_with(created["id"])
    assert created["status"] == "generating"
    assert created["request_text"] == "明天下午五点提醒大家下楼开会。"
    assert db.scalar(select(func.count(ChatMessage.id))) == 0
    private_event = db.scalar(
        select(ChatRealtimeOutbox)
        .where(
            ChatRealtimeOutbox.payload["data"]["type"].as_string()
            == "chat.task_draft.updated",
        )
        .order_by(ChatRealtimeOutbox.id.desc()),
    )
    assert private_event is not None
    assert private_event.payload["channel"] == (
        f"chat:project_{project.id}:user_{requester.id}"
    )

    generated_flow = {
                "title": "下午五点会议提醒",
                "summary": "提醒项目成员下楼开会",
                "task_type": "automation",
                "risk_level": "low",
                "run_mode": "once",
                "trigger_date": "2026-09-03",
                "trigger_time": "17:00",
                "trigger_interval_value": 1,
                "trigger_interval_unit": "week",
                "steps": [
                    {
                        "name": "发送会议提醒",
                        "node_type": "project_chat_message",
                        "action": {
                            "type": "project_chat_message",
                            "channel_id": channel_id,
                            "mention_mode": "all",
                            "mentioned_user_ids": [],
                            "content": "请大家下午五点下楼开会。",
                        },
                    },
                ],
                "generated_by": "ai",
    }

    with (
        patch(
            "backend.app.chat_api.SessionLocal",
            new=session_factory,
        ),
        patch("backend.app.chat_api._agentscope_client", return_value=fake_client),
        patch(
            "backend.app.chat_api._task_flow_from_agent_reply",
            return_value=generated_flow,
        ),
    ):
        asyncio.run(chat_api._generate_private_task_draft(created["id"]))

    db.expire_all()
    draft = db.get(ChatTaskDraft, created["id"])
    assert draft is not None
    assert draft.status == "ready"
    assert draft.draft_payload["title"] == "下午五点会议提醒"
    assert db.scalar(select(func.count(ChatMessage.id))) == 0
    assert chat_api.list_private_chat_task_drafts(
        project.id,
        True,
        db,
        requester,
    )["data"][0]["id"] == draft.id
    assert chat_api.list_private_chat_task_drafts(
        project.id,
        True,
        db,
        colleague,
    )["data"] == []
    with pytest.raises(HTTPException) as permission_error:
        chat_api.get_private_chat_task_draft(draft.id, db, colleague)
    assert permission_error.value.status_code == 403

    task_payload = TaskInput(
        title="下午五点会议提醒",
        task_type="automation",
        action_type="project_chat_message",
        run_mode="once",
        trigger_date="2026-09-03",
        trigger_time="17:00",
        target_channel_id=channel_id,
        mention_mode="all",
        message_content="请大家下午五点下楼开会。",
        workflow_steps=[],
    )
    with patch(
        "backend.app.api.create_task",
        return_value={
            "success": True,
            "message": "执行计划已登记",
            "data": {"id": "task-private-draft-1"},
        },
    ):
        published = chat_api.publish_private_chat_task_draft(
            draft.id,
            task_payload,
            db,
            requester,
        )["data"]

    assert published["draft"]["status"] == "published"
    assert published["message"]["message_type"] == "task_event"
    assert published["message"]["metadata"]["task_title"] == (
        "下午五点会议提醒"
    )
    colleague_messages = list_chat_messages(
        channel_id,
        None,
        100,
        db,
        colleague,
    )["data"]
    assert [message["message_type"] for message in colleague_messages] == [
        "task_event",
    ]


def test_home_agent_task_draft_uses_private_conversation_context(
    db: Session,
) -> None:
    project, requester, _, _ = _project_with_members(db)
    conversation = AgentConversation(
        project_id=project.id,
        user_id=requester.id,
        agent_id="dobby-main",
        agent_name="Dobby",
        conversation_type="general",
        title="会议安排",
        agentscope_session_id="home-session-1",
        status="active",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    selected_agent = {
        "id": "managed-home-task-assistant",
        "name": "任务助手",
        "role": "system_internal",
        "enabled": True,
        "published": False,
        "model_ready": True,
    }
    fake_client = SimpleNamespace(
        get_catalog=lambda: {
            "task_assistant": selected_agent,
            "business_agents": [],
        },
        create_session=lambda **_: "home-task-session",
        chat=lambda **_: AgentScopeReply(
            status="completed",
            content="已生成任务草稿",
            message_id="home-task-reply",
            raw_message=None,
        ),
        list_messages=lambda *args, **kwargs: {
            "messages": [
                {
                    "id": "message-1",
                    "role": "user",
                    "content": [{"type": "text", "text": "注入内容"}],
                    "metadata": {"platform_display_content": "明天下午开协调会"},
                    "created_at": "2026-09-03T09:00:00+08:00",
                },
                {
                    "id": "message-2",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "建议通知全体项目成员。"}],
                    "created_at": "2026-09-03T09:00:05+08:00",
                },
            ],
        },
    )

    with (
        patch("backend.app.chat_api._agentscope_client", return_value=fake_client),
        patch("backend.app.chat_api._start_private_task_draft_generation") as start,
    ):
        created = asyncio.run(
            chat_api.create_home_agent_task_draft(
                project.id,
                HomeTaskDraftCreateInput(
                    requirement="@任务助手 明天下午五点提醒大家开协调会。",
                    client_request_id="home-task-draft-0001",
                    conversation_id=conversation.id,
                ),
                db,
                requester,
            ),
        )["data"]

    start.assert_called_once_with(created["id"])
    draft = db.get(ChatTaskDraft, created["id"])
    assert draft is not None
    assert draft.request_text == "明天下午五点提醒大家开协调会。"
    assert draft.context_json == [
        {
            "source": "home_agent_reference",
            "conversation_id": conversation.id,
        },
    ]
    assert db.scalar(select(func.count(ChatMessage.id))) == 0

    with patch("backend.app.chat_api._agentscope_client", return_value=fake_client):
        snapshot = asyncio.run(
            chat_api._home_agent_task_context_snapshot(
                session_id="home-session-1",
                agent_id="dobby-main",
                agent_name="Dobby",
                user_name=requester.real_name,
            ),
        )
    assert [item["content"] for item in snapshot] == [
        "明天下午开协调会",
        "建议通知全体项目成员。",
    ]
    assert all(item["source"] == "home_agent" for item in snapshot)

    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    async def fake_snapshot(**kwargs):
        assert kwargs["session_id"] == "home-session-1"
        return snapshot

    generated_flow = {
                "title": "协调会提醒",
                "summary": "提醒项目成员参加协调会",
                "task_type": "daily_work",
                "risk_level": "low",
                "run_mode": "immediate",
                "trigger_time": "09:00",
                "steps": [
                    {
                        "name": "发送会议通知",
                        "node_type": "manual",
                        "owner_user_id": requester.id,
                        "material": "会议通知记录",
                    },
                ],
                "generated_by": "ai",
    }

    with (
        patch("backend.app.chat_api.SessionLocal", new=session_factory),
        patch("backend.app.chat_api._agentscope_client", return_value=fake_client),
        patch(
            "backend.app.chat_api._home_agent_task_context_snapshot",
            new=fake_snapshot,
        ),
        patch(
            "backend.app.chat_api._task_flow_from_agent_reply",
            return_value=generated_flow,
        ),
    ):
        asyncio.run(chat_api._generate_private_task_draft(draft.id))

    db.expire_all()
    generated_draft = db.get(ChatTaskDraft, draft.id)
    assert generated_draft is not None
    assert generated_draft.status == "ready"
    assert generated_draft.draft_payload["title"] == "协调会提醒"
    assert generated_draft.context_json[0]["source"] == "home_agent_reference"
    assert generated_draft.context_json[1:-1] == snapshot
    assert generated_draft.context_json[-1] == {
        "source": "task_assistant_runtime",
        "agent_id": selected_agent["id"],
        "session_id": "home-task-session",
    }


def test_task_assistant_shared_message_route_creates_private_draft(
    db: Session,
) -> None:
    project, requester, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, requester)["data"][0][
        "id"
    ]

    selected_agent = {
        "id": "managed-shared-task-assistant",
        "name": "任务助手",
        "role": "system_internal",
        "enabled": True,
        "published": False,
        "model_ready": True,
    }
    with (
        patch(
            "backend.app.chat_api._validate_mentioned_agents",
            return_value=[selected_agent],
        ),
        patch("backend.app.chat_api._schedule_chat_agent_invocations") as schedule,
    ):
        created = asyncio.run(
            chat_api.create_chat_message_route(
                channel_id,
                ChatMessageInput(
                    content="@任务助手 明天下午五点提醒大家下楼开会。",
                    mentioned_agent_ids=[selected_agent["id"]],
                ),
                db,
                requester,
            ),
        )

    schedule.assert_called_once_with(created["data"])
    draft = db.scalar(
        select(ChatMessage).where(ChatMessage.message_type == "task_draft"),
    )
    assert draft is not None
    assert draft.sender_agent_id == selected_agent["id"]
    assert draft.metadata_json["requires_confirmation"] is True


def test_dobby_orchestrated_task_result_becomes_private_confirmation_draft(
    db: Session,
) -> None:
    project, requester, _, _ = _project_with_members(db)
    conversation = AgentConversation(
        project_id=project.id,
        user_id=requester.id,
        agent_id="dobby-main",
        agent_name="Dobby",
        conversation_type="general",
        title="安排明日例会",
        agentscope_session_id="dobby-task-session",
        status="running",
    )
    db.add(conversation)
    db.flush()
    flow = {
        "title": "明日例会通知",
        "summary": "通知项目成员参会",
        "task_type": "automation",
        "risk_level": "low",
        "run_mode": "once",
        "trigger_date": "2026-09-05",
        "trigger_time": "09:00",
        "steps": [
            {
                "name": "发送例会通知",
                "node_type": "project_chat_message",
                "action": {
                    "type": "project_chat_message",
                    "mention_mode": "all",
                    "mentioned_user_ids": [],
                    "content": "请明日上午九点参加例会。",
                },
            },
        ],
    }
    tagged = f"草稿已完成。<task-draft>{json.dumps(flow, ensure_ascii=False)}</task-draft>"
    reply = AgentScopeReply(
        status="completed",
        content=tagged,
        message_id="dobby-task-reply",
        raw_message={"id": "dobby-task-reply", "content": []},
    )

    first = materialize_dobby_task_draft(
        db,
        conversation,
        reply,
        user_request="帮我安排明天上午九点的项目例会",
    )
    second = materialize_dobby_task_draft(
        db,
        conversation,
        reply,
        user_request="帮我安排明天上午九点的项目例会",
    )

    assert first == second
    assert first is not None
    assert "<task-draft>" not in first[1]
    draft = db.get(ChatTaskDraft, first[0])
    assert draft is not None
    assert draft.status == "ready"
    assert draft.draft_payload["title"] == "明日例会通知"
    assert draft.published_task_ids == []
    assert db.scalar(select(func.count(ChatMessage.id))) == 0


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


def test_one_message_cannot_explicitly_mention_two_agents(db: Session) -> None:
    project, member, _, _ = _project_with_members(db)
    channel_id = list_project_chat_channels(project.id, db, member)["data"][0]["id"]

    with pytest.raises(HTTPException) as mention_error:
        create_chat_message(
            channel_id,
            ChatMessageInput.model_construct(
                content="@资料助手 @任务助手 同时处理",
                mentioned_user_ids=[],
                mentioned_agent_ids=["knowledge-agent", "task-agent"],
                mention_all=False,
                client_message_id=None,
                reply_to_id=None,
            ),
            db,
            member,
        )

    assert mention_error.value.status_code == 422
    assert "最多只能明确提及一个智能体" in str(mention_error.value.detail)


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
            ChatPrivateChannelInput(
                title="外部成员协调",
                participant_user_ids=[outsider.id],
            ),
            db,
            creator,
        )

    assert create_error.value.status_code == 422


def test_private_channel_requires_a_non_blank_group_name() -> None:
    with pytest.raises(ValueError, match="群名称不能为空"):
        ChatPrivateChannelInput(
            title="   ",
            participant_user_ids=[2],
        )


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


def test_login_scoped_realtime_token_has_no_project_channels(
    db: Session,
) -> None:
    _, member, _, _ = _project_with_members(db)
    realtime_secret = "chat-test-secret-with-32-bytes-minimum"
    settings = SimpleNamespace(
        centrifugo_enabled=True,
        centrifugo_ws_url="ws://127.0.0.1:38431/connection/websocket",
        effective_centrifugo_token_secret=realtime_secret,
        centrifugo_token_ttl_seconds=120,
    )

    with patch("backend.app.chat_api.get_settings", return_value=settings):
        result = create_chat_connection_token(member)["data"]

    claims = jwt.decode(
        result["token"],
        realtime_secret,
        algorithms=["HS256"],
        audience="dobby-realtime",
        issuer="dobby-platform",
    )
    assert result["enabled"] is True
    assert claims["sub"] == str(member.id)
    assert "channels" not in claims
    assert "channel" not in claims


def test_project_realtime_subscriptions_are_individually_authorized(
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
        result = list_chat_realtime_subscriptions(
            project.id,
            db,
            member,
        )["data"]

    subscriptions = result["subscriptions"]
    assert result["project_id"] == project.id
    assert len(subscriptions) == 2
    channels = [subscription["channel"] for subscription in subscriptions]
    assert channels[0] == f"chat:project_{project.id}:user_{member.id}"
    assert channels[1].startswith(f"chat:project_{project.id}:channel_")
    for subscription in subscriptions:
        claims = jwt.decode(
            subscription["token"],
            realtime_secret,
            algorithms=["HS256"],
            audience="dobby-realtime",
            issuer="dobby-platform",
        )
        assert claims["sub"] == str(member.id)
        assert claims["channel"] == subscription["channel"]
        assert "channels" not in claims

    with patch("backend.app.chat_api.get_settings", return_value=settings):
        refreshed = create_chat_realtime_subscription_token(
            project.id,
            channels[1],
            db,
            member,
        )["data"]
        with pytest.raises(HTTPException) as channel_error:
            create_chat_realtime_subscription_token(
                project.id,
                "chat:project_999:channel_999",
                db,
                member,
            )
        with pytest.raises(HTTPException) as project_error:
            list_chat_realtime_subscriptions(project.id, db, outsider)

    assert refreshed["channel"] == channels[1]
    assert channel_error.value.status_code == 403
    assert project_error.value.status_code == 403


def test_legacy_project_realtime_endpoint_uses_login_and_subscription_tokens(
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
    assert "channels" not in claims
    assert "channel" not in claims
    assert len(result["channels"]) == 2
    assert result["channels"][0] == f"chat:project_{project.id}:user_{member.id}"
    assert result["channels"][1].startswith(
        f"chat:project_{project.id}:channel_",
    )
    assert [item["channel"] for item in result["subscriptions"]] == result["channels"]
    for item in result["subscriptions"]:
        subscription_claims = jwt.decode(
            item["token"],
            realtime_secret,
            algorithms=["HS256"],
            audience="dobby-realtime",
            issuer="dobby-platform",
        )
        assert subscription_claims["channel"] == item["channel"]
        assert "channels" not in subscription_claims

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
        ChatPrivateChannelInput(
            title="令牌测试私聊",
            participant_user_ids=[invited.id],
        ),
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
