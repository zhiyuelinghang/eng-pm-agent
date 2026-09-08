"""Trusted, read-only chat evidence transport. The database journals changes."""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select, text, exists, func, or_

from .chat_membership_policy import chat_auto_sync
from .models import ChatChannel, ChatChannelMember, ChatMessage, ProjectMember


def message_hash(message):
    value = [message.id, message.content, message.sender_type, message.sender_user_id,
             message.sender_agent_id, str(message.edited_at), str(message.deleted_at)]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def channel_policy(db, channel):
    project_users = set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == channel.project_id)))
    # Explicit automatic membership is authoritative; a historical type/name is insufficient.
    full = chat_auto_sync(channel)
    members = project_users if full else project_users & set(db.scalars(select(ChatChannelMember.user_id).where(
        ChatChannelMember.channel_id == channel.id, ChatChannelMember.left_at.is_(None))))
    return full, sorted(members)


def visible_channels(db, project_id, user_id):
    shared = func.coalesce(ChatChannel.auto_sync_members, ChatChannel.channel_type.in_(['project','topic']))
    member = exists(select(ChatChannelMember.id).where(ChatChannelMember.channel_id==ChatChannel.id,
        ChatChannelMember.user_id==user_id, ChatChannelMember.left_at.is_(None)))
    rows = db.execute(select(ChatChannel.id, shared.label('shared')).where(ChatChannel.project_id==project_id,
        ChatChannel.archived_at.is_(None), or_(shared, member))).all()
    return [str(row.id) for row in rows], [str(row.id) for row in rows if row.shared]


def list_sources(db, after_channel=0, limit=100):
    return [dict(r) for r in db.execute(text('''SELECT s.channel_id,s.revision,s.policy_revision,s.changed_at,
        c.project_id,c.title,c.archived_at FROM group_learning_source_clocks s
        LEFT JOIN chat_channels c ON c.id=s.channel_id WHERE s.channel_id>:after
        ORDER BY s.channel_id LIMIT :limit'''), {'after': after_channel, 'limit': limit}).mappings()]


def source_changes(db, channel_id, after_revision):
    return [dict(row) for row in db.execute(text('''SELECT revision,message_id,kind FROM group_learning_source_changes
        WHERE channel_id=:id AND revision>:after ORDER BY revision LIMIT 1000'''),
        {'id': channel_id, 'after': after_revision}).mappings()]


def read_source(db, channel_id, after_revision=0, limit=50):
    channel = db.get(ChatChannel, channel_id)
    if channel is None or channel.archived_at is not None:
        raise HTTPException(404, '群聊已删除或归档')
    clock = db.execute(text('SELECT * FROM group_learning_source_clocks WHERE channel_id=:id'), {'id': channel_id}).mappings().first()
    if not clock:
        raise HTTPException(404, '群聊暂无待学习消息')
    full, members = channel_policy(db, channel)
    changes = db.execute(text('''SELECT * FROM group_learning_source_changes
        WHERE channel_id=:id AND revision>:after ORDER BY revision LIMIT :limit'''),
        {'id': channel_id, 'after': after_revision, 'limit': limit}).mappings().all()
    context = db.execute(text('''SELECT * FROM group_learning_source_changes WHERE channel_id=:id
        AND revision<=:after AND message_id IS NOT NULL ORDER BY revision DESC LIMIT 10'''),
        {'id': channel_id, 'after': after_revision}).mappings().all()
    messages = []
    seen = set()
    for change in [*reversed(changes), *context]:
        mid = change['message_id']
        if mid is None or mid in seen:
            continue
        seen.add(mid)
        latest = db.execute(text('''SELECT max(revision) FROM group_learning_source_changes
            WHERE channel_id=:cid AND message_id=:mid'''), {'cid':channel_id, 'mid':mid}).scalar()
        batch_end = changes[-1]['revision'] if changes else after_revision
        if latest is not None and latest > batch_end:
            # A later edit owns this message. Do not summarize its current text in two intervals.
            continue
        message = db.get(ChatMessage, mid)
        audience = change['audience']
        if isinstance(audience, str):
            audience = json.loads(audience)
        # A later membership expansion cannot grant historical evidence new recipients.
        recipients = sorted(set(members) & set(audience))
        if message is None or message.deleted_at is not None:
            messages.append({'id': str(mid), 'deleted': True})
            continue
        messages.append({'id': str(mid), 'text': message.content, 'hash': message_hash(message),
            'context_only': change['revision'] <= after_revision,
            'kind': message.sender_type, 'user_id': str(message.sender_user_id or ''),
            'agent_id': message.sender_agent_id, 'created_at': message.created_at.isoformat(),
            'audience': [str(uid) for uid in recipients],
            'project_shared': full and change['project_shared'],
            'outcome': 'assistant_claim' if message.sender_type == 'agent' else 'observed'})
    return {'channel_id': channel_id, 'project_id': str(channel.project_id), 'title': channel.title,
        'full_project': full, 'members': [str(uid) for uid in members],
        'policy_revision': clock['policy_revision'], 'observed_revision': clock['revision'],
        'from_revision': after_revision, 'to_revision': changes[-1]['revision'] if changes else after_revision,
        'changed_at': clock['changed_at'], 'messages': list(reversed(messages)),
        'changed_message_ids': sorted({c['message_id'] for c in changes if c['message_id'] is not None}),
        'has_policy_change': any(c['kind'] == 'policy' for c in changes)}


def validate_source(db, snapshot):
    channel = db.get(ChatChannel, int(snapshot['channel_id']))
    if channel is None or channel.archived_at is not None:
        raise HTTPException(403, '群聊来源已失效')
    full, members = channel_policy(db, channel)
    clock = db.execute(text('SELECT policy_revision FROM group_learning_source_clocks WHERE channel_id=:id'),
        {'id': channel.id}).mappings().first()
    if not clock or clock['policy_revision'] != snapshot['policy_revision'] or full != snapshot['full_project'] or [str(i) for i in members] != snapshot['members']:
        raise HTTPException(409, '群成员或可见范围已改变，请重新读取本批消息')
    for item in snapshot['messages']:
        if item.get('deleted'):
            continue
        message = db.get(ChatMessage, int(item['id']))
        if not message or message.deleted_at is not None or message_hash(message) != item['hash']:
            raise HTTPException(409, '来源消息已修改或撤回，请重新读取本批消息')
    return {'valid': True}
