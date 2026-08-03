# -*- coding: utf-8 -*-
"""Helpers for resolving platform-wide AgentScope settings at runtime."""

from ..storage import AgentRecord, StorageBase


async def get_global_main_agent_id(
    storage: StorageBase,
    user_id: str,
    *,
    legacy_record: AgentRecord | None = None,
) -> str | None:
    """Return the authoritative global-main ID with a legacy fallback.

    New installations persist a single pointer in ``platform_settings``.
    The record fallback keeps old databases and third-party storage backends
    usable until the management API performs its one-time migration.
    """
    getter = getattr(storage, "get_platform_settings", None)
    if getter is not None:
        try:
            settings = await getter(user_id)
        except NotImplementedError:
            settings = None
        if settings is not None:
            return settings.data.global_main_agent_id
    if (
        legacy_record is not None
        and legacy_record.data.platform_config.role == "global_main"
    ):
        return legacy_record.id
    return None


async def get_project_initializer_agent_id(
    storage: StorageBase,
    user_id: str,
) -> str | None:
    """Return the platform-wide project-initializer agent id."""
    getter = getattr(storage, "get_platform_settings", None)
    if getter is None:
        return None
    try:
        settings = await getter(user_id)
    except NotImplementedError:
        settings = None
    if settings is None:
        return None
    return settings.data.project_initializer_agent_id
