import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.tests.test_meeting_workspace import workspace, new_group, group_document
from backend.app.chat_management_api import (
    ChatMembersInput, ChatOwnerInput, ChatSettingsInput, add_chat_members,
    transfer_chat_owner, update_chat_settings, list_chat_files, ChatTitleCheckInput, check_chat_title, remove_chat_member,
    ChatMembershipSettingsInput, save_chat_membership,
)
from backend.app.chat_api import list_chat_channel_members, list_project_chat_channels
from backend.app.models import ChatChannel, ChatChannelMember, ChatRealtimeOutbox, ProjectMember


@pytest.mark.parametrize('kind', ['project', 'topic', 'private'])
def test_member_checkboxes_disable_sync_and_preserve_channel_and_files(workspace, kind):
    from backend.app.chat_api import ensure_project_chat_channel, _visible_chat_realtime_channels, chat_realtime_channel
    from backend.app.chat_workspace_api import chat_unread_counts
    from backend.app.engineering_document_catalog import readable_external_ids
    db, project, users = workspace
    channel = ensure_project_chat_channel(db, project.id, users[0]) if kind == 'project' else new_group(db, project, users, all_members=kind == 'topic')
    db.commit()
    _, file, _ = group_document(db, project, channel)
    channel_id, original_title, old_realtime = channel.id, channel.title, chat_realtime_channel(channel)
    result = save_chat_membership(channel.id, ChatMembershipSettingsInput(user_ids=[users[0].id, users[2].id], owner_user_id=users[0].id), db, users[0])['data']
    assert result['all_members'] is False
    assert channel.id == channel_id and channel.title == original_title and channel.channel_type == kind
    assert chat_realtime_channel(channel) != old_realtime
    for _ in range(2):
        listed = list_project_chat_channels(project.id, db, users[1])['data']
        assert channel.id not in {row['id'] for row in listed}
        assert str(channel.id) not in chat_unread_counts(project.id, db, users[1])['data']['channels']
    if kind == 'project':
        assert ensure_project_chat_channel(db, project.id, users[1]).id == channel_id
    assert old_realtime not in _visible_chat_realtime_channels(db, project.id, users[0])
    assert chat_realtime_channel(channel) not in _visible_chat_realtime_channels(db, project.id, users[1])
    with pytest.raises(HTTPException):
        list_chat_files(channel.id, None, 50, db, users[1])
    assert file.external_id not in readable_external_ids(db, project.id, users[1], ['kb'])
    assert [row['knowledge_id'] for row in list_chat_files(channel.id, None, 50, db, users[2])['data']['items']] == [file.external_id]
    db.add(ProjectMember(project_id=project.id, user_id=users[3].id)); db.commit()
    assert users[3].id not in {row['user_id'] for row in list_chat_channel_members(channel.id, db, users[0])['data']}
    save_chat_membership(channel.id, ChatMembershipSettingsInput(user_ids=[u.id for u in users], auto_sync=True, owner_user_id=users[2].id), db, users[0])
    assert list_project_chat_channels(project.id, db, users[1])['data']
    members = list_chat_channel_members(channel.id, db, users[0])['data']
    assert {row['user_id'] for row in members} == {u.id for u in users}
    assert [row['user_id'] for row in members if row['member_role'] == 'owner'] == [users[2].id]


def test_member_settings_validate_sync_owner_and_permissions(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users, all_members=True)
    invalid = [
        ({'user_ids': [users[0].id], 'auto_sync': True, 'owner_user_id': users[0].id}, users[0], 422),
        ({'user_ids': [users[1].id], 'owner_user_id': users[1].id}, users[0], 422),
        ({'user_ids': [users[0].id], 'owner_user_id': users[1].id}, users[0], 422),
        ({'user_ids': [users[0].id, users[3].id], 'owner_user_id': users[0].id}, users[0], 422),
        ({'user_ids': [users[0].id, users[1].id], 'owner_user_id': users[1].id}, users[1], 403),
    ]
    for payload, actor, status in invalid:
        with pytest.raises(HTTPException) as error:
            save_chat_membership(channel.id, ChatMembershipSettingsInput(**payload), db, actor)
        assert error.value.status_code == status
    assert channel.auto_sync_members is None


