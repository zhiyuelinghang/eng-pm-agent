"""Shared value handling for atomic platform-settings persistence."""

from datetime import datetime
from hashlib import sha256

from ._model import MemorySettingsData, PlatformSettingsData, PlatformSettingsRecord


class MemorySettingsConflict(ValueError):
    """The submitted memory revision no longer matches stored settings."""


def merge_platform_settings(
    user_id: str,
    existing: PlatformSettingsRecord | None,
    *,
    now: datetime,
    data: PlatformSettingsData | None = None,
    memory_settings: MemorySettingsData | None = None,
    expected_revision: int | None = None,
) -> PlatformSettingsRecord:
    """Build a replacement only after the caller holds its storage write lock."""
    current = existing.data if existing else PlatformSettingsData()
    if memory_settings is not None:
        if expected_revision != current.memory_settings_revision:
            raise MemorySettingsConflict("记忆配置已被其他操作更新，请刷新页面后重新修改。")
        validated = MemorySettingsData.model_validate(memory_settings.model_dump())
        updated = current.model_copy(update={
            "memory_settings": validated,
            "memory_settings_revision": current.memory_settings_revision + 1,
        })
    else:
        if data is None:
            raise ValueError("Platform settings data is required.")
        updated = data.model_copy(deep=True)
        if existing:
            # Other settings endpoints carry an earlier full settings snapshot.
            # They never own the independently versioned memory configuration.
            updated = updated.model_copy(update={
                "memory_settings": current.memory_settings,
                "memory_settings_revision": current.memory_settings_revision,
            })
    return PlatformSettingsRecord(
        id=existing.id if existing else sha256(f"platform-settings:{user_id}".encode()).hexdigest(),
        user_id=user_id,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        data=updated,
    )
