"""Transactional memory records. No model calls occur in a write transaction.

The caller supplies server-resolved access. Scopes are checked again here so
tools, management APIs and background jobs share the same data invariants.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import re
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)
ScopeType = Literal["user", "user_project", "project"]


def learning_fingerprint(memory_type: str, content: str, detail: dict) -> str:
    value=[memory_type,content.strip(),str(detail.get('conditions','')).strip(),
           str(detail.get('limitations','')).strip(),detail.get('steps',[])]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class MemoryError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: ScopeType
    content: str = Field(min_length=1, max_length=16000)
    fact_key: str | None = Field(default=None, max_length=120, pattern=r"^[a-z][a-z0-9_.-]*$")
    memory_type: Literal["fact", "preference", "decision", "reference", "reflection", "experience", "skill"] = "fact"
    importance: float = Field(default=0.5, ge=0, le=1)
    memory_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    source_message_id: str | None = Field(default=None, max_length=255)
    status: Literal["active"] = "active"

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("记忆内容不能为空。")
        return value.strip()


@dataclass(frozen=True)
class MemoryAccess:
    tenant_id: str
    user_id: str
    project_id: str = ""
    identity_type: str = "business_user"
    actor_id: str = ""
    private: bool = True
    project_read: bool = False
    project_write: bool = False
    management: bool = False
    read_scopes: tuple[str, ...] = ("user", "user_project", "project")
    write_scopes: tuple[str, ...] = ("user", "user_project", "project")
    learning_capture: bool = True
    learning_process: bool = True
    learning_use: bool = True
    group_source_channels: tuple[str, ...] = ()
    group_shared_channels: tuple[str, ...] = ()

    @property
    def actor(self) -> str:
        return self.actor_id or f"{self.identity_type}:{self.user_id}"

    def target(self, scope: str, *, write: bool = False) -> tuple[str, str]:
        if scope not in (self.write_scopes if write else self.read_scopes):
            raise MemoryError("scope_disabled", "该智能体未启用此记忆抽屉。", status=403)
        if scope == "user" and self.private and self.user_id:
            return self.user_id, ""
        if scope == "user_project" and self.private and self.user_id and self.project_id and self.project_read:
            return self.user_id, self.project_id
        if scope == "project" and self.project_id and self.project_read and self.identity_type == "business_user":
            if not write or self.project_write:
                return "", self.project_id
        raise MemoryError("scope_forbidden", "当前身份或会话无权使用该记忆抽屉。", status=403)


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _public(row: dict) -> dict:
    return _json({key: value for key, value in row.items() if key != "embedding"})


def _visible(row: dict, access: MemoryAccess) -> dict:
    result = _public(row)
    if not access.management:
        # A published fact must not publish its original private conversation.
        result["source"] = {k:v for k,v in result.get("source",{}).items()
                            if k in {"kind", "message_id", "reference"}}
        result["learning"] = {k:v for k,v in result.get("learning",{}).items()
                              if k in {"conditions","limitations","steps","validation_state","review_due_at"}}
    return result


class MemoryRepository:
    def __init__(self, database_url: str):
        self.pool = ConnectionPool(
            conninfo=database_url, min_size=0, max_size=6, timeout=5,
            kwargs={"row_factory": dict_row, "connect_timeout": 5, "prepare_threshold": None},
            check=ConnectionPool.check_connection,
            open=False,
        )
        self.pool.open(wait=False)

    def close(self) -> None:
        self.pool.close()

    def _connection(self):
        return self.pool.connection(timeout=5)

    @staticmethod
    def _check_record(access: MemoryAccess, row: dict, *, write: bool = False) -> None:
        if row["tenant_id"] != access.tenant_id:
            raise MemoryError("not_found", "未找到该记忆。", status=404)
        if access.management:
            return
        user, project = access.target(row["scope_type"], write=write)
        if (row["platform_user_id"], row["project_id"], row["identity_type"]) != (user, project, access.identity_type):
            raise MemoryError("not_found", "未找到该记忆。", status=404)
        source = row.get('source') or {}
        if source.get('kind') == 'group_learning' and row['scope_type'] != 'user':
            allowed = access.group_shared_channels if row['scope_type'] == 'project' else access.group_source_channels
            if str(source.get('channel_id')) not in allowed:
                raise MemoryError('not_found', '当前无权访问该群聊来源记忆。', status=404)

    @staticmethod
    def _version(conn, row: dict, actor: str, action: str) -> None:
        conn.execute(
            "INSERT INTO memory_versions(memory_id, version, snapshot, action, actor_id) VALUES (%s,%s,%s,%s,%s)",
            (row["id"], row["version"], Jsonb(_public(row)), action, actor),
        )

    @staticmethod
    def _queue(conn, row: dict) -> None:
        conn.execute("""INSERT INTO memory_index_jobs(memory_id, version) VALUES (%s,%s)
            ON CONFLICT(memory_id) DO UPDATE SET version=excluded.version, state='pending',
            attempts=0, available_at=now(), lease_until=NULL, lease_id=NULL, error_code=NULL, updated_at=now()""",
            (row["id"], row["version"]))

    def write(self, access: MemoryAccess, items: list[MemoryWrite], *, request_id: str, source: dict) -> list[dict]:
        if not items or len(items) > 20 or not request_id or len(request_id) > 255:
            raise MemoryError("invalid_request", "一次保存需要 1–20 条记忆和有效的请求标识。")
        # Validate the entire batch before persisting anything.
        targets = [access.target(item.scope_type, write=True) for item in items]
        if any(item.memory_type in {'reflection','experience','skill'} for item in items):
            raise MemoryError('learning_pipeline_required','反思、经验和技能须通过学习流程生成候选并验证，不能直接作为事实保存。')
        payload_hash = hashlib.sha256(json.dumps(
            {"items": [i.model_dump(mode="json") for i in items], "targets": targets,
             "identity": access.identity_type, "source": source},
            sort_keys=True, ensure_ascii=False, default=str,
        ).encode()).hexdigest()
        with self._connection() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            # Serializes retries and modifications in one tenant, identity and owner.
            # Project writes from different users also take a drawer-level lock below.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"memory-request:{access.tenant_id}:{access.actor}:{request_id}",))
            previous = conn.execute("SELECT * FROM memory_requests WHERE tenant_id=%s AND actor_id=%s AND request_id=%s",
                                    (access.tenant_id, access.actor, request_id)).fetchone()
            if previous:
                if previous["payload_hash"] != payload_hash:
                    raise MemoryError("idempotency_conflict", "同一请求标识对应的内容已改变。", status=409)
                for result in previous["result"]:
                    saved = result["memory"]
                    current = conn.execute("SELECT * FROM memory_records WHERE id=%s",(UUID(saved["id"]),)).fetchone()
                    if not current:
                        raise MemoryError("request_superseded", "原请求已处理，但记录已不存在，请重新查询。", status=409)
                    self._check_record(access,current,write=True)
                    if current["version"] != saved["version"] or current["status"] == "deleted":
                        raise MemoryError("request_superseded", "原请求已处理，但记忆此后已变更或删除，请读取当前状态后操作。", status=409)
                return previous["result"]
            locks = sorted({json.dumps([access.tenant_id, access.identity_type, i.scope_type, *t]) for i,t in zip(items, targets)})
            for lock in locks:
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock,))
            result = []
            for item, (user, project) in zip(items, targets):
                row = None
                if item.memory_id:
                    row = conn.execute("SELECT * FROM memory_records WHERE id=%s FOR UPDATE", (item.memory_id,)).fetchone()
                    if not row or row["status"] == "deleted":
                        raise MemoryError("not_found", "未找到需要更新的记忆。", status=404)
                    self._check_record(access, row, write=True)
                    if (row["scope_type"], row["fact_key"]) != (item.scope_type, item.fact_key):
                        raise MemoryError("invalid_update", "修改正文不能同时改变抽屉或事实字段。")
                elif item.fact_key:
                    row = conn.execute("""SELECT * FROM memory_records WHERE tenant_id=%s AND identity_type=%s
                        AND scope_type=%s AND platform_user_id=%s AND project_id=%s AND fact_key=%s AND status<>'deleted' FOR UPDATE""",
                        (access.tenant_id, access.identity_type, item.scope_type, user, project, item.fact_key)).fetchone()
                if row and all(row[k] == getattr(item, k) for k in ("content", "memory_type", "importance", "status")):
                    result.append({"status": "unchanged", "memory": _visible(row, access)})
                    continue
                if row and item.expected_version != row["version"]:
                    raise MemoryError("version_conflict", f"记忆已有版本 {row['version']}，请读取后携带该版本明确更新。", status=409)
                if not row and item.expected_version is not None:
                    raise MemoryError("version_conflict", "该字段还不存在，请按新增保存。", status=409)
                item_source = {**source, "message_id": item.source_message_id or source.get("message_id")}
                if row:
                    row = conn.execute("""UPDATE memory_records SET content=%s, memory_type=%s, importance=%s,
                        status=%s, source=%s, version=version+1, updated_at=now(), embedding=NULL,
                        indexed_version=NULL, index_status='pending' WHERE id=%s RETURNING *""",
                        (item.content, item.memory_type, item.importance, item.status, Jsonb(item_source), row["id"])).fetchone()
                    action = "updated"
                else:
                    row = conn.execute("""INSERT INTO memory_records
                        (id,tenant_id,identity_type,scope_type,platform_user_id,project_id,fact_key,content,memory_type,importance,status,source,created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (uuid4(), access.tenant_id, access.identity_type, item.scope_type, user, project,
                         item.fact_key, item.content, item.memory_type, item.importance, item.status, Jsonb(item_source), access.actor)).fetchone()
                    action = "saved"
                self._version(conn, row, access.actor, action)
                self._queue(conn, row)
                result.append({"status": action, "memory": _visible(row, access)})
            conn.execute("INSERT INTO memory_requests VALUES (%s,%s,%s,%s,%s,now())",
                         (access.tenant_id, access.actor, request_id, payload_hash, Jsonb(result)))
            return result

    @staticmethod
    def _where(access: MemoryAccess, scope_type: str | None = None) -> tuple[str, list]:
        if access.management:
            if scope_type:
                return "tenant_id=%s AND scope_type=%s", [access.tenant_id, scope_type]
            return "tenant_id=%s", [access.tenant_id]
        clauses, params = [], [access.tenant_id, access.identity_type]
        for scope in ([scope_type] if scope_type else access.read_scopes):
            try:
                user, project = access.target(scope)
            except MemoryError:
                if scope_type:
                    raise
                continue
            clauses.append("(scope_type=%s AND platform_user_id=%s AND project_id=%s)")
            params.extend([scope, user, project])
        where = "tenant_id=%s AND identity_type=%s AND (" + (" OR ".join(clauses) or "FALSE") + ")"
        where += " AND (source->>'kind' IS DISTINCT FROM 'group_learning' OR scope_type='user' OR (scope_type='project' AND source->>'channel_id'=ANY(%s)) OR (scope_type='user_project' AND source->>'channel_id'=ANY(%s)))"
        params.extend([list(access.group_shared_channels), list(access.group_source_channels)])
        return where, params

    def get(self, access: MemoryAccess, memory_id: str) -> dict:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id=%s", (UUID(memory_id),)).fetchone()
            if not row:
                raise MemoryError("not_found", "未找到该记忆。", status=404)
            self._check_record(access, row)
            if row["status"] == "deleted" and not access.management:
                raise MemoryError("not_found", "该记忆已删除。", status=404)
            return _visible(row, access)

    def search(self, access: MemoryAccess, *, query: str = "", fact_key: str | None = None,
               scope_type: str | None = None, limit: int = 5, vector: list[float] | None = None,
               memory_type: str | None = None) -> list[dict]:
        where, params = self._where(access, scope_type)
        where += " AND status='active'"
        where += " AND (memory_type NOT IN ('reflection','experience','skill') OR learning->>'validation_state'='verified')"
        if not access.learning_use:
            where += " AND memory_type NOT IN ('reflection','experience','skill')"
        if memory_type:
            where += " AND memory_type=%s"
            params.append(memory_type)
        if fact_key:
            where += " AND fact_key=%s"
            params.append(fact_key)
        terms = list(dict.fromkeys(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", query.casefold())))
        terms = [term for word in terms for term in ([word] if not re.match(r"[\u4e00-\u9fff]", word) else [word, *[word[i:i+2] for i in range(len(word)-1)]])][:24]
        # position() treats %, _ and backslashes literally, unlike an unescaped LIKE.
        score_parts = ["CASE WHEN position(%s in lower(content))>0 THEN 1.0 ELSE 0.0 END" for _ in terms]
        score = "(" + "+".join(score_parts) + f")/{max(len(terms),1)}" if terms else "0.0"
        score_params: list[Any] = terms[:]
        if vector:
            score += "+ CASE WHEN indexed_version=version AND embedding IS NOT NULL THEN greatest(0,1-(embedding <=> %s::public.vector)) ELSE 0 END"
            score_params.append("[" + ",".join(str(float(v)) for v in vector) + "]")
        with self._connection() as conn:
            conn.execute("SET LOCAL statement_timeout = '3s'")
            rows = conn.execute(f"""SELECT * FROM (SELECT memory_records.*, {score} AS score,
                least(3,(SELECT count(DISTINCT actor_id) FROM learning_feedback f
                    WHERE f.memory_id=memory_records.id AND f.memory_version=memory_records.version AND f.outcome='success')) AS feedback_support
                FROM memory_records WHERE {where}) found
                WHERE (%s OR score>0) ORDER BY score DESC, feedback_support DESC, importance DESC, updated_at DESC LIMIT %s""",
                [*score_params, *params, bool(fact_key) or not query.strip(), min(max(limit,1),50)]).fetchall()
        return [_visible(row, access) for row in rows]

    def list(self, access: MemoryAccess, *, scope_type: str | None = None, user_id: str | None = None,
             project_id: str | None = None, query: str = "", status: str = "active", offset: int = 0, limit: int = 50,
             memory_type: str | None = None, origin: str | None = None) -> dict:
        where, params = self._where(access, scope_type)
        for column, value in (("platform_user_id", user_id), ("project_id", project_id), ("status", status), ("memory_type",memory_type), ("origin",origin)):
            if value is not None:
                where += f" AND {column}=%s"
                params.append(value)
        if query.strip():
            where += " AND position(%s in lower(content))>0"
            params.append(query.strip().casefold())
        with self._connection() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            total = conn.execute(f"SELECT count(*) AS n FROM memory_records WHERE {where}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT * FROM memory_records WHERE {where} ORDER BY updated_at DESC,id LIMIT %s OFFSET %s",
                                [*params, min(max(limit,1),200), max(offset,0)]).fetchall()
        return {"memories": [_visible(row, access) for row in rows], "total": total}

    def profile(self, access: MemoryAccess) -> list[dict]:
        where, params = self._where(access)
        with self._connection() as conn:
            conn.execute("SET LOCAL statement_timeout = '1s'")
            rows = conn.execute(f"""SELECT DISTINCT ON (fact_key) * FROM memory_records WHERE {where} AND status='active'
                AND scope_type IN ('user','user_project')
                AND fact_key IN ('profile.name','profile.address','preference.response_detail')
                ORDER BY fact_key, CASE WHEN scope_type='user_project' THEN 0 ELSE 1 END, updated_at DESC,id""",params).fetchall()
        return [_visible(row,access) for row in rows]

    def history(self, access: MemoryAccess, memory_id: str) -> list[dict]:
        self.get(access, memory_id)
        # Earlier versions can have broader/private ownership; only management can review them.
        if not access.management:
            raise MemoryError("forbidden", "历史版本仅供管理审计。", status=403)
        with self._connection() as conn:
            return _json(conn.execute("SELECT * FROM memory_versions WHERE memory_id=%s ORDER BY version DESC", (UUID(memory_id),)).fetchall())

    def forget(self, access: MemoryAccess, memory_id: str, expected_version: int) -> dict:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id=%s FOR UPDATE",(UUID(memory_id),)).fetchone()
            if not row:
                raise MemoryError("not_found", "未找到该记忆。", status=404)
            self._check_record(access,row,write=True)
            if row["status"] == "deleted":
                return {"status":"unchanged","memory_id":memory_id}
            if row["version"] != expected_version:
                raise MemoryError("version_conflict", "记忆版本已改变，请重新读取后再删除。", status=409)
            changed = conn.execute("""UPDATE memory_records SET status='deleted',index_status='deleted',
                version=version+1,embedding=NULL,indexed_version=NULL,updated_at=now() WHERE id=%s RETURNING *""",(row["id"],)).fetchone()
            self._version(conn,changed,access.actor,"forgotten")
            conn.execute("DELETE FROM memory_index_jobs WHERE memory_id=%s",(row["id"],))
            return {"status":"deleted","memory_id":memory_id,"version":changed["version"]}

    def manage(self, access: MemoryAccess, memory_id: str, *, expected_version: int,
               content: str | None = None, scope_type: str | None = None, user_id: str | None = None,
               project_id: str | None = None, status: str | None = None, publish: bool = False) -> dict:
        if not access.management:
            raise MemoryError("forbidden", "需要管理权限。", status=403)
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id=%s FOR UPDATE", (UUID(memory_id),)).fetchone()
            if not row:
                raise MemoryError("not_found", "未找到该记忆。", status=404)
            self._check_record(access, row, write=True)
            if row["version"] != expected_version:
                raise MemoryError("version_conflict", "记忆已被其他操作修改，请刷新后重试。", status=409)
            new_scope = scope_type or row["scope_type"]
            new_user = row["platform_user_id"] if user_id is None else user_id
            new_project = row["project_id"] if project_id is None else project_id
            new_status = status or row["status"]
            if row.get('source', {}).get('kind') == 'group_learning' and (
                new_scope != row['scope_type'] or new_user != row['platform_user_id'] or new_project != row['project_id']):
                raise MemoryError('group_scope_fixed', '群聊学习成果保留原始可见范围，不能调整抽屉或转交其他用户。')
            learning = dict(row.get('learning') or {})
            if row['memory_type'] in {'reflection','experience','skill'}:
                if status == 'active':
                    raise MemoryError('learning_review_required','学习成果需要携带验证依据，通过学习审核入口启用。')
                if content is not None or scope_type is not None or user_id is not None or project_id is not None:
                    if new_status != 'deleted':
                        new_status = 'candidate'
                        learning['validation_state'] = 'unverified'
            if new_scope == "project":
                if row["scope_type"] != "project" and not publish:
                    raise MemoryError("publish_required", "转为项目级会向项目成员共享，需要明确确认发布。")
                new_user = ""
            if new_scope == "user":
                new_project = ""
            validator = MemoryAccess(access.tenant_id, new_user, new_project, row["identity_type"], private=True, project_read=True, project_write=True)
            validator.target(new_scope, write=True)
            new_content = content.strip() if content is not None else row["content"]
            if not 1 <= len(new_content) <= 16000 or new_status not in {"active", "candidate", "inactive", "deleted"}:
                raise MemoryError("invalid_content", "记忆内容或状态无效。")
            if row['memory_type'] in {'reflection','experience','skill'}:
                learning['fingerprint']=learning_fingerprint(row['memory_type'],new_content,learning)
            index_status = "deleted" if new_status == "deleted" else "pending"
            changed = conn.execute("""UPDATE memory_records SET content=%s,scope_type=%s,platform_user_id=%s,project_id=%s,
                status=%s,version=version+1,updated_at=now(),embedding=NULL,indexed_version=NULL,index_status=%s,learning=%s
                WHERE id=%s RETURNING *""", (new_content,new_scope,new_user,new_project,new_status,index_status,Jsonb(learning),row["id"])).fetchone()
            self._version(conn, changed, access.actor, "deleted" if new_status == "deleted" else "managed_update")
            if new_status == "deleted":
                conn.execute("DELETE FROM memory_index_jobs WHERE memory_id=%s", (row["id"],))
            else:
                self._queue(conn, changed)
            return _public(changed)

    def claim_index_job(self) -> dict | None:
        with self._connection() as conn:
            return conn.execute("""WITH next_job AS (
                SELECT j.memory_id FROM memory_index_jobs j JOIN memory_records r ON r.id=j.memory_id
                WHERE r.status<>'deleted' AND ((j.state='pending' AND j.available_at<=now()) OR (j.state='failed' AND j.updated_at<now()-interval '1 hour') OR
                    (j.state='running' AND j.lease_until<now())) ORDER BY j.available_at
                FOR UPDATE OF j SKIP LOCKED LIMIT 1)
                UPDATE memory_index_jobs j SET state='running', attempts=attempts+1,
                    lease_until=now()+interval '5 minutes', lease_id=%s, updated_at=now()
                FROM next_job n, memory_records r WHERE j.memory_id=n.memory_id AND r.id=j.memory_id
                RETURNING j.*, r.content""", (uuid4(),)).fetchone()

    def finish_index_job(self, job: dict, *, vector: list[float] | None = None, error_code: str | None = None) -> bool:
        with self._connection() as conn:
            # Writers lock records before jobs. Use the same order to avoid deadlocks.
            conn.execute("SELECT id FROM memory_records WHERE id=%s FOR UPDATE", (job["memory_id"],))
            current = conn.execute("SELECT * FROM memory_index_jobs WHERE memory_id=%s FOR UPDATE", (job["memory_id"],)).fetchone()
            if not current or (current["version"], current["lease_id"], current["state"]) != (job["version"],job["lease_id"],"running"):
                return False
            if error_code:
                failed = current["attempts"] >= 5
                conn.execute("""UPDATE memory_index_jobs SET state=%s,error_code=%s,lease_until=NULL,lease_id=NULL,
                    available_at=now()+(%s * interval '1 second'),updated_at=now() WHERE memory_id=%s""",
                    ("failed" if failed else "pending", error_code[:120], min(300,2**min(current["attempts"],6)*5),job["memory_id"]))
                conn.execute("UPDATE memory_records SET index_status=%s WHERE id=%s AND version=%s",
                             ("failed" if failed else "pending",job["memory_id"],job["version"]))
            else:
                if not vector or len(vector) != 1024:
                    raise MemoryError("embedding_dimensions", "向量维度必须为 1024。")
                conn.execute("""UPDATE memory_records SET embedding=%s::public.vector,indexed_version=version,index_status='ready'
                    WHERE id=%s AND version=%s AND status<>'deleted'""",
                    ("["+",".join(str(float(v)) for v in vector)+"]",job["memory_id"],job["version"]))
                conn.execute("UPDATE memory_index_jobs SET state='done',lease_until=NULL,lease_id=NULL,error_code=NULL,updated_at=now() WHERE memory_id=%s", (job["memory_id"],))
            return True

    def retry_index(self, access: MemoryAccess, memory_id: str) -> dict:
        if not access.management:
            raise MemoryError("forbidden", "需要管理权限。", status=403)
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id=%s FOR UPDATE", (UUID(memory_id),)).fetchone()
            if not row or row["status"] == "deleted":
                raise MemoryError("not_found", "未找到有效记忆。", status=404)
            self._check_record(access, row)
            self._queue(conn, row)
            conn.execute("UPDATE memory_records SET index_status='pending' WHERE id=%s", (row["id"],))
            return {"status": "pending"}

    def diagnostics(self, access: MemoryAccess) -> list[dict]:
        if not access.management:
            raise MemoryError("forbidden", "需要管理权限。", status=403)
        with self._connection() as conn:
            return _json(conn.execute("""SELECT j.*,r.scope_type,r.project_id,r.platform_user_id FROM memory_index_jobs j
                JOIN memory_records r ON r.id=j.memory_id WHERE r.tenant_id=%s AND j.state<>'done'
                ORDER BY j.updated_at DESC LIMIT 100""", (access.tenant_id,)).fetchall())

    def counts(self, access: MemoryAccess) -> list[dict]:
        if not access.management:
            raise MemoryError("forbidden", "需要管理权限。", status=403)
        with self._connection() as conn:
            return conn.execute("""SELECT identity_type,scope_type,platform_user_id,project_id,count(*) AS count
                FROM memory_records WHERE tenant_id=%s AND status<>'deleted'
                GROUP BY identity_type,scope_type,platform_user_id,project_id""",(access.tenant_id,)).fetchall()

    def legacy_reviews(self, access: MemoryAccess) -> list[dict]:
        if not access.management:
            raise MemoryError("forbidden", "需要管理权限。", status=403)
        with self._connection() as conn:
            return _json(conn.execute("""SELECT legacy_id,content,reason,created_at FROM memory_legacy_reviews
                WHERE tenant_id=%s AND resolved_memory_id IS NULL ORDER BY created_at,legacy_id LIMIT 500""",(access.tenant_id,)).fetchall())

    def resolve_legacy(self, access: MemoryAccess, legacy_id: str, *, user_id: str, project_id: str,
                       scope_type: str, content: str, publish: bool = False) -> dict:
        if not access.management:
            raise MemoryError("forbidden", "需要管理权限。", status=403)
        target = MemoryAccess(access.tenant_id,user_id,project_id,project_read=True,project_write=True)
        user, project = target.target(scope_type,write=True)
        item = MemoryWrite(scope_type=scope_type,content=content)
        if scope_type == "project" and not publish:
            raise MemoryError("publish_required", "发布旧记忆到项目级需要明确确认。")
        with self._connection() as conn:
            legacy = conn.execute("SELECT * FROM memory_legacy_reviews WHERE legacy_id=%s AND tenant_id=%s FOR UPDATE",
                                  (UUID(legacy_id),access.tenant_id)).fetchone()
            if not legacy:
                raise MemoryError("not_found", "未找到待审查的旧记忆。", status=404)
            if legacy["resolved_memory_id"]:
                raise MemoryError("already_resolved", "这条旧记忆已完成归属调整，请刷新。", status=409)
            row = conn.execute("""INSERT INTO memory_records
                (id,tenant_id,identity_type,scope_type,platform_user_id,project_id,content,source,created_by,legacy_id)
                VALUES (%s,%s,'business_user',%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (uuid4(),access.tenant_id,scope_type,user,project,item.content,
                 Jsonb({"kind":"legacy_assignment","legacy_metadata":legacy["original_payload"],"review_reason":legacy["reason"]}),
                 access.actor,legacy["legacy_id"])).fetchone()
            self._version(conn,row,access.actor,"legacy_assignment")
            self._queue(conn,row)
            conn.execute("UPDATE memory_legacy_reviews SET resolved_memory_id=%s WHERE legacy_id=%s",(row["id"],legacy["legacy_id"]))
            return _public(row)
