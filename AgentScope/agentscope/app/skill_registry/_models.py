# -*- coding: utf-8 -*-
"""Models for the platform-managed skill package registry."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _clean_text(value: str, *, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL bytes")
    return value


class SkillPackageRecord(BaseModel):
    """One immutable published version of a managed skill package."""

    id: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    relative_dir: str
    source: Literal["editor", "upload"]
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", "name", "description")
    @classmethod
    def _validate_text(cls, value: str, info) -> str:
        return _clean_text(value, field_name=info.field_name)


class SkillPackageView(BaseModel):
    """Current package version returned to the management interface."""

    id: str
    version: int
    name: str
    description: str
    markdown: str
    source: Literal["editor", "upload"]
    assigned: bool = False
    asset_count: int = 0
    created_at: datetime
    updated_at: datetime

class SkillPackageVersionView(BaseModel):
    """Metadata for one retained immutable package version."""

    package_id: str
    version: int
    name: str
    description: str
    source: Literal["editor", "upload"]
    asset_count: int = 0
    created_at: datetime
    updated_at: datetime
