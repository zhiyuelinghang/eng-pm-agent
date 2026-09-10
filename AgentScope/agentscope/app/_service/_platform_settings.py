# -*- coding: utf-8 -*-
"""Helpers for resolving platform-wide AgentScope settings at runtime."""

from ..storage import StorageBase, PlatformSettingsData
from fastapi import HTTPException


def ensure_fixed_agent_entry(settings, agent_id: str, context, *, delegated=False):
    """Fixed entry points stay fixed even in old sessions or forged requests."""
    if settings is None:
        return
    initializer_id = getattr(settings, "project_initializer_agent_id", None)
    main_id = getattr(settings, "global_main_agent_id", None)
    if delegated and agent_id in {main_id, initializer_id}:
        raise HTTPException(status_code=403, detail="总控和项目初始化不接受其他智能体调用。")
    if (agent_id == initializer_id and context is not None
            and getattr(context, "conversation_type", None) != "initialization"):
        raise HTTPException(status_code=403, detail="项目初始化只能从初始化页面使用。")


async def get_platform_duties(storage: StorageBase, user_id: str) -> PlatformSettingsData:
    """Read the explicit fixed-duty configuration; never infer it from roles."""
    record = await storage.get_platform_settings(user_id)
    return record.data if record is not None else PlatformSettingsData()


def fixed_agent_ids(settings: PlatformSettingsData) -> set[str]:
    """The four platform duties cannot be disabled or removed as agents."""
    return {
        agent_id for agent_id in (
            settings.global_main_agent_id,
            settings.project_initializer_agent_id,
            settings.task_assistant_agent_id,
            settings.knowledge_assistant_agent_id,
        ) if agent_id
    }


async def can_query_project_knowledge(
    storage: StorageBase, user_id: str, agent_id: str,
) -> bool:
    """Resolve direct knowledge access from the fixed duty, never a checkbox."""
    settings = await storage.get_platform_settings(user_id)
    if settings is None or settings.data.knowledge_assistant_agent_id != agent_id:
        return False
    if agent_id in {
        settings.data.global_main_agent_id,
        settings.data.project_initializer_agent_id,
        settings.data.task_assistant_agent_id,
    }:
        return False
    record = await storage.get_agent(user_id, agent_id)
    return record is not None and record.data.platform_config.enabled


async def get_global_main_agent_id(storage: StorageBase, user_id: str) -> str | None:
    """The platform duty is the only source of the orchestrator identity."""
    return (await get_platform_duties(storage, user_id)).global_main_agent_id


async def get_project_initializer_agent_id(storage: StorageBase, user_id: str) -> str | None:
    """Return the explicitly configured initialization duty."""
    return (await get_platform_duties(storage, user_id)).project_initializer_agent_id


async def get_task_assistant_agent_id(storage: StorageBase, user_id: str) -> str | None:
    """Return the explicitly configured task duty."""
    return (await get_platform_duties(storage, user_id)).task_assistant_agent_id
