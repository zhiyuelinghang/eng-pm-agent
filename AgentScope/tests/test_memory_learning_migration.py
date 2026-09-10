"""Exercise the one-time source migration only inside an isolated test schema."""
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace

from test_memory_repository import repository, access, write
from test_learning_pipeline import candidate, event
from test_group_learning import snapshot, output
from utils.group_learning_schema import GROUP_LEARNING_DDL
from utils.group_learning_repository import GroupLearningRepository
from utils.learning_repository import LearningRepository


def test_migration_keeps_explicit_and_group_memory_and_archives_untraceable_lessons(repository):
    explicit = write(repository,key='profile.name')['memory']['id']
    historical = candidate(repository)
    pending = event(repository)
    with repository._connection() as conn:
        conn.execute(GROUP_LEARNING_DDL)
    groups = GroupLearningRepository(repository)
    source = snapshot()
    groups.observe('t',dict(channel_id=10,project_id='p',title='工程讨论群',revision=1))
    groups.enqueue('t',source,config_owner='owner',daily_limit=100)
    group_job = groups.claim('t')
    group_result = groups.complete(group_job,output(memory_type='experience',conditions='有附件清单',limitations='不能代替专业检查'))
    group_memory = group_result['candidates'][0]['memory_id']
    with repository._connection() as conn:
        conn.execute("UPDATE learning_events SET source_type='interaction',agent_id='main',provenance='{}' WHERE source_type='group'")
        conn.execute("UPDATE learning_events SET access_snapshot=(access_snapshot-'learning_enabled') || '{\"learning_capture\":true,\"learning_process\":true}'::jsonb")
    location = Path(__file__).resolve().parents[2] / 'backend/alembic/versions/fc62e708b193_统一记忆运行与系统学习来源.py'
    spec = importlib.util.spec_from_file_location('memory_source_migration',location)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with repository._connection() as conn:
        schema = conn.execute('SELECT current_schema() AS schema').fetchone()['schema']
        assert re.fullmatch(r'memory_test_[a-f0-9]{32}',schema)
        migration.op = SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='postgresql')),
            execute=lambda statement:conn.execute(statement.replace('memory.',schema+'.')))
        migration.upgrade()
    manager = access(management=True)
    old = repository.get(manager,historical)
    assert old['status'] == 'inactive' and old['learning']['validation_state'] == 'source_provenance_missing'
    assert len(repository.history(manager,historical)) == 2
    assert repository.get(manager,explicit)['status'] == 'active'
    assert repository.get(manager,group_memory)['status'] == 'active'
    with repository._connection() as conn:
        assert conn.execute('SELECT state FROM learning_jobs WHERE event_id=%s',(pending['event_id'],)).fetchone()['state'] == 'cancelled'
        group = conn.execute("SELECT * FROM learning_events WHERE source_type='group'").fetchone()
        assert group['agent_id'] == '' and group['provenance']['batch_id'] == str(group_job['id'])
        assert 'learning_capture' not in group['access_snapshot'] and 'learning_process' not in group['access_snapshot']
        assert group['access_snapshot']['learning_enabled'] is True
        assert conn.execute("SELECT count(*) AS n FROM memory_runs").fetchone()['n'] == 0
        assert conn.execute("SELECT count(*) AS n FROM business_learning_cursors").fetchone()['n'] == 0
