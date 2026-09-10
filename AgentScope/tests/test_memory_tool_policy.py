"""Memory tool exposure follows explicit capabilities, including lazy tools."""

from types import SimpleNamespace

import pytest

from agentscope.app._platform_tool_policy import PlatformToolPolicy


MEMORY_TOOLS = {"search_memory", "add_memory", "forget_memory", "learn_from_task", "learning_feedback"}


@pytest.mark.parametrize("global_main", [True, False])
@pytest.mark.parametrize("config,allowed", [
    ({}, set()),
    ({"memory_read_scopes": ["project"]}, {"search_memory"}),
    ({"memory_write_scopes": ["user"]}, {"add_memory", "forget_memory"}),
    ({"memory_read_scopes": ["user"], "learning_use": True}, {"search_memory"}),
    ({"memory_write_scopes": ["user_project"], "learning_enabled": True}, {"add_memory", "forget_memory", "learn_from_task"}),
    ({"memory_read_scopes": ["project"], "learning_enabled": True, "learning_use": True}, {"search_memory", "learning_feedback"}),
    ({"memory_read_scopes": [], "memory_write_scopes": [], "learning_enabled": True, "learning_use": True}, set()),
    ({"memory_read_scopes": ["invalid"], "memory_write_scopes": ["invalid"], "learning_enabled": True, "learning_use": True}, set()),
    ({"memory_read_scopes": ["user"], "memory_write_scopes": ["user"], "learning_enabled": True, "learning_use": True}, MEMORY_TOOLS),
])
def test_each_memory_tool_obeys_its_explicit_capability(global_main, config, allowed):
    policy = PlatformToolPolicy(global_main=global_main, **config)
    exposed = {name for name in MEMORY_TOOLS if policy(SimpleNamespace(name=name))}
    assert exposed == allowed


def test_memory_restrictions_do_not_disable_unrelated_business_tools():
    assert PlatformToolPolicy(global_main=False)(SimpleNamespace(name="calculate"))
    assert PlatformToolPolicy(global_main=True)(SimpleNamespace(name="agent_invoke"))
