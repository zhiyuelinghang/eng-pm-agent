"""
Skill registry — CRUD + lifecycle + context injection (Step 10).

Manages the skill_registry PG table and provides:
  - write_skill: upsert with repeat_count bump
  - get_active_skills: query by project + role
  - run_lifecycle: hot/warm/cold tiers + review_pending → active gate
  - render_injection: format skills as <skill-injection> block

Design decisions (ref: Agentica compiled_store.py):
  - Dual lifecycle: statistical (general) + human-review (safety-critical)
  - Unified PG storage (not file-based like Agentica)
  - render_injection returns formatted str ready for ContextAssembler
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

import psycopg

from . import config as _cfg
from .skill_compiler import SkillRecord


def _get_db_conn():
    return psycopg.Connection.connect(
        _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
    )


class SkillRegistry:
    """Skill CRUD + lifecycle + injection manager."""

    # ── Write (upsert with repeat_count bump) ──

    @staticmethod
    async def write_skill(record: SkillRecord) -> bool:
        """Write a skill record. Bumps repeat_count if slug+role_id exists.

        Returns True if written (new or updated).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _write_skill_sync, record)

    # ── Read active skills ──

    @staticmethod
    async def get_active_skills(project_id: str, role_id: str) -> list[dict]:
        """Get active skills for a project + role scope.

        Returns skills where status IN ('active', 'shadow', 'review_pending')
        AND role_id matches (global skills always included).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_active_skills_sync, project_id, role_id)

    # ── Bump reference count ──

    @staticmethod
    async def bump_reference(slug: str, role_id: str) -> None:
        """Increment reference_count and update last_referenced_at."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _bump_reference_sync, slug, role_id)

    # ── Lifecycle ──

    @staticmethod
    async def run_lifecycle(project_id: str) -> dict:
        """Run promotion/demotion/archive sweep.

        Returns: {"promoted": N, "demoted": N, "archived": N, "review_passed": N}
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run_lifecycle_sync, project_id)

    # ── Render injection ──

    @staticmethod
    async def render_injection(
        project_id: str,
        role_id: str,
        token_budget: int | None = None,
    ) -> str:
        """Format active skills as <skill-injection> block.

        Returns empty string if no active skills or token budget exhausted.
        """
        if token_budget is None:
            token_budget = _cfg.TOKEN_BUDGET_SKILL_INJECTION

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _render_injection_sync, project_id, role_id, token_budget,
        )


# ── Sync implementations ──

def _write_skill_sync(record: SkillRecord) -> bool:
    conn = None
    try:
        conn = _get_db_conn()
        # Check existing
        cur = conn.execute(
            """SELECT id, repeat_count, source_event_ids
               FROM skill_registry
               WHERE project_id = %s AND slug = %s AND role_id = %s
               LIMIT 1""",
            (record.project_id, record.slug, record.role_id),
        )
        existing = cur.fetchone()

        if existing:
            # Bump repeat_count, merge source_event_ids
            new_count = existing[1] + 1
            existing_ids = existing[2] or []
            merged_ids = list(set(existing_ids + record.source_event_ids))
            conn.execute(
                """UPDATE skill_registry
                   SET repeat_count = %s, source_event_ids = %s,
                       body_md = %s, updated_at = NOW()
                   WHERE id = %s""",
                (new_count, merged_ids, record.body_md, existing[0]),
            )
        else:
            conn.execute(
                """INSERT INTO skill_registry
                   (project_id, slug, role_id, bucket, title, body_md,
                    status, tier, importance, repeat_count, source_event_ids)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    record.project_id, record.slug, record.role_id,
                    record.bucket, record.title, record.body_md,
                    record.status, record.tier, record.importance,
                    record.repeat_count, record.source_event_ids,
                ),
            )
        return True
    except Exception:
        return False
    finally:
        if conn:
            conn.close()


def _get_active_skills_sync(project_id: str, role_id: str) -> list[dict]:
    conn = None
    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """SELECT slug, role_id, bucket, title, body_md, status, tier,
                      importance, repeat_count, reference_count
               FROM skill_registry
               WHERE project_id = %s
                 AND status IN ('active', 'shadow', 'review_pending')
                 AND (role_id = %s OR role_id = 'global')
               ORDER BY
                 CASE tier WHEN 'hot' THEN 1 WHEN 'warm' THEN 2 ELSE 3 END,
                 repeat_count DESC
               LIMIT 20""",
            (project_id, role_id),
        )
        rows = cur.fetchall()
        cols = [
            "slug", "role_id", "bucket", "title", "body_md",
            "status", "tier", "importance", "repeat_count", "reference_count",
        ]
        return [{cols[i]: row[i] for i in range(len(cols))} for row in rows]
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def _bump_reference_sync(slug: str, role_id: str) -> None:
    conn = None
    try:
        conn = _get_db_conn()
        conn.execute(
            """UPDATE skill_registry
               SET reference_count = reference_count + 1,
                   last_referenced_at = NOW()
               WHERE slug = %s AND role_id = %s""",
            (slug, role_id),
        )
    except Exception:
        pass
    finally:
        if conn:
            conn.close()


