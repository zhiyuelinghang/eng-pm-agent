"""Gateway attribution and live visibility checks, without an LLM or network."""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from test_group_agent_authorization import scoped_project
from backend.app.models import ChatChannel, ChatChannelMember, ChatMessage
from backend.app.group_learning_source import read_source, validate_source, channel_policy


def test_gateway_preserves_historical_audience_and_checks_edits(scoped_project):
    db, project, users = scoped_project
    channel = ChatChannel(project_id=project.id, title='名字叫全体但实际上是子群', channel_type='project', auto_sync_members=False)
    db.add(channel)
    db.flush()
    db.add_all([ChatChannelMember(channel_id=channel.id,user_id=u.id) for u in users])
    message = ChatMessage(channel_id=channel.id,sender_type='user',sender_user_id=users[0].id,content='以后称呼我雷总')
    db.add(message)
    db.flush()
    db.execute(text('''CREATE TABLE group_learning_source_clocks(channel_id integer primary key,revision integer,policy_revision integer,changed_at text)'''))
    db.execute(text('''CREATE TABLE group_learning_source_changes(channel_id integer,revision integer,message_id integer,kind text,audience text,project_shared boolean)'''))
    db.execute(text("INSERT INTO group_learning_source_clocks VALUES(:cid,1,0,'2026-09-08T01:00:00+00:00')"), {'cid':channel.id})
    db.execute(text("INSERT INTO group_learning_source_changes VALUES(:cid,1,:mid,'message',:aud,false)"),
        {'cid':channel.id,'mid':message.id,'aud':json.dumps([users[0].id])})
    db.commit()
    data = read_source(db, channel.id)
    assert data['full_project'] is False
    assert data['messages'][0]['user_id'] == str(users[0].id)
    assert data['messages'][0]['audience'] == [str(users[0].id)]
    assert validate_source(db, data) == {'valid':True}
    message.content = '不要用旧称呼'
    db.commit()
    with pytest.raises(HTTPException) as changed:
        validate_source(db, data)
    assert changed.value.status_code == 409
    channel.auto_sync_members = True
    db.commit()
    new = read_source(db, channel.id)
    assert new['full_project'] is True and not new['messages'][0]['project_shared']
    assert channel_policy(db, channel)[0] is True
