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
from typing import Any


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
    """Overlay persisted platform policy onto the copied upstream modules.

    These values are platform-global by design. The model context size is
    deliberately excluded and remains a per-agent runtime value.
    """

    values = _settings_dict(settings)
    if not values:
        return values

    from utils import config as memory_config

    mapping = {
        "recall_top_k": "MEMORY_TOP_K",
        "recall_threshold": "MEMORY_THRESHOLD",
        "recall_reinforce_threshold": "MEMORY_REINFORCE_THRESHOLD",
        "fusion_weight_mem0": "FUSION_WEIGHT_MEM0",
        "fusion_weight_kb": "FUSION_WEIGHT_KB",
        "fusion_weight_timeline": "FUSION_WEIGHT_TIMELINE",
        "fusion_weight_experience": "FUSION_WEIGHT_EXPERIENCE",
        "fusion_weight_graphrag": "FUSION_WEIGHT_GRAPHRAG",
        "fusion_mmr_lambda": "FUSION_MMR_LAMBDA",
        "rrf_k": "RRF_K",
        "mem0_infer_enabled": "MEM0_INFER_ENABLED",
        "mem0_infer_async": "MEM0_INFER_ASYNC",
        "compression_trigger_ratio": "CONTEXT_TRIGGER_RATIO",
        "compression_keep_messages": "COMPRESSION_KEEP_MESSAGES",
        "compression_mode": "COMPRESSION_MODE",
        "emergency_compression_ratio": "EMERGENCY_COMPRESSION_THRESHOLD",
        "compression_background": "COMPRESSION_BACKGROUND",
        "compression_max_consecutive": "COMPRESSION_MAX_CONSECUTIVE",
        "compression_quality_threshold": "COMPRESSION_QUALITY_THRESHOLD",
        "compression_min_rounds_between": "COMPRESSION_MIN_ROUNDS_BETWEEN",
        "token_budget_system_prompt": "TOKEN_BUDGET_SYSTEM_PROMPT",
        "token_budget_skill_injection": "TOKEN_BUDGET_SKILL_INJECTION",
        "token_budget_summary": "TOKEN_BUDGET_SUMMARY",
        "token_budget_ltm_kb_timeline": "TOKEN_BUDGET_LTM_KB_TIMELINE",
        "token_budget_runtime": "TOKEN_BUDGET_RUNTIME",
        "token_budget_recent_history": "TOKEN_BUDGET_RECENT_HISTORY",
        "token_budget_output_reserve": "TOKEN_BUDGET_OUTPUT_RESERVE",
        "dreamer_enabled": "DREAMER_ENABLED",
        "experience_event_driven_enabled": "EXPERIENCE_EVENT_DRIVEN_ENABLED",
    }
    for source, target in mapping.items():
        if source in values:
            setattr(memory_config, target, values[source])

    from utils import compression, historian

    compression.COMPRESS_SYSTEM = values.get(
        "compression_system_prompt",
        compression.COMPRESS_SYSTEM,
    )
    compression.COMPRESS_USER = values.get(
        "compression_user_prompt",
        compression.COMPRESS_USER,
    )
    compression.COMPRESS_USER_INCREMENTAL = values.get(
        "compression_incremental_prompt",
        compression.COMPRESS_USER_INCREMENTAL,
    )
    historian.HISTORIAN_SYSTEM = values.get(
        "historian_system_prompt",
        historian.HISTORIAN_SYSTEM,
    )
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
class MemoryScope:
    """Immutable mapping from one AgentScope session to a Dobby project."""

    tenant_id: str
    project_id: str | None
    platform_user_id: str | None
    agent_id: str
    session_id: str
    scope_key: str


class MemoryRuntime:
    """Creates and reuses the upstream manager; it does not store memories."""

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = (
            tenant_id
            or os.getenv("MEMORY_TENANT_ID", "").strip()
            or os.getenv("AGENTSCOPE_GLOBAL_CONFIG_ID", "").strip()
            or "projectcopilot"
        )
        self._managers: dict[tuple[str, str], Any] = {}
        self._lock = threading.RLock()

    def scope(
        self,
        *,
        project_id: str | None,
        platform_user_id: str | None,
        agent_id: str,
        session_id: str,
    ) -> MemoryScope:
        """Use one shared project pool, or a private management-user pool."""

        scope_key = (
            _safe_scope_key("project", project_id)
            if project_id
            else _safe_scope_key("management", platform_user_id or "anonymous")
        )
        return MemoryScope(
            tenant_id=self.tenant_id,
            project_id=project_id,
            platform_user_id=platform_user_id,
            agent_id=agent_id,
            session_id=session_id,
            scope_key=scope_key,
        )

    def manager(self, scope: MemoryScope, settings: Any | None = None) -> Any:
        """Return the complete upstream ``MemoryManager`` for this role."""

        values = apply_global_memory_settings(settings)
        cache_key = (scope.scope_key, scope.agent_id)
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
