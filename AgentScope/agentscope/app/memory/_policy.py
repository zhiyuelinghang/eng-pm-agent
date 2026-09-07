"""Govern which managed agents may receive shared long-term memory."""

from __future__ import annotations

from typing import Any


def agent_can_use_shared_memory(agent_record: Any | None) -> bool:
    """Return true only for an explicitly configured management agent."""

    if agent_record is None:
        return False
    platform_config = getattr(
        getattr(agent_record, "data", None),
        "platform_config",
        None,
    )
    return getattr(platform_config, "agent_level", None) == "management"
