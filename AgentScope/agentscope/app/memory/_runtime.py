# -*- coding: utf-8 -*-
"""Thin AgentScope binding for the upstream Dobby ``MemoryManager``.

This module deliberately contains no memory implementation.  Long-term
storage, retrieval, context fusion, lifecycle handling and maintenance all
remain in the integrated ``utils`` memory package.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import threading
from typing import Any, Literal


_UNSAFE_SCOPE_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def _settings_dict(settings: Any | None) -> dict[str, Any]:
    if settings is None:
        return {}
    if hasattr(settings, "model_dump"):
        return dict(settings.model_dump())
    if isinstance(settings, dict):
        return dict(settings)
    return {
        name: getattr(settings, name)
        for name in dir(settings)
        if not name.startswith("_") and not callable(getattr(settings, name))
    }


def apply_global_memory_settings(settings: Any | None) -> dict[str, Any]:
    """Apply only the code-owned conversation compression policy."""
    values = _settings_dict(settings)
    from utils import config as memory_config, compression
    mapping = {
        "compression_trigger_ratio": "CONTEXT_TRIGGER_RATIO",
        "compression_keep_messages": "COMPRESSION_KEEP_MESSAGES",
        "compression_mode": "COMPRESSION_MODE",
        "emergency_compression_ratio": "EMERGENCY_COMPRESSION_THRESHOLD",
        "compression_max_consecutive": "COMPRESSION_MAX_CONSECUTIVE",
        "compression_quality_threshold": "COMPRESSION_QUALITY_THRESHOLD",
        "compression_min_rounds_between": "COMPRESSION_MIN_ROUNDS_BETWEEN",
    }
    for source, target in mapping.items():
        if source in values:
            setattr(memory_config, target, values[source])
    memory_config.COMPRESSION_BACKGROUND = False
    from ._prompts import (DEFAULT_COMPRESSION_SYSTEM_PROMPT,
        DEFAULT_COMPRESSION_USER_PROMPT, DEFAULT_COMPRESSION_INCREMENTAL_PROMPT)
    compression.COMPRESS_SYSTEM = DEFAULT_COMPRESSION_SYSTEM_PROMPT
    compression.COMPRESS_USER = DEFAULT_COMPRESSION_USER_PROMPT
    compression.COMPRESS_USER_INCREMENTAL = DEFAULT_COMPRESSION_INCREMENTAL_PROMPT
    return values


def _safe_scope_key(prefix: str, value: str) -> str:
    """Build a stable Mem0-safe key (mem0 2.0.12 rejects colons)."""

    raw = f"{prefix}_{value.strip() or 'anonymous'}"
    safe = _UNSAFE_SCOPE_CHARS.sub("_", raw).strip("_")
    if len(safe) <= 120:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{safe[:95]}_{digest}"


@dataclass(frozen=True)
class MemoryTarget:
    """One explicit Mem0 namespace owned by a platform identity."""

    scope_type: Literal["user", "user_project"]
    user_id: str
    agent_id: str
    tenant_id: str
    identity_type: Literal["business_user", "management_user"]
    platform_user_id: str
    project_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return the serializable runtime and metadata representation."""

        return {
            "scope_version": "2",
            "scope_type": self.scope_type,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "identity_type": self.identity_type,
            "platform_user_id": self.platform_user_id,
            "project_id": self.project_id,
        }


def build_business_memory_target(
    *,
    tenant_id: str,
    platform_user_id: str,
    scope_type: Literal["user", "user_project"],
    project_id: str | None = None,
) -> MemoryTarget:
    """Build the canonical v2 namespace used by runtime and administration."""

    if scope_type == "user_project" and not project_id:
        raise ValueError("用户＋项目记忆必须指定项目。")
    owner_key = _safe_scope_key(
        "memory_v2_business_user",
        f"{tenant_id}_{platform_user_id}",
    )
    agent_key = (
        "memory_v2_user"
        if scope_type == "user"
        else _safe_scope_key("memory_v2_user_project", str(project_id))
    )
    return MemoryTarget(
        scope_type=scope_type,
        user_id=owner_key,
        agent_id=agent_key,
        tenant_id=tenant_id,
        identity_type="business_user",
        platform_user_id=platform_user_id,
        project_id=project_id if scope_type == "user_project" else None,
    )


