from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api import save_my_connector
from backend.app.chat_api import create_chat_message, create_private_chat_channel, list_chat_messages
from backend.app.chat_workspace_api import ChatReadInput, chat_unread_counts, mark_chat_read, upload_chat_file
from backend.app.connector_secrets import decrypt_connector_secret
from backend.app.db import Base
from backend.app.engineering_document_catalog import (
    add_local_folder, add_pending_local_file, authorized_qa_payload, local_folder_tree_view,
    local_knowledge_page, readable_external_ids, require_catalogue_capability,
)
from backend.app.models import ChatChannel, ChatChannelMember, ChatMessage, EngineeringDocumentNode, Project, ProjectMember, RiskSource, User, UserConnectorConfig
from backend.app.project_status_details import meeting_status_details, project_status_tasks
from backend.app.schemas import ChatMessageInput, ChatPrivateChannelInput, UserConnectorConfigInput
from backend.app.workspace_api import (
    AnnouncementInput, PlatformAccountInput, PlatformInput, create_platform, list_announcements,
    list_platform_accounts, list_platforms, publish_announcement, save_platform_account, withdraw_announcement,
    my_task_counts,
)
from backend.app.workspace_migrations import upgrade_workspace
from backend.app.workspace_models import ChatKnowledgeFolder, UserPlatformAccount


@pytest.fixture
def workspace():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        users = [User(username=f'u{i}', password_hash='hash', real_name=f'成员{i}', identity_card_no=f'ID{i}', role='admin' if i == 0 else 'user') for i in range(4)]
        project = Project(name='会议测试工程')
        db.add_all([project, *users]); db.flush()
        db.add_all([ProjectMember(project_id=project.id, user_id=user.id) for user in users[:3]])
        db.commit()
        yield db, project, users


def new_group(db, project, users, title='资料组', **kwargs):
    result = create_private_chat_channel(project.id, ChatPrivateChannelInput(title=title, participant_user_ids=[users[1].id], **kwargs), db, users[0])
    return db.get(ChatChannel, result['data']['id'])


def add_root(db, project):
    root = EngineeringDocumentNode(project_id=project.id, node_type='knowledge_base', node_key='test-kb', knowledge_base_id='kb', external_id='kb', name='B_工程知识库', folder_path='')
    db.add(root); db.commit()
    return root


def group_document(db, project, channel):
    add_root(db, project)
    add_local_folder(db, project.id, 'kb', '群聊')
    folder = add_local_folder(db, project.id, 'kb', f'群聊/{channel.title}')
    db.add(ChatKnowledgeFolder(channel_id=channel.id, project_id=project.id, knowledge_base_id='kb', folder_path=folder.folder_path))
    file = add_pending_local_file(db, project.id, 'kb', folder.folder_path, {'knowledge_id': 'private-file'}, fallback_name='安全检查记录.pdf')
    shared = add_pending_local_file(db, project.id, 'kb', '', {'knowledge_id': 'shared-file'}, fallback_name='公共资料.pdf')
    db.commit()
    return folder, file, shared


def test_announcements_are_project_scoped_and_admin_published(workspace):
    db, project, users = workspace
    payload = AnnouncementInput(title='施工安排', content='明日开展安全检查。')
    with pytest.raises(HTTPException) as error:
        publish_announcement(project.id, payload, db, users[1])
    assert error.value.status_code == 403
    row = publish_announcement(project.id, payload, db, users[0])['data']
    assert list_announcements(project.id, db, users[1])['data'][0]['content'] == payload.content
    with pytest.raises(HTTPException):
        list_announcements(project.id, db, users[3])
    withdraw_announcement(project.id, row['id'], db, users[0])
    assert list_announcements(project.id, db, users[1])['data'] == []


