"""Exercise actual PostgreSQL triggers without touching platform or memory schemas."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from test_memory_repository import repository


def test_journal_is_transactional_and_records_edits_deletes_and_membership(repository):
    with repository._connection() as conn:
        schema = conn.execute('SELECT current_schema() AS name').fetchone()['name']
        conn.execute('''CREATE TABLE chat_channels(id integer PRIMARY KEY, project_id integer, channel_type text,
            auto_sync_members boolean, archived_at timestamptz, membership_revision integer DEFAULT 0);
            CREATE TABLE project_members(id integer PRIMARY KEY,project_id integer,user_id integer);
            CREATE TABLE chat_channel_members(id integer PRIMARY KEY,channel_id integer,user_id integer,left_at timestamptz);
            CREATE TABLE chat_messages(id integer PRIMARY KEY,channel_id integer,content text,edited_at timestamptz,deleted_at timestamptz);''')
    # Supply an isolated connection and redirect the migration's memory-qualified DDL.
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy.engine import URL
    values = conninfo_to_dict(repository.pool.conninfo)
    engine = create_engine(URL.create('postgresql+psycopg', username=values.get('user'), password=values.get('password'),
        host=values.get('host'), port=int(values.get('port',5432)), database=values.get('dbname')),
        connect_args={'options':f'-csearch_path={schema},public'})
    spec = importlib.util.spec_from_file_location('journal_migration', Path(__file__).resolve().parents[2] / 'backend/alembic/versions/e31f790abc42_群聊增量学习与来源变更日志.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        with engine.begin() as connection:
            module.op = SimpleNamespace(get_bind=lambda:connection, execute=lambda statement:connection.exec_driver_sql(statement.replace('memory.',f'{schema}.')))
            module.upgrade()
        with repository._connection() as conn:
            conn.execute("INSERT INTO chat_channels(id,project_id,channel_type,auto_sync_members) VALUES(1,1,'project',false)")
            conn.execute('INSERT INTO project_members(id,project_id,user_id) VALUES(1,1,1),(2,1,2),(3,1,3)')
            conn.execute('INSERT INTO chat_channel_members(id,channel_id,user_id) VALUES(1,1,1),(2,1,2)')
            conn.execute("INSERT INTO chat_messages(id,channel_id,content) VALUES(1,1,'确定周五验收')")
            first = conn.execute("SELECT * FROM group_learning_source_changes WHERE message_id=1 ORDER BY revision DESC LIMIT 1").fetchone()
            assert first['audience'] == [1,2] and first['project_shared'] is False
            conn.execute("UPDATE chat_messages SET content='改为周六验收',edited_at=now() WHERE id=1")
            conn.execute('UPDATE chat_channels SET auto_sync_members=true WHERE id=1')
            conn.execute("INSERT INTO chat_messages(id,channel_id,content) VALUES(2,1,'周六验收，全体已确认')")
            last = conn.execute('SELECT * FROM group_learning_source_changes WHERE message_id=2').fetchone()
            assert last['audience'] == [1,2,3] and last['project_shared'] is True
            conn.execute('DELETE FROM chat_messages WHERE id=1')
            assert conn.execute('SELECT count(*) AS n FROM group_learning_source_changes WHERE message_id=1').fetchone()['n'] == 3
            before = conn.execute('SELECT revision FROM group_learning_source_clocks WHERE channel_id=1').fetchone()['revision']
        try:
            with repository._connection() as conn:
                conn.execute("INSERT INTO chat_messages(id,channel_id,content) VALUES(3,1,'将回滚')")
                raise ValueError('rollback')
        except ValueError:
            pass
        with repository._connection() as conn:
            assert conn.execute('SELECT revision FROM group_learning_source_clocks WHERE channel_id=1').fetchone()['revision'] == before
            assert conn.execute('SELECT 1 FROM group_learning_source_changes WHERE message_id=3').fetchone() is None
    finally:
        engine.dispose()
