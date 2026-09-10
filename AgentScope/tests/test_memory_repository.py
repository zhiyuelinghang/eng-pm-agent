"""Real PostgreSQL invariants for the authoritative three-drawer store.

Run with DOBBY_MEMORY_TEST_DATABASE_URL set. Every test uses a disposable,
randomly named schema; existing project tables and memories are untouched.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import re
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg.conninfo import make_conninfo
import pytest

from utils.memory_repository import MemoryAccess, MemoryError, MemoryRepository, MemoryWrite
from utils.memory_schema import MEMORY_DDL
from utils.learning_schema import LEARNING_DDL
from utils.memory_run_repository import MEMORY_RUN_DDL


@pytest.fixture
def repository(monkeypatch):
    url = os.environ.get("DOBBY_MEMORY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DOBBY_MEMORY_TEST_DATABASE_URL for isolated PostgreSQL integration tests")
    schema = "memory_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {},public").format(sql.Identifier(schema)))
        conn.execute(MEMORY_DDL)
        conn.execute(LEARNING_DDL)
        conn.execute(MEMORY_RUN_DDL)
        # The publication guard must read the actual authoritative row in the
        # same test database, never the developer's application settings.
        conn.execute('CREATE TABLE platform_settings (user_id text PRIMARY KEY, payload json NOT NULL)')
        settings = {'learning_enabled':True, 'learning_interactions_enabled':True,
            'learning_business_events_enabled':True, 'group_learning_enabled':True,
            'learning_model_config':{'type':'custom_openai_credential', 'credential_id':'test',
                'model':'test', 'parameters':{}}, 'compression_model_config':None}
        for owner in ('owner', 'o', 'default'):
            conn.execute('INSERT INTO platform_settings(user_id,payload) VALUES(%s,%s)',
                (owner, Jsonb({'data':{'memory_settings':settings, 'memory_settings_revision':0}})))
    monkeypatch.setenv('AGENTSCOPE_DATABASE_SCHEMA', schema)
    repo = MemoryRepository(make_conninfo(url, options=f"-csearch_path={schema},public"))
    try:
        yield repo
    finally:
        repo.close()
        assert re.fullmatch(r"memory_test_[a-f0-9]{32}", schema)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def access(user="a", project="p", tenant="t", **kwargs):
    return MemoryAccess(tenant,user,project,project_read=True,project_write=True,**kwargs)


def write(repo, actor=None, scope="user", content="雷淦文", key=None, request=None, **kwargs):
    return repo.write(actor or access(), [MemoryWrite(scope_type=scope,content=content,fact_key=key,**kwargs)],
                      request_id=request or str(uuid4()),source={"message_id":"source-1"})[0]


def test_save_requires_no_model_and_retries_are_idempotent(repository):
    a = write(repository,key="profile.name",request="one")
    b = write(repository,key="profile.name",request="one")
    assert a == b
    assert a["memory"]["index_status"] == "pending"
    assert repository.search(access(),fact_key="profile.name")[0]["content"] == "雷淦文"
    assert repository.list(access())["total"] == 1
    with pytest.raises(MemoryError,match="请求标识"):
        write(repository,key="profile.name",content="不同",request="one")


def test_pool_replaces_disconnected_idle_connection_before_next_write(repository):
    with repository._connection() as conn:
        pid=conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
        schema=conn.execute('SELECT current_schema() AS schema').fetchone()['schema']
        assert re.fullmatch(r'memory_test_[a-f0-9]{32}',schema)
    # Terminate only the test-owned idle connection, never the database server.
    with psycopg.connect(repository.pool.conninfo) as control:
        assert control.execute('SELECT pg_terminate_backend(%s)',(pid,)).fetchone()[0]
    assert write(repository,key='profile.name')['memory']['content']=='雷淦文'
    assert repository.search(access(),fact_key='profile.name')


def test_three_drawers_and_identity_isolation(repository):
    for scope in ("user","user_project","project"):
        write(repository,scope=scope,content=scope)
    assert len(repository.search(access())) == 3
    assert [r["scope_type"] for r in repository.search(access(user="b"))] == ["project"]
    assert [r["scope_type"] for r in repository.search(access(project="other"))] == ["user"]
    assert repository.search(access(tenant="other")) == []
    assert repository.search(access(identity_type="management_user")) == []
    assert [r["scope_type"] for r in repository.search(access(private=False))] == ["project"]
    with pytest.raises(MemoryError):
        write(repository,actor=access(private=False),scope="user")


def test_shared_write_permission_and_atomic_batch(repository):
    member = MemoryAccess("t","a","p",project_read=True)
    with pytest.raises(MemoryError):
        repository.write(member,[MemoryWrite(scope_type="user",content="private"),MemoryWrite(scope_type="project",content="shared")],request_id="batch",source={})
    assert repository.list(access())["total"] == 0


def test_fact_correction_requires_version_and_retains_history(repository):
    original = write(repository,key="profile.name")["memory"]
    with pytest.raises(MemoryError,match="已有版本"):
        write(repository,key="profile.name",content="新名字")
    corrected = write(repository,key="profile.name",content="新名字",expected_version=1)["memory"]
    assert corrected["id"] == original["id"]
    assert corrected["version"] == 2
    history = repository.history(access(management=True),corrected["id"])
    assert [h["snapshot"]["content"] for h in history] == ["新名字","雷淦文"]
    assert repository.search(access(),fact_key="profile.name")[0]["content"] == "新名字"


def test_concurrent_same_request_creates_one_record(repository):
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _:write(repository,request="concurrent"),range(4)))
    assert len({r["memory"]["id"] for r in results}) == 1
    assert repository.list(access())["total"] == 1


def test_stale_worker_cannot_restore_changed_or_deleted_content(repository):
    original = write(repository,key="profile.name")["memory"]
    old_job = repository.claim_index_job()
    corrected = write(repository,key="profile.name",content="新名字",expected_version=1)["memory"]
    assert repository.finish_index_job(old_job,vector=[0.1]*1024) is False
    job = repository.claim_index_job()
    assert job["version"] == 2
    assert repository.finish_index_job(job,vector=[0.1]*1024)
    repository.manage(access(management=True),corrected["id"],expected_version=2,status="deleted")
    assert repository.search(access(),fact_key="profile.name") == []
    assert repository.finish_index_job(job,vector=[0.1]*1024) is False
    assert repository.get(access(management=True),original["id"])["index_status"] == "deleted"


def test_publication_is_explicit_and_changes_visibility(repository):
    row = write(repository,scope="user_project")["memory"]
    with pytest.raises(MemoryError,match="确认发布"):
        repository.manage(access(management=True),row["id"],expected_version=1,scope_type="project")
    repository.manage(access(management=True),row["id"],expected_version=1,scope_type="project",publish=True)
    assert repository.search(access(user="b"))[0]["content"] == "雷淦文"
    with pytest.raises(MemoryError):
        repository.history(access(user="b"),row["id"])


def test_failed_index_preserves_content_and_can_be_retried(repository):
    row = write(repository,key="profile.name")["memory"]
    job = repository.claim_index_job()
    assert repository.finish_index_job(job,error_code="EmbeddingUnavailable")
    assert repository.search(access(),fact_key="profile.name")[0]["content"] == "雷淦文"
    repository.retry_index(access(management=True),row["id"])
    next_job = repository.claim_index_job()
    assert next_job and next_job["lease_id"] != job["lease_id"]
    assert repository.finish_index_job(job,vector=[0.1]*1024) is False


def test_expired_index_lease_is_recovered_and_old_worker_is_rejected(repository):
    write(repository)
    abandoned = repository.claim_index_job()
    with repository._connection() as conn:
        conn.execute("UPDATE memory_index_jobs SET lease_until=now()-interval '1 second'")
    recovered = repository.claim_index_job()
    assert recovered["lease_id"] != abandoned["lease_id"]
    assert recovered["attempts"] == 2
    assert repository.finish_index_job(abandoned,vector=[0.1]*1024) is False
    assert repository.finish_index_job(recovered,vector=[0.1]*1024)


def test_forget_checks_owner_version_and_immediately_stops_recall(repository):
    row = write(repository,key="profile.name")["memory"]
    with pytest.raises(MemoryError):
        repository.forget(access(user="b"),row["id"],1)
    with pytest.raises(MemoryError,match="版本"):
        repository.forget(access(),row["id"],2)
    assert repository.forget(access(),row["id"],1)["status"] == "deleted"
    assert repository.forget(access(),row["id"],1)["status"] == "unchanged"
    assert repository.profile(access()) == []
    assert repository.search(access(),fact_key="profile.name") == []
    assert repository.history(access(management=True),row["id"])[0]["action"] == "forgotten"


def test_retry_after_later_deletion_does_not_report_obsolete_success(repository):
    row = write(repository,request="old-request")["memory"]
    repository.forget(access(),row["id"],1)
    with pytest.raises(MemoryError) as error:
        write(repository,request="old-request")
    assert error.value.code == "request_superseded"


def test_profiles_exclude_candidates_and_public_sessions(repository):
    write(repository,key="preference.response_detail",content="简短")
    write(repository,scope="user_project",key="preference.response_detail",content="详细")
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        write(repository,key="profile.name",status="candidate")
    old=write(repository,key="profile.name")['memory']
    with repository._connection() as conn:
        conn.execute("UPDATE memory_records SET status='candidate' WHERE id=%s",(old['id'],))
    assert [r["content"] for r in repository.profile(access())] == ["详细"]
    assert [r["content"] for r in repository.profile(access(project='other'))] == ["简短"]
    assert repository.profile(access(user='other')) == []
    assert repository.profile(access(private=False)) == []


def test_published_fact_does_not_expose_private_source(repository):
    row = repository.write(access(),[MemoryWrite(scope_type="user_project",content="会议安排")],request_id="private-source",
        source={"messages":{"private-1":"仅供我个人使用的敏感上下文"},"session_id":"private-session"})[0]["memory"]
    repository.manage(access(management=True),row["id"],expected_version=1,scope_type="project",publish=True)
    public = repository.search(access(user="b"))[0]
    assert public["content"] == "会议安排"
    assert "messages" not in public["source"]
    assert "session_id" not in public["source"]
    assert repository.history(access(management=True),row["id"])[0]["snapshot"]["source"]["messages"]


def test_tool_saves_without_classifier_and_live_revocation_blocks_access(repository,monkeypatch):
    import asyncio,json
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agentscope.message import UserMsg
    from agentscope.app.memory._direct import ThreeDrawerMemoryMiddleware
    from agentscope.app.memory._runtime import MemoryRuntime
    from agentscope.app.memory import _scope_router
    def forbidden(*args,**kwargs):
        raise AssertionError("Saving must not call a classifier")
    monkeypatch.setattr(_scope_router,"route_memory_content",forbidden)
    allowed = True
    async def resolve():
        if not allowed:
            raise MemoryError("revoked","项目权限已撤销。",status=403)
        return access()
    from memory_run_test_support import MemoryRunHarness
    harness = MemoryRunHarness(repository)
    runtime = MagicMock()
    middleware = ThreeDrawerMemoryMiddleware(runtime,MemoryRuntime().scope(project_id="p",platform_user_id="a",agent_id="agent",session_id="s"),{},access_resolver=resolve,repository=repository,controller=harness.controller())
    middleware.active_agent = SimpleNamespace(state=SimpleNamespace(context=[UserMsg("user","我叫雷淦文")]))
    async def run():
        nonlocal allowed
        await harness.start("我叫雷淦文")
        add,search,*_others = await middleware.list_tools()
        result = json.loads((await add.call(items=[{"scope_type":"user","fact_key":"profile.name","content":"雷淦文"}])).content[0].text)
        assert result["status"] == "saved"
        assert result["results"][0]["memory"]["index_status"] == "pending"
        assert json.loads((await search.call(fact_key="profile.name")).content[0].text)["results"][0]["content"] == "雷淦文"
        allowed = False
        assert json.loads((await search.call(fact_key="profile.name")).content[0].text)["error_code"] == "revoked"
    asyncio.run(run())


def test_management_api_allows_only_read_delete_and_checks_service_boundary(repository,monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agentscope.app._router import _memory_management as api
    from agentscope.app._auth import AgentScopePrincipal
    from agentscope.app.deps import get_current_principal
    monkeypatch.setattr(api,"get_memory_repository",lambda:repository)
    monkeypatch.setattr(api,"get_memory_runtime",lambda:SimpleNamespace(tenant_id="t"))
    async def catalog():
        return {"users":[{"user_id":"a","username":"a","display_name":"A","role":"user"}],
                "projects":[{"project_id":"p","project_name":"P"}],"memberships":[{"user_id":"a","project_id":"p"}]}
    app = FastAPI()
    app.state.database_interaction_manager = SimpleNamespace(memory_identity_catalog=catalog)
    app.include_router(api.memory_management_router)
    app.dependency_overrides[get_current_principal] = lambda:AgentScopePrincipal(kind="management",subject="admin")
    row = write(repository,key="profile.name")["memory"]
    with TestClient(app) as client:
        listed = client.get('/memory-management/memories',params={"scope_type":"user"})
        assert listed.status_code == 200,listed.text
        assert listed.json()["total"] == 1
        url = f"/memory-management/memories/{row['id']}"
        updated = client.patch(url,json={"expected_version":1,"content":"修正名字"})
        assert updated.status_code == 409,updated.text
        assert repository.search(access(),fact_key="profile.name")[0]["content"] == "雷淦文"
        assert client.patch(url,json={"expected_version":1,"content":"过时修改"}).status_code == 409
        assert len(client.get(url+'/history').json()) == 1
        assert client.delete(url,params={"expected_version":1}).status_code == 204
        assert repository.search(access(),fact_key="profile.name") == []
        app.dependency_overrides[get_current_principal] = lambda:AgentScopePrincipal(kind="service",subject="service")
        assert client.get('/memory-management/memories').status_code == 403


def test_migration_is_idempotent_and_never_infers_project_publication(repository):
    from psycopg.types.json import Jsonb
    from utils.memory_migration import migrate_legacy_memories
    legacy = uuid4()
    unknown = uuid4()
    with repository._connection() as conn:
        conn.execute('CREATE TABLE legacy_memories (id uuid PRIMARY KEY,payload jsonb)')
        conn.execute('INSERT INTO legacy_memories VALUES (%s,%s),(%s,%s)',(legacy,Jsonb({
            "scope_version":"2","tenant_id":"t","identity_type":"business_user","scope_type":"user_project",
            "platform_user_id":"a","project_id":"p","data":"原个人项目记忆"}),unknown,Jsonb({"data":"不明确的旧项目池","user_id":"project_p"})))
    preview = migrate_legacy_memories(repository,tenant_id="t",collection="legacy_memories")
    assert preview["imported"] == 1 and preview["needs_review"] == 1
    assert repository.list(access())["total"] == 0
    migrate_legacy_memories(repository,tenant_id="t",collection="legacy_memories",apply=True)
    repeated = migrate_legacy_memories(repository,tenant_id="t",collection="legacy_memories",apply=True)
    assert repeated["already_imported"] == 1 and repeated["imported"] == 0
    assert repository.search(access())[0]["scope_type"] == "user_project"
    assert repository.search(access(user="b")) == []
    review = repository.legacy_reviews(access(management=True))[0]
    with pytest.raises(MemoryError,match="确认"):
        repository.resolve_legacy(access(management=True),review["legacy_id"],user_id="",project_id="p",scope_type="project",content="核实后的项目事实")
    resolved = repository.resolve_legacy(access(management=True),review["legacy_id"],user_id="a",project_id="p",scope_type="user_project",content="核实后的私人项目事实")
    assert resolved["source"]["kind"] == "legacy_assignment"
    assert repository.legacy_reviews(access(management=True)) == []
    assert repository.search(access(user="b")) == []


def test_failed_index_automatically_retries_after_hourly_cooldown(repository):
    mid=write(repository)['memory']['id']
    with repository._connection() as conn:
        conn.execute("UPDATE memory_index_jobs SET state='failed',attempts=5 WHERE memory_id=%s",(mid,))
    assert repository.claim_index_job() is None
    with repository._connection() as conn:
        conn.execute("UPDATE memory_index_jobs SET updated_at=now()-interval '2 hours' WHERE memory_id=%s",(mid,))
    job=repository.claim_index_job()
    assert str(job['memory_id'])==mid and job['attempts']==6
    assert repository.finish_index_job(job,vector=[0.1]*1024)
    assert repository.get(access(),mid)['index_status']=='ready'