def test_personal_accounts_are_separate_for_each_platform_and_user(workspace):
    db, project, users = workspace
    platforms = [create_platform(project.id, PlatformInput(name=f'平台{i}', platform_type='监测平台', url=f'https://example.com/{i}'), db, users[0])['data'] for i in range(2)]
    for i, platform in enumerate(platforms):
        result = save_platform_account(project.id, platform['id'], PlatformAccountInput(account_identifier=f'my-account-{i}', secret=f'secret-{i}'), db, users[1])['data']
        assert 'secret_encrypted' not in result and result['has_secret']
    assert len(list_platform_accounts(project.id, db, users[1])['data']) == 2
    assert list_platform_accounts(project.id, db, users[2])['data'] == []
    rows = db.scalars(select(UserPlatformAccount)).all()
    assert decrypt_connector_secret(rows[0].secret_encrypted) == 'secret-0'
    save_platform_account(project.id, platforms[0]['id'], PlatformAccountInput(account_identifier='renamed'), db, users[1])
    assert decrypt_connector_secret(rows[0].secret_encrypted) == 'secret-0'
    assert 'secret-0' not in str(list_platforms(project.id, db, users[0]))
    other = Project(name='另一个工程'); db.add(other); db.commit()
    with pytest.raises(HTTPException):
        save_platform_account(other.id, platforms[0]['id'], PlatformAccountInput(account_identifier='wrong'), db, users[0])


def test_platform_definition_requires_admin_and_valid_address(workspace):
    db, project, users = workspace
    payload = PlatformInput(name='监测', platform_type='监测平台', url='https://example.com')
    with pytest.raises(HTTPException):
        create_platform(project.id, payload, db, users[1])
    with pytest.raises(ValidationError):
        PlatformInput(name='监测', platform_type='监测平台', url='javascript:alert(1)')
    create_platform(project.id, payload, db, users[0])
    with pytest.raises(HTTPException) as error:
        create_platform(project.id, payload, db, users[0])
    assert error.value.status_code == 409


def test_mail_receive_only_needs_no_secret_and_disabling_removes_it(workspace):
    db, _, users = workspace
    received = save_my_connector('mail', UserConnectorConfigInput(account_identifier='user@example.com', sending_enabled=False), db, users[1])['data']
    assert received['configured'] and not received['has_secret'] and not received['sending_enabled']
    with pytest.raises(HTTPException) as error:
        save_my_connector('mail', UserConnectorConfigInput(account_identifier='user@example.com', sending_enabled=True), db, users[1])
    assert error.value.status_code == 422
    save_my_connector('mail', UserConnectorConfigInput(account_identifier='user@example.com', sending_enabled=True, secret='authorization'), db, users[1])
    disabled = save_my_connector('mail', UserConnectorConfigInput(account_identifier='user@example.com', sending_enabled=False, secret='ignored'), db, users[1])['data']
    assert not disabled['has_secret'] and not disabled['sending_enabled']


def test_legacy_personal_credential_can_be_associated_explicitly(workspace):
    db, project, users = workspace
    save_my_connector('platform', UserConnectorConfigInput(account_identifier='old-account', platform_type='监测平台', secret='old-secret'), db, users[1])
    platform = create_platform(project.id, PlatformInput(name='监测', platform_type='监测平台', url='https://example.com'), db, users[0])['data']
    save_platform_account(project.id, platform['id'], PlatformAccountInput(account_identifier='old-account', use_legacy_account=True), db, users[1])
    row = db.scalar(select(UserPlatformAccount))
    assert decrypt_connector_secret(row.secret_encrypted) == 'old-secret'


def test_group_names_unique_in_project_and_all_members_join(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users, title='Safety', all_members=True)
    for name in ['Safety', ' Safety ', 'safety']:
        with pytest.raises(HTTPException) as error:
            new_group(db, project, users, title=name)
        assert error.value.status_code == 409
    members = set(db.scalars(select(ChatChannelMember.user_id).where(ChatChannelMember.channel_id == channel.id)).all())
    assert members == {user.id for user in users[:3]}
    assert channel.channel_type == 'topic'
    with pytest.raises(ValidationError):
        ChatPrivateChannelInput(title='../文件', participant_user_ids=[users[1].id])
    other = Project(name='其他工程'); db.add(other); db.flush()
    db.add(ChatChannel(project_id=other.id, title='Safety', channel_type='private')); db.commit()
    db.add(ChatChannel(project_id=project.id, title='safety', channel_type='private'))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_all_unread_messages_count_and_history_fetch_does_not_clear(workspace):
    db, project, users = workspace
    group = new_group(db, project, users)
    first = create_chat_message(group.id, ChatMessageInput(content='普通消息，无需艾特', client_message_id='message-1'), db, users[0])['data']
    second = create_chat_message(group.id, ChatMessageInput(content='另一条消息', client_message_id='message-2'), db, users[0])['data']
    create_chat_message(group.id, ChatMessageInput(content='自己的消息', client_message_id='message-3'), db, users[1])
    assert chat_unread_counts(project.id, db, users[1])['data']['total'] == 2
    assert chat_unread_counts(project.id, db, users[2])['data']['total'] == 0
    list_chat_messages(group.id, None, 100, db, users[1])
    assert chat_unread_counts(project.id, db, users[1])['data']['total'] == 2
    mark_chat_read(group.id, ChatReadInput(message_id=second['id']), db, users[1])
    mark_chat_read(group.id, ChatReadInput(message_id=first['id']), db, users[1])
    assert chat_unread_counts(project.id, db, users[1])['data']['total'] == 0
    assert chat_unread_counts(project.id, db, users[0])['data']['total'] == 1
    with pytest.raises(HTTPException):
        mark_chat_read(group.id, ChatReadInput(message_id=second['id']), db, users[2])


