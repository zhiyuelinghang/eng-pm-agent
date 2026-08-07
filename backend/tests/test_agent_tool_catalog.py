"""Regression tests for host-side, non-catalogued platform capabilities."""

from scripts.dobby_agent_tools import create_dobby_agent_tool_catalog


def test_host_catalog_contains_no_fixed_business_tools() -> None:
    catalog = create_dobby_agent_tool_catalog()

    assert catalog == []


def test_host_catalog_does_not_duplicate_database_or_mcp_capabilities() -> None:
    catalog = create_dobby_agent_tool_catalog()
    assert catalog == []
