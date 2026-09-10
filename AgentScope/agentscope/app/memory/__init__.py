# -*- coding: utf-8 -*-
"""AgentScope adapter for the copied Dobby context-control module."""

from ._middleware import DobbyMemoryMiddleware
from ._model import get_compression_model
from ._policy import agent_can_use_shared_memory
from ._runtime import (
    MemoryTarget,
    MemoryRuntime,
    MemoryScope,
    apply_global_memory_settings,
    build_business_memory_target,
    get_memory_runtime,
)

__all__ = [
    "DobbyMemoryMiddleware",
    "MemoryTarget",
    "MemoryRuntime",
    "MemoryScope",
    "apply_global_memory_settings",
    "agent_can_use_shared_memory",
    "build_business_memory_target",
    "get_compression_model",
    "get_memory_runtime",
]
