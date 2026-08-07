"""Tests for exact-tool permission rules owned by platform sessions."""

from unittest import TestCase

from agentscope.app._platform_permissions import (
    PLATFORM_SESSION_RULE_SOURCE,
    apply_platform_tool_allow_rules,
)
from agentscope.app.storage import PlatformSessionContext
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionRule,
)


def _context(tool_names: list[str]) -> PlatformSessionContext:
    return PlatformSessionContext(
        user_id="1",
        username="admin",
        display_name="系统管理员",
        project_id="2",
        project_name="测试项目",
        conversation_id="3",
        conversation_title="项目初始化",
        conversation_type="initialization",
        agent_name="初始化助手",
        auto_allowed_tool_names=tool_names,
    )


class PlatformPermissionRulesTest(TestCase):
    """Platform rules are exact, replaceable, and do not erase user rules."""

    def test_applies_exact_rules_and_preserves_non_platform_rules(self) -> None:
        existing = PermissionRule(
            tool_name="Write",
            rule_content="scratch/**",
            behavior=PermissionBehavior.ALLOW,
            source="userSettings",
        )
        permission_context = PermissionContext(
            allow_rules={"Write": [existing]},
        )

        updated = apply_platform_tool_allow_rules(
            permission_context,
            _context(["internal_tool", "internal_tool"]),
        )

        self.assertEqual(updated.allow_rules["Write"], [existing])
        platform_rules = updated.allow_rules["internal_tool"]
        self.assertEqual(len(platform_rules), 1)
        self.assertIsNone(platform_rules[0].rule_content)
        self.assertEqual(
            platform_rules[0].source,
            PLATFORM_SESSION_RULE_SOURCE,
        )

    def test_replaces_only_previous_platform_rules(self) -> None:
        platform_rule = PermissionRule(
            tool_name="old_tool",
            rule_content=None,
            behavior=PermissionBehavior.ALLOW,
            source=PLATFORM_SESSION_RULE_SOURCE,
        )
        permission_context = PermissionContext(
            allow_rules={"old_tool": [platform_rule]},
        )

        updated = apply_platform_tool_allow_rules(
            permission_context,
            _context(["new_tool"]),
        )

        self.assertNotIn("old_tool", updated.allow_rules)
        self.assertIn("new_tool", updated.allow_rules)