def _run_lifecycle_sync(project_id: str) -> dict:
    stats = {"promoted": 0, "demoted": 0, "archived": 0, "review_passed": 0}
    conn = None

    try:
        conn = _get_db_conn()
        cur = conn.execute(
            """SELECT id, slug, role_id, status, tier, repeat_count,
                      reference_count, last_referenced_at, importance, bucket,
                      reviewed_by
               FROM skill_registry
               WHERE project_id = %s""",
            (project_id,),
        )
        rows = cur.fetchall()

        for row in rows:
            (
                rid, slug, role_id, status, tier, repeat_count,
                ref_count, last_ref, importance, bucket, reviewed_by,
            ) = row

            days_since_ref = 999
            if last_ref:
                if isinstance(last_ref, datetime):
                    last_ref_dt = last_ref
                else:
                    last_ref_dt = datetime.fromisoformat(str(last_ref).replace("Z", "+00:00"))
                days_since_ref = (date.today().toordinal() -
                                  last_ref_dt.date().toordinal())

            new_status = status
            new_tier = tier

            # ── Tier: hot/warm/cold by recency (ref: compiled_store.py:run_lifecycle) ──
            if days_since_ref > _cfg.SKILL_ARCHIVE_DAYS:
                new_tier = "cold"
                new_status = "archived"
            elif days_since_ref > _cfg.SKILL_DEMOTION_DAYS:
                new_tier = "warm"

            # ── Promotion / review gates (only if not archived) ──
            if new_status != "archived":
                # C3: review_pending → active gate (human review completed)
                if status == "review_pending" and reviewed_by is not None:
                    new_status = "active"
                # Existing promotion: shadow → active or shadow → review_pending
                elif tier == "hot" and status == "shadow":
                    # Check if this is a safety-critical skill
                    is_safety = (
                        bucket in _cfg.SKILL_REVIEW_REQUIRED_BUCKETS
                        and (importance or 0.5) >= _cfg.SKILL_REVIEW_IMPORTANCE_THRESHOLD
                    )
                    if not is_safety and ref_count >= _cfg.SKILL_PROMOTION_REF_COUNT:
                        new_status = "active"
                    elif is_safety and status != "review_pending":
                        new_status = "review_pending"

            # ── Apply changes ──
            if new_status != status or new_tier != tier:
                conn.execute(
                    """UPDATE skill_registry
                       SET status = %s, tier = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (new_status, new_tier, rid),
                )

                if new_status == "active" and status == "review_pending":
                    stats["review_passed"] += 1
                elif new_status == "active" and status != "active":
                    stats["promoted"] += 1
                elif new_tier == "warm" and tier == "hot":
                    stats["demoted"] += 1
                elif new_status == "archived":
                    stats["archived"] += 1
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    return stats


def _render_injection_sync(
    project_id: str, role_id: str, token_budget: int,
) -> str:
    skills = _get_active_skills_sync(project_id, role_id)
    if not skills:
        return ""

    # Separate global vs role-specific
    global_skills = [s for s in skills if s["role_id"] == "global"]
    role_skills = [s for s in skills if s["role_id"] != "global"]

    parts = ["<skill-injection>"]
    parts.append("以下是从历史经验中编译的持久技能，请在回答时主动参考：")

    # Estimate chars per token (conservative for CJK)
    chars_per_token = _cfg.TOKEN_ESTIMATION_CHARS_PER_TOKEN  # 2.5
    max_chars = int(token_budget * chars_per_token)
    used_chars = sum(len(p) for p in parts)

    def _append_with_budget(text: str) -> bool:
        nonlocal used_chars
        if used_chars + len(text) > max_chars:
            return False
        parts.append(text)
        used_chars += len(text)
        return True

    if global_skills:
        if not _append_with_budget("\n【项目通用 — 跨角色经验】"):
            return "\n".join(parts) + "\n</skill-injection>"
        for s in global_skills:
            entry = _format_skill_entry(s)
            if not _append_with_budget(entry):
                break

    if role_skills:
        if not _append_with_budget(f"\n【{role_id} — 角色专属技能】"):
            return "\n".join(parts) + "\n</skill-injection>"
        for s in role_skills:
            entry = _format_skill_entry(s)
            if not _append_with_budget(entry):
                break

    parts.append("</skill-injection>")
    return "\n".join(parts)


def _format_skill_entry(skill: dict) -> str:
    """Format a single skill entry for injection (ref: compiled_store.py:get_relevant)."""
    title = skill.get("title", skill.get("slug", ""))
    repeat = skill.get("repeat_count", 1)
    tier = skill.get("tier", "hot")
    tier_badge = "" if tier == "hot" else f"[{tier.upper()}]"

    lines = [f"\n### {title} {tier_badge} (确认{repeat}次)"]
    body = skill.get("body_md", "")

    # Strip YAML frontmatter
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:].strip()
    lines.append(body[:500])
    return "\n".join(lines)
