"""Idempotent import of explicitly owned legacy records; no inferred publication."""
from __future__ import annotations

from typing import Any
from uuid import UUID
from psycopg import sql
from psycopg.types.json import Jsonb
from .memory_repository import MemoryRepository, _public


def classify_legacy(payload: dict, tenant_id: str) -> tuple[dict | None, str]:
    if payload.get("tenant_id") not in {None, "", tenant_id}:
        return None, "other_tenant"
    content = str(payload.get("data") or payload.get("memory") or "").strip()
    if not content or len(content)>16000:
        return None, "invalid_content"
    identity = payload.get("identity_type")
    scope = payload.get("scope_type")
    user = str(payload.get("platform_user_id") or "").strip()
    project = str(payload.get("project_id") or "").strip()
    if (str(payload.get("scope_version")) != "2" or not payload.get("tenant_id") or
        identity not in {"business_user","management_user"} or not user or user.startswith("anonymous") or
        scope not in {"user","user_project"} or (scope=="user_project" and not project)):
        return None, "owner_requires_review"
    if identity == "management_user" and scope != "user":
        return None, "management_scope_requires_review"
    return {"content":content,"identity_type":identity,"scope_type":scope,"platform_user_id":user,
            "project_id":project if scope=="user_project" else ""}, "owned_v2"


def migrate_legacy_memories(repository: MemoryRepository, *, tenant_id: str, collection: str, apply: bool = False) -> dict[str,Any]:
    result = {"apply":apply,"scanned":0,"imported":0,"already_imported":0,"needs_review":0,"other_tenant":0}
    with repository._connection() as conn:
        # Migration is explicit and resumable. Record IDs remain stable.
        last_id = UUID(int=0)
        while True:
            rows = conn.execute(sql.SQL("SELECT id,payload FROM {} WHERE id>%s ORDER BY id LIMIT 250").format(sql.Identifier(collection)),(last_id,)).fetchall()
            if not rows:
                break
            for old in rows:
                last_id = old["id"]
                result["scanned"] += 1
                payload = dict(old["payload"] or {})
                normalized, reason = classify_legacy(payload,tenant_id)
                if reason=="other_tenant":
                    result["other_tenant"] += 1
                    continue
                exists = conn.execute("SELECT id FROM memory_records WHERE legacy_id=%s",(old["id"],)).fetchone()
                if exists:
                    result["already_imported"] += 1
                    continue
                if normalized is None:
                    result["needs_review"] += 1
                    if apply:
                        conn.execute("""INSERT INTO memory_legacy_reviews(legacy_id,tenant_id,content,original_payload,reason)
                            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(legacy_id) DO NOTHING""",
                            (old["id"],tenant_id,str(payload.get("data") or ""),Jsonb(payload),reason))
                    continue
                result["imported"] += 1
                if not apply:
                    continue
                try:
                    importance = max(0,min(1,float(payload.get("importance",0.5))))
                except (ValueError,TypeError):
                    importance = 0.5
                row = conn.execute("""INSERT INTO memory_records
                    (id,tenant_id,identity_type,scope_type,platform_user_id,project_id,content,memory_type,importance,source,created_by,legacy_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(legacy_id) DO NOTHING RETURNING *""",
                    (old["id"],tenant_id,normalized["identity_type"],normalized["scope_type"],normalized["platform_user_id"],normalized["project_id"],
                     normalized["content"],str(payload.get("memory_type") or "fact"),importance,
                     Jsonb({"kind":"legacy_import","legacy_metadata":payload,"session_id":payload.get("source_session_id")}),
                     "migration:v3",old["id"])).fetchone()
                if row:
                    repository._version(conn,row,"migration:v3","legacy_import")
                    repository._queue(conn,row)
    return result
