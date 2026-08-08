# -*- coding: utf-8 -*-
"""Models used by the managed MCP package registry."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


_MCP_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
PROJECT_INITIALIZATION_VALIDATION_CAPABILITY = (
    "project_initialization_validation"
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class MCPPackageManifest(BaseModel):
    """The required ``mcp.json`` contract inside an uploaded package.

    Uploaded packages are already dependency-complete.  The registry only
    needs a deterministic command, working directory and a small amount of
    presentation metadata; it deliberately performs no dependency install or
    build step.
    """

    schema_version: Literal[1] = 1
    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=_MCP_NAME_PATTERN,
        description="Stable technical MCP name used in model-facing tools.",
    )
    display_name: str = Field(min_length=1, max_length=100)
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=_VERSION_PATTERN,
    )
    description: str = Field(default="", max_length=4000)
    transport: Literal["stdio"] = "stdio"
    command: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Executable path relative to the package root, or a bare command "
            "available on the server PATH."
        ),
    )
    args: list[str] = Field(default_factory=list, max_length=100)
    env: dict[str, str] = Field(default_factory=dict)
    platform_capabilities: list[
        Literal[
            "dobby_database_interactions",
            "project_initialization_validation",
        ]
    ] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Host-managed runtime capabilities requested by this package. "
            "Secrets are injected only for explicitly requested capabilities."
        ),
    )
    startup_timeout: float = Field(default=30.0, ge=1.0, le=300.0)
    execution_timeout: float = Field(default=120.0, ge=1.0, le=3600.0)

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("command must be a non-empty executable path")
        return value

    @field_validator("args")
    @classmethod
    def _validate_args(cls, values: list[str]) -> list[str]:
        for value in values:
            if "\x00" in value:
                raise ValueError("args must not contain NUL bytes")
        return values

    @field_validator("env")
    @classmethod
    def _validate_env(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if not key.strip() or "=" in key or "\x00" in key or "\x00" in value:
                raise ValueError("env contains an invalid name or value")
        return values

    @field_validator("platform_capabilities")
    @classmethod
    def _normalise_platform_capabilities(
        cls,
        values: list[
            Literal[
                "dobby_database_interactions",
                "project_initialization_validation",
            ]
        ],
    ) -> list[
        Literal[
            "dobby_database_interactions",
            "project_initialization_validation",
        ]
    ]:
        return list(dict.fromkeys(values))


class MCPPackageTool(BaseModel):
    """Cached tool metadata discovered during package verification."""

    name: str
    display_name: str | None = Field(default=None, max_length=200)
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    read_only: bool = False


class MCPPackageRecord(BaseModel):
    """Durable registry entry for the currently published package version."""

    id: str
    manifest: MCPPackageManifest
    relative_dir: str
    tools: list[MCPPackageTool] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MCPPackageView(BaseModel):
    """Secret-free package representation returned to management clients."""

    id: str
    name: str
    display_name: str
    version: str
    description: str
    transport: Literal["stdio"] = "stdio"
    status: Literal["ready"] = "ready"
    tools: list[MCPPackageTool] = Field(default_factory=list)
    platform_capabilities: list[str] = Field(default_factory=list)
    assigned: bool = False
    active_instances: int = 0
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(
        cls,
        record: MCPPackageRecord,
        *,
        assigned: bool = False,
        active_instances: int = 0,
    ) -> "MCPPackageView":
        """Build a public view without exposing command environment values."""
        manifest = record.manifest
        return cls(
            id=record.id,
            name=manifest.name,
            display_name=manifest.display_name,
            version=manifest.version,
            description=manifest.description,
            tools=record.tools,
            platform_capabilities=list(manifest.platform_capabilities),
            assigned=assigned,
            active_instances=active_instances,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class MCPPackageVersionView(BaseModel):
    """One immutable installed version exposed to platform settings."""

    package_id: str
    display_name: str
    version: str
    description: str
    status: Literal["ready"] = "ready"
    tools: list[MCPPackageTool] = Field(default_factory=list)
    platform_capabilities: list[str] = Field(default_factory=list)
    active_instances: int = 0
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(
        cls,
        record: MCPPackageRecord,
        *,
        active_instances: int = 0,
    ) -> "MCPPackageVersionView":
        """Build a secret-free view of one retained package version."""
        manifest = record.manifest
        return cls(
            package_id=record.id,
            display_name=manifest.display_name,
            version=manifest.version,
            description=manifest.description,
            tools=record.tools,
            platform_capabilities=list(manifest.platform_capabilities),
            active_instances=active_instances,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