def test_read_marker_rejects_message_from_another_group(workspace):
    db, project, users = workspace
    group = new_group(db, project, users)
    other = new_group(db, project, users, title='另一个群')
    message = create_chat_message(other.id, ChatMessageInput(content='其他群消息'), db, users[0])['data']
    with pytest.raises(HTTPException) as error:
        mark_chat_read(group.id, ChatReadInput(message_id=message['id']), db, users[1])
    assert error.value.status_code == 422


def test_group_file_acl_applies_to_lists_downloads_qa_and_ancestor_operations(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    folder, file, _ = group_document(db, project, channel)
    assert readable_external_ids(db, project.id, users[1]) == {'private-file', 'shared-file'}
    assert readable_external_ids(db, project.id, users[2]) == {'shared-file'}
    assert readable_external_ids(db, project.id, users[0]) == {'private-file', 'shared-file'}
    visible = local_knowledge_page(db, project.id, 'kb', users[2], page=1, page_size=100, folder_path=None, folder_recursive=True, keyword='')
    assert [row['id'] for row in visible['knowledge']] == ['shared-file']
    tree = local_folder_tree_view(db, project.id, 'kb', users[2])
    assert '资料组' not in str(tree)
    with pytest.raises(HTTPException):
        require_catalogue_capability(db, project.id, users[2], file, 'can_read')
    with pytest.raises(HTTPException):
        require_catalogue_capability(db, project.id, users[2], db.get(EngineeringDocumentNode, folder.parent_id), 'can_delete')
    constrained = authorized_qa_payload(db, project.id, users[2], {'query': '汇总工程资料'})
    assert constrained['knowledge_ids'] == ['shared-file']
    with pytest.raises(HTTPException):
        authorized_qa_payload(db, project.id, users[2], {'knowledge_ids': ['private-file']})
    member = db.scalar(select(ChatChannelMember).where(ChatChannelMember.channel_id == channel.id, ChatChannelMember.user_id == users[1].id))
    member.left_at = datetime.now(UTC); db.commit()
    assert readable_external_ids(db, project.id, users[1]) == {'shared-file'}


def test_group_upload_creates_knowledge_folder_and_durable_file_message(workspace, monkeypatch):
    db, project, users = workspace
    channel = new_group(db, project, users)
    add_root(db, project)
    folders, uploads = [], []
    class Client:
        def create_weknora_folder(self, agent_id, kb, *, folder_path):
            folders.append(folder_path); return {}
        def upload_weknora_knowledge(self, agent_id, kb, **kwargs):
            uploads.append(kwargs); return {'knowledge_id': 'uploaded-file'}
    monkeypatch.setattr('backend.app.chat_workspace_api._agentscope_client', lambda: Client())
    monkeypatch.setattr('backend.app.chat_workspace_api._ready_project_weknora_agent_id', lambda *args: 'agent')
    result = upload_chat_file(channel.id, UploadFile(filename='检查记录.txt', file=BytesIO(b'content')), 'upload-id', db, users[1])['data']
    assert folders == ['群聊', '群聊/资料组']
    assert uploads[0]['folder_path'] == '群聊/资料组'
    assert result['metadata']['attachments'][0]['knowledge_id'] == 'uploaded-file'
    assert readable_external_ids(db, project.id, users[2]) == set()
    upload_chat_file(channel.id, UploadFile(filename='检查记录.txt', file=BytesIO(b'content')), 'upload-id', db, users[1])
    assert len(uploads) == 1
    assert db.scalar(select(ChatMessage).where(ChatMessage.id == result['id']))


def test_group_upload_failure_never_reports_success(workspace, monkeypatch):
    from backend.app.agentscope_client import AgentScopeGatewayError
    db, project, users = workspace
    channel = new_group(db, project, users); add_root(db, project)
    class Client:
        def create_weknora_folder(self, *args, **kwargs): return {}
        def upload_weknora_knowledge(self, *args, **kwargs): raise AgentScopeGatewayError('知识库离线', status_code=503)
    monkeypatch.setattr('backend.app.chat_workspace_api._agentscope_client', lambda: Client())
    monkeypatch.setattr('backend.app.chat_workspace_api._ready_project_weknora_agent_id', lambda *args: 'agent')
    with pytest.raises(HTTPException) as error:
        upload_chat_file(channel.id, UploadFile(filename='test.txt', file=BytesIO(b'x')), 'failed-upload', db, users[1])
    assert error.value.status_code == 503
    assert db.scalar(select(ChatMessage).where(ChatMessage.client_message_id == 'failed-upload')) is None
    assert db.get(ChatKnowledgeFolder, channel.id) is not None


def test_status_counts_all_today_files_and_respects_china_date_and_permissions(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users); _, file, shared = group_document(db, project, channel)
    file.external_created_at = '2026-09-05T16:00:00Z'
    shared.external_created_at = '2026-09-05T15:59:59Z'
    for i in range(7):
        row = add_pending_local_file(db, project.id, 'kb', '', {'knowledge_id': f'today-{i}'}, fallback_name=f'今日资料{i}.pdf')
        row.external_created_at = '2026-09-06T03:00:00Z'
    risk = RiskSource(project_id=project.id, serial_no=1, related_process_name='安全检查', risk_part='高处作业隐患', risk_level='high', evaluation_condition='检查安全措施', status='active', material_requirements=['安全检查记录', '安全交底'])
    db.add(risk); db.commit()
    details = meeting_status_details(db, project.id, users[1], [risk], [], now=datetime(2026, 9, 6, 4, tzinfo=UTC))
    assert details['documents']['today_count'] == 8
    assert details['documents']['missing_materials'] == ['安全交底']
    assert details['documents']['complete'] is False and details['safety']['total'] == 1
    hidden = meeting_status_details(db, project.id, users[2], [risk], [], now=datetime(2026, 9, 6, 4, tzinfo=UTC))
    assert hidden['documents']['today_count'] == 7
    assert len(hidden['documents']['missing_materials']) == 2
    risk.status = 'closed'
    assert meeting_status_details(db, project.id, users[1], [risk], [])['safety']['total'] == 0


def test_task_summary_paginates_beyond_500():
    tasks = [SimpleNamespace(id=str(i)) for i in range(503)]
    class Engine:
        def list_tasks(self, *, project_id, open_only, limit, offset):
            assert project_id == 7 and open_only
            return tasks[offset:offset + limit]
    assert len(list(project_status_tasks(Engine(), 7))) == 503


def test_personal_badges_separate_tasks_and_home_todos(workspace, monkeypatch):
    db, project, users = workspace
    def row(status, assignee, confirmer=None):
        return {'status': status, 'assignee_user_id': assignee, 'confirmer_user_id': confirmer}
    tasks = [row('pending', users[1].id), row('processing', users[1].id), row('overdue', users[1].id),
             row('pending_confirm', users[2].id, users[1].id), row('pending', users[2].id), row('completed', users[1].id)]
    monkeypatch.setattr('backend.app.workspace_api.get_engine', lambda: object())
    monkeypatch.setattr('backend.app.workspace_api.project_status_tasks', lambda *args: tasks)
    monkeypatch.setattr('backend.app.workspace_api.to_api_task', lambda task: task)
    assert my_task_counts(project.id, db, users[1])['data'] == {'tasks': 4, 'home_todo': 3}


def test_workspace_migration_preserves_duplicate_groups_and_can_run_twice(workspace):
    db, project, users = workspace
    new_group(db, project, users, title='同名')
    db.execute(text('DROP INDEX uq_chat_channels_project_title'))
    duplicate = ChatChannel(project_id=project.id, title='同名', channel_type='private'); db.add(duplicate); db.commit()
    with db.get_bind().begin() as connection:
        upgrade_workspace(connection); upgrade_workspace(connection)
    db.expire_all()
    assert db.get(ChatChannel, duplicate.id).title == f'同名（{duplicate.id}）'
    assert len(db.scalars(select(ChatChannel).where(ChatChannel.project_id == project.id)).all()) == 3