def test_turning_off_sync_without_removing_members_stays_off(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users, all_members=True)
    saved = save_chat_membership(channel.id, ChatMembershipSettingsInput(user_ids=[u.id for u in users[:3]], owner_user_id=users[0].id), db, users[0])['data']
    assert not saved['all_members']
    db.add(ProjectMember(project_id=project.id, user_id=users[3].id)); db.commit()
    assert len(list_chat_channel_members(channel.id, db, users[0])['data']) == 3


def test_member_positions_are_scoped_to_current_project(workspace):
    from backend.app.chat_api import list_project_chat_participants
    from backend.app.models import ProjectPosition, ProjectMemberPosition
    db, project, users = workspace
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == users[1].id))
    for index, name in enumerate(['质量员', '安全员', '资料员']):
        position = ProjectPosition(project_id=project.id, position_name=name); db.add(position); db.flush()
        db.add(ProjectMemberPosition(project_id=project.id, project_member_id=member.id, position_id=position.id, serial_no=index + 1, certificate_no='', responsibility_description=''))
    db.commit()
    row = next(r for r in list_project_chat_participants(project.id, db, users[0])['data'] if r['user_id'] == users[1].id)
    assert row['positions'] == ['质量员', '安全员', '资料员']
    assert users[1].title not in row['positions']


def test_all_group_tracks_project_members_and_rejects_manual_settings(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users, all_members=True)
    db.add(ProjectMember(project_id=project.id, user_id=users[3].id)); db.commit()
    assert users[3].id in {row['user_id'] for row in list_chat_channel_members(channel.id, db, users[1])['data']}
    membership = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == users[2].id))
    db.delete(membership); db.commit()
    assert users[2].id not in {row['user_id'] for row in list_chat_channel_members(channel.id, db, users[1])['data']}
    with pytest.raises(HTTPException) as error:
        add_chat_members(channel.id, ChatMembersInput(user_ids=[users[1].id]), db, users[0])
    assert error.value.status_code == 409


@pytest.mark.parametrize('channel_type', ['project', 'topic'])
def test_all_group_transfer_survives_member_and_channel_sync(workspace, channel_type):
    from backend.app.chat_api import ensure_project_chat_channel
    db, project, users = workspace
    channel = ensure_project_chat_channel(db, project.id, users[0]) if channel_type == 'project' else new_group(db, project, users, all_members=True)
    db.commit()
    transfer_chat_owner(channel.id, ChatOwnerInput(user_id=users[1].id), db, users[0])
    db.add(ProjectMember(project_id=project.id, user_id=users[3].id)); db.commit()
    for visitor in [users[0], users[1], users[3]]:
        list_project_chat_channels(project.id, db, visitor)
        members = list_chat_channel_members(channel.id, db, visitor)['data']
        assert [m['user_id'] for m in members if m['member_role'] == 'owner'] == [users[1].id]
    assert channel.created_by_user_id == users[0].id
    with pytest.raises(HTTPException) as error:
        transfer_chat_owner(channel.id, ChatOwnerInput(user_id=users[2].id), db, users[0])
    assert error.value.status_code == 403
    update_chat_settings(channel.id, ChatSettingsInput(title='转让后改名'), db, users[1])


