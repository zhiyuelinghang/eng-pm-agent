"""启动只装配服务；数据库结构必须通过单独审核的 SQL 更新。"""
import ast
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def startup_fixture():
    source = Path(__file__).resolve().parents[1] / 'app' / 'main.py'
    function = next(node for node in ast.parse(source.read_text(encoding='utf-8')).body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == 'lifespan')
    calls = []

    class Session:
        def __enter__(self):
            calls.append('session')
            return self

        def __exit__(self, *args):
            pass

    async def worker():
        await asyncio.Event().wait()

    client = Mock()
    client.cache_info.return_value = SimpleNamespace(currsize=0)
    namespace = dict(asynccontextmanager=asynccontextmanager, suppress=suppress,
        asyncio=asyncio, FastAPI=object,
        SessionLocal=Session, bootstrap_declarative_catalog=lambda db: calls.append('catalog'),
        seed_admin=lambda: calls.append('seed'), _tick_loop=worker,
        _notification_loop=worker, _agentscope_client=client)
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), namespace)
    return namespace['lifespan'], calls


def test_startup_serves_without_schema_upgrade_dependencies():
    lifespan, calls = startup_fixture()

    async def run():
        async with lifespan(None):
            assert calls == ['session', 'catalog', 'seed']
            calls.append('serving')

    asyncio.run(run())
    assert calls[-1] == 'serving'


def test_application_entry_does_not_import_migration_runners():
    source = Path(__file__).resolve().parents[1] / 'app' / 'main.py'
    imports = [node.module for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
               if isinstance(node, ast.ImportFrom)]
    assert not {'schema_migrations', 'alembic_runner', 'alembic'} & set(imports)
