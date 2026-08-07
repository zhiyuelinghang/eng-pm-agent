# -*- coding: utf-8 -*-
"""Permission rules supplied by the authenticated engineering platform."""
from __future__ import annotations

from ..permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionRule,
)
from .storage import PlatformSessionContext


PLATFORM_SESSION_RULE_SOURCE = "platformSession"


def apply_platform_tool_allow_rules(
    permission_context: PermissionContext,
    platform_context: PlatformSessionContext | None,
) -> PermissionContext:
    """Replace platform-owned exact-tool allow rules in a session context.

    The platform service is authenticated separately from management users.
    It can therefore declare the small set of internal orchestration tools a
    platform-owned session needs to run unattended. Existing user, project,
    and agent rules are preserved; only rules created by this helper are
    refreshed.
    """
    allow_rules: dict[str, list[PermissionRule]] = {}
    for tool_name, rules in permission_context.allow_rules.items():
        retained = [
            rule
            for rule in rules
            if rule.source != PLATFORM_SESSION_RULE_SOURCE
        ]
        if retained:
            allow_rules[tool_name] = retained

    if platform_context is not None:
        for tool_name in dict.fromkeys(
            name.strip()
            for name in platform_context.auto_allowed_tool_names
            if name.strip()
        ):
            allow_rules.setdefault(tool_name, []).append(
                PermissionRule(
                    tool_name=tool_name,
                    rule_content=None,
                    behavior=PermissionBehavior.ALLOW,
                    source=PLATFORM_SESSION_RULE_SOURCE,
                ),
            )

    return permission_context.model_copy(
        update={"allow_rules": allow_rules},
        deep=True,
    )
