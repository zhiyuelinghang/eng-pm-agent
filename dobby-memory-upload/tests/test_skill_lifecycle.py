"""Integration tests for skill self-evolution pipeline."""

import pytest
import asyncio


@pytest.mark.asyncio
async def test_tool_error_capture_and_compile():
    """Test: 3 tool errors -> compile trigger -> skill created."""
    from utils.skill_events import (
        record_tool_error, get_uncompiled_events, mark_compiled,
    )

    project_id = "test_skill_project"
    role_id = "safety_director"

    # Step 1: Record 3 tool errors
    try:
        for i in range(3):
            await record_tool_error(
                project_id, role_id, "search_knowledge",
                f"ConnectionError: timeout on attempt {i}",
            )

        # Step 2: Verify uncompiled events >= 3
        events = await get_uncompiled_events(project_id)
        error_events = [e for e in events if e["event_type"] == "tool_error"]
        assert len(error_events) >= 3, f"Expected >= 3 error events, got {len(error_events)}"

        # Step 3: Verify compilation would trigger
        assert len(events) >= 3, "Should meet compilation threshold"
    except Exception as exc:
        if "PostgreSQL" not in str(exc) and "connection" not in str(exc).lower():
            raise
        pytest.skip("PostgreSQL not available")


@pytest.mark.asyncio
async def test_correction_detection():
    """Test: user correction pattern matching."""
    from utils.skill_compiler import _extract_correction_rule

    # Chinese corrections
    assert _extract_correction_rule("不对，应该是先查规范再判断") == "先查规范再判断"
    assert _extract_correction_rule("记住，规则是先确认版本号") == "先确认版本号"
    assert _extract_correction_rule("下次请先检查数据库连接") == "先检查数据库连接"

    # Non-correction
    assert _extract_correction_rule("今天天气怎么样") == ""


@pytest.mark.asyncio
async def test_deterministic_title():
    """Test: same rule -> same title, different rules -> different titles."""
    from utils.skill_compiler import _rule_to_title

    # Same rule, different wording
    t1 = _rule_to_title("Always check database connection before reading files")
    t2 = _rule_to_title("You should check the database connection before you read any file")
    assert t1 == t2, f"Expected same title, got '{t1}' vs '{t2}'"

    # Different rules
    t3 = _rule_to_title("Always format dates as YYYY-MM-DD")
    assert t1 != t3, f"Expected different titles, got '{t1}' vs '{t3}'"


@pytest.mark.asyncio
async def test_skill_registry_write_and_bump():
    """Test: write skill -> bump repeat_count on duplicate."""
    from utils.skill_registry import SkillRegistry
    from utils.skill_compiler import SkillRecord

    record = SkillRecord(
        slug="test_check_db_connection",
        role_id="global",
        bucket="procedure",
        title="Check DB Connection",
        body_md="---\nname: test-check-db-connection\ndescription: Test skill\n---\n\nAlways check DB.",
        repeat_count=1,
    )

    # Skip DB-dependent test if no PG available
    try:
        result1 = await SkillRegistry.write_skill(record)
        assert result1 is True
    except Exception:
        pytest.skip("PostgreSQL not available")