def test_remove_member_revokes_access_and_can_readd_as_member(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    group_document(db, project, channel)
    remove_chat_member(channel.id, users[1].id, db, users[0])
    assert channel.id not in {row['id'] for row in list_project_chat_channels(project.id, db, users[1])['data']}
    for action in [lambda: list_chat_channel_members(channel.id, db, users[1]),
                   lambda: list_chat_files(channel.id, None, 50, db, users[1])]:
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 403
    events = db.scalars(select(ChatRealtimeOutbox)).all()
    assert any(event.method == 'unsubscribe' and event.payload['user'] == str(users[1].id) for event in events)
    assert any(event.method == 'publish' and event.payload['channel'].endswith(f'user_{users[1].id}') and event.payload['data']['type'] == 'chat.channel.updated' for event in events)
    add_chat_members(channel.id, ChatMembersInput(user_ids=[users[1].id]), db, users[0])
    assert next(m for m in list_chat_channel_members(channel.id, db, users[1])['data'] if m['user_id'] == users[1].id)['member_role'] == 'member'


def test_remove_requires_owner_and_disallows_self_and_all_group(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    for actor, target, status in [(users[1], users[0].id, 403), (users[0], users[0].id, 422), (users[0], users[3].id, 404)]:
        with pytest.raises(HTTPException) as error:
            remove_chat_member(channel.id, target, db, actor)
        assert error.value.status_code == status
    all_channel = new_group(db, project, users, title='全员群', all_members=True)
    with pytest.raises(HTTPException) as error:
        remove_chat_member(all_channel.id, users[1].id, db, users[0])
    assert error.value.status_code == 409


def test_owner_adds_members_once_and_notifies_new_member(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    add_chat_members(channel.id, ChatMembersInput(user_ids=[users[2].id, users[2].id]), db, users[0])
    add_chat_members(channel.id, ChatMembersInput(user_ids=[users[2].id]), db, users[0])
    members = list_chat_channel_members(channel.id, db, users[2])['data']
    assert len(members) == 3
    assert channel.id in {row['id'] for row in list_project_chat_channels(project.id, db, users[2])['data']}
    events = db.scalars(select(ChatRealtimeOutbox)).all()
    assert any(row.payload['data']['type'] == 'chat.channel.updated' and row.payload['channel'].endswith(f'user_{users[2].id}') for row in events)


def test_members_and_project_outsiders_cannot_manage_group(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    with pytest.raises(HTTPException) as error:
        add_chat_members(channel.id, ChatMembersInput(user_ids=[users[2].id]), db, users[1])
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        add_chat_members(channel.id, ChatMembersInput(user_ids=[users[3].id]), db, users[0])
    assert error.value.status_code == 422
    assert len(list_chat_channel_members(channel.id, db, users[0])['data']) == 2


def test_transfer_changes_authority_without_changing_creator(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    transfer_chat_owner(channel.id, ChatOwnerInput(user_id=users[1].id), db, users[0])
    assert channel.created_by_user_id == users[0].id
    owners = db.scalars(select(ChatChannelMember).where(ChatChannelMember.channel_id == channel.id, ChatChannelMember.member_role == 'owner')).all()
    assert [owner.user_id for owner in owners] == [users[1].id]
    with pytest.raises(HTTPException) as error:
        update_chat_settings(channel.id, ChatSettingsInput(title='原群主不能修改'), db, users[0])
    assert error.value.status_code == 403
    update_chat_settings(channel.id, ChatSettingsInput(title='新群主已修改'), db, users[1])
    assert channel.title == '新群主已修改'


def test_transfer_rejects_self_nonmember_and_departed_project_member(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    for target in [users[0].id, users[2].id]:
        with pytest.raises(HTTPException) as error:
            transfer_chat_owner(channel.id, ChatOwnerInput(user_id=target), db, users[0])
        assert error.value.status_code == 422
    project_member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == users[1].id))
    db.delete(project_member); db.commit()
    with pytest.raises(HTTPException) as error:
        transfer_chat_owner(channel.id, ChatOwnerInput(user_id=users[1].id), db, users[0])
    assert error.value.status_code == 422


def test_renaming_rejects_duplicates_and_keeps_existing_group_files(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    _, file, _ = group_document(db, project, channel)
    new_group(db, project, users, title='另一群')
    with pytest.raises(HTTPException) as error:
        update_chat_settings(channel.id, ChatSettingsInput(title='另一群'), db, users[0])
    assert error.value.status_code == 409
    update_chat_settings(channel.id, ChatSettingsInput(title='更新后的群名'), db, users[0])
    assert list_chat_files(channel.id, None, 50, db, users[1])['data']['items'][0]['knowledge_id'] == file.external_id


def test_group_file_list_is_scoped_and_rejects_nonmembers(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    _, file, _ = group_document(db, project, channel)
    page = list_chat_files(channel.id, None, 50, db, users[1])['data']
    assert [row['knowledge_id'] for row in page['items']] == [file.external_id]
    assert page['next_cursor'] is None
    with pytest.raises(HTTPException) as error:
        list_chat_files(channel.id, None, 50, db, users[2])
    assert error.value.status_code == 403


def test_file_list_pagination_does_not_repeat_rows(workspace):
    from backend.app.engineering_document_catalog import add_pending_local_file
    db, project, users = workspace
    channel = new_group(db, project, users)
    folder, _, _ = group_document(db, project, channel)
    for i in range(2):
        add_pending_local_file(db, project.id, 'kb', folder.folder_path, {'knowledge_id': f'more-{i}'}, fallback_name=f'文件{i}.pdf')
    db.commit()
    first = list_chat_files(channel.id, None, 2, db, users[1])['data']
    second = list_chat_files(channel.id, first['next_cursor'], 2, db, users[1])['data']
    assert len(first['items']) == 2 and len(second['items']) == 1
    assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}
    assert second['next_cursor'] is None


def test_title_check_includes_groups_not_joined_and_normalizes_names(workspace):
    db, project, users = workspace
    new_group(db, project, users, title='Team A')
    result = check_chat_title(project.id, ChatTitleCheckInput(title='  TEAM A  '), db, users[2])
    assert result['data'] == {'available': False}
    assert check_chat_title(project.id, ChatTitleCheckInput(title='新名称'), db, users[2])['data']['available']


def test_title_check_is_project_scoped_and_requires_membership(workspace):
    from backend.app.models import Project
    db, project, users = workspace
    new_group(db, project, users)
    another = Project(name='另一工程'); db.add(another); db.commit()
    assert check_chat_title(another.id, ChatTitleCheckInput(title='资料组'), db, users[0])['data']['available']
    with pytest.raises(HTTPException) as error:
        check_chat_title(project.id, ChatTitleCheckInput(title='资料组'), db, users[3])
    assert error.value.status_code == 403


def test_title_check_excludes_only_the_owned_group_being_renamed(workspace):
    db, project, users = workspace
    channel = new_group(db, project, users)
    payload = ChatTitleCheckInput(title=channel.title, exclude_channel_id=channel.id)
    assert check_chat_title(project.id, payload, db, users[0])['data']['available']
    with pytest.raises(HTTPException) as error:
        check_chat_title(project.id, payload, db, users[1])
    assert error.value.status_code == 403
    new_group(db, project, users, title='另一群')
    assert not check_chat_title(project.id, ChatTitleCheckInput(title='另一群', exclude_channel_id=channel.id), db, users[0])['data']['available']


@pytest.mark.parametrize('channel_type', ['project', 'topic'])
def test_all_group_owner_can_rename_with_validation_and_keep_auto_sync(workspace, channel_type):
    from backend.app.chat_api import ensure_project_chat_channel
    db, project, users = workspace
    channel = ensure_project_chat_channel(db, project.id, users[0]) if channel_type == 'project' else new_group(db, project, users, all_members=True)
    db.commit()
    original_title = channel.title
    assert check_chat_title(project.id, ChatTitleCheckInput(title=original_title, exclude_channel_id=channel.id), db, users[0])['data']['available']
    with pytest.raises(HTTPException) as error:
        update_chat_settings(channel.id, ChatSettingsInput(title='普通成员不能改'), db, users[1])
    assert error.value.status_code == 403
    result = update_chat_settings(channel.id, ChatSettingsInput(title='全员协作新群名'), db, users[0])
    assert result['data']['title'] == '全员协作新群名'
    assert result['data']['all_members'] is True
    assert channel.channel_type == channel_type
    assert check_chat_title(project.id, ChatTitleCheckInput(title=original_title), db, users[0])['data']['available']
    db.add(ProjectMember(project_id=project.id, user_id=users[3].id)); db.commit()
    assert users[3].id in {row['user_id'] for row in list_chat_channel_members(channel.id, db, users[0])['data']}
    listed = list_project_chat_channels(project.id, db, users[0])['data']
    assert next(row for row in listed if row['id'] == channel.id)['title'] == '全员协作新群名'
    new_group(db, project, users, title='已占用名称')
    with pytest.raises(HTTPException) as error:
        update_chat_settings(channel.id, ChatSettingsInput(title='已占用名称'), db, users[0])
    assert error.value.status_code == 409
