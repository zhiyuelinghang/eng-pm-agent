"""Real PostgreSQL test: disposable schemas, no application rows or notifications."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.db import Base, engine as database_engine
from backend.app.models import BusinessLearningSource, Project, ProjectMember, User
from backend.app.business_learning_sources import record_task_event
from backend.app.task_engine_gateway import transaction_engine
from task_engine.domain.models import Assignee, Site, StepSpec, TaskFlow
from task_engine.engine import TaskEngine
from task_engine.store.postgres import PostgresStore


@pytest.fixture
def isolated_postgres():
    if database_engine.dialect.name != 'postgresql':
        pytest.skip('requires local PostgreSQL')
    suffix = uuid4().hex[:12]
    business_schema, task_schema = f'test_learning_{suffix}_b', f'test_learning_{suffix}_t'
    migration_path = Path(__file__).parents[1] / 'alembic/versions/9d7b31a4c2e8_建立任务引擎_postgresql_存储.py'
    spec = spec_from_file_location('isolated_task_tables', migration_path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.SCHEMA = task_schema
    try:
        with database_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{business_schema}"'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        local = database_engine.execution_options(schema_translate_map={None: business_schema})
        Base.metadata.create_all(local)
        yield local, task_schema
    finally:
        # Only the two freshly generated test schemas can be removed.
        for schema in (business_schema, task_schema):
            assert re.fullmatch(r'test_learning_[a-f0-9]{12}_[bt]', schema)
        with database_engine.begin() as connection:
            for schema in (business_schema, task_schema):
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_task_and_learning_source_roll_back_together(isolated_postgres):
    engine, task_schema = isolated_postgres
    standalone = TaskEngine(store=PostgresStore(engine, schema=task_schema))
    with Session(engine) as db:
        user = User(username='atomic-test', real_name='测试', role='user', password_hash='test', identity_card_no='atomic-test')
        project = Project(name='事务测试')
        db.add_all([user, project])
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=user.id))
        db.commit()
        flow = TaskFlow(title='隔离事务任务', site=Site('site', '测试工点'),
            confirmer=Assignee(str(user.id), '测试'),
            steps=(StepSpec(name='检查', assignee=Assignee(str(user.id), '测试')),),
            scope={'project_id': project.id})
        bound = transaction_engine(db, standalone)
        task = bound.dispatch(flow, actor=str(user.id))
        record_task_event(db, task, user.id, 'task_published')
        db.flush()
        assert bound.get_task(task.id) is not None
        # Separate connection sees neither uncommitted task nor event.
        assert standalone.get_task(task.id) is None
        with Session(engine) as observer:
            assert list(observer.scalars(select(BusinessLearningSource))) == []
        db.rollback()
        assert standalone.get_task(task.id) is None
        assert standalone.get_flow(flow.id) is None
        assert list(db.scalars(select(BusinessLearningSource))) == []
        assert standalone.store.connection is None


def test_task_and_source_commit_and_acceptance_rollback_together(isolated_postgres):
    engine, task_schema = isolated_postgres
    standalone = TaskEngine(store=PostgresStore(engine, schema=task_schema))
    with Session(engine) as db:
        user = User(username='commit-test', real_name='测试', role='user', password_hash='test', identity_card_no='commit-test')
        project = Project(name='提交测试')
        db.add_all([user, project])
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=user.id))
        db.commit()
        flow = TaskFlow(title='隔离提交任务', site=Site('site', '测试工点'), confirmer=Assignee(str(user.id), '测试'),
            steps=(StepSpec(name='检查', assignee=Assignee(str(user.id), '测试')),), scope={'project_id': project.id})
        task = transaction_engine(db, standalone).dispatch(flow, actor=str(user.id))
        record_task_event(db, task, user.id, 'task_published')
        db.commit()
        assert standalone.get_task(task.id) is not None
        assert len(list(db.scalars(select(BusinessLearningSource)))) == 1
        bound = transaction_engine(db, standalone)
        bound.complete_step(task.id, 0, actor=str(user.id))
        accepted = bound.accept(task.id, actor=str(user.id))
        record_task_event(db, accepted, user.id, 'task_accepted')
        db.flush()
        assert str(bound.get_task(task.id).state) == 'done'
        db.rollback()
        assert str(standalone.get_task(task.id).state) != 'done'
        assert len(list(db.scalars(select(BusinessLearningSource)))) == 1
