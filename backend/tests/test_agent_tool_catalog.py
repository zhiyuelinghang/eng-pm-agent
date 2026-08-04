"""Regression tests for the assignable Dobby tool catalogue."""

from scripts.dobby_agent_tools import create_dobby_agent_tool_catalog


def test_business_catalog_is_not_bound_to_a_live_session() -> None:
    catalog = create_dobby_agent_tool_catalog(None)
    names = {tool.name for tool in catalog}

    assert "dobby_list_project_items" in names
    assert "dobby_create_task" in names
    assert "dobby_update_wbs_progress" in names
    assert all(tool.display_name for tool in catalog)


def test_initializer_catalog_only_contains_role_relevant_tools() -> None:
    catalog = create_dobby_agent_tool_catalog("orchestrator")
    names = {tool.name for tool in catalog}

    assert "dobby_list_project_items" in names
    assert "dobby_begin_project_initialization_normalization" in names
    assert "dobby_read_project_initialization_file" in names
    assert "dobby_create_task" not in names
