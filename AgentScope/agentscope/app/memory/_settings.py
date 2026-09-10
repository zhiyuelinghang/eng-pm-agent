"""Code-owned memory execution policy, separate from the six product settings."""
from pydantic import ConfigDict

from ..storage._model._platform_settings import MemorySettingsData
from ._prompts import (
    DEFAULT_COMPRESSION_SYSTEM_PROMPT,
    DEFAULT_COMPRESSION_USER_PROMPT,
    DEFAULT_COMPRESSION_INCREMENTAL_PROMPT,
)


class RuntimeMemorySettings(MemorySettingsData):
    """Internal policy. Never accepted or returned by the settings API."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    recall_top_k: int = 5
    learning_auto_consolidate: bool = True
    learning_capture_corrections: bool = True
    learning_capture_failures: bool = True
    learning_capture_patterns: bool = True
    learning_daily_job_limit: int = 30
    learning_cooldown_seconds: int = 60
    learning_pattern_threshold: int = 3
    learning_timeout_seconds: int = 90
    learning_input_char_limit: int = 16000
    learning_review_days: int = 90
    learning_skill_limit: int = 3
    group_learning_scan_seconds: int = 300
    group_learning_message_threshold: int = 20
    group_learning_idle_seconds: int = 600
    group_learning_max_wait_seconds: int = 3600
    group_learning_batch_size: int = 50
    group_learning_daily_limit: int = 100
    compression_trigger_ratio: float = 0.8
    compression_keep_messages: int = 20
    compression_mode: str = 'incremental'
    emergency_compression_ratio: float = 0.95
    compression_background: bool = False
    compression_max_consecutive: int = 3
    compression_quality_threshold: float = 0.3
    compression_min_rounds_between: int = 5
    compression_system_prompt: str = DEFAULT_COMPRESSION_SYSTEM_PROMPT
    compression_user_prompt: str = DEFAULT_COMPRESSION_USER_PROMPT
    compression_incremental_prompt: str = DEFAULT_COMPRESSION_INCREMENTAL_PROMPT


def runtime_memory_settings(settings: MemorySettingsData) -> RuntimeMemorySettings:
    if isinstance(settings, RuntimeMemorySettings):
        return settings
    return RuntimeMemorySettings(**settings.model_dump())