@dataclass(frozen=True)
class MemoryScope:
    """Immutable mapping from one session to public and personal scopes."""

    tenant_id: str
    project_id: str | None
    platform_user_id: str | None
    agent_id: str
    session_id: str
    scope_key: str
    memory_owner_key: str
    global_memory_key: str
    project_memory_key: str | None
    identity_type: Literal["business_user", "management_user"]
    project_name: str | None = None

    @property
    def memory_targets(self) -> tuple[MemoryTarget, ...]:
        """Return every personal long-term namespace visible in this turn."""

        global_target = MemoryTarget(
            scope_type="user",
            user_id=self.memory_owner_key,
            agent_id=self.global_memory_key,
            tenant_id=self.tenant_id,
            identity_type=self.identity_type,
            platform_user_id=self.platform_user_id or "anonymous",
        )
        if not self.project_id or not self.project_memory_key:
            return (global_target,)
        return (
            global_target,
            MemoryTarget(
                scope_type="user_project",
                user_id=self.memory_owner_key,
                agent_id=self.project_memory_key,
                tenant_id=self.tenant_id,
                identity_type=self.identity_type,
                platform_user_id=self.platform_user_id or "anonymous",
                project_id=self.project_id,
            ),
        )

    def memory_target(
        self,
        scope_type: Literal["user", "user_project"],
    ) -> MemoryTarget:
        """Resolve one writable target, rejecting an unavailable project."""

        for target in self.memory_targets:
            if target.scope_type == scope_type:
                return target
        raise ValueError("当前会话没有可用的用户＋项目记忆作用域。")


class MemoryRuntime:
    """Creates and reuses the upstream manager; it does not store memories."""

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = (
            tenant_id
            or os.getenv("MEMORY_TENANT_ID", "").strip()
            or os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "").strip()
            or "projectcopilot"
        )
        self._managers: dict[tuple[str, str, str], Any] = {}
        self._lock = threading.RLock()

    def scope(
        self,
        *,
        project_id: str | None,
        platform_user_id: str | None,
        agent_id: str,
        session_id: str,
        project_name: str | None = None,
    ) -> MemoryScope:
        """Keep project resources shared while personal memories stay private."""

        scope_key = (
            _safe_scope_key("project", project_id)
            if project_id
            else _safe_scope_key("management", platform_user_id or "anonymous")
        )
        if project_id:
            identity_type: Literal["business_user", "management_user"] = (
                "business_user"
            )
            effective_user_id = (
                platform_user_id
                or f"anonymous_session_{session_id}"
            )
            global_target = build_business_memory_target(
                tenant_id=self.tenant_id,
                platform_user_id=effective_user_id,
                scope_type="user",
            )
            project_target = build_business_memory_target(
                tenant_id=self.tenant_id,
                platform_user_id=effective_user_id,
                scope_type="user_project",
                project_id=project_id,
            )
            memory_owner_key = global_target.user_id
            global_memory_key = global_target.agent_id
            project_memory_key = project_target.agent_id
        else:
            # Preserve the existing management-user namespace so its current
            # memories remain visible after the business-scope correction.
            identity_type = "management_user"
            memory_owner_key = scope_key
            global_memory_key = scope_key
            project_memory_key = None
        return MemoryScope(
            tenant_id=self.tenant_id,
            project_id=project_id,
            platform_user_id=platform_user_id,
            agent_id=agent_id,
            session_id=session_id,
            scope_key=scope_key,
            memory_owner_key=memory_owner_key,
            global_memory_key=global_memory_key,
            project_memory_key=project_memory_key,
            identity_type=identity_type,
            project_name=project_name,
        )

    def manager(self, scope: MemoryScope, settings: Any | None = None) -> Any:
        """Return the complete upstream ``MemoryManager`` for this role."""

        values = apply_global_memory_settings(settings)
        cache_key = (
            scope.scope_key,
            scope.agent_id,
            scope.memory_owner_key,
        )
        with self._lock:
            manager = self._managers.get(cache_key)
            if manager is None:
                # Lazy import is required because the platform loads .env after
                # importing AgentScope modules; upstream config is import-time.
                from utils.memory_manager import MemoryManager

                manager = MemoryManager(
                    project_id=scope.scope_key,
                    role_id=scope.agent_id,
                    runtime_settings=values,
                )
                self._managers[cache_key] = manager
            elif values:
                manager.configure(values)
            return manager

    def invalidate_memory_caches(self) -> None:
        """Invalidate manager-local entity graphs after admin mutations."""

        with self._lock:
            for manager in self._managers.values():
                invalidate = getattr(manager, "invalidate_entity_graph", None)
                if callable(invalidate):
                    invalidate()


_runtime: MemoryRuntime | None = None
_runtime_lock = threading.Lock()


def get_memory_runtime() -> MemoryRuntime:
    """Return the process-wide AgentScope-to-Dobby adapter."""

    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = MemoryRuntime()
    return _runtime
