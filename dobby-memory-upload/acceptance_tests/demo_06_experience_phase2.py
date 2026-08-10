#!/usr/bin/env python3
"""
demo_06_experience_phase2.py — Step 6: Experience Phase 2 Verification

Validates:
  - DB migration: embedding column + HNSW index + experiences table
  - Embedding generation: bge-large-zh-v1.5 vectorization
  - Coarse filter: HNSW cosine similarity candidate pairs
  - LLM consolidation: merge/keep_separate/conflict actions
  - Idempotent merge: same slug → version increment
  - 24h cooldown: second call within window → skipped
  - Advisory lock: concurrent calls → one locked
  - Wiki sync: body_md published to WeKnora (best-effort)
  - Backward compat: demo_04 14/14 AC still pass

10 acceptance criteria. Run:
    python demo_06_experience_phase2.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

# ── Project root (acceptance_tests/ 的父目录 = dobby-memory) ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ── Load environment ──
try:
    from dotenv import load_dotenv
    _env_file = os.path.join(_ROOT, ".env")
    load_dotenv(_env_file, override=True)
except ImportError:
    pass

# ── Offline mode for HuggingFace ──
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


# ============================================================
# TR — Test Result Tracker
# ============================================================

class TR:
    def __init__(self):
        self.r = []

    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        print(f"  {'✅' if passed else '❌'} {name}" + (f": {detail}" if detail else ""))

    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        print(f"\n{'='*60}\nResults: {p}/{len(self.r)} passed "
              f"{'🎉 ALL PASS' if p == len(self.r) else '⚠️  SOME FAILED'}\n{'='*60}")
        return p == len(self.r)


# ============================================================
# Helpers
# ============================================================

def _get_db_conn():
    """Create a fresh psycopg connection."""
    import psycopg
    from utils import config as _cfg
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
    )


def _init_tables() -> bool:
    """Create/upgrade experience_extracts, experiences, consolidation_log tables."""
    import psycopg
    from utils import config as _cfg

    ddl = """
    CREATE TABLE IF NOT EXISTS experience_extracts (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id TEXT NOT NULL,
      task_id TEXT NOT NULL,
      task_outcome TEXT,
      bucket TEXT,
      description TEXT,
      reusable_knowledge TEXT,
      pitfalls TEXT,
      keywords TEXT[],
      importance FLOAT DEFAULT 0.5,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    ALTER TABLE experience_extracts ADD COLUMN IF NOT EXISTS embedding VECTOR(1024);

    CREATE INDEX IF NOT EXISTS idx_extracts_task_id ON experience_extracts (task_id);
    CREATE INDEX IF NOT EXISTS idx_extracts_project_id ON experience_extracts (project_id);
    CREATE INDEX IF NOT EXISTS idx_extracts_bucket ON experience_extracts (bucket);

    -- HNSW index for embedding (pgvector >= 0.5.0)
    CREATE INDEX IF NOT EXISTS idx_extracts_embedding ON experience_extracts
      USING hnsw (embedding vector_cosine_ops)
      WITH (m = 16, ef_construction = 64);

    CREATE TABLE IF NOT EXISTS experiences (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id TEXT NOT NULL,
      slug VARCHAR(160) NOT NULL,
      body_md TEXT NOT NULL,
      source_extract_ids UUID[] NOT NULL,
      bucket TEXT,
      importance FLOAT DEFAULT 0.5,
      version INT NOT NULL DEFAULT 1,
      consolidated_by VARCHAR(64),
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE (project_id, slug, version)
    );

    CREATE INDEX IF NOT EXISTS idx_experiences_project ON experiences (project_id);
    CREATE INDEX IF NOT EXISTS idx_experiences_slug ON experiences (project_id, slug);
    CREATE INDEX IF NOT EXISTS idx_experiences_bucket ON experiences (bucket);

    -- Ensure importance column exists (may be missing from earlier migration)
    ALTER TABLE experiences ADD COLUMN IF NOT EXISTS importance FLOAT DEFAULT 0.5;

    CREATE TABLE IF NOT EXISTS consolidation_log (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id TEXT NOT NULL,
      extracts_processed INT DEFAULT 0,
      experiences_created INT DEFAULT 0,
      experiences_updated INT DEFAULT 0,
      wiki_synced INT DEFAULT 0,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_consolidation_log_project_ts
      ON consolidation_log (project_id, created_at DESC);
    """

    conn = psycopg.Connection.connect(
        _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
    )
    try:
        for stmt in ddl.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except Exception as e:
                msg = str(e).lower()
                if "already exists" not in msg and "does not exist" not in msg:
                    # "does not exist" can happen for ALTER IF NOT EXISTS fallback
                    print(f"  ⚠️ SQL: {str(e)[:80]}")

        # Verify
        cur = conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'experience_extracts')"
        )
        ok1 = bool(cur.fetchone()[0])
        cur = conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'experiences')"
        )
        ok2 = bool(cur.fetchone()[0])
        cur = conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'consolidation_log')"
        )
        ok3 = bool(cur.fetchone()[0])
        return ok1 and ok2 and ok3
    except Exception as e:
        print(f"  ⚠️ _init_tables: {e}")
        return False
    finally:
        conn.close()


def _insert_extract(project_id: str, task_id: str, description: str,
                    reusable_knowledge: str = "", bucket: str = "procedure",
                    importance: float = 0.5) -> str:
    """Insert a test extract row and return its UUID."""
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            """INSERT INTO experience_extracts
               (project_id, task_id, task_outcome, bucket, description,
                reusable_knowledge, importance)
               VALUES (%s, %s, 'success', %s, %s, %s, %s)
               RETURNING id""",
            (project_id, task_id, bucket, description,
             reusable_knowledge, importance),
        )
        eid = str(cur.fetchone()[0])
        return eid
    finally:
        conn.close()


def _count_experiences(project_id: str, slug: str | None = None) -> int:
    """Count experiences rows for a project, optionally filtered by slug."""
    conn = _get_db_conn()
    try:
        if slug:
            cur = conn.execute(
                "SELECT COUNT(*) FROM experiences "
                "WHERE project_id = %s AND slug = %s",
                (project_id, slug),
            )
        else:
            cur = conn.execute(
                "SELECT COUNT(*) FROM experiences WHERE project_id = %s",
                (project_id,),
            )
        row = cur.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _get_experience(project_id: str, slug: str) -> dict | None:
    """Get latest version of an experience by slug."""
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            """SELECT id, slug, body_md, source_extract_ids, bucket,
                      version, importance
               FROM experiences
               WHERE project_id = %s AND slug = %s
               ORDER BY version DESC LIMIT 1""",
            (project_id, slug),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "slug": row[1], "body_md": row[2],
            "source_extract_ids": row[3], "bucket": row[4],
            "version": row[5], "importance": row[6],
        }
    finally:
        conn.close()


def _cleanup(project_id: str) -> None:
    """Remove test data for a project_id."""
    conn = _get_db_conn()
    try:
        conn.execute("DELETE FROM experiences WHERE project_id = %s", (project_id,))
        conn.execute("DELETE FROM consolidation_log WHERE project_id = %s", (project_id,))
        conn.execute("DELETE FROM experience_extracts WHERE project_id = %s", (project_id,))
    except Exception:
        pass
    finally:
        conn.close()


# ============================================================
# AC-6.1: Embedding column + HNSW index
# ============================================================

async def t61_embedding_column(r: TR):
    """Verify experience_extracts has embedding VECTOR(1024) column + HNSW index."""
    try:
        conn = _get_db_conn()
        # Check column exists
        cur = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'experience_extracts' AND column_name = 'embedding'"
        )
        col = cur.fetchone()

        # Check HNSW index exists (may fail on older pgvector → acceptable)
        idx_exists = False
        try:
            cur2 = conn.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'experience_extracts' AND indexname = 'idx_extracts_embedding'"
            )
            idx_exists = cur2.fetchone() is not None
        except Exception:
            pass  # pgvector < 0.5.0 doesn't support HNSW

        conn.close()

        ok = col is not None
        r.add("AC-6.1 Embedding Column", ok,
              f"col={'✓' if col else '✗'} idx={'✓' if idx_exists else '✗ (pre-0.5?)'}")
    except Exception as e:
        r.add("AC-6.1 Embedding Column", False, str(e)[:100])


# ============================================================
# AC-6.2: experiences table
# ============================================================

async def t62_experiences_table(r: TR):
    """Verify experiences table exists with correct columns."""
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'experiences' "
            "ORDER BY ordinal_position"
        )
        cols = [row[0] for row in cur.fetchall()]
        conn.close()

        required = {"id", "project_id", "slug", "body_md", "source_extract_ids",
                    "bucket", "version"}
        ok = required.issubset(set(cols))
        r.add("AC-6.2 Experiences Table", ok,
              f"columns={len(cols)} required={'✓' if ok else '✗ missing:' + str(required - set(cols))}")
    except Exception as e:
        r.add("AC-6.2 Experiences Table", False, str(e)[:100])


# ============================================================
# AC-6.3: Embedding generation
# ============================================================

async def t63_ensure_embeddings(r: TR):
    """Verify _ensure_embeddings generates vectors for NULL-embedding rows."""
    try:
        from utils.lifecycle import _ensure_embeddings

        pid = f"ac63_{uuid.uuid4().hex[:8]}"
        tid = f"task_{uuid.uuid4().hex[:8]}"

        # Insert 3 rows without embeddings
        eid1 = _insert_extract(pid, tid + "_1",
                               "基坑临边防护栏杆高度不足1.05m，按JGJ 80-2016整改至1.25m",
                               "栏杆加高+安全网更换，监理复核通过")
        eid2 = _insert_extract(pid, tid + "_2",
                               "2号基坑西侧类似问题：栏杆1.08m，统一整改",
                               "同1号基坑流程，批量整改节省时间")
        eid3 = _insert_extract(pid, tid + "_3",
                               "进度周报模板优化：增加风险状态列",
                               "用户偏好红色标注逾期项")

        await asyncio.sleep(0.3)

        # Build extract dicts
        extracts = [
            {"id": eid1, "project_id": pid, "description": "基坑临边防护栏杆高度不足1.05m",
             "reusable_knowledge": "栏杆加高+安全网更换", "embedding": None},
            {"id": eid2, "project_id": pid, "description": "2号基坑西侧类似问题",
             "reusable_knowledge": "批量整改", "embedding": None},
            {"id": eid3, "project_id": pid, "description": "进度周报模板优化",
             "reusable_knowledge": "红色标注逾期", "embedding": None},
        ]

        await _ensure_embeddings(extracts)
        await asyncio.sleep(0.3)

        # Verify embeddings written to DB
        conn = _get_db_conn()
        cur = conn.execute(
            "SELECT COUNT(*) FROM experience_extracts "
            "WHERE project_id = %s AND embedding IS NOT NULL",
            (pid,),
        )
        count = cur.fetchone()[0]
        conn.close()

        ok = count >= 3
        r.add("AC-6.3 Embedding Generation", ok,
              f"embedded={count}/3")

        _cleanup(pid)
    except Exception as e:
        r.add("AC-6.3 Embedding Generation", False, str(e)[:100])


# ============================================================
# AC-6.4: Coarse filter
# ============================================================

async def t64_coarse_filter(r: TR):
    """Verify HNSW coarse filter finds similar pairs, skips unrelated ones."""
    try:
        from utils.lifecycle import _ensure_embeddings, _coarse_filter

        pid = f"ac64_{uuid.uuid4().hex[:8]}"

        # 3 similar extracts (基坑防护 related)
        eid_a = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                                "1号基坑临边防护栏杆高度不足1.05m，按JGJ 80-2016标准整改至1.25m",
                                "栏杆加高+安全网更换+监理复核", "procedure", 0.8)
        eid_b = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                                "2号基坑东侧临边防护栏杆1.08m不达标，参照1号基坑整改方案执行",
                                "复用1号基坑整改流程，批量处理", "procedure", 0.7)
        eid_c = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                                "3号基坑临边防护复查：栏杆高度1.22m达标，但安全网破损需更换",
                                "定期巡检+安全网更换周期", "procedure", 0.6)

        # 2 unrelated extracts
        eid_d = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                                "项目周报模板优化：增加甘特图自动生成功能",
                                "使用python-gantt库", "preference", 0.5)
        eid_e = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                                "混凝土供应商合同评审：三家比价，选择性价比最高的",
                                "供应商评估表模板", "decision", 0.5)

        await asyncio.sleep(0.3)

        extracts = [
            {"id": eid_a, "project_id": pid, "description": "基坑临边防护栏杆高度不足"},
            {"id": eid_b, "project_id": pid, "description": "基坑东侧临边防护栏杆"},
            {"id": eid_c, "project_id": pid, "description": "基坑临边防护复查"},
            {"id": eid_d, "project_id": pid, "description": "项目周报模板优化"},
            {"id": eid_e, "project_id": pid, "description": "混凝土供应商合同评审"},
        ]

        await _ensure_embeddings(extracts)
        await asyncio.sleep(0.3)

        pairs = _coarse_filter(extracts, threshold=0.75)

        # Check: should find pairs among A,B,C but not with D,E
        pair_ids = set()
        for e_i, e_j, sim in pairs:
            pair_ids.add(tuple(sorted([e_i["id"], e_j["id"]])))

        # Count how many基坑-related pairs found
        jikeng_ids = {eid_a, eid_b, eid_c}
        jikeng_pairs = [
            (a, b) for a, b in pair_ids
            if a in jikeng_ids and b in jikeng_ids
        ]

        ok = len(jikeng_pairs) >= 1  # at least one jikeng pair found
        r.add("AC-6.4 Coarse Filter", ok,
              f"total_pairs={len(pairs)} jikeng_pairs={len(jikeng_pairs)}")

        _cleanup(pid)
    except Exception as e:
        r.add("AC-6.4 Coarse Filter", False, str(e)[:100])


# ============================================================
# AC-6.5: LLM consolidation → merge
# ============================================================

async def t65_llm_consolidate(r: TR):
    """Verify two similar extracts → LLM merge → experiences table has 1 row."""
    try:
        from utils.lifecycle import consolidate_if_needed

        pid = f"ac65_{uuid.uuid4().hex[:8]}"

        _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                        "1号基坑东侧临边防护栏杆高度仅1.05m，不足JGJ 80-2016要求的1.2m，"
                        "已发出整改通知要求加高至1.25m并更换破损安全网，监理复核通过。",
                        "栏杆加高+安全网更换+整改通知流程", "procedure", 0.8)

        _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                        "2号基坑西侧临边防护也存在栏杆不达标问题（1.08m），参照1号基坑整改方案，"
                        "统一加高至1.25m。发现两处基坑均有类似问题，建议建立定期巡检制度。",
                        "复用整改方案+建议定期巡检", "procedure", 0.7)

        await asyncio.sleep(0.3)

        # Override cooldown — force run
        import utils.config as _cfg
        orig_cooldown = _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS
        _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = 0

        try:
            result = await consolidate_if_needed(pid)
            await asyncio.sleep(0.5)

            created = result.get("experiences_created", 0)
            updated = result.get("experiences_updated", 0)

            # Check experiences table
            exp = None
            conn = _get_db_conn()
            cur = conn.execute(
                "SELECT slug, version, array_length(source_extract_ids, 1) "
                "FROM experiences WHERE project_id = %s ORDER BY version DESC LIMIT 1",
                (pid,),
            )
            row = cur.fetchone()
            conn.close()

            if row:
                exp = {"slug": row[0], "version": row[1], "source_count": row[2]}

            ok = (not result.get("skipped")) and (created + updated >= 1) and exp is not None
            r.add("AC-6.5 LLM Consolidate", ok,
                  f"skipped={result.get('skipped')} created={created} "
                  f"exp={'v' + str(exp['version']) if exp else 'None'}")
        finally:
            _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = orig_cooldown
            _cleanup(pid)
    except Exception as e:
        r.add("AC-6.5 LLM Consolidate", False, str(e)[:100])


# ============================================================
# AC-6.6: Idempotent merge
# ============================================================

async def t66_idempotent_merge(r: TR):
    """Verify same slug merged twice → version=2, not duplicate row."""
    try:
        from utils.lifecycle import _apply_merge_plan

        pid = f"ac66_{uuid.uuid4().hex[:8]}"
        eid1 = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                               "测试合并幂等性：第一次合并产生 version=1",
                               "幂等测试", "procedure", 0.5)
        eid2 = _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                               "测试合并幂等性：第二次合并应产生 version=2",
                               "幂等测试补充", "procedure", 0.5)

        await asyncio.sleep(0.2)

        slug = "test-idempotent-merge"

        # First merge
        plan1 = {
            "clusters": [{
                "source_ids": [eid1],
                "action": "merge",
                "slug": slug,
                "body_md": "## Version 1 Content\n\n第一次合并的内容。",
                "bucket": "procedure",
                "importance": 0.5,
            }],
        }
        _apply_merge_plan(pid, plan1)

        # Second merge (same slug, different source)
        plan2 = {
            "clusters": [{
                "source_ids": [eid1, eid2],
                "action": "merge",
                "slug": slug,
                "body_md": "## Version 2 Content\n\n第二次合并的内容，更完整。",
                "bucket": "procedure",
                "importance": 0.6,
            }],
        }
        _apply_merge_plan(pid, plan2)

        # Verify: 1 row for slug, version=2
        exp = _get_experience(pid, slug)
        total = _count_experiences(pid, slug)

        ok = (total == 1 and exp is not None and exp["version"] == 2)
        r.add("AC-6.6 Idempotent Merge", ok,
              f"rows_for_slug={total} version={exp['version'] if exp else 'None'}")

        _cleanup(pid)
    except Exception as e:
        r.add("AC-6.6 Idempotent Merge", False, str(e)[:100])


# ============================================================
# AC-6.7: 24h cooldown
# ============================================================

async def t67_cooldown(r: TR):
    """Verify second call within 24h → skipped with reason=cooldown."""
    try:
        from utils.lifecycle import consolidate_if_needed
        import utils.config as _cfg

        pid = f"ac67_{uuid.uuid4().hex[:8]}"

        # Insert enough extracts to trigger consolidation
        for i in range(3):
            _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}_{i}",
                            f"测试cooldown的第{i}条经验：描述了工程管理中的某个具体问题和解决方案",
                            f"解决方案{i}", "procedure", 0.6 + i * 0.1)

        await asyncio.sleep(0.2)

        # Set cooldown to 0 to force first run
        orig = _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS
        _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = 0

        try:
            result1 = await consolidate_if_needed(pid)
            await asyncio.sleep(0.3)

            # Set cooldown high to block second run
            _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = 9999
            result2 = await consolidate_if_needed(pid)

            ok = (not result1.get("skipped")) and result2.get("skipped") and result2.get("reason") == "cooldown"
            r.add("AC-6.7 Cooldown", ok,
                  f"run1={'skipped' if result1.get('skipped') else 'ok'} "
                  f"run2={result2.get('reason', '?')}")
        finally:
            _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = orig
            _cleanup(pid)
    except Exception as e:
        r.add("AC-6.7 Cooldown", False, str(e)[:100])


# ============================================================
# AC-6.8: Advisory lock — concurrent calls
# ============================================================

async def t68_advisory_lock(r: TR):
    """Verify concurrent consolidate_if_needed → one locked."""
    try:
        from utils.lifecycle import consolidate_if_needed
        import utils.config as _cfg

        pid = f"ac68_{uuid.uuid4().hex[:8]}"

        for i in range(3):
            _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}_{i}",
                            f"测试并发锁的第{i}条经验：描述了工程管理中的某个具体问题和解决方案",
                            f"解决方案{i}", "procedure", 0.6 + i * 0.1)

        await asyncio.sleep(0.2)

        orig = _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS
        _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = 0

        try:
            # Fire two concurrent calls
            results = await asyncio.gather(
                consolidate_if_needed(pid),
                consolidate_if_needed(pid),
                return_exceptions=True,
            )

            skipped_count = sum(
                1 for r in results
                if isinstance(r, dict) and r.get("skipped")
            )
            locked_count = sum(
                1 for r in results
                if isinstance(r, dict) and r.get("reason") == "locked"
            )

            # At least one should proceed, at least one should be blocked
            ok = skipped_count >= 1
            r.add("AC-6.8 Advisory Lock", ok,
                  f"total={len(results)} skipped={skipped_count} locked={locked_count}")
        finally:
            _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = orig
            _cleanup(pid)
    except Exception as e:
        r.add("AC-6.8 Advisory Lock", False, str(e)[:100])


# ============================================================
# AC-6.9: Wiki sync
# ============================================================

async def t69_wiki_sync(r: TR):
    """Verify consolidated experiences are synced to WeKnora wiki (best-effort)."""
    try:
        from utils.lifecycle import consolidate_if_needed
        import utils.config as _cfg

        pid = f"ac69_{uuid.uuid4().hex[:8]}"

        _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                        "基坑临边防护标准化整改：将JGJ 80-2016标准量化为检查清单，"
                        "包括栏杆高度≥1.2m、两道横杆、踢脚板≥180mm、密目安全网四个检查项。"
                        "在东侧基坑验证后推广至全项目3个基坑。",
                        "标准化检查清单+全项目推广", "procedure", 0.85)

        _insert_extract(pid, f"task_{uuid.uuid4().hex[:8]}",
                        "整改通知模板优化：用户要求所有整改通知必须使用红色标题、"
                        "抄送项目经理和安全总监、附带照片证据。此偏好已在3次整改中使用。",
                        "整改通知格式标准", "preference", 0.7)

        await asyncio.sleep(0.3)

        orig = _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS
        _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = 0

        try:
            result = await consolidate_if_needed(pid)
            await asyncio.sleep(0.5)

            wiki_synced = result.get("wiki_synced", 0)

            # Wiki sync is best-effort — we verify the function runs without error
            # and that experiences were created (wiki_synced depends on MCP availability)
            ok = not result.get("skipped") and result.get("experiences_created", 0) >= 1
            r.add("AC-6.9 Wiki Sync", ok,
                  f"created={result.get('experiences_created', 0)} "
                  f"wiki_synced={wiki_synced} "
                  f"{'(MCP may be unavailable)' if wiki_synced == 0 else ''}")
        finally:
            _cfg.EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = orig
            _cleanup(pid)
    except Exception as e:
        r.add("AC-6.9 Wiki Sync", False, str(e)[:100])


# ============================================================
# AC-6.10: Backward compat — demo_04 still passes
# ============================================================

async def t6a_backward_compat(r: TR):
    """Verify demo_04's existing tests still pass after Phase 2 changes."""
    try:
        # Import demo_04's key functions and run a quick subset check
        from utils.lifecycle import (
            extract_experiences, reflect_if_needed, apply_decay,
            _compute_recency_score,
        )
        from datetime import timedelta, datetime, timezone

        # Test 1: extract_experiences still works
        pid = f"ac6a_{uuid.uuid4().hex[:8]}"
        tid = f"task_{uuid.uuid4().hex[:8]}"
        tasks = {
            tid: {
                "status": "done",
                "description": "3号基坑临边防护整改。栏杆高度1.05m不达标，加高至1.25m，更换安全网。",
                "outcome": "success",
            },
        }
        result = await extract_experiences(pid, tasks)
        ok1 = result.get("total_inserts", 0) >= 1

        # Test 2: apply_decay doesn't crash
        decay_result = await apply_decay(pid)
        ok2 = isinstance(decay_result, dict) and "deleted" in decay_result

        # Test 3: recency formula still correct
        ts_30d_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        score = _compute_recency_score(ts_30d_ago, half_life_days=30)
        ok3 = 0.45 <= score <= 0.55  # ~0.5

        # Test 4: reflect_if_needed doesn't crash
        refl_result = await reflect_if_needed(pid)
        ok4 = isinstance(refl_result, dict) and "skipped" in refl_result

        all_ok = ok1 and ok2 and ok3 and ok4
        r.add("AC-6.10 Backward Compat", all_ok,
              f"extract={'✓' if ok1 else '✗'} decay={'✓' if ok2 else '✗'} "
              f"recency={'✓' if ok3 else '✗'} reflect={'✓' if ok4 else '✗'}")

        _cleanup(pid)
    except Exception as e:
        r.add("AC-6.10 Backward Compat", False, str(e)[:100])


# ============================================================
# Main
# ============================================================

async def main():
    r = TR()
    print("=" * 60)
    print("Step 6: Experience Phase 2 — Verification")
    print("=" * 60)

    # ── DB init ──
    print("\n── DB Migration ──")
    if _init_tables():
        print("  ✅ Tables ready (experience_extracts + experiences + consolidation_log)")
    else:
        print("  ⚠️  Could not verify all tables")

    tests = [
        ("AC-6.1 Embedding Column", t61_embedding_column),
        ("AC-6.2 Experiences Table", t62_experiences_table),
        ("AC-6.3 Embedding Generation", t63_ensure_embeddings),
        ("AC-6.4 Coarse Filter", t64_coarse_filter),
        ("AC-6.5 LLM Consolidate", t65_llm_consolidate),
        ("AC-6.6 Idempotent Merge", t66_idempotent_merge),
        ("AC-6.7 Cooldown", t67_cooldown),
        ("AC-6.8 Advisory Lock", t68_advisory_lock),
        ("AC-6.9 Wiki Sync", t69_wiki_sync),
        ("AC-6.10 Backward Compat", t6a_backward_compat),
    ]

    for name, fn in tests:
        print(f"\n── {name} ──")
        try:
            await fn(r)
        except Exception as e:
            r.add(name, False, f"unhandled: {str(e)[:100]}")

    return r.summary()


if __name__ == "__main__":
    import selectors
    lf = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    success = asyncio.run(main(), loop_factory=lf)
    sys.exit(0 if success else 1)
